import json
import logging
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.support_diagnostics import APP_ROOT, SupportLogHandler, router
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
