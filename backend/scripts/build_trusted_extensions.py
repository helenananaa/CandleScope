"""Build reproducible .csext samples; never installs or executes their entries."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "candlescope-plugin-sdk" / "src"))
from app.trusted_extensions.store import unpack


def build(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(source.rglob("*")):
            if not file.is_file() or "__pycache__" in file.parts:
                continue
            record = zipfile.ZipInfo(file.relative_to(source).as_posix(), (2026, 1, 1, 0, 0, 0))
            record.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(record, file.read_bytes())
    unpack(destination.read_bytes())
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "trusted-extensions")
    args = parser.parse_args()
    for name in ("paper", "terminal"):
        print(build(ROOT / "examples" / "trusted-extensions" / name, args.out / f"{name}.csext"))
