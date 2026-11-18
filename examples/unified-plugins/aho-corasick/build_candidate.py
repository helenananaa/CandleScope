"""Build an unsigned native .cspkg for the current Rust host."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

CANDIDATE = Path(__file__).resolve().parent
REPO = CANDIDATE.parents[2]
LEGACY = REPO / "examples/plugins/aho-corasick-adapter"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads((CANDIDATE / "manifest.json").read_text())
    rust_version = subprocess.check_output(["rustc", "-vV"], text=True)
    target = next(
        line.removeprefix("host: ")
        for line in rust_version.splitlines()
        if line.startswith("host: ")
    )
    binary_suffix = ".exe" if "-windows-" in target else ""
    manifest["entries"][0]["path"] += binary_suffix

    with TemporaryDirectory(prefix="candlescope-aho-build-") as temporary:
        workspace = Path(temporary)
        cargo_target = workspace / "cargo"
        subprocess.run(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--offline",
                "--manifest-path",
                str(CANDIDATE / "Cargo.toml"),
                "--target",
                target,
                "--target-dir",
                str(cargo_target),
            ],
            cwd=CANDIDATE,
            check=True,
        )

        source = workspace / "source"
        executable = source / manifest["entries"][0]["path"]
        executable.parent.mkdir(parents=True)
        shutil.copyfile(
            cargo_target
            / target
            / "release"
            / f"candlescope-aho-corasick-unified{binary_suffix}",
            executable,
        )
        (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        shutil.copytree(LEGACY / "licenses", source / "licenses")
        notices = source / "licenses/THIRD_PARTY_NOTICES.txt"
        _, separator, body = notices.read_text(encoding="utf-8").partition("\n")
        if not separator or not body:
            raise ValueError("missing reference license notice")
        notices.write_text(
            f"CandleScope aho-corasick unified candidate {manifest['version']} third-party notices\n"
            + body,
            encoding="utf-8",
        )
        (source / "sbom").mkdir()
        shutil.copyfile(
            CANDIDATE / "sbom.cyclonedx.json", source / "sbom/cyclonedx.json"
        )
        subprocess.run(
            [
                sys.executable,
                str(REPO / "backend/scripts/unified_plugin.py"),
                "build",
                str(source),
                str(args.output.resolve()),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
