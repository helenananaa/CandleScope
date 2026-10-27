import json
from dataclasses import replace
from decimal import Decimal
from time import perf_counter

import pytest
from app.replay.training import tape_phases
from app.replay.training.models import ReplayV2CommandType as C
from app.replay.training.multi_interval_store import reconstruct_portfolio_interval

from tests import test_replay_v2_training_phase5 as fixtures
from tests.fixtures.replay.hedge_input_fakes import (
    import_hedge_track_public_inputs,
    prepare_hedge_request,
)
from tests.test_replay_hedge_tape_cohort_batch import _assert_complete_global_prefix
from tests.test_replay_tape_phases import arguments
from tests.test_replay_v2_training_phase6 import _send

pytestmark = pytest.mark.anyio


async def make_run(
    root,
    *,
    enabled,
    margin="CROSS",
    sides=("LONG", "SHORT"),
    track_count=1,
    initial_equity="10000",
    later_mark="105",
    time_policy="NONE",
    track_marks=None,
):
    root.mkdir()
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT",
               "ADAUSDT", "XRPUSDT", "LTCUSDT", "BNBUSDT")[:track_count]
    service = await fixtures._trade_service(
        root / "run.db",
        archive_root=root / "tape",
        symbols=symbols,
        symbol_time_offset_ms=5 if track_count > 1 else 0,
    )
    service.settings = replace(
        service.settings,
        replay_fast_forward_optimization_enabled=enabled,
        controller_ttl_seconds=600,
    )
    request = replace(
        await fixtures._trade_request(service),
        integrity_mode="SANDBOX",
        margin_mode=margin,
        initial_equity=initial_equity,
        time_disclosure_policy=time_policy,
    )
    request = await prepare_hedge_request(
        service,
        request,
        root=root,
        prefix="fixed-mark",
        book_mode="OFF",
        mark_prices=[
            "100" if i < 2 else later_mark
            for i in range(request.forward_cache_ms // 60000 + 1)
        ],
        funding_event_offset_bars=2,
        required_symbols=list(symbols),
    )
    for symbol in symbols[1:]:
        await import_hedge_track_public_inputs(
            service,
            request,
            root=root,
            prefix="second",
            symbol=symbol,
            mark_prices=track_marks,
            include_book=False,
        )
    created = await service.training.create_run(request)
    run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await fixtures._acquire(
        service, run_id=run, selected_session_id=sid, command_id="acquire"
    )

    async def send(key, kind, payload):
        return await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id=key,
            command_type=kind,
            payload=payload,
        )

    for symbol in symbols[1:]:
        await send(
            "add-" + symbol,
            C.ADD_TRACK,
            {
                "exchange": "binance",
                "market_type": "futures",
                "symbol": symbol,
                "settlement_asset": "USDT",
                "subscription_tier": "FULL",
            },
        )
    for i, symbol in enumerate(symbols):
        if i:
            viewer = await service.training.get_viewer_state(run)
            selected = await send(
                "select-" + symbol,
                C.SELECT_TRACK,
                {
                    "track_id": f"track-{i + 1}",
                    "expected_viewer_revision": viewer["semantic_view_revision"],
                },
            )
            sid = selected["session_id"]
        for side in sides:
            if margin == "ISOLATED":
                await send(
                    "margin-" + symbol + side,
                    C.ALLOCATE_ISOLATED_MARGIN,
                    {
                        "track_id": f"track-{i + 1}",
                        "position_side": side,
                        "amount": "1000",
                    },
                )
            await send(
                "open-" + symbol + side,
                C.PLACE_ORDER,
                {
                    "client_order_id": "open-" + symbol + side,
                    "position_side": side,
                    "side": "BUY" if side == "LONG" else "SELL",
                    "order_type": "MARKET",
                    "quantity": "1" if side == "LONG" else "2",
                    "reduce_only": False,
                    "limit_price": None,
                    "stop_price": None,
                },
            )
    from app.replay.training.control_rules import virtual_event_time_ms

    binding = await service.training.store.run_binding(run)
    await send(
        "prime",
        C.ADVANCE_TO,
        {
            "virtual_time_ms": virtual_event_time_ms(
                binding, request.requested_start_ms + 1010
            ),
            "stop_on_event": False,
        },
    )
    return service, run, sid, request, send


