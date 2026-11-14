import json
import logging
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.support_diagnostics import (
    APP_ROOT, SupportLogHandler, install_support_logging, local_warnings, router, support_logs,
)
from app.local_data.runtime import LocalOfflineProfileMiddleware


def test_support_logs_exclude_messages_arguments_exceptions_and_paths():
    handler = SupportLogHandler(capacity=2)
    for i in range(3):
        record = logging.LogRecord("private-account", logging.ERROR,
                                   str(APP_ROOT / "main.py"), i + 1,
                                   "token=secret strategy=%s", ("private-source",),
                                   (ValueError, ValueError("secret"), None))
        handler.handle(record)
    snapshot = handler.snapshot(15)
    assert len(snapshot["events"]) == 2
    assert snapshot["dropped_since_start"] == 1
    assert snapshot["events"][0]["source"] == "main.py"
    exported = json.dumps(snapshot)
    assert all(value not in exported for value in ["secret", "private-source", "private-account", str(APP_ROOT)])
    record = logging.LogRecord("plugin", logging.ERROR, "/private/strategy.py", 1, "secret", (), None)
    handler.handle(record)
    assert handler.snapshot(15) == snapshot


def test_support_logs_filter_expired_events():
    handler = SupportLogHandler()
    record = logging.LogRecord("test", logging.WARNING, str(APP_ROOT / "main.py"), 1, "hidden", (), None)
    record.created = time.time() - 1000
    handler.handle(record)
    assert handler.snapshot(15)["events"] == []
    assert len(handler.snapshot(60)["events"]) == 1


def test_support_endpoint_available_offline_with_bounded_range_and_no_store():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(LocalOfflineProfileMiddleware, enabled=True)
    with TestClient(app) as client:
        response = client.get("/api/v1/support/diagnostics?minutes=15")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["data_engine"] == "not_initialized"
        assert response.json()["schema_version"] == 1
        app.state.data_manager = object()
        assert client.get("/api/v1/support/diagnostics").json()["data_engine"] == "active"
        for minutes in (0, 61):
            assert client.get(f"/api/v1/support/diagnostics?minutes={minutes}").status_code == 422


def test_unconfigured_process_keeps_warning_text_on_stderr_but_not_in_the_export(monkeypatch, capsys):
    # The packaged sidecar configures no logging, so the support handler would
    # otherwise be the only root handler and silence logging.lastResort.
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    install_support_logging()
    install_support_logging()
    assert root.handlers == [local_warnings, support_logs]
    logging.getLogger("candlescope.storage.klines").info("routine %s", "detail")
    try:
        raise RuntimeError("stale write")
    except RuntimeError as error:
        failure = (RuntimeError, error, error.__traceback__)
    root.handle(logging.LogRecord("candlescope.storage.klines", logging.ERROR, str(APP_ROOT / "main.py"), 7,
                                  "Write batch failed for %s", ("BTCUSDT@1m",), failure))
    printed = capsys.readouterr().err
    assert "ERROR candlescope.storage.klines: Write batch failed for BTCUSDT@1m" in printed
    assert "RuntimeError: stale write" in printed and "routine" not in printed
    snapshot = support_logs.snapshot(15)
    assert snapshot["events"][-1]["source"] == "main.py" and snapshot["events"][-1]["line"] == 7
    exported = json.dumps(snapshot)
    assert all(value not in exported for value in ["Write batch failed", "BTCUSDT", "stale write"])


def test_configured_process_keeps_its_own_log_output(monkeypatch):
    root = logging.getLogger()
    existing = logging.NullHandler()
    monkeypatch.setattr(root, "handlers", [existing])
    install_support_logging()
    assert root.handlers == [existing, support_logs]
