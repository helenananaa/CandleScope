from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.backtests import router
from app.backtest.native import NativeBacktests, PROTOCOL, digest
from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions
from tests.test_native_strategy_plugins import plugin, PINE, PYNE
pytestmark = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"), reason="requires installed native strategy plugins")


@pytest.fixture
def runtime(tmp_path):
    csv = tmp_path / "bars.csv"
    csv.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{i*60000},{v},{v+1},{v-1},{v},100" for i, v in enumerate([10,10,10,20,20,5,5,15,15,8])))
    local = LocalDatasetService(tmp_path / "local")
    manifest = local.import_csv(csv, LocalImportOptions(name="native", symbol="BTCUSDT", interval="1m", timestamp_unit="ms"))
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
                                     data_dir=tmp_path, klines_db_path=tmp_path / "klines.db", replay_db_path=tmp_path / "replay.db")
    runtime = BacktestRuntime.start(settings, local_data_dir=tmp_path / "local")
    runtime.native.resolver = plugin
    snapshot = runtime.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
                                        start_time_ms=0, end_time_ms=599999, interval="1m")
    payload = {"language": "pine", "source": PINE, "dataset_id": manifest["dataset_id"],
               "data_epoch": manifest["data_epoch"], "snapshot_hash": snapshot["snapshot_hash"],
               "start_time_ms": 0, "end_time_ms": 599999, "interval": "1m",
               "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}}
    yield runtime, payload
    runtime.shutdown()


def terminal(native, run_id):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        result = native.get(run_id)
        if result["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return result
        time.sleep(.05)
    raise AssertionError("native run did not finish")


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", PYNE)])
def test_http_real_engine_report_is_not_rematched(runtime, monkeypatch, language, source):
    host, payload = runtime
    def forbidden(*args, **kwargs):
        raise AssertionError("native results must never enter host matching")
    monkeypatch.setattr(host.service, "execute_bar_run", forbidden)
    payload.update(language=language, source=source)
    app = FastAPI()
    app.state.backtest_runtime = host
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/backtests/native/runs", json=payload, headers={"Idempotency-Key": language})
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        result = terminal(host.native, run_id)
        assert result["state"] == "COMPLETED", result
        assert result["result"]["trades"]
        assert host.service.repository.list_runs() == []
        assert client.get(f"/backtests/native/runs/{run_id}/export").json() == result
        repeat = client.post("/backtests/native/runs", json=payload, headers={"Idempotency-Key": language})
        assert repeat.json()["run_id"] == run_id
        changed = client.post("/backtests/native/runs", json={**payload, "source": source + "\n"}, headers={"Idempotency-Key": language})
        assert changed.status_code == 400
        assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_invalid_snapshot_and_chart_metadata_fail_before_execution(runtime):
    host, payload = runtime
    with pytest.raises(ValueError, match="snapshot"):
        host.native.create({**payload, "snapshot_hash": "sha256:" + "ab" * 32}, "bad-snapshot")
    with pytest.raises(ValueError, match="metadata"):
        host.native.create({**payload, "context": {"symbol": "WRONG", "timeframe": "1"}}, "bad-symbol")


def test_cancellation_never_publishes_late_result(runtime):
    host, payload = runtime
    entered, release = threading.Event(), threading.Event()
    identity = {"protocol": PROTOCOL}
    def runner(plugin, wire, **kwargs):
        if wire.get("operation") == "describe": return {"identity": identity}
        entered.set()
        release.wait(5)
        return {"identity": identity, "execution_mode": "NATIVE", "account_authority": "pine-compat-runtime"}
    host.native.runner = runner
    record = host.native.create(payload, "cancel")
    assert entered.wait(3)
    assert host.native.cancel(record["run_id"])["state"] == "CANCELLED"
    release.set()
    host.native.pool.shutdown(wait=True)
    assert host.native.get(record["run_id"])["result"] is None


def test_restart_marks_unfinished_runs_interrupted(runtime):
    host, payload = runtime
    record = {"run_id": "native_interrupted", "state": "RUNNING"}
    with host.native.lock:
        host.native.db.execute("INSERT INTO runs VALUES (?,?,?,?)", (record["run_id"], "interrupted", "hash", json.dumps(record)))
        host.native.db.commit()
    host.native.shutdown()
    host.native = NativeBacktests(host)
    assert host.native.get(record["run_id"])["state"] == "INTERRUPTED"
