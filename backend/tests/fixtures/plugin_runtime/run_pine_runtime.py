"""Run the repository Pine plugin with a test-owned observation journal."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
for package in ("candlescope-plugin-sdk", "candlescope-plugin-pine-compat"):
    sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / package / "src"))

from candlescope_plugin_sdk import serve_runtime  # noqa: E402
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(serve_runtime(PineCompatRuntimePlugin(journal_path=sys.argv[1])))
