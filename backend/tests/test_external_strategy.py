from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.backtests import router
from tests.test_native_backtests import runtime, terminal, pytestmark

PINE = '''//@version=6
strategy("Feedback")
if close > 12 and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty=2)
if close < 9 and strategy.position_size > 0
    strategy.close("L")
plot(strategy.position_size)
plot(strategy.equity)
'''
PYNE = '''strategy("Feedback")
strategy.entry_when((close > 12) & (strategy.position_size == 0), "L", strategy.long, qty=2)
strategy.close_when((close < 9) & (strategy.position_size > 0), "L")
plot(strategy.position_size)
plot(strategy.equity)
'''
INCREMENTAL = '''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    if bar.close > 12 and ctx.strategy.position_size == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=2)
    if bar.close < 9 and ctx.strategy.position_size > 0:
        ctx.strategy.close("L")
'''


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", PYNE), ("pyne", INCREMENTAL)])
def test_host_matching_feedback_controls_complete_script_and_owns_report(runtime, language, source):
    host, payload = runtime
    app = FastAPI()
    app.state.backtest_runtime = host
    app.include_router(router)
    payload.update(language=language, source=source, host_settings={"initial_balance": 10000, "slippage_bps": 100, "taker_fee_bps": 10})
    with TestClient(app) as client:
        response = client.post("/backtests/external/runs", json=payload, headers={"Idempotency-Key": "external"})
        assert response.status_code == 200, response.text
        result = terminal(host.native, response.json()["run_id"])
        assert result["state"] == "COMPLETED", result
        report = result["result"]
        assert report["execution_mode"] == "CANDLESCOPE"
        assert report["account_authority"] == "candlescope"
        assert report["trades"] and report["orders"]
        raw = report["raw_output"]
        assert float(raw["kernel"]["ledger"]["fee_total"]) > 0
        feedback = raw["account_feedback"]
        assert feedback[4]["position_size"] == 2
        assert feedback[4]["position_avg_price"] > 20  # real host slippage, not native assumed price
        assert not raw["strategy_output"].get("strategy")
        if language == "pine":
            assert raw["strategy_output"]["plots"][0]["values"] == [frame["position_size"] for frame in feedback]
            assert raw["strategy_output"]["plots"][1]["values"] == [frame["equity"] for frame in feedback]
        assert client.get("/backtests/native/runs").json()["runs"] == []
        assert len(client.get("/backtests/external/runs").json()["runs"]) == 1
        assert client.get(f"/backtests/external/runs/{result['run_id']}/export").json() == result
        with pytest.raises(ValueError, match="native replay"):
            host.native.replay.create(result["run_id"])


@pytest.mark.parametrize("language,source", [("pine", PINE.replace('qty=2)', 'qty=2, comment="unsupported")')),
                                           ("pyne", PYNE.replace('qty=2)', 'qty=2, comment="unsupported")'))])
def test_host_mode_rejects_unsupported_orders_without_native_fallback(runtime, language, source):
    host, payload = runtime
    payload.update(language=language, source=source, execution_mode="CANDLESCOPE",
                   host_settings={"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0})
    record = host.native.create(payload, "reject")
    result = terminal(host.native, record["run_id"])
    assert result["state"] == "FAILED"
    assert result["result"] is None


def test_host_mode_rejects_prefix_repainting_decisions(runtime):
    host, payload = runtime
    source = '''//@version=6
strategy("Noncausal")
if barstate.islast
    strategy.entry("L", strategy.long)
'''
    payload.update(source=source, execution_mode="CANDLESCOPE",
                   host_settings={"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0})
    record = host.native.create(payload, "noncausal")
    result = terminal(host.native, record["run_id"])
    assert result["state"] == "FAILED"
    assert "EXTERNAL_NONCAUSAL_PREFIX" in result["error"]["message"]
    assert result["result"] is None
