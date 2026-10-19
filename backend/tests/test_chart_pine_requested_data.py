import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router
from app.backtest.errors import BacktestError
from app.backtest.pine_requested_data import load_contexts, normalize_contexts
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.local_data.service import LocalImportOptions
from tests.test_chart_pine_engine import frame
from tests.test_native_additional_inputs import additional
from tests.test_native_backtests import runtime as runtime, pytestmark as pytestmark

SOURCE = '''//@version=6
strategy("Requested chart")
remote = request.security("OKX:ETH-USDT", "2", close)
if remote >= 200 and strategy.position_size == 0
    strategy.entry("L",strategy.long,qty=2)
if remote >= 400
    strategy.close("L")
plot(remote)
'''


def inputs(host):
    reference = additional(host, "higher", "ETH-USDT", "2m", 120000, [100, 200, 300, 400, 500])
    return {**reference, "symbol": "OKX:ETH-USDT", "timeframe": "2", "exchange": "okx", "market_type": "spot"}


@pytest.mark.parametrize("profile", ["higher", "dynamic", "library", "lower", "prepared", "metadata"])
def test_queued_chart_run_uses_frozen_requested_data_and_authoritative_fills(runtime, profile):
    host, main = runtime
    context = inputs(host)
    source, libraries = SOURCE, {}
    if profile == "metadata":
        context["metadata"] = {"priceTickSize": ".25", "currency": "USDT"}
        source = source.replace('"2", close)', '"2", close + syminfo.mintick)')
    if profile == "dynamic":
        source = source.replace('remote = request.security("OKX:ETH-USDT", "2", close)',
            'instrument = input.symbol("OKX:ETH-USDT")\nremote = request.security(instrument,"2",close)')
    if profile == "library":
        source = source.replace('remote = request.security("OKX:ETH-USDT", "2", close)',
            'import local/Higher/1 as helper\nremote = helper.value()')
        libraries = {"local/Higher/1": '//@version=6\nlibrary("Higher")\nexport value() => request.security("OKX:ETH-USDT","2",close)'}
    if profile == "lower":
        context = {**additional(host, "lower", "ETH-USDT", "30s", 30000, [value for value in range(100,1100,100) for _ in range(2)]),
            "symbol": "OKX:ETH-USDT", "timeframe": "30S", "exchange": "okx", "market_type": "spot"}
        source = source.replace('remote = request.security("OKX:ETH-USDT", "2", close)',
            'values = request.security_lower_tf("OKX:ETH-USDT","30S",close)\nremote = array.avg(values)')
    revision = host.service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Requested", "source_text": source, "libraries": libraries})
    payload = {key: main[key] for key in ("dataset_id", "data_epoch", "snapshot_hash", "interval", "start_time_ms", "end_time_ms")}
    payload.update(strategy_revision_id=revision["revision_id"], fidelity_mode="BAR_APPROX", source_event_kind="BAR",
        exchange="binance", market_type="usdm", symbol="BTCUSDT", pine_contexts=[context],
        account_model="LINEAR_PERP_ONE_WAY_V1", initial_balance="10000", slippage_bps="0", taker_fee_bps="0")
    if profile == "metadata":
        payload["price_tick"] = ".1"
    host.service.smoke_strategy_revision(revision["revision_id"], {**payload, "parameters": {}})
    app = FastAPI()
    app.state.backtest_runtime = host
    app.state.backtest_service = host.service
    app.include_router(router)
    if profile == "prepared":
        from app.api.v1.data_preparation import StrategyLaunchPayload
        from app.backtest.quick_presets import quick_preset_for_market
        from app.data_preparation.strategy_launcher import launch
        preset = quick_preset_for_market("usdm")
        intent = StrategyLaunchPayload(strategy_revision_id=revision["revision_id"], parameters={}, pine_contexts=[context]).model_dump()
        resolution = {**main, "request": {"exchange": "binance", "market_type": "usdm", "symbol": "BTCUSDT", "interval": "1m", "range_mode": "CUSTOM"},
            "fidelity": {"mode": "BAR_APPROX"}, "coverage": {"requested_start_ms": 0, "requested_end_ms": 599999},
            "quick_preset_id": preset["id"], "account_execution_preset": preset,
            "cost_preset": {**preset, "preset_revision": preset["revision"]}}
        record = launch(host, intent, resolution, "pinned-auxiliary")
    else:
        with TestClient(app) as client:
            response = client.post("/backtests/runs", json=payload, headers={"Idempotency-Key": "requested-chart"})
            assert response.status_code == 200, response.text
            record = response.json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = host.service.get_run(record["run_id"])
        if result["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(.05)
    assert result["state"] == "COMPLETED", result
    report = host.service.get_report(record["run_id"])
    # BAR_APPROX records fills at the next host bar event, whose timestamp is
    # its inclusive close. Requested HTF values first appear at their own close.
    expected_times = [179999, 299999] if profile == "lower" else [299999, 539999]
    assert [row["event_time_ms"] for row in report["fills"]] == expected_times
    assert [float(row["qty"]) for row in report["fills"]] == [2, 2]
    config = json.loads(result["config_json"])
    assert config["pine_contexts"] == [context]
    assert config["pine_local_data_root"] == str(host.local_data.root)


def test_restore_reads_the_pinned_revision_after_a_new_active_revision_is_imported(runtime):
    host, _ = runtime
    context = inputs(host)
    revision = host.service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Requested", "source_text": SOURCE})
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        stored = host.service.repository.get_strategy_revision(revision["revision_id"])
        provider.prepare({"source": json.loads(stored["compiled_json"])["executionSource"], "parameters": {},
            "pineChartInterval": "1m", "pineLocalDataRoot": str(host.local_data.root), "pineRequestedContexts": [context]})
        for i in range(3):
            assert provider.step(frame(i, 20)) is None
        snapshot = provider.snapshot()
        assert "bars" not in snapshot["context"]["pineRequestedContexts"][0]
        path = host.settings.db_path.parent / "new-aux.csv"
        path.write_text("time,open,high,low,close,volume\n" + "\n".join(
            f"{i*120000},{900+i},{901+i},{899+i},{900+i},1" for i in range(8)), encoding="utf-8")
        latest = host.local_data.import_csv(path, LocalImportOptions(name="new", symbol="ETH-USDT", interval="2m",
            timestamp_unit="ms", dataset_id=context["dataset_id"]))
        assert latest["data_epoch"] != context["data_epoch"]
        restored.restore(snapshot)
        result = provider.step(frame(3, 20))
        assert result.payload["targetExposure"] == "2.0"
        assert restored.step(frame(3, 20)) == result
    finally:
        provider.close()
        restored.close()


@pytest.mark.parametrize("changed", [{"snapshot_hash": "sha256:" + "0"*64}, {"symbol": "OKX:BTC-USDT"}, {"exchange": "binance"}])
def test_bad_frozen_contexts_fail_before_trading(runtime, changed):
    host, _ = runtime
    with pytest.raises(BacktestError, match="snapshot|symbol|exchange"):
        load_contexts(host.local_data.root, [{**inputs(host), **changed}])


def test_duplicate_or_mismatched_timeframes_are_not_accepted(runtime):
    host, _ = runtime
    context = inputs(host)
    for refs in ([context, context], [{**context, "timeframe": "5"}]):
        with pytest.raises(BacktestError, match="Duplicate context|mismatched timeframe"):
            normalize_contexts(refs)
