"""Repository entry point for unified packages and platform plugin tools."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# The repository CLI is a supported source-checkout entry point. Pin its SDK
# before importing any app package so a clean child process neither requires an
# installed wheel nor accidentally imports a sibling worktree's SDK.
from plugin_sdk_isolation import pin_in_repo_plugin_sdk  # noqa: E402

pin_in_repo_plugin_sdk(BACKEND_ROOT)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["v2"]:
        from app.plugin_installer_v2.cli import main as platform_v2_main

        return platform_v2_main(arguments[1:])
    if arguments[:1] == ["v3"]:
        from app.plugin_github_import_v3.cli import main as platform_v3_main

        return platform_v3_main(arguments[1:])
    if arguments[:1] == ["unified"]:
        from unified_plugin import main as unified_main

        return unified_main(arguments[1:])
    print(
        "The legacy script installer is retired. Use 'unified' with an updated package, or 'v2'/'v3' for platform tools.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
