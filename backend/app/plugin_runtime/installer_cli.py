"""Read-only inspection of retired runtime plugin packages and registries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bundle import inspect_plugin_bundle
from .errors import PluginHostError, PluginInstallerError
from .installer import PluginInstaller


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="candlescope-plugin",
        description="Inspect archived .cspkg files and list historical script runtime records.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="managed plugin root (defaults to the CandleScope user data directory)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="activation registry path (defaults to <root>/runtime-registry.json)",
    )
    parser.add_argument(
        "--python",
        type=Path,
        dest="python_executable",
        help="Python interpreter used to create isolated environments",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit compact machine-readable JSON",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_command = commands.add_parser(
        "inspect", help="strictly inspect a local bundle and print its digest"
    )
    inspect_command.add_argument("bundle", type=Path)

    build_command = commands.add_parser(
        "build", help=argparse.SUPPRESS
    )
    build_command.add_argument("--manifest", type=Path, required=True)
    build_command.add_argument("--wheel", type=Path, action="append", required=True)
    build_command.add_argument("--output", type=Path, required=True)
    build_command.add_argument("--force", action="store_true")

    install_command = commands.add_parser(
        "install", help=argparse.SUPPRESS
    )
    install_command.add_argument("bundle", type=Path)
    install_command.add_argument(
        "--sha256",
        required=True,
        help="expected outer bundle SHA-256 (64 hex or sha256:<hex>)",
    )
    install_command.add_argument("--disabled", action="store_true")
    install_command.add_argument("--auto-start", action="store_true")
    install_command.add_argument("--required", action="store_true")

    check_command = commands.add_parser(
        "check",
        help=argparse.SUPPRESS,
    )
    check_command.add_argument("runtime_id")

    commands.add_parser(
        "list", help="list active registry entries without starting them"
    )

    rollback_command = commands.add_parser(
        "rollback", help=argparse.SUPPRESS
    )
    rollback_command.add_argument("runtime_id")
    return parser


def _installer(args: argparse.Namespace) -> PluginInstaller:
    return PluginInstaller(
        root=args.root,
        registry_path=args.registry,
        python_executable=args.python_executable,
    )


def _bundle_payload(bundle: Any) -> dict[str, Any]:
    return {
        "path": str(bundle.path),
        "sha256": bundle.sha256,
        "size": bundle.size,
        "manifestSha256": bundle.manifest_sha256,
        "manifest": bundle.manifest.to_wire(),
    }


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "inspect":
        return {
            "ok": True,
            "bundle": _bundle_payload(inspect_plugin_bundle(args.bundle)),
        }
    if args.command == "list":
        return {"ok": True, "plugins": list(_installer(args).list_plugins())}
    raise PluginInstallerError(
        "This script installer is retired. Use the unified plugin CLI with an updated package."
    )


def _emit(payload: dict[str, Any], *, compact: bool, stream: Any) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            **({"separators": (",", ":")} if compact else {"indent": 2}),
        ),
        file=stream,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = _execute(args)
    except PluginHostError as exc:
        _emit(
            {"ok": False, "error": exc.to_dict()},
            compact=args.as_json,
            stream=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "PLUGIN_INSTALLER_INTERRUPTED",
                    "message": "plugin operation was interrupted",
                },
            },
            compact=args.as_json,
            stream=sys.stderr,
        )
        return 130
    _emit(payload, compact=args.as_json, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
