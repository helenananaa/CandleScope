"""Tell the desktop host why the backend could not start.

The host names a private file in ``CANDLESCOPE_DESKTOP_STARTUP_FAILURE_FILE``.
When startup fails, the backend writes the error's code and message there, so
the host's dialog can show the cause instead of a generic "could not start".
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENVIRONMENT = "CANDLESCOPE_DESKTOP_STARTUP_FAILURE_FILE"
_MAX_MESSAGE = 2000


def describe(error: BaseException) -> dict[str, str | None]:
    code = getattr(error, "code", None)
    message = str(error).strip() or type(error).__name__
    return {
        "code": code if isinstance(code, str) and code else None,
        "message": message[:_MAX_MESSAGE],
        "type": type(error).__name__,
    }


def record(error: BaseException) -> bool:
    """Write the first startup failure for the host; never raise."""
    target = os.environ.get(ENVIRONMENT)
    if not target:
        return False
    path = Path(target)
    temporary = path.with_name(path.name + ".tmp")
    try:
        if path.exists():
            return False  # Keep the first cause; later errors are usually cleanup fallout.
        temporary.write_text(json.dumps(describe(error)), encoding="utf-8")
        temporary.replace(path)
        return True
    except OSError:
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
