#!/usr/bin/env python3
"""Compatibility entrypoint for the Pine managed plugin.

New setup flows use ``ensure_managed_plugins.py``. This command remains stable
for developers and automation that explicitly check or install only Pine.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__:
    from .managed_plugin_installer import (
        DEFAULT_TIMEOUT_SECONDS,
        InstallerError,
        default_cache_dir,
        ensure_managed_plugin,
        load_plugin_lock,
    )
else:
    from managed_plugin_installer import (
        DEFAULT_TIMEOUT_SECONDS,
        InstallerError,
        default_cache_dir,
        ensure_managed_plugin,
        load_plugin_lock,
    )


def _default_lock_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "pine-compat-runtime"
        / "CANDLESCOPE_RUNTIME.json"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or install CandleScope's Pine managed plugin."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the current interpreter without downloading or installing",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="install only from the verified local plugin cache",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="override the per-user verified plugin cache",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=_default_lock_path(),
        help="path to Pine's CANDLESCOPE_RUNTIME.json",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="network timeout in seconds",
    )
    parser.add_argument(
        "--allow-system-python",
        action="store_true",
        help="allow installation outside a virtual environment",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress success messages")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lock = load_plugin_lock(args.lock_file)
        if lock.plugin_id != "pine-compat":
            raise InstallerError(
                f"Pine compatibility entrypoint requires pluginId 'pine-compat', "
                f"got {lock.plugin_id!r}"
            )
        ready = ensure_managed_plugin(
            lock,
            check=args.check,
            offline=args.offline,
            cache_dir=(args.cache_dir or default_cache_dir()).expanduser().resolve(),
            timeout=args.timeout,
            allow_system_python=args.allow_system_python,
            quiet=args.quiet,
        )
        return 0 if ready else 1
    except InstallerError as exc:
        print(f"[plugin:pine-compat] {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