@pytest.mark.parametrize(
    "margin,sides,track_count,capital_kind",
    [
        ("CROSS", ("LONG",), 1, None),
        ("CROSS", ("SHORT",), 1, None),
        ("CROSS", ("LONG", "SHORT"), 1, None),
        ("ISOLATED", ("LONG", "SHORT"), 1, None),
        ("CROSS", ("LONG", "SHORT"), 2, None),
        ("ISOLATED", ("LONG", "SHORT"), 2, None),
        ("CROSS", ("LONG", "SHORT"), 8, None),
        ("CROSS", ("LONG", "SHORT"), 2, C.DEPOSIT),
        ("CROSS", ("LONG", "SHORT"), 2, C.WITHDRAW),
    ],
    ids=["cross-long", "cross-short", "cross-both", "isolated-both",
         "cross-two", "isolated-two", "cross-eight", "capital-deposit", "capital-withdraw"],
)
async def test_hedge_tape_intervals_match_scalar_across_mark_and_funding(
    tmp_path, monkeypatch, margin, sides, track_count, capital_kind
):
    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, **kw),
    )
    outcomes = []
    for enabled in (True, False):
        service, run, sid, request, send = await make_run(
            tmp_path / str(enabled),
            enabled=enabled,
            margin=margin,
            sides=sides,
            track_count=track_count,
        )
        try:
            if capital_kind is not None:
                before = (await service.training.get_market_tracks(run))["portfolio"]
                await send("capital-before-interval", capital_kind,
                           {"amount": "10", "reason": "interval capital parity"})
                after = (await service.training.get_market_tracks(run))["portfolio"]
                delta = Decimal(10) if capital_kind == C.DEPOSIT else Decimal(-10)
                assert Decimal(after["cash_balance"]) == Decimal(before["cash_balance"]) + delta
                assert (await service.training.get_live_market_tracks(run))["portfolio"]["equity"] == after["equity"]
                assert (await service.training.get_run(run))["equity"] == after["equity"]
            start_writes = service.store._metrics["transactions"]
            start = perf_counter()
            await send(
                "advance",
                C.ADVANCE_TO,
                {
                    "virtual_time_ms": request.requested_start_ms + 3 * 60000 - 1,
                    "stop_on_event": False,
                },
            )
            elapsed = perf_counter() - start
            writes = service.store._metrics["transactions"] - start_writes
            assert (await service.training.audit_account(run))["status"] == "PASS"
            await _assert_complete_global_prefix(service, run)
            heads = await service.training.store.get_market_track_heads(run)
            portfolio = (await service.training.get_market_tracks(run))["portfolio"]
            for resolution in ("EVENT", "1M"):
                await service.training.equity(run, resolution=resolution, limit=1000)
            curve_rows = await service.store.run_extension_read(
                lambda c: [
                    tuple(r)
                    for r in c.execute(
                        "SELECT resolution,bucket_id,source_sequence,public_time_json,equity,cash_balance,unrealized_pnl "
                        "FROM replay_equity_sample ORDER BY resolution,bucket_id"
                    )
                ]
            )
            excursions = await service.store.run_extension_read(
                lambda c: [
                    tuple(r)
                    for r in c.execute(
                        "SELECT track_id,highest_mark,lowest_mark FROM replay_training_trade_projection ORDER BY track_id,position_side"
                    )
                ]
            )
            rows = await service.store.run_extension_read(
                lambda c, run=run: c.execute(
                    "SELECT basis_json,summary_json FROM replay_multi_bar_interval WHERE run_id=? ORDER BY end_time_ms",
                    (run,),
                ).fetchall()
            )
            intervals = [
                json.loads(r[0])
                for r in rows
                if json.loads(r[0])["schema"] == "multi-tape-interval.v2"
            ]
            assert bool(intervals) == enabled
            if enabled:
                for row in rows:
                    basis, summary = map(json.loads, row)
                    if basis["schema"] != "multi-tape-interval.v2":
                        continue
                    restored = reconstruct_portfolio_interval(
                        basis, input_root=tmp_path, bucket_ms=0
                    )
                    for key in ("last", "peak", "trough", "max_drawdown"):
                        assert Decimal(restored[key]) == Decimal(summary[key])
                    # Never cross even an unchanged mark, let alone funding.
                    assert (basis["start_time_ms"] // 60000) == (
                        basis["end_time_ms"] // 60000
                    )
            outcomes.append(
                {
                    "finance": [(t["position"], t["account"]) for t in heads],
                    "equity": portfolio["equity"],
                    "positions": portfolio["positions"],
                    "orders": portfolio["orders"],
                    "fills": portfolio["fills"],
                    "curve": curve_rows,
                    "excursions": excursions,
                    "source_chain": service._sessions[sid].actor._event_chain_hash,
                    "broker": service._sessions[sid].actor._reducer.snapshot(),
                    "events": [
                        (
                            e["actual_event_time_ms"],
                            e["event_phase"],
                            e["track_id"],
                            e["source_sequence"],
                        )
                        for e in await service.training.store.global_events(run)
                    ],
                    "elapsed": elapsed,
                    "writes": writes,
                }
            )
        finally:
            await service.shutdown(step_timeout=5)
    (tmp_path / "comparison.json").write_text(json.dumps(outcomes, indent=2))
    for field in (
        "finance",
        "equity",
        "positions",
        "orders",
        "fills",
        "events",
        "curve",
        "excursions",
        "source_chain",
        "broker",
    ):
        assert outcomes[0][field] == outcomes[1][field]
    assert outcomes[0]["writes"] < outcomes[1]["writes"] / 2


