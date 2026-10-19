"""Fixed-model funding must charge actual HEDGE legs at the shared boundary."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request, import_hedge_track_public_inputs
from tests.test_replay_v2_training_phase5 import _acquire, _request, _command
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("rate", ["0.001", "-0.001"])
async def test_fixed_funding_charges_nonzero_hedge_leg(tmp_path, rate):
    service = await _risk_service(tmp_path / "fixed-funding.db")
    try:
        prepared = await prepare_hedge_request(
            service,
            replace(_sandbox_request(await _request(service)), market_type="futures"),
            root=tmp_path, prefix="fixed-funding", book_mode="OFF",
            mark_prices=["100"] * 13, funding_event_offset_bars=12,
        )
        request = replace(prepared, funding_mode="SANDBOX_FIXED",
                          fixed_funding_rate=rate, funding_interval_ms=60_000)
        created = await service.training.create_run(request)
        run = created["run"]["run_id"]
        sid = created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
        await _send(service, run_id=run, session_id=sid, command_id="long",
                    command_type=ReplayV2CommandType.PLACE_ORDER,
                    payload={"client_order_id": "long", "position_side": "LONG",
                             "side": "BUY", "order_type": "MARKET", "quantity": "1",
                             "reduce_only": False, "limit_price": None, "stop_price": None})
        before = (await service.training.get_market_tracks(run))["portfolio"]
        assert before["positions"][0]["position"]["quantity"] == "1"
        await _send(service, run_id=run, session_id=sid, command_id="cross-funding",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        after = (await service.training.get_market_tracks(run))["portfolio"]
        assert after["fidelity"]["funding"] == "AVAILABLE_APPROX_SANDBOX_FIXED"
        expected = -Decimal("100") * Decimal(rate)
        assert Decimal(after["funding_cashflow"]) == expected
        assert Decimal(after["cash_balance"]) - Decimal(before["cash_balance"]) == expected
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
    finally:
        await service.shutdown(step_timeout=1.0)


async def _place(service, run, sid, key, side, quantity, *, close=False):
    return await _send(service, run_id=run, session_id=sid, command_id=key,
                       command_type=ReplayV2CommandType.PLACE_ORDER,
                       payload={"client_order_id": key, "position_side": side,
                                "side": ("SELL" if close else "BUY") if side == "LONG" else ("BUY" if close else "SELL"),
                                "order_type": "MARKET", "quantity": quantity,
                                "reduce_only": close, "limit_price": None, "stop_price": None})


@pytest.mark.parametrize("time_policy", ["NONE", "HIDE_ALL"])
@pytest.mark.parametrize("bars,periods", [(2, 1), (5, 3)])
@pytest.mark.parametrize("closed", [False, True])
async def test_multitrack_fixed_funding_rounds_each_leg_recovers_and_forks(tmp_path, time_policy, bars, periods, closed):
    database = tmp_path / "multiple-fixed.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        prepared = await prepare_hedge_request(
            service, replace(_sandbox_request(await _request(service)), market_type="futures",
                             time_disclosure_policy=time_policy),
            root=tmp_path, prefix="multiple-fixed", book_mode="OFF",
            mark_prices=["100"] * 13, required_symbols=["BTCUSDT", "ETHUSDT"],
            funding_event_offset_bars=12,
        )
        request = replace(prepared, funding_mode="SANDBOX_FIXED",
                          fixed_funding_rate="0.00003", funding_interval_ms=90_000)
        await import_hedge_track_public_inputs(service, request, root=tmp_path,
                                              prefix="multiple-fixed", symbol="ETHUSDT",
                                              mark_prices=["200"] * 13, include_book=False)
        created = await service.training.create_run(request)
        run, primary = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=primary, command_id="acquire")
        await _place(service, run, primary, "long-primary", "LONG", "1")
        await _place(service, run, primary, "short-primary", "SHORT", "1")
        added = await _send(service, run_id=run, session_id=primary, command_id="add-secondary",
                            command_type=ReplayV2CommandType.ADD_TRACK,
                            payload={"exchange": "binance", "market_type": "futures", "symbol": "ETHUSDT",
                                     "settlement_asset": "USDT", "subscription_tier": "FULL"})
        selected = await _send(service, run_id=run, session_id=primary, command_id="select-secondary",
                               command_type=ReplayV2CommandType.SELECT_TRACK,
                               payload={"track_id": added["data"]["track"]["track_id"], "expected_viewer_revision": 0})
        sid = selected["session_id"]
        await _place(service, run, sid, "short-secondary", "SHORT", "2")
        before = (await service.training.get_market_tracks(run))["portfolio"]
        advance = _command(run, "funding-between-bars", ReplayV2CommandType.STEP_BASE,
                           await service.get_session(sid), {"count": bars})
        result = await service.training.command(run, advance)
        after = (await service.training.get_market_tracks(run))["portfolio"]
        expected_total = Decimal("0.02") * periods
        assert Decimal(after["cash_balance"]) - Decimal(before["cash_balance"]) == expected_total
        assert Decimal(after["funding_cashflow"]) == expected_total
        leg_funding = {(x["track_id"], x["position_side"]): x["accumulated_funding"]
                       for x in after["hedge_state"]["position_legs"]}
        assert {k: Decimal(v) for k, v in leg_funding.items()} == {
            ("track-1", "LONG"): Decimal("-0.01") * periods,
            ("track-1", "SHORT"): Decimal("0.01") * periods,
            ("track-2", "LONG"): Decimal(0),
            ("track-2", "SHORT"): expected_total}
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        after = (await service.training.get_market_tracks(run))["portfolio"]
        retry = await service.training.command(run, advance)
        assert retry == result
        assert (await service.training.get_market_tracks(run))["portfolio"] == after
        if closed:
            await _place(service, run, sid, "close-secondary", "SHORT", "2", close=True)
            await _send(service, run_id=run, session_id=sid, command_id="close-select-primary",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-1", "expected_viewer_revision": 1})
            await _place(service, run, primary, "close-long", "LONG", "1", close=True)
            await _place(service, run, primary, "close-short", "SHORT", "1", close=True)
            after = (await service.training.get_market_tracks(run))["portfolio"]
            assert after["positions"] == []
            assert Decimal(after["funding_cashflow"]) == expected_total
        funding_review = await service.training.start_review(run, event_id=None)
        assert any(event["event_type"] == "FUNDING_SETTLEMENT" for event in funding_review["events"])
        await service.training.record_review_marker(run, command_id="fixed-fork", text="Fixed funding settled")
        review = await service.training.start_review(run, event_id=None)
        child = (await service.training.fork_run(run, event_id=review["selected_event_id"]))["run"]["run_id"]
        child_portfolio = (await service.training.get_market_tracks(child))["portfolio"]
        assert Decimal(child_portfolio["funding_cashflow"]) == expected_total
        assert child_portfolio["cash_balance"] == after["cash_balance"]
        assert (await service.training.audit_account(child))["status"] == "PASS"
        saved = after
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored.training.get_market_tracks(run))["portfolio"] == saved
        assert (await restored.training.audit_account(run))["status"] == "PASS"
        assert (await restored.training.audit_account(child))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)


async def test_fixed_funding_waits_for_same_time_trade_close_cohort(tmp_path, monkeypatch):
    from tests import test_replay_v2_training_phase5 as tape

    original_import = tape.ParquetRawAggTradeArchive.import_verified_day

    def at_minute_boundary(archive, rows, metadata):
        shifted = [{**row, "is_buyer_maker": not row["is_buyer_maker"],
                    **{key: int(row[key]) - 1000
                              for key in ("trade_time_ms", "event_time_ms", "received_at_ms")}}
                   for row in rows]
        return original_import(archive, shifted, replace(
            metadata, first_trade_time_ms=metadata.first_trade_time_ms - 1000,
            last_trade_time_ms=metadata.last_trade_time_ms - 1000))

    monkeypatch.setattr(tape.ParquetRawAggTradeArchive, "import_verified_day", at_minute_boundary)
    original_sources = tape._multi_trade_sources
    monkeypatch.setattr(tape, "_multi_trade_sources", lambda *args, **kwargs:
                        original_sources(*args, coalesce_trade_timestamps=True, **kwargs))
    service = await tape._trade_service(tmp_path / "same-time-fixed.db", archive_root=tmp_path / "tape",
                                        symbols=("BTCUSDT",))
    try:
        marks = [str(100 + 10 * i) for i in range(tape.TRADE_REPLAY_MINUTES + 1)]
        prepared = await prepare_hedge_request(
            service, replace(await tape._trade_request(service), integrity_mode="SANDBOX"),
            root=tmp_path, prefix="same-time-fixed", book_mode="OFF", mark_prices=marks,
            funding_event_offset_bars=tape.TRADE_REPLAY_MINUTES,
        )
        request = replace(prepared, funding_mode="SANDBOX_FIXED",
                          fixed_funding_rate="0.001", funding_interval_ms=60_000)
        created = await service.training.create_run(request)
        run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
        await _place(service, run, sid, "long", "LONG", "1")
        await _place(service, run, sid, "short", "SHORT", "1")
        await _send(service, run_id=run, session_id=sid, command_id="close-at-next-print",
                    command_type=ReplayV2CommandType.PLACE_ORDER,
                    payload={"client_order_id": "close-at-next-print", "position_side": "LONG",
                             "side": "SELL", "order_type": "LIMIT", "quantity": "1",
                             "reduce_only": True, "limit_price": "100.5", "stop_price": None})
        await _send(service, run_id=run, session_id=sid, command_id="first-minute",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        first = await _send(service, run_id=run, session_id=sid, command_id="first-boundary-print",
                            command_type=ReplayV2CommandType.STEP_EVENT, payload={"count": 1})
        partial = (await service.training.get_market_tracks(run))["portfolio"]
        assert partial["funding_cashflow"] == "0"
        assert partial["next_funding_time_ms"] == request.requested_start_ms + 60_000
        assert [(p["position_side"], p["position"]["quantity"]) for p in partial["positions"]] == [("SHORT", "-1")]
        assert partial["positions"][0]["position"]["mark_price"] == "100"
        second = await _send(service, run_id=run, session_id=sid, command_id="last-boundary-print",
                             command_type=ReplayV2CommandType.STEP_EVENT, payload={"count": 1})
        final = (await service.training.get_market_tracks(run))["portfolio"]
        assert second["cursor"]["source_sequence"] == first["cursor"]["source_sequence"] + 1
        assert second["cursor"]["virtual_time_ms"] == first["cursor"]["virtual_time_ms"]
        assert final["funding_cashflow"] == "0.11"
        assert final["positions"][0]["position"]["mark_price"] == "110"
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        review = await service.training.start_review(run, event_id=None)
        assert any(e["event_type"] == "FUNDING_SETTLEMENT" for e in review["events"])
    finally:
        await service.shutdown(step_timeout=1.0)
