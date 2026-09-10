from __future__ import annotations

import random
import json
import sqlite3
import shutil
from dataclasses import replace
from pathlib import Path
from decimal import Decimal

import pytest

from app.replay.broker.interval_index import BarInteractionIndex
from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.bar_builder_fakes import make_replay_bar
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_v2_training_phase5 import _request, _acquire
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send


def test_interval_index_matches_linear_first_touch():
    randomizer = random.Random(7201)
    bars = [
        make_replay_bar(1710000000000 + i * 60000, str(randomizer.randrange(20, 200)))
        for i in range(513)
    ]
    index = BarInteractionIndex(bars)
    for _ in range(500):
        a = randomizer.randrange(len(bars))
        b = randomizer.randrange(a + 1, len(bars) + 1)
        price = Decimal(randomizer.randrange(10, 220))
        below = bool(randomizer.randrange(2))
        expected = next(
            (
                i
                for i in range(a, b)
                if (
                    Decimal(bars[i].low) <= price
                    if below
                    else Decimal(bars[i].high) >= price
                )
            ),
            b,
        )
        assert index.first_touch(price, below=below, start=a, end=b) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "touch,funding_offset,held",
    [
        (False, 0, False),
        (True, 0, False),
        (False, 11, False),
        (True, 0, True),
        (False, 0, True),
    ],
)
async def test_waiting_order_skips_safe_prefix_and_stops_at_first_fill(
    tmp_path,
    monkeypatch,
    touch,
    funding_offset,
    held,
    position_side="LONG",
    margin_mode="CROSS",
    varying_mark=False,
    review_fork=False,
    time_disclosure_policy="NONE",
    indexed=False,
    touch_offset=37,
    initial_equity=None,
    holding_quantity="0.001",
    mark_prices=None,
    liquidation=False,
    previous_checkpoint=False,
    shared=False,
):
    forward = 260
    prices = ["100"] * 1260
    if held:
        prices[504 + 5] = "110"
        prices[504 + 10] = "95"
        prices[504 + 20] = "105"
    if touch:
        prices[504 + touch_offset] = "80"
        prices[504 + touch_offset + 63] = "1000"
    service = await _risk_service(
        tmp_path / "run.db",
        bar_prices=prices,
        leading_bars=500,
        now_ms=1710000000000 + 700 * 60000,
        event_buffer_size=512,
    )
    if not indexed:
        async def no_index(**kwargs):
            return None
        monkeypatch.setattr(service.training, "_try_indexed_interval", no_index)
    try:
        catalog = await service.catalog(
            warmup_bars=2,
            horizon_ms=forward * 60000,
            quality_mode="exact",
            blind_mode=False,
        )
        base = replace(
            _sandbox_request(await _request(service), margin_mode=margin_mode, initial_equity=initial_equity),
            catalog_epoch=str(catalog["catalog_epoch"]),
            market_type="futures",
            display_interval="4h",
            forward_cache_ms=forward * 60000,
            time_disclosure_policy=time_disclosure_policy,
        )
        request = await prepare_hedge_request(
            service,
            base,
            root=tmp_path,
            prefix="indexed",
            mark_prices=mark_prices or (
                [str(100 + i % 11) for i in range(forward + 1)]
                if varying_mark
                else ["100"] * (forward + 1)
            ),
            book_mode="OFF",
            funding_event_offset_bars=funding_offset,
        )
        created = await service.training.create_run(request)
        run = str(created["run"]["run_id"])
        session = str(created["run"]["adapter_session_id"])
        await _acquire(
            service, run_id=run, selected_session_id=session, command_id="acquire"
        )
        if held:
            if margin_mode == "ISOLATED":
                await _send(
                    service,
                    run_id=run,
                    session_id=session,
                    command_id="allocate",
                    command_type=ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN,
                    payload={
                        "track_id": "track-1",
                        "position_side": position_side,
                        "amount": "70",
                    },
                )
            await _send(
                service,
                run_id=run,
                session_id=session,
                command_id="holding",
                command_type=ReplayV2CommandType.PLACE_ORDER,
                payload={
                    "client_order_id": "holding",
                    "side": "SELL" if position_side == "SHORT" else "BUY",
                    "position_side": position_side,
                    "order_type": "MARKET",
                    "quantity": holding_quantity,
                    "reduce_only": False,
                    "limit_price": None,
                    "stop_price": None,
                },
            )
        await _send(
            service,
            run_id=run,
            session_id=session,
            command_id="place",
            command_type=ReplayV2CommandType.PLACE_ORDER,
            payload={
                "client_order_id": "wait",
                "side": ("BUY" if position_side == "SHORT" else "SELL")
                if held
                else "BUY",
                "position_side": position_side,
                "order_type": "STOP_MARKET" if held else "LIMIT",
                "quantity": "0.001",
                "reduce_only": held,
                "limit_price": None if held else "90",
                "stop_price": ("120" if position_side == "SHORT" else "90")
                if held
                else None,
            },
        )
        reference_path = tmp_path / "reference.db"
        with (
            sqlite3.connect(service.store.path) as source,
            sqlite3.connect(reference_path) as target,
        ):
            source.backup(target)
        original_db = tmp_path / "run.db"
        for suffix in (
            ".datasets",
            "-hedge-inputs",
            "-historical-books",
            "-account-history",
        ):
            src = (
                Path(str(original_db) + suffix)
                if suffix.startswith(".")
                else original_db.with_name(original_db.stem + suffix)
            )
            dst = (
                Path(str(reference_path) + suffix)
                if suffix.startswith(".")
                else reference_path.with_name(reference_path.stem + suffix)
            )
            if src.is_dir():
                shutil.copytree(src, dst)
        before = await service.get_session_state(session)
        batches = []
        original = service.training._advance_adapter_to

        async def observe(**kwargs):
            batches.append(kwargs.get("final_state_max_events"))
            return await original(**kwargs)

        monkeypatch.setattr(service.training, "_advance_adapter_to", observe)
        result = await _send(
            service,
            run_id=run,
            session_id=session,
            command_id="advance",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={
                "basis": "DISPLAY_BAR",
                "count": 1,
                "display_interval": "4h",
                "viewer_revision": 0,
                "stop_on_event": True,
            },
        )
        consumed = (
            result["cursor"]["source_sequence"] - before["cursor"]["source_sequence"]
        )
        if liquidation:
            assert result["data"]["event_stop"]["reason"] == "LIQUIDATION"
            assert not result["data"]["target_reached"]
        elif funding_offset:
            assert result["data"]["event_stop"]["reason"] == "ACCOUNT_EVENT"
            assert not result["data"]["target_reached"]
            assert consumed <= funding_offset + 2
        elif touch:
            assert result["data"]["event_stop"]["reason"] == "ORDER_FILLED"
            assert not result["data"]["target_reached"]
            assert consumed == touch_offset + 1
        else:
            assert result["data"]["event_stop"] is None
            assert result["data"]["target_reached"]
            assert consumed >= 200
        if varying_mark:
            assert len(batches) < consumed // 2
            recorded_count = await service.store.run_extension_read(
                lambda c: c.execute(
                    "SELECT COUNT(*) FROM replay_command_log WHERE session_id = ? AND command_json LIKE '%_training_recorded_interval%'",
                    (session,),
                ).fetchone()[0]
            )
            if not indexed:
                assert recorded_count > 0
            elif consumed >= 128:
                assert service._sessions[session].actor._metrics.get("indexed_skipped_events", 0) > 100
        elif held:
            assert len(batches) < consumed // 2
            assert any(x and x > 1 for x in batches)
        else:
            assert len(batches) <= 3
            assert any(x and x > 1 for x in batches)
        final = await service.get_session_state(session)
        if shared and consumed >= 128:
            assert await service.store.run_extension_read(
                lambda c: c.execute("SELECT COUNT(*) FROM replay_command_log WHERE session_id=? AND command_json LIKE '%_training_shared_indexed_interval%'", (session,)).fetchone()[0]
            ) > 0
        assert final["cursor"] == result["cursor"]
        if result["data"]["event_stop"]:
            assert (
                result["data"]["event_stop"]["virtual_time_ms"]
                == result["cursor"]["virtual_time_ms"]
            )
            revealed = (await service.get_session(session))["snapshot"]["components"][
                "bar_builder"
            ]
            assert all(
                Decimal(bar["high"]) < Decimal("1000")
                for bar in revealed["closed_bars"]
            )
        if varying_mark:
            from app.replay.training import storage as training_storage

            monkeypatch.setattr(
                training_storage, "_direct_liquidation_tick", lambda **kwargs: None
            )
        reference = await _risk_service(
            reference_path,
            bar_prices=prices,
            leading_bars=500,
            now_ms=1710000000000 + 700 * 60000,
            event_buffer_size=512,
        )
        try:
            if varying_mark:
                reference_store = reference.training.store

                async def separate_mark_inputs(
                    run_id,
                    *,
                    risk_virtual_time_ms,
                    input_events,
                    events,
                    event_virtual_times_ms=None,
                    checkpoint_market_wave=True,
                ):
                    applied = await reference_store.apply_hedge_input_events(
                        run_id,
                        events=input_events,
                        virtual_time_ms=risk_virtual_time_ms,
                        event_virtual_times_ms=event_virtual_times_ms,
                    )
                    if checkpoint_market_wave:
                        checkpointed = (
                            await reference_store.finalize_hedge_inputs_and_checkpoint(
                                run_id,
                                risk_virtual_time_ms=risk_virtual_time_ms,
                                events=(*events, *applied),
                            )
                        )
                    else:
                        await reference_store.finalize_hedge_inputs(
                            run_id,
                            risk_virtual_time_ms=risk_virtual_time_ms,
                        )
                        checkpointed = False
                    return applied, checkpointed

                monkeypatch.setattr(
                    reference_store,
                    "apply_hedge_inputs_and_checkpoint",
                    separate_mark_inputs,
                )
            monkeypatch.setattr(
                reference.training,
                "_ordered_final_state_batch_profile",
                lambda **kwargs: None,
            )
            if liquidation:
                expected = await _send(
                    reference, run_id=run, session_id=session, command_id="reference",
                    command_type=ReplayV2CommandType.ADVANCE,
                    payload={"basis": "DISPLAY_BAR", "count": 1, "display_interval": "4h",
                             "viewer_revision": 0, "stop_on_event": True},
                )
            elif funding_offset:
                from tests.test_replay_v2_training_phase5 import _command

                command = _command(
                    run,
                    "reference",
                    ReplayV2CommandType.ADVANCE,
                    await reference.get_session(session),
                    {"basis": "BASE_BAR", "count": consumed},
                )
                await reference.training._advance_full_tracks_to(
                    command=command,
                    binding=await reference.training.store.run_binding(run),
                    tracks=tuple(
                        await reference.training.store.get_market_track_heads(run)
                    ),
                    target_virtual_time_ms=result["cursor"]["virtual_time_ms"],
                    allow_final_state_batch=False,
                )
                expected = await reference.get_session_state(session)
            else:
                expected = await _send(
                    reference,
                    run_id=run,
                    session_id=session,
                    command_id="reference",
                    command_type=ReplayV2CommandType.ADVANCE,
                    payload={"basis": "BASE_BAR", "count": consumed},
                )
            state = await reference.get_session_state(session)
            assert expected["cursor"] == result["cursor"]
            assert (await reference.get_session(session))["snapshot"]["components"] == (
                await service.get_session(session)
            )["snapshot"]["components"]
            if not shared:
                assert state["state_hash"] == final["state_hash"]

            async def ledger(instance):
                return await instance.store.run_extension_read(
                    lambda connection: [
                        tuple(row)
                        for row in connection.execute(
                            "SELECT kind,cash_delta,asset,virtual_time_ms,source_sequence,reference_type,reference_id FROM replay_training_contract_ledger WHERE run_id = ? AND kind NOT IN ('POSITION_MUTATION','MARGIN_MUTATION') ORDER BY ledger_sequence",
                            (run,),
                        )
                    ]
                )

            assert await ledger(reference) == await ledger(service)

            if held:

                async def samples(instance):
                    # Curve rows are a lazy cache of the committed interval
                    # journal. Request them through the product read path.
                    await instance.training.equity(run, resolution="EVENT")
                    return await instance.store.run_extension_read(
                        lambda connection: {
                            int(row[0]): tuple(row[1:])
                            for row in connection.execute(
                                "SELECT source_sequence,equity,cash_balance,unrealized_pnl,state_hash FROM replay_equity_sample WHERE run_id = ? AND resolution = 'EVENT' ORDER BY source_sequence",
                                (run,),
                            )
                        }
                    )

                reference_samples = await samples(reference)
                optimized_samples = await samples(service)
                assert all(
                    reference_samples[sequence][:3] == value[:3]
                    and (shared or value[3].startswith("interval-state:")
                         or reference_samples[sequence][3] == value[3])
                    for sequence, value in optimized_samples.items()
                )
                changes = {}
                previous = None
                for sequence, value in reference_samples.items():
                    if value[:3] != previous:
                        changes[sequence] = value[:3]
                    previous = value[:3]
                assert all(
                    sequence in optimized_samples
                    and optimized_samples[sequence][:3] == value
                    for sequence, value in changes.items()
                )
                if varying_mark:

                    async def critical_review(owner):
                        return await owner.store.run_extension_read(
                            lambda c: [
                                tuple(row)
                                for row in c.execute(
                                    "SELECT category,event_type,virtual_time_ms,source_sequence,state_hash,json_extract(projection_json,'$.domain.equity'),json_extract(projection_json,'$.domain.position_hash'),json_extract(projection_json,'$.domain.order_hash') FROM replay_review_timeline_event WHERE run_id = ? AND category IN ('ORDER','FILL','POSITION','FUNDING','LIQUIDATION','EQUITY') ORDER BY timeline_sequence",
                                    (run,),
                                )
                            ]
                        )

                    async def all_samples(owner):
                        return await owner.store.run_extension_read(
                            lambda c: [
                                tuple(row)
                                for row in c.execute(
                                    "SELECT resolution,bucket_id,source_sequence,equity,cash_balance,unrealized_pnl,ledger_tail_hash,public_time_json FROM replay_equity_sample WHERE run_id=? ORDER BY resolution,bucket_id",
                                    (run,),
                                )
                            ]
                        )

                    assert await all_samples(service) == await all_samples(reference)
                    actual_review, expected_review = await critical_review(service), await critical_review(reference)
                    if shared:
                        actual_review = [row[:4]+row[5:] for row in actual_review]
                        expected_review = [row[:4]+row[5:] for row in expected_review]
                    if indexed:
                        assert all(row in expected_review for row in actual_review)
                    else:
                        assert actual_review == expected_review
                    future_anchors = await service.store.run_extension_read(
                        lambda c: c.execute(
                            "SELECT COUNT(*) FROM replay_review_timeline_event e JOIN replay_review_event_anchor r USING(run_id,timeline_sequence) JOIN replay_review_actor_anchor a ON a.run_id=r.run_id AND a.anchor_id=r.anchor_id WHERE e.run_id=? AND (a.source_sequence>e.source_sequence OR a.virtual_time_ms>e.virtual_time_ms)",
                            (run,),
                        ).fetchone()[0]
                    )
                    assert future_anchors == 0

        finally:
            await reference.shutdown(step_timeout=1)
        from app.replay.training.commands import ReplayV2Command

        if review_fork:
            event = await service.store.run_extension_read(
                lambda c: dict(
                    c.execute(
                        "SELECT event_id,virtual_time_ms,source_sequence FROM replay_review_timeline_event WHERE run_id=? AND category='EQUITY' AND source_sequence>? AND source_sequence<? ORDER BY timeline_sequence LIMIT 1",
                        (
                            run,
                            before["cursor"]["source_sequence"],
                            result["cursor"]["source_sequence"],
                        ),
                    ).fetchone()
                )
            )
            review = await service.training.start_review(
                run, event_id=event["event_id"]
            )
            assert review["selected_event_id"] == event["event_id"]
            forked = await service.training.fork_run(run, event_id=event["event_id"])
            assert forked["account_audit"]["status"] == "PASS"
            assert {
                track["cursor"]["virtual_time_ms"] for track in forked["tracks"]
            } == {event["virtual_time_ms"]}
            assert (await service.get_session_state(session))["cursor"] == result[
                "cursor"
            ]
        command_json = await service.store.run_extension_read(
            lambda connection: connection.execute(
                "SELECT command_json FROM replay_training_command WHERE run_id = ? AND command_id = 'advance'",
                (run,),
            ).fetchone()[0]
        )
        if varying_mark:
            await service.shutdown(step_timeout=1)
            if previous_checkpoint:
                with sqlite3.connect(original_db) as database:
                    assert database.execute(
                        "SELECT COUNT(*) FROM replay_checkpoint WHERE source_sequence<? AND active=1",
                        (result["cursor"]["source_sequence"],),
                    ).fetchone()[0] > 0
                    database.execute("UPDATE replay_checkpoint SET active=0 WHERE source_sequence=?",
                                     (result["cursor"]["source_sequence"],))
            service = await _risk_service(
                original_db,
                bar_prices=prices,
                leading_bars=500,
                now_ms=1710000000000 + 700 * 60000,
                event_buffer_size=512,
            )
            assert (await service.get_session_state(session))["state_hash"] == result[
                "state_hash"
            ]
            audit = await service.training.audit_account(run)
            assert audit["status"] == "PASS", audit
        assert (
            await service.training.command(
                run, ReplayV2Command.from_dict(json.loads(command_json))
            )
            == result
        )

    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.parametrize(
    "kind,side,price",
    [
        ("LIMIT", "BUY", "90"),
        ("LIMIT", "SELL", "110"),
        ("STOP_MARKET", "BUY", "110"),
        ("STOP_MARKET", "SELL", "90"),
        ("TAKE_PROFIT_MARKET", "BUY", "90"),
        ("TAKE_PROFIT_MARKET", "SELL", "110"),
    ],
)
def test_indexed_prefix_matches_broker_trigger_and_rebinds_replaced_bars(
    kind, side, price
):
    from tests.fixtures.replay.broker_fakes import make_broker, request, bar

    broker = make_broker()
    order = broker.place_order(
        request(
            client_order_id="indexed",
            side=side,
            order_type=kind,
            limit_price=price if kind == "LIMIT" else None,
            stop_price=None if kind == "LIMIT" else price,
        ),
        command_id="indexed",
        accepted_source_sequence=0,
        created_time_ms=1710000000000,
    )
    events = tuple(
        bar(i, value) for i, value in enumerate([100, 80, 120, 100, 95, 85, 115, 100])
    )

    def expected(items):
        return next(
            (
                i
                for i, event in enumerate(items)
                if i + 1 > order.accepted_source_sequence
                and broker._trigger(order, event) is not None
            ),
            len(items),
        )

    assert broker.final_state_safe_prefix_length(events) == expected(events)
    assert broker.final_state_safe_prefix_length(events[:5]) == expected(events[:5])
    replacement = tuple(bar(i, 100) for i in range(8))
    assert broker.final_state_safe_prefix_length(replacement) == expected(replacement)