async def test_hedge_tape_intervals_continue_past_an_earlier_track_input_bound(
    tmp_path, monkeypatch
):
    # An added FULL track is bound through the dataset end (the final bar's
    # open), the primary through that bar's close. Past the earlier bound the
    # exact path keeps the leg's committed mark; intervals must do the same.
    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, **kw),
    )
    outcomes = []
    for enabled in (True, False):
        service, run, sid, request, send = await make_run(
            tmp_path / str(enabled),
            enabled=enabled,
            sides=("LONG",),
            track_count=2,
            track_marks=["200", "200", "200", "210", "220"],
        )
        try:
            bounds = await service.store.run_extension_read(
                lambda c: dict(
                    c.execute(
                        "SELECT track_id,bound_range_end_ms FROM replay_hedge_track_public_binding WHERE run_id=?",
                        (run,),
                    ).fetchall()
                )
            )
            earlier, final = bounds["track-2"], bounds["track-1"]
            assert earlier == request.requested_start_ms + 3 * 60000 < final
            await send(
                "before-bound",
                C.ADVANCE_TO,
                {"virtual_time_ms": earlier - 1, "stop_on_event": False},
            )
            counted = dict(getattr(service.training.store, "_tape_interval_outcomes", {}))
            start_writes = service.store._metrics["transactions"]
            result = await send(
                "past-bound",
                C.ADVANCE_TO,
                {"virtual_time_ms": final - 1, "stop_on_event": False},
            )
            writes = service.store._metrics["transactions"] - start_writes
            assert result["cursor"]["virtual_time_ms"] == final - 1
            assert (await service.training.audit_account(run))["status"] == "PASS"
            await _assert_complete_global_prefix(service, run)
            recorded = service.training.store._tape_interval_outcomes
            if enabled:
                assert recorded["accepted"] > counted.get("accepted", 0)
            else:
                assert set(recorded) == {"disabled"}
            heads = await service.training.store.get_market_track_heads(run)
            # The mark committed at the earlier bound holds until the archive's
            # next mark, which lies beyond this target.
            assert {
                t["track_id"]: Decimal(t["position"]["long"]["mark_price"]) for t in heads
            } == {"track-1": Decimal("105"), "track-2": Decimal("210")}
            rows = await service.store.run_extension_read(
                lambda c: c.execute(
                    "SELECT basis_json,summary_json FROM replay_multi_bar_interval WHERE run_id=? AND start_time_ms>=?",
                    (run, earlier),
                ).fetchall()
            )
            past = [
                tuple(map(json.loads, r))
                for r in rows
                if json.loads(r[0])["schema"] == "multi-tape-interval.v2"
            ]
            assert bool(past) == enabled
            for basis, summary in past:
                restored = reconstruct_portfolio_interval(
                    basis, input_root=tmp_path, bucket_ms=0
                )
                for key in ("last", "peak", "trough", "max_drawdown"):
                    assert Decimal(restored[key]) == Decimal(summary[key])
            portfolio = (await service.training.get_market_tracks(run))["portfolio"]
            for resolution in ("EVENT", "1M"):
                await service.training.equity(run, resolution=resolution, limit=1000)
            outcomes.append(
                {
                    "finance": [(t["position"], t["account"]) for t in heads],
                    "portfolio": [
                        portfolio[k]
                        for k in (
                            "equity",
                            "cash_balance",
                            "positions",
                            "orders",
                            "fills",
                            "fees_paid",
                            "funding_cashflow",
                        )
                    ],
                    "ledger": await service.store.run_extension_read(
                        lambda c: [
                            tuple(r)
                            for r in c.execute(
                                "SELECT ledger_sequence,track_id,kind,cash_delta,virtual_time_ms,source_sequence,entry_hash "
                                "FROM replay_training_contract_ledger WHERE run_id=? ORDER BY ledger_sequence",
                                (run,),
                            )
                        ]
                    ),
                    "inputs": await service.store.run_extension_read(
                        lambda c: [
                            tuple(r)
                            for r in c.execute(
                                "SELECT track_id,last_event_sequence,state_json,input_chain_hash "
                                "FROM replay_hedge_track_public_projection WHERE run_id=? ORDER BY track_id",
                                (run,),
                            )
                        ]
                    ),
                    "curve": await service.store.run_extension_read(
                        lambda c: [
                            tuple(r)
                            for r in c.execute(
                                "SELECT resolution,bucket_id,source_sequence,public_time_json,equity,cash_balance,unrealized_pnl "
                                "FROM replay_equity_sample ORDER BY resolution,bucket_id"
                            )
                        ]
                    ),
                    "events": [
                        (
                            e["actual_event_time_ms"],
                            e["event_phase"],
                            e["track_id"],
                            e["source_sequence"],
                        )
                        for e in await service.training.store.global_events(run)
                    ],
                    "report": await service.training.report(run),
                    "source_chain": service._sessions[sid].actor._event_chain_hash,
                    "writes": writes,
                }
            )
        finally:
            await service.shutdown(step_timeout=5)
    for field in (
        "finance",
        "portfolio",
        "ledger",
        "inputs",
        "curve",
        "events",
        "report",
        "source_chain",
    ):
        assert outcomes[0][field] == outcomes[1][field]
    assert outcomes[0]["writes"] < outcomes[1]["writes"] / 2


