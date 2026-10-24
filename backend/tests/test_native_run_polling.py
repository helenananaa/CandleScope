"""Run metadata polls never decode large frozen inputs or hide state transitions."""
import sqlite3
import threading

import pytest

from app.backtest.native import NativeBacktests, encoded


@pytest.fixture
def service():
    native = object.__new__(NativeBacktests)
    native.lock = threading.RLock()
    native.db = sqlite3.connect(":memory:", check_same_thread=False)
    native.db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY, record TEXT)")
    native.db.execute("CREATE TABLE native_run_summaries(id TEXT PRIMARY KEY, record TEXT)")
    record = {"run_id":"run", "state":"RUNNING", "execution_mode":"CANDLESCOPE", "error":None,
        "config":{"source":"strategy", "frozen_input":"x"*2000000}, "result":None}
    native.db.execute("INSERT INTO runs VALUES (?,?)", ("run", encoded(record)))
    native._save_summary(record)
    yield native, record
    native.db.close()


def test_unchanged_poll_reads_only_small_metadata_and_preserves_default_get(service):
    native, record = service
    statements = []
    native.db.set_trace_callback(statements.append)
    header = native.get("run", if_state="RUNNING")
    assert "config" not in header and "result" not in header and header["run_unchanged"]
    assert statements == ["SELECT record FROM native_run_summaries WHERE id='run'"]
    assert native.get("run") == record
    record.update(state="COMPLETED", result={"financial_result":"complete"})
    native.db.execute("UPDATE runs SET record=? WHERE id='run'", (encoded(record),))
    native._save_summary(record)
    assert native.get("run", if_state="RUNNING") == record
    with pytest.raises(ValueError, match="RUN_NOT_FOUND"):
        native.get("missing", if_state="RUNNING")


def test_conditional_run_http_native_external_and_export_preserve_full_results(service, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import native_backtests as api
    native, record = service
    monkeypatch.setattr(api, "_native", lambda _:native)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(api.external_router)
    with TestClient(app) as client:
        for route in ("native", "external"):
            path = f"/{route}/runs/run"
            assert client.get(path).json() == record
            header = client.get(path, params={"if_state":"RUNNING"}).json()
            assert header["run_unchanged"] and "config" not in header and "result" not in header
            assert client.get(path+"/export").json() == record
