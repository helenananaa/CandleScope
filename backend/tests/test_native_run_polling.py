"""Run metadata polls never decode large frozen inputs or hide state transitions."""
import json
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


def queued(service):
    native, record = service
    record.update(state="QUEUED", values=[True, 1, 1.0, -0.0, None, "观察🙂"])
    native.db.execute("UPDATE runs SET record=? WHERE id='run'", (encoded(record),))
    native.db.commit()
    return native, record


def test_running_transition_preserves_complete_record_bytes_and_repairs_stale_summary(service, monkeypatch):
    native, record = queued(service)
    native.db.execute("UPDATE native_run_summaries SET record='{}'")
    native.db.commit()
    with monkeypatch.context() as patch:
        patch.setattr(native, "get", lambda *_: pytest.fail("RUNNING decoded the complete input"))
        native._mark_running("run")
    record["state"] = "RUNNING"
    raw, = native.db.execute("SELECT record FROM runs WHERE id='run'").fetchone()
    summary, = native.db.execute("SELECT record FROM native_run_summaries WHERE id='run'").fetchone()
    assert raw == encoded(record)
    assert summary == encoded({key: value for key, value in record.items() if key not in {"result", "config"}})
    assert native.get("run", if_state="QUEUED") == record


@pytest.mark.parametrize("legacy", ["missing_state", "missing_result", "nonobject_config", "completed"])
def test_running_transition_preserves_legacy_update_semantics(service, legacy):
    native, record = queued(service)
    if legacy == "missing_state":
        record.pop("state")
    elif legacy == "missing_result":
        record.pop("result")
    elif legacy == "nonobject_config":
        record["config"] = []
    else:
        record.update(state="COMPLETED", result={"complete": [1, True, -0.0]})
    native.db.execute("UPDATE runs SET record=? WHERE id='run'", (encoded(record),))
    native.db.commit()
    native._mark_running("run")
    record["state"] = "RUNNING"
    assert native.db.execute("SELECT record FROM runs").fetchone()[0] == encoded(record)


def test_running_transition_preserves_missing_and_malformed_record_errors(service):
    native, _ = service
    with pytest.raises(ValueError, match="RUN_NOT_FOUND"):
        native._mark_running("missing")
    native.db.execute("UPDATE runs SET record='{' WHERE id='run'")
    native.db.commit()
    with pytest.raises(json.JSONDecodeError):
        native._mark_running("run")
    assert native.db.execute("SELECT record FROM runs").fetchone()[0] == "{"


@pytest.mark.parametrize("message", ['near "RETURNING": syntax error', 'no such function: json_set', 'no such function: json_remove'])
def test_running_transition_falls_back_on_older_sqlite_capabilities(service, message):
    native, record = queued(service)
    connection = native.db
    class OlderSQLite:
        def execute(self, sql, *args):
            if "json_set" in sql:
                raise sqlite3.OperationalError(message)
            return connection.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(connection, name)
    native.db = OlderSQLite()
    native._mark_running("run")
    record["state"] = "RUNNING"
    assert native.get("run") == record


def test_running_summary_failure_does_not_commit_partial_state(service):
    native, _ = queued(service)
    native.db.execute("CREATE TRIGGER fail_summary BEFORE INSERT ON native_run_summaries BEGIN SELECT RAISE(ABORT, 'summary failure'); END")
    native.db.commit()
    before = tuple(native.db.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="summary failure"):
        native._mark_running("run")
    assert native.db.in_transaction
    native.db.rollback()
    assert tuple(native.db.iterdump()) == before


def test_cancelled_job_never_marks_running_or_invokes_an_engine(service, monkeypatch):
    native, _ = queued(service)
    native.cancel_events = {"run": threading.Event()}
    native.cancel_events["run"].set()
    before = tuple(native.db.iterdump())
    monkeypatch.setattr(native, "_mark_running", lambda _: pytest.fail("cancelled job marked RUNNING"))
    native._execute("run", {}, {}, native.cancel_events["run"])
    assert tuple(native.db.iterdump()) == before and not native.cancel_events