@pytest.mark.parametrize(
    "count,restart,time_policy",
    [
        (53, False, "NONE"),
        (53, True, "NONE"),
        (53, False, "HIDE_ALL"),
        (53, True, "HIDE_ALL"),
    ],
)
async def test_exact_source_count_keeps_partial_final_cohort(
    tmp_path, monkeypatch, count, restart, time_policy
):
    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, trades_per_timestamp=2, **kw),
    )
    outcomes = []
    for enabled in (True, False):
        root = tmp_path / str(enabled)
        service, run, sid, _request, _send_command = await make_run(
            root, enabled=enabled, time_policy=time_policy
        )
        try:
            before = (await service.get_session_state(sid))["cursor"]["source_sequence"]
            snapshot = await service.get_session(sid)
            cmd = fixtures._command(
                run,
                "exact",
                C.ADVANCE,
                snapshot,
                {"basis": "SOURCE_EVENT", "count": count},
            )
            if enabled and restart:
                kwargs = await arguments(service, run, sid)
                goal = await service.training._ordered_source_goal(
                    kwargs["tracks"],
                    max_events=count,
                    expected_snapshot=snapshot["snapshot"],
                )
                kwargs.update(
                    command=cmd,
                    target=goal.target_virtual_time_ms,
                    source_goal=goal,
                    runtime_snapshot=await service.training.hedge_inputs.runtime_snapshot(
                        run
                    ),
                )
                assert (
                    await tape_phases.try_advance(service.training, **kwargs)
                    is not None
                )
                await service.shutdown(step_timeout=5)
                service = await fixtures._trade_service(
                    root / "run.db", archive_root=root / "tape", symbols=("BTCUSDT",)
                )
                service.settings = replace(
                    service.settings, replay_fast_forward_optimization_enabled=True
                )
            result = await service.training.command(run, cmd)
            assert result["cursor"]["source_sequence"] == before + count
            assert await service.training.command(run, cmd) == result
            count_intervals = await service.store.run_extension_read(
                lambda c, run=run: c.execute(
                    "SELECT count(*) FROM replay_multi_bar_interval WHERE run_id=?",
                    (run,),
                ).fetchone()[0]
            )
            assert bool(count_intervals) == enabled
            outcomes.append(
                (
                    result["cursor"],
                    (await service.training.get_market_tracks(run))["portfolio"][
                        "positions"
                    ],
                    service._sessions[sid].actor._event_chain_hash,
                )
            )
            assert (await service.training.audit_account(run))["status"] == "PASS"
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("boundary", ["funding", "liquidation", "order"])
async def test_hedge_tape_exact_event_stop_after_safe_prefix(
    tmp_path, monkeypatch, boundary
):
    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, **kw),
    )
    outcomes = []
    for enabled in (True, False):
        service, run, _sid, request, send = await make_run(
            tmp_path / str(enabled),
            enabled=enabled,
            sides=("LONG",),
            initial_equity="40" if boundary == "liquidation" else "10000",
            later_mark="1" if boundary == "liquidation" else "105",
        )
        try:
            if boundary == "order":
                await send(
                    "limit",
                    C.PLACE_ORDER,
                    {
                        "client_order_id": "limit",
                        "side": "SELL",
                        "position_side": "LONG",
                        "order_type": "LIMIT",
                        "quantity": "1",
                        "reduce_only": True,
                        "limit_price": "101",
                        "stop_price": None,
                    },
                )
            result = await send(
                "advance",
                C.ADVANCE_TO,
                {
                    "virtual_time_ms": request.requested_start_ms + 3 * 60000 - 1,
                    "stop_on_event": True,
                },
            )
            assert (
                result["cursor"]["virtual_time_ms"]
                < request.requested_start_ms + 3 * 60000 - 1
            )
            portfolio = (await service.training.get_market_tracks(run))["portfolio"]
            outcomes.append(
                (
                    result["cursor"],
                    result["data"].get("event_stop"),
                    [
                        portfolio[k]
                        for k in (
                            "equity",
                            "cash_balance",
                            "positions",
                            "fees_paid",
                            "funding_cashflow",
                        )
                    ],
                )
            )
            assert (await service.training.audit_account(run))["status"] == "PASS"
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("historical_anchor", [False, True])
async def test_hedge_tape_review_fork_keeps_pinned_marks_and_export_semantics(
    tmp_path, monkeypatch, historical_anchor
):
    from app.replay.training.portfolio_history import export_intervals

    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, **kw),
    )
    service, run, _sid, request, send = await make_run(tmp_path / "run", enabled=True)
    try:
        await send(
            "advance",
            C.ADVANCE_TO,
            {"virtual_time_ms": request.requested_start_ms + 3 * 60000 - 1},
        )
        parent = (await service.training.get_market_tracks(run))["portfolio"]
        expected = parent
        await service.training.record_review_marker(
            run, command_id="fork-here", text="HEDGE interval endpoint"
        )
        event_id = None
        if historical_anchor:
            # A real interval anchor before funding and before the mark changed,
            # not just the ordinary command/marker after the terminal tail.
            anchor = await service.store.run_extension_read(
                lambda c: c.execute(
                    "SELECT end_time_ms,summary_json,basis_json FROM replay_multi_bar_interval "
                    "WHERE run_id=? AND end_time_ms>? AND end_time_ms<? ORDER BY end_time_ms LIMIT 1",
                    (
                        run,
                        request.requested_start_ms + 60000,
                        request.requested_start_ms + 120000,
                    ),
                ).fetchone()
            )
            event_id = await service.store.run_extension_read(
                lambda c: c.execute(
                    "SELECT event_id FROM replay_review_timeline_event WHERE run_id=? AND virtual_time_ms=? "
                    "ORDER BY timeline_sequence DESC LIMIT 1",
                    (run, anchor[0]),
                ).fetchone()[0]
            )
        review = await service.training.start_review(run, event_id=event_id)
        if historical_anchor:
            expected = review["projection"]["domain"]["portfolio"]
            assert Decimal(expected["equity"]) == Decimal(json.loads(anchor[1])["last"])
            assert expected["equity"] != parent["equity"]
        for key in (
            "equity",
            "available_equity",
            "unrealized_pnl",
            "margin_used",
            "reserved_margin",
        ):
            assert review["projection"]["domain"]["portfolio"][key] == expected[key]
        fork = await service.training.fork_run(
            run, event_id=review["selected_event_id"]
        )
        child = fork["run"]["run_id"]
        restored = (await service.training.get_market_tracks(child))["portfolio"]
        if historical_anchor:
            for key in (
                "equity",
                "available_equity",
                "unrealized_pnl",
                "margin_used",
                "reserved_margin",
            ):
                assert restored[key] == expected[key]
            assert [
                {"track_id": p["track_id"], "position_side": p["position_side"],
                 "quantity": p["position"]["quantity"]}
                for p in restored["positions"]
            ] == expected["positions"]
            assert Decimal(restored["cash_balance"]) == Decimal(
                json.loads(anchor[2])["cash"]
            )
            assert restored["fees_paid"] == parent["fees_paid"]
            assert restored["funding_cashflow"] == "0"
            heads = await service.training.store.get_market_track_heads(child)
            assert all(
                Decimal(t["position"][leg]["mark_price"]) == 100
                for t in heads
                for leg in ("long", "short")
            )
        else:
            for key in (
                "equity",
                "cash_balance",
                "positions",
                "fees_paid",
                "funding_cashflow",
            ):
                assert restored[key] == expected[key]
        assert (await service.training.audit_account(child))["status"] == "PASS"
        assert (await service.training.get_market_tracks(run))["portfolio"] == parent
        rows = await service.store.run_extension_read(
            lambda c: [
                tuple(r)
                for r in c.execute(
                    "SELECT command_id,start_time_ms,end_time_ms,summary_json,basis_json FROM replay_multi_bar_interval WHERE run_id=? ORDER BY end_time_ms",
                    (run,),
                )
            ]
        )
        snapshot = {
            "rows": rows,
            "end": rows[-1][2],
            "run_id": run,
            "versions": {},
            "settlement_asset": "USDT",
            "markets": [],
        }
        exported = [
            json.loads(line) for line in export_intervals(snapshot, input_root=tmp_path)
        ]
        assert exported[0]["schema"] == "replay.portfolio-curve-export.v3"
        assert any(row.get("kind") == "pinned_hedge_mark" for row in exported)
        assert not any(row.get("kind") == "trade_mark" for row in exported)
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.parametrize("failure", [False, "write", "risk", "inputs"])
async def test_hedge_tape_atomic_failure_or_restart_resumes_parent(
    tmp_path, monkeypatch, failure
):
    source = fixtures._multi_trade_sources
    monkeypatch.setattr(
        fixtures,
        "_multi_trade_sources",
        lambda *a, **kw: source(*a, trades_per_minute=60, **kw),
    )
    root = tmp_path / "run"
    service, run, sid, _request, _send_command = await make_run(root, enabled=True)
    try:
        kwargs = await arguments(service, run, sid)
        kwargs[
            "runtime_snapshot"
        ] = await service.training.hedge_inputs.runtime_snapshot(run)
        before = await service.get_session_state(sid)
        events_before = await service.training.store.global_events(run)
        portfolio_before = (await service.training.get_market_tracks(run))["portfolio"]
        commit = service.store.commit_command_phases

        async def intercepted(phases):
            assert service._sessions[sid].actor._events.after(before["sequence"]) == ()
            if failure in {"write", "risk"}:
                rows, pre, post = phases[-1]

                def fail(connection):
                    post(connection)
                    raise (
                        tape_phases.TapeRiskBoundary()
                        if failure == "risk"
                        else RuntimeError("injected write")
                    )

                phases = [*phases[:-1], (rows, pre, fail)]
            return await commit(phases)

        monkeypatch.setattr(service.store, "commit_command_phases", intercepted)
        if failure == "inputs":
            from app.replay.training import hedge_tape_interval

            monkeypatch.setattr(
                hedge_tape_interval, "validate_input_cursors", lambda *args: False
            )
        if failure == "write":
            with pytest.raises(RuntimeError, match="injected write"):
                await tape_phases.try_advance(service.training, **kwargs)
        else:
            result = await tape_phases.try_advance(service.training, **kwargs)
            assert (result is None) == bool(failure)
        monkeypatch.setattr(service.store, "commit_command_phases", commit)
        if failure:
            after = await service.get_session_state(sid)
            assert (after["cursor"], after["state_hash"]) == (
                before["cursor"],
                before["state_hash"],
            )
            assert await service.training.store.global_events(run) == events_before
            assert (await service.training.get_market_tracks(run))[
                "portfolio"
            ] == portfolio_before
            assert service._sessions[sid].actor._events.after(before["sequence"]) == ()
        else:
            published = service._sessions[sid].actor._events.after(before["sequence"])
            assert len(published) == 1
            event = published[0]
            assert event.type.value == "replay.snapshot"
            emitted = event.data["snapshot"]
            assert emitted["status_reason"] == "tape_cohort_batch_complete"
            current = await service.get_session_state(sid)
            assert emitted["sequence"] == event.sequence == current["sequence"]
            for key in ("revision", "state_hash", "cursor"):
                assert emitted[key] == current[key]
            await service.shutdown(step_timeout=5)
            service = await fixtures._trade_service(
                root / "run.db", archive_root=root / "tape", symbols=("BTCUSDT",)
            )
            service.settings = replace(
                service.settings, replay_fast_forward_optimization_enabled=True
            )
            recovered = await service.training.command(run, kwargs["command"])
            assert recovered["data"]["recovered"] is True
            assert recovered["cursor"]["virtual_time_ms"] == kwargs["target"]
            assert await service.training.command(run, kwargs["command"]) == recovered
            assert (await service.training.audit_account(run))["status"] == "PASS"
            await _assert_complete_global_prefix(service, run)
    finally:
        await service.shutdown(step_timeout=5)
