"""Inspect candidate unified manifests without installing or importing any entry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plugin_sdk_isolation import pin_in_repo_plugin_sdk

pin_in_repo_plugin_sdk()

from candlescope_plugin_sdk.platform_v2 import PlatformContractError
from candlescope_plugin_sdk.unified import (
    Manifest,
    ManifestError,
    PlanError,
    activation_order,
)
from candlescope_plugin_sdk.unified.manifest import MAX_MANIFEST_BYTES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifests",
        nargs="+",
        type=Path,
        help="complete proposed enabled set of manifest.json files",
    )
    args = parser.parse_args(argv)
    try:
        manifests = []
        for path in args.manifests:
            with path.open("rb") as stream:
                payload = stream.read(MAX_MANIFEST_BYTES + 1)
            manifests.append(Manifest.from_json(payload))
        ordered = activation_order(manifests)
    except (OSError, ManifestError, PlanError, PlatformContractError) as exc:
        print(
            json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "metadata-valid",
                "productionInstallable": False,
                "activationOrder": [manifest.id for manifest in ordered],
                "plugins": [manifest.to_wire() for manifest in ordered],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
