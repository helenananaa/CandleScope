"""Build a test successor from the verified first-party Pine archive."""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

from app.plugin_lifecycle.bundle import build_package, verify_package
from app.plugin_lifecycle.script_bundle import PINE_ID
from candlescope_plugin_sdk.platform_v2 import canonical_dumps, loads_strict


def main(descriptor: Path, output: Path) -> None:
    entry = loads_strict(descriptor.read_bytes())
    archive = descriptor.parent / entry["filename"]
    previous = verify_package(archive)
    if previous.sha256 != entry["sha256"] or previous.manifest.id != PINE_ID:
        raise ValueError("bundled Pine descriptor does not match its verified package")
    major, minor, patch = map(int, previous.manifest.version.split("."))
    manifest = previous.manifest.to_wire()
    manifest["version"] = f"{major}.{minor}.{patch + 1}"
    with tempfile.TemporaryDirectory(prefix="candlescope-pine-qa-upgrade-") as temporary:
        source = Path(temporary)
        with zipfile.ZipFile(archive) as original:
            original.extractall(source)
        (source / "bundle.json").unlink()
        (source / "manifest.json").write_text(canonical_dumps(manifest), encoding="utf-8")
        build_package(source, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.descriptor, args.output)
