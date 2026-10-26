from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.backtests import router
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark

PINE = '''//@version=6
strategy("Feedback")
if close > 12 and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty=2)
if close < 9 and strategy.position_size > 0
    strategy.close("L")
plot(strategy.position_size)
plot(strategy.equity)
'''


@pytest.mark.parametrize("language,source", [("pine", PINE)])
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
        if language == "pine":
            replay = host.native.replay.create(result["run_id"])
            assert replay["method"] == "HOST_ACCOUNT_CHECKPOINT"
            assert replay["cursor"] == 0 and replay["result"] is None
            assert replay["execution_mode"] == "CANDLESCOPE"
        else:
            with pytest.raises(ValueError, match="external replay"):
                host.native.replay.create(result["run_id"])


@pytest.mark.parametrize("language,source", [("pine", PINE.replace('qty=2)', 'qty=2, comment="entry note")'))])
def test_host_mode_preserves_order_comments_without_native_fallback(runtime, language, source):
    host, payload = runtime
    payload.update(language=language, source=source, execution_mode="CANDLESCOPE",
                   host_settings={"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0})
    record = host.native.create(payload, "reject")
    result = terminal(host.native, record["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["account_authority"] == "candlescope"
    assert result["result"]["trades"][0]["pine_comment"] == "entry note"


def test_host_mode_fixed_horizon_does_not_repaint_islast_on_each_prefix(runtime):
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
    assert result["state"] == "COMPLETED", result.get("error")
    report = result["result"]
    assert [intent["bar_index"] for intent in report["raw_output"]["intent_history"]] == [9]
    assert report["trades"] == []  # Last-bar order has no later execution event.
    from app.backtest.native_replay import NativeReplay
    from tests.test_native_replay import settle
    service = host.native.replay
    replay = service.create(result["run_id"])
    key = replay["replay_id"]
    service.command(key, replay["revision"], "seek", 5)
    middle = settle(service, key)
    assert middle["result"]["raw_output"]["intent_history"] == []
    saved = service.snapshot(key, middle["revision"])
    checkpoint = saved["snapshots"][0]["snapshot_id"]
    service.command(key, service.get(key)["revision"], "seek", 10)
    assert settle(service, key)["result"] == report
    service.restore(key, service.get(key)["revision"], checkpoint)
    service.shutdown()
    service = host.native.replay = NativeReplay(host.native)
    service.command(key, service.get(key)["revision"], "seek", 10)
    assert settle(service, key)["result"] == report
