"""ADR-BACKTEST-015 P0: the three Pine execution paths pinned to financial oracles.

Needs the qualified Pine runtime, so it runs in the "Pine host contracts"
workflow (``qualify_host_contracts.py``) rather than the plain backend job.
See ``tests/strategy_run_oracles.py`` for the scenario and how to regenerate.
"""
from __future__ import annotations

import os

import pytest

from app.backtest.native import resolve_plugin
from app.backtest.runtime import BacktestRuntime
from app.backtest.service import BacktestService
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions
from tests import strategy_run_oracles as oracles
from tests.test_native_backtests import terminal

pytestmark = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),
                                reason="requires the qualified installed Pine runtime")
END_MS = len(oracles.bars()) * 60_000 - 1


def _settings(tmp_path):
    return load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
                                  data_dir=tmp_path, klines_db_path=tmp_path / "candlescope.db",
                                  replay_db_path=tmp_path / "replay.db")


@pytest.fixture
def native_runtime(tmp_path, qualified_pine):
    """Backtest runtime over a local dataset holding exactly the oracle bars."""
    csv = tmp_path / "oracle-bars.csv"
    csv.write_text(oracles.bars_csv(), encoding="utf-8")
    manifest = LocalDatasetService(tmp_path / "local").import_csv(
        csv, LocalImportOptions(name="oracle", symbol="BTCUSDT", interval="1m", timestamp_unit="ms"))
    runtime = BacktestRuntime.start(_settings(tmp_path), local_data_dir=tmp_path / "local")
    runtime.native.resolver = resolve_plugin
    snapshot = runtime.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
                                        start_time_ms=0, end_time_ms=END_MS, interval="1m")
    request = {"language": "pine", "source": oracles.PINE_SMA_SOURCE, "dataset_id": manifest["dataset_id"],
               "data_epoch": manifest["data_epoch"], "snapshot_hash": snapshot["snapshot_hash"],
               "start_time_ms": 0, "end_time_ms": END_MS, "interval": "1m",
               "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}}
    yield runtime, request
    runtime.shutdown()


def _complete(runtime, request, key):
    run = terminal(runtime.native, runtime.native.create(request, key)["run_id"], timeout=90)
    assert run["state"] == "COMPLETED", run.get("error")
    return run["result"]


def test_native_pine_oracle(native_runtime):
    runtime, request = native_runtime
    report = _complete(runtime, request, "oracle-native")
    assert report["account_authority"] != "HOST"
    oracles.assert_oracle(oracles.native_oracle(report))


def test_external_pine_feedback_oracle(native_runtime):
    runtime, request = native_runtime
    report = _complete(runtime, {**request, "execution_mode": "CANDLESCOPE", "execution_fidelity": "BAR_APPROX",
                                 "fill_recalculation": False,
                                 "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 10}},
                       "oracle-external")
    oracles.assert_oracle(oracles.external_oracle(report))


def test_host_pine_engine_oracle(tmp_path, qualified_pine):
    service = BacktestService.start(_settings(tmp_path), now_ms=1, enforce_registered_revisions=True)
    provider = PineEngineProvider()
    try:
        revision = service.create_strategy_revision(
            {"language": "PINE_ENGINE", "name": "Oracle SMA", "source_text": oracles.PINE_SMA_SOURCE})
        payload = {"strategy_revision_id": revision["revision_id"], "dataset_id": f"oracle-{oracles.SCENARIO_ID}",
                   "data_epoch": "sha256:" + "a1" * 32, "snapshot_hash": "sha256:" + "b2" * 32,
                   "fidelity_mode": "BAR_APPROX", "source_event_kind": "BAR", "start_time_ms": 0,
                   "end_time_ms": oracles.MINUTES * 60_000, "symbol": "BTCUSDT", "interval": "1m",
                   "parameters": {}, "output_mode": "TARGET_POSITION", "initial_balance": "10000",
                   "account_model": "LINEAR_PERP_ONE_WAY_V1", "slippage_bps": "1", "taker_fee_bps": "3",
                   "maker_fee_bps": "1", "exchange": "binance", "market_type": "usdm"}
        service.smoke_strategy_revision(str(revision["revision_id"]), payload, now_ms=2)
        row = service.create_run(payload, idempotency_key="oracle-host-pine", now_ms=3)
        completed = service.execute_bar_run(str(row["run_id"]), events=oracles.bars(), provider=provider, now_ms=4,
                                            observation_market={"venue": "binance", "symbol": "BTCUSDT"})
        assert completed["state"] == "COMPLETED"
        oracles.assert_oracle(oracles.host_oracle("host-pine-engine", completed["result"]))
    finally:
        provider.close()
        service.shutdown()
