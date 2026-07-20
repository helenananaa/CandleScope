#!/usr/bin/env python3
"""Internal fresh-process probe runner for managed plugins."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from managed_plugin_installer import (
    InstallerError,
    load_plugin_lock,
    probe_in_current_process,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--without-stamp", action="store_true")
    args = parser.parse_args(argv)
    try:
        lock = load_plugin_lock(args.lock_file)
        result = probe_in_current_process(
            lock,
            require_stamp=not args.without_stamp,
        )
    except InstallerError as exc:
        result = {"ok": False, "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