def test_index_rejects_an_entire_safe_range_with_one_bound_read():
    bars = tuple(make_replay_bar(1710000000000 + i * 60000, "100") for i in range(4096))
    index = BarInteractionIndex(bars)

    class Counted(list):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    index.low = Counted(index.low)
    assert index.first_touch(Decimal("90"), below=True, start=0, end=4096) == 4096
    assert index.low.reads == 1


@pytest.mark.anyio
async def test_single_track_target_scan_stops_and_retries_at_fill(tmp_path):
    from tests.test_replay_v2_training_phase15 import (
        _bar_service,
        _create_acquired_bar_run,
    )

    from tests.test_replay_v2_training_phase15 import _v2_command

    async def send(service, *, run_id, session_id, command_id, command_type, payload):
        return await service.training.command(
            run_id,
            _v2_command(
                run_id,
                command_id,
                command_type,
                await service.get_session(session_id),
                payload,
            ),
        )

    service = await _bar_service(tmp_path / "single.db", optimized=True)
    try:
        run, session = await _create_acquired_bar_run(service)
        await send(
            service,
            run_id=run,
            session_id=session,
            command_id="stop-buy",
            command_type=ReplayV2CommandType.PLACE_ORDER,
            payload={
                "client_order_id": "stop-buy",
                "side": "BUY",
                "order_type": "STOP_MARKET",
                "quantity": "0.1",
                "reduce_only": False,
                "limit_price": None,
                "stop_price": "120",
            },
        )
        before = await service.get_session_state(session)
        target = before["cursor"]["virtual_time_ms"] + 120 * 60000
        result = await send(
            service,
            run_id=run,
            session_id=session,
            command_id="single-advance",
            command_type=ReplayV2CommandType.ADVANCE_TO,
            payload={"virtual_time_ms": target, "stop_on_event": True},
        )
        assert result["data"]["event_stop"]["reason"] == "ORDER_FILLED"
        assert result["cursor"]["virtual_time_ms"] < target
        assert not result["data"]["target_reached"]
        assert (
            len((await service.get_session(session))["snapshot"]["components"]["fills"])
            == 1
        )
        stored_command = await service.store.run_extension_read(
            lambda connection: connection.execute(
                "SELECT command_json FROM replay_training_command WHERE run_id = ? AND command_id = 'single-advance'",
                (run,),
            ).fetchone()[0]
        )
        await service.shutdown(step_timeout=1)
        service = await _bar_service(tmp_path / "single.db", optimized=True)
        from app.replay.training.commands import ReplayV2Command

        assert (
            await service.training.command(
                run, ReplayV2Command.from_dict(json.loads(stored_command))
            )
            == result
        )

    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "side,margin", [("SHORT", "CROSS"), ("LONG", "ISOLATED"), ("SHORT", "ISOLATED")]
)
async def test_static_risk_certificate_preserves_short_and_isolated_accounts(
    tmp_path, monkeypatch, side, margin
):
    await test_waiting_order_skips_safe_prefix_and_stops_at_first_fill(
        tmp_path, monkeypatch, False, 0, True, side, margin
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "side,margin",
    [
        ("LONG", "CROSS"),
        ("SHORT", "CROSS"),
        ("LONG", "ISOLATED"),
        ("SHORT", "ISOLATED"),
    ],
)
async def test_varying_marks_preserve_reference_ledger_and_curve(
    tmp_path, monkeypatch, side, margin
):
    await test_waiting_order_skips_safe_prefix_and_stops_at_first_fill(
        tmp_path, monkeypatch, False, 0, True, side, margin, True
    )
