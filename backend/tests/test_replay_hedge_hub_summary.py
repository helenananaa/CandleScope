"""Archive cards must retain the pinned mark before lazy actor recovery."""

import sqlite3
from dataclasses import replace

import pytest

from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("return_to_hub", [False, True])
@pytest.mark.parametrize("position_side", ["LONG", "SHORT"])
async def test_held_hedge_archive_equity_uses_pinned_mark_after_shutdown(tmp_path, return_to_hub, position_side):
    database = tmp_path / "summary.db"
    service = await _risk_service(database, symbols=("BTCUSDT",))
    try:
        request = await prepare_hedge_request(
            service, replace(_sandbox_request(await _request(service)), market_type="futures"),
            root=tmp_path, prefix="summary", mark_prices=["104"] * 13,
        )
        created = await service.training.create_run(request)
        run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
        await _send(service, run_id=run, session_id=sid, command_id="open",
                    command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                        "client_order_id": "open", "position_side": position_side,
                        "side": "BUY" if position_side == "LONG" else "SELL",
                        "order_type": "MARKET", "quantity": "1", "reduce_only": False,
                        "limit_price": None, "stop_price": None})
        await _send(service, run_id=run, session_id=sid, command_id="step",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        saved = (await service.training.get_market_tracks(run))["portfolio"]
        assert saved["positions"][0]["position"]["mark_price"] == "104"
        stable_financials = {key: saved[key] for key in ("cash_balance", "fees_paid", "realized_pnl")}
        if return_to_hub:
            await service.training.return_to_hub(run)
            assert (await service.training.store.get_run(run))["equity"] == saved["equity"]
            tracks = await service.training.get_market_tracks(run)
            leg = "long" if position_side == "LONG" else "short"
            assert tracks["tracks"][0]["position"][leg]["mark_price"] == "104"
            assert {key: tracks["portfolio"][key] for key in stable_financials} == stable_financials
    finally:
        await service.shutdown(step_timeout=1.0)
    with sqlite3.connect(database) as connection:
        summary = connection.execute("SELECT current_equity FROM replay_training_run WHERE run_id=?", (run,)).fetchone()[0]
    assert summary == saved["equity"]

    restored = await _risk_service(database, symbols=("BTCUSDT",))
    try:
        # Read the hub card before lazy actor recovery, then restore the actor.
        assert (await restored.training.get_run(run))["equity"] == saved["equity"]
        tracks = await restored.training.get_market_tracks(run)
        portfolio = tracks["portfolio"]
        assert portfolio["equity"] == saved["equity"]
        assert portfolio["positions"] == saved["positions"]
        assert {key: portfolio[key] for key in stable_financials} == stable_financials
    finally:
        await restored.shutdown(step_timeout=1.0)
