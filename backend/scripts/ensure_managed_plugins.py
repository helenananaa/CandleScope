#!/usr/bin/env python3
"""Check or install the managed plugins selected by CandleScope's registry."""
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
        default_registry_path,
        ensure_managed_plugin,
        load_plugin_registry,
        select_plugins,
    )
else:
    from managed_plugin_installer import (
        DEFAULT_TIMEOUT_SECONDS,
        InstallerError,
        default_cache_dir,
        default_registry_path,
        ensure_managed_plugin,
        load_plugin_registry,
        select_plugins,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or install CandleScope's registered managed plugins."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check selected plugins without downloading, installing, or migrating stamps",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="install only from the verified local plugin cache",
    )
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        metavar="ID",
        help="select a registered plugin; repeat for multiple (default: autoInstall entries)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="ID",
        help="exclude a registered plugin from the selected set",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered plugins without probing or installing",
    )
    parser.add_argument(
        "--registry-file",
        type=Path,
        default=default_registry_path(),
        help="path to CANDLESCOPE_PLUGINS.json",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="override the per-user verified plugin cache",
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
        help="allow managed plugin installation outside a virtual environment",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress success messages")
    return parser


def _print(message: str, *, error: bool = False) -> None:
    print(
        f"[managed-plugins] {message}",
        file=sys.stderr if error else sys.stdout,
        flush=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.timeout <= 0:
            raise InstallerError("--timeout must be greater than zero")
        registry = load_plugin_registry(args.registry_file)
        if args.list:
            for plugin in registry:
                lock = plugin.lock
                print(
                    f"{lock.plugin_id}\t{lock.installer_kind}\t"
                    f"autoInstall={str(plugin.auto_install).lower()}\t"
                    f"{lock.package}=={lock.version}"
                )
            return 0
        selected = select_plugins(
            registry,
            requested=args.plugin,
            excluded=args.exclude,
        )
        if not selected:
            if not args.quiet:
                _print("no managed plugins selected")
            return 0

        cache_dir = (args.cache_dir or default_cache_dir()).expanduser().resolve()
        ready = True
        for plugin in selected:
            plugin_ready = ensure_managed_plugin(
                plugin.lock,
                check=args.check,
                offline=args.offline,
                cache_dir=cache_dir,
                timeout=args.timeout,
                allow_system_python=args.allow_system_python,
                quiet=args.quiet,
            )
            ready = ready and plugin_ready
        if args.check and not ready:
            return 1
        if not args.quiet:
            _print(f"{len(selected)} managed plugin(s) ready")
        return 0
    except InstallerError as exc:
        _print(str(exc), error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
