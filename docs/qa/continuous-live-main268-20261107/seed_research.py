"""Create one completed research run in a fresh Native QA profile.

The research fixture uses deterministic bars. The eventual chart account must
initialize and advance through the installed application's ordinary LIVE source.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions

profile = Path(sys.argv[1]).resolve()
data = profile / "data"
data.mkdir(parents=True, exist_ok=False)
program_model = Path("frontend/src/features/backtest/chart-tester/chartStrategyTesterUiModel.ts")
program = json.loads(program_model.read_text().split("export const PYTHON_SMA_SOURCE = ", 1)[1].split(";\n", 1)[0])
settings = load_backtest_settings(
    {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
    data_dir=data,
    klines_db_path=data / "market.db",
    replay_db_path=data / "replay.db",
)
start = (int(time.time()) // 60 - 25) * 60000
end = start + 20 * 60000
csv = profile.parent / "research-bars.csv"
csv.write_text("time,open,high,low,close,volume\n" + "".join(
    f"{start + i * 60000},{100 + i % 7},{102 + i % 7},{99 + i % 7},{101 + i % 7},100\n"
    for i in range(20)
))
local_root = profile / "local-data"
manifest = LocalDatasetService(local_root).import_csv(
    csv, LocalImportOptions(name="Native QA frozen research", symbol="BTCUSDT", interval="1m", timestamp_unit="ms")
)
runtime = BacktestRuntime.start(settings, local_data_dir=local_root)
service = runtime.service
try:
    revision = service.create_strategy_revision({
        "name": "Native QA selected Python SMA",
        "language": "PYTHON_EDITOR",
        "source_text": program,
        "parameter_schema": [],
    })
    snapshot = runtime.preview_snapshot(
        dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
        start_time_ms=start, end_time_ms=end, interval="1m", exchange="binance",
        market_type="spot", account_model="SPOT_CASH_V1",
    )
    body = dict(
        strategy_revision_id=revision["revision_id"], dataset_id=manifest["dataset_id"],
        data_epoch=manifest["data_epoch"], snapshot_hash=snapshot["snapshot_hash"],
        fidelity_mode="BAR_APPROX", source_event_kind="BAR",
        start_time_ms=start, end_time_ms=start + 20 * 60000,
        symbol="BTCUSDT", interval="1m", parameters={"fast": 3, "slow": 7},
        output_mode="TARGET_POSITION", initial_balance="5000", account_model="SPOT_CASH_V1",
        contract_data_mode="LEGACY_FIXED_V1", funding_mode="OFF", funding_rate="0",
        leverage="1", sizing_policy="EQUITY_PERCENT_V1", equity_percent="20",
        slippage_bps="2", taker_fee_bps="3.5", maker_fee_bps="3.5",
        execution_model_revision="EXECUTION_REALISM_V2", participation_rate="0.1",
        order_end_policy="CANCEL_AT_END", gap_policy="REJECT",
        quick_preset_id="CRYPTO_SPOT_STANDARD_V1", quick_preset_revision="2",
        fee_source="user-defined", exchange="binance", market_type="spot",
        python_runtime_mode="TRUSTED_LOCAL", python_trusted_confirmed=True,
    )
    service.smoke_strategy_revision(revision["revision_id"], body)
    run = service.create_run(body, idempotency_key="native-selected-research-20")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        completed = service.get_run(run["run_id"])
        if completed["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(0.05)
    assert completed["state"] == "COMPLETED", completed
    report = service.get_report(run["run_id"])
    assert report["fills"]
    chart = runtime.chart_data(run["run_id"])
    assert len(chart["bars"]) == 20
    selected = service.selected_run_version(run["run_id"])
    assert selected["program"]["source_text"] == program
    assert selected["configuration"]["start_time_ms"] == start
finally:
    runtime.shutdown()

receipt = {
    "scope": "Completed synthetic research fixture only, no continuous account and no LIVE launch.",
    "runId": run["run_id"], "selected": selected,
    "researchFillCount": len(report["fills"]),
    "backtestDbSha256": hashlib.sha256(settings.db_path.read_bytes()).hexdigest(),
}
(profile.parent / "research-seed.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"researchRunId": run["run_id"], "fills": receipt["researchFillCount"], "startMs": start}))
