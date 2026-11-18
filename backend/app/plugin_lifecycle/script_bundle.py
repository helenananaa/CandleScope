"""Build desktop indicator packages from verified wheels."""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import canonical_dumps
from candlescope_plugin_sdk.unified.manifest import package_path

from .bundle import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, build_package

PINE_ID = "candlescope.pine-compat"
PINE_ENTRY = "pine"
PYTHON_ID = "candlescope.python-indicator"


@dataclass(frozen=True)
class BundledScript:
    entry: str
    label: str
    module: str
    exchange: str
    environment: str
    max_processes: int = 1


SCRIPT_BUNDLES = {
    PINE_ID: BundledScript(
        PINE_ENTRY,
        "Pine",
        "candlescope_plugin_pine_compat",
        "pine",
        "CANDLESCOPE_BUNDLED_UNIFIED_PINE",
    ),
    PYTHON_ID: BundledScript(
        "python",
        "Python Indicators",
        "candlescope_plugin_python_indicator",
        "python",
        "CANDLESCOPE_BUNDLED_UNIFIED_PYTHON",
        # The runtime starts one fresh evaluator for each serialized batch.
        max_processes=2,
    ),
}


def build_pine_package(wheels, version, output):
    return build_script_package(PINE_ID, wheels, version, output)


def build_script_package(plugin_id, wheels, version, output):
    spec = SCRIPT_BUNDLES[plugin_id]
    with tempfile.TemporaryDirectory(prefix="candlescope-script-unified-") as temporary:
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
                            "unsafe or duplicate file in locked script wheels"
                        )
                    total += info.file_size
                    files.add(name.casefold())
                    if len(files) > MAX_FILES - 3 or total > MAX_TOTAL_BYTES:
                        raise ValueError("Script wheel files exceed the package budget")
                    destination = source / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as content, destination.open("xb") as file:
                        shutil.copyfileobj(content, file)
        entry_path = f"{spec.entry}-entry.py"
        (source / entry_path).write_text(
            f"from {spec.module}.unified_entry import main\nraise SystemExit(main())\n",
            encoding="utf-8",
        )
        (source / "manifest.json").write_text(
            canonical_dumps(
                {
                    "schema": "candlescope.unified-plugin/1",
                    "id": plugin_id,
                    "version": version,
                    "name": spec.label,
                    "hostApiVersion": 1,
                    "trust": "full-trust",
                    "entries": [
                        {
                            "id": spec.entry,
                            "kind": "sidecar",
                            "path": entry_path,
                            "runtime": "python-module",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return build_package(source, output)
