"""Bounded, metadata-only support logs. Never retain messages, args or locals."""
from collections import deque
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
import time

from fastapi import APIRouter, Query, Request, Response

from app.core.version import APP_VERSION

APP_ROOT = Path(__file__).resolve().parents[1]
RETENTION_SECONDS = 3600


class SupportLogHandler(logging.Handler):
    def __init__(self, capacity: int = 500):
        super().__init__(logging.WARNING)
        self.events = deque(maxlen=capacity)
        self.started_at = time.time()
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        # Only shipped application code is eligible; plugin/user source paths,
        # formatted log messages, exception text and arbitrary extras are excluded.
        try:
            source = Path(record.pathname).resolve().relative_to(APP_ROOT).as_posix()
        except (ValueError, OSError):
            return
        event = {"time": record.created, "level": record.levelname,
                 "source": source, "line": record.lineno,
                 "has_exception": bool(record.exc_info)}
        if record.exc_info and record.exc_info[0]:
            name = record.exc_info[0].__name__
            event["exception_type"] = name if name in {
                "ValueError", "TypeError", "RuntimeError", "KeyError", "IndexError",
                "TimeoutError", "ConnectionError", "OSError", "FileNotFoundError",
                "PermissionError", "AssertionError", "MemoryError", "ImportError",
            } else "Other"
        cutoff = time.time() - RETENTION_SECONDS
        while self.events and self.events[0]["time"] < cutoff:
            self.events.popleft()
        if len(self.events) == self.events.maxlen:
            self.dropped += 1
        self.events.append(event)

    def snapshot(self, minutes: int) -> dict:
        self.acquire()
        try:
            cutoff = time.time() - minutes * 60
            return {"started_at": self.started_at, "capacity": self.events.maxlen,
                    "dropped_since_start": self.dropped,
                    "policy": "warning/error metadata only; message, args, exception text and locals excluded",
                    "events": [dict(event) for event in self.events if event["time"] >= cutoff]}
        finally:
            self.release()


class LocalWarningHandler(logging.StreamHandler):
    """Warnings and errors on the process's current stderr, with their text.

    This is what ``logging.lastResort`` printed before the root logger had a
    handler. The desktop shell appends stderr to the local sidecar log; the
    support export above still carries metadata only.
    """

    def __init__(self):
        logging.Handler.__init__(self, logging.WARNING)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    @property
    def stream(self):
        return sys.stderr


support_logs = SupportLogHandler()
local_warnings = LocalWarningHandler()
router = APIRouter(prefix="/api/v1/support", tags=["system"])


def install_support_logging() -> None:
    root = logging.getLogger()
    if support_logs in root.handlers:
        return
    # Any root handler turns logging.lastResort off. In a process that
    # configured no logging, keep the local output it provided.
    if not root.handlers:
        root.addHandler(local_warnings)
    root.addHandler(support_logs)


@router.get("/diagnostics")
def diagnostics(request: Request, response: Response,
                minutes: int = Query(default=15, ge=1, le=60)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": APP_VERSION,
        "data_engine": "active" if getattr(request.app.state, "data_manager", None) is not None else "not_initialized",
        "logs": support_logs.snapshot(minutes),
    }
