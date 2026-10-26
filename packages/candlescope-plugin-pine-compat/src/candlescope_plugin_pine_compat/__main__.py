"""Module entry point used by the managed plugin host."""

from __future__ import annotations

from candlescope_plugin_sdk import serve_runtime

from .runtime import PineCompatRuntimePlugin


def main() -> int:
    import os
    from pathlib import Path
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    journal = os.environ.get("CANDLESCOPE_PINE_JOURNAL") or root / "CandleScope" / "pine" / "observations-v1.sqlite3"
    return serve_runtime(PineCompatRuntimePlugin(journal_path=journal))


if __name__ == "__main__":
    raise SystemExit(main())
