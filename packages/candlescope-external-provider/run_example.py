"""Explicit standalone entry point; safe with Python -I -B after relocation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from candlescope_external_provider.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
