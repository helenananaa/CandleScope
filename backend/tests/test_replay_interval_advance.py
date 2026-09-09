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
):
    forward = 260
    prices = ["100"] * 1260
    if held:
        prices[504 + 5] = "110"
        prices[504 + 10] = "95"
        prices[504 + 20] = "105"
    if touch:
        prices[504 + 37] = "80"
        prices[504 + 100] = "1000"
    service = await _risk_service(
        tmp_path / "run.db",
        bar_prices=prices,
        leading_bars=500,
        now_ms=1710000000000 + 700 * 60000,
        event_buffer_size=512,
    )
    try:
        catalog = await service.catalog(
            warmup_bars=2,
            horizon_ms=forward * 60000,
            quality_mode="exact",
            blind_mode=False,
        )
        base = replace(
            _sandbox_request(await _request(service), margin_mode=margin_mode),
            catalog_epoch=str(catalog["catalog_epoch"]),
            market_type="futures",
            display_interval="4h",
            forward_cache_ms=forward * 60000,
        )
        request = await prepare_hedge_request(
            service,
            base,
            root=tmp_path,
            prefix="indexed",
            mark_prices=["100"] * (forward + 1),
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
                    "quantity": "0.001",
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
        if funding_offset:
            assert result["data"]["event_stop"]["reason"] == "ACCOUNT_EVENT"
            assert not result["data"]["target_reached"]
            assert consumed < 38
        elif touch:
            assert result["data"]["event_stop"]["reason"] == "ORDER_FILLED"
            assert not result["data"]["target_reached"]
            assert consumed == 38
        else:
            assert result["data"]["event_stop"] is None
            assert result["data"]["target_reached"]
            assert consumed >= 200
        if held:
            assert len(batches) < consumed // 2
            assert any(x and x > 1 for x in batches)
        else:
            assert len(batches) <= 3
            assert any(x and x > 1 for x in batches)
        final = await service.get_session_state(session)
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
        reference = await _risk_service(
            reference_path,
            bar_prices=prices,
            leading_bars=500,
            now_ms=1710000000000 + 700 * 60000,
            event_buffer_size=512,
        )
        try:
            monkeypatch.setattr(
                reference.training,
                "_ordered_final_state_batch_profile",
                lambda **kwargs: None,
            )
            if funding_offset:
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
            assert state["state_hash"] == final["state_hash"]

            async def ledger(instance):
                return await instance.store.run_extension_read(
                    lambda connection: [
                        tuple(row)
                        for row in connection.execute(
                            "SELECT ledger_sequence,entry_hash FROM replay_training_contract_ledger WHERE run_id = ? ORDER BY ledger_sequence",
                            (run,),
                        )
                    ]
                )

            assert await ledger(reference) == await ledger(service)

            if held:

                async def samples(instance):
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
                    reference_samples[sequence] == value
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

        finally:
            await reference.shutdown(step_timeout=1)
        from app.replay.training.commands import ReplayV2Command

        command_json = await service.store.run_extension_read(
            lambda connection: connection.execute(
                "SELECT command_json FROM replay_training_command WHERE run_id = ? AND command_id = 'advance'",
                (run,),
            ).fetchone()[0]
        )
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
