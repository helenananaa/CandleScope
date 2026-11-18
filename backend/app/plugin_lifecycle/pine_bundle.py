"""Build the signed-desktop Pine archive from its verified platform wheels."""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import canonical_dumps
from candlescope_plugin_sdk.unified.manifest import package_path

from .bundle import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, build_package

PINE_ID = "candlescope.pine-compat"
PINE_ENTRY = "pine"


def build_pine_package(wheels, version, output):
    with tempfile.TemporaryDirectory(prefix="candlescope-pine-unified-") as temporary:
        source = Path(temporary)
        files = set()
        total = 0
        for wheel in wheels:
            with zipfile.ZipFile(wheel) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    top, slash, rest = info.filename.partition("/")
                    # Distribution lookup uses METADATA for the actual version.
                    # Keep local-version wheel metadata inside portable paths.
                    if top.endswith(".dist-info"):
                        top = top.replace("+", "_")
                    name = package_path(top + slash + rest)
                    if (
                        name.casefold() in files
                        or stat.S_IFMT(info.external_attr >> 16)
                        not in {0, stat.S_IFREG}
                        or info.file_size > MAX_FILE_BYTES
                    ):
                        raise ValueError(
                            "unsafe or duplicate file in locked Pine wheels"
                        )
                    total += info.file_size
                    files.add(name.casefold())
                    if len(files) > MAX_FILES - 3 or total > MAX_TOTAL_BYTES:
                        raise ValueError("Pine wheel files exceed the package budget")
                    destination = source / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as content, destination.open("xb") as file:
                        shutil.copyfileobj(content, file)
        (source / "pine-entry.py").write_text(
            "from candlescope_plugin_pine_compat.unified_entry import main\nraise SystemExit(main())\n",
            encoding="utf-8",
        )
        (source / "manifest.json").write_text(
            canonical_dumps(
                {
                    "schema": "candlescope.unified-plugin/1",
                    "id": PINE_ID,
                    "version": version,
                    "name": "Pine",
                    "hostApiVersion": 1,
                    "trust": "full-trust",
                    "entries": [
                        {
                            "id": PINE_ENTRY,
                            "kind": "sidecar",
                            "path": "pine-entry.py",
                            "runtime": "python-module",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return build_package(source, output)
