"""Build/inspect/stage candidate packages in an explicit isolated store; no execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plugin_sdk_isolation import pin_in_repo_plugin_sdk

pin_in_repo_plugin_sdk(Path(__file__).resolve().parents[1])

from app.plugin_lifecycle import (
    LifecycleError,
    PackageError,
    PackageStore,
    build_package,
    verify_package,
)
from app.plugin_security_v2.errors import PlatformSecurityError
from candlescope_plugin_sdk.platform_v2 import PlatformContractError
from candlescope_plugin_sdk.unified import ManifestError, PlanError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("source", type=Path)
    build.add_argument("output", type=Path)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("package", type=Path)
    for name in ("stage", "review", "list", "activate", "disable", "uninstall"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name == "stage":
            command.add_argument("package", type=Path)
        elif name in {"review", "activate"}:
            command.add_argument("digest")
        elif name in {"disable", "uninstall"}:
            command.add_argument("plugin_id")
        if name in {"activate", "disable", "uninstall"}:
            command.add_argument("--expected-revision", type=int, required=True)
        if name == "activate":
            command.add_argument(
                "--approve",
                required=True,
                help="reviewed trust:sha256:<digest>; not an authentication token",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_package(args.source, args.output).review()
        elif args.command == "inspect":
            result = verify_package(args.package).review()
        else:
            store = PackageStore(args.root)
            if args.command == "stage":
                result = store.stage(args.package).review()
            elif args.command == "review":
                result = store.review(args.digest)
            elif args.command == "list":
                result = store.snapshot()
            elif args.command == "activate":
                result = store.activate(
                    args.digest,
                    expected_revision=args.expected_revision,
                    acknowledgement=args.approve,
                )
            else:
                result = getattr(store, args.command)(
                    args.plugin_id, expected_revision=args.expected_revision
                )
    except (
        OSError,
        LifecycleError,
        PackageError,
        ManifestError,
        PlanError,
        PlatformContractError,
        PlatformSecurityError,
    ) as exc:
        print(
            json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"status": "ok", "executorsAttached": False, "result": result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
