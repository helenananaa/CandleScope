"""Materialize a digest-pinned platform bundle and test its offline installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from build_bundle import build_locked_bundle, load_release_lock


def download(url: str, path: Path, expected: str) -> None:
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected.removeprefix("sha256:"):
        raise ValueError(f"Release asset digest mismatch: {path.name}")
    path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = load_release_lock(args.lock)
    args.output.mkdir(parents=True, exist_ok=True)
    engine = lock["wheels"]["pine-compat-runtime"]
    manifest_path = args.output / "engine-manifest.json"
    download(engine["manifestUrl"], manifest_path, engine["manifestSha256"])
    manifest = json.loads(manifest_path.read_text())
    if manifest["commit"] != engine["releaseCommit"] or manifest["version"] != engine["version"]:
        raise ValueError("Engine release identity mismatch")
    asset = next(item for item in manifest["assets"] if item["filename"] == engine["artifactFilename"])
    if asset["sha256"] != engine["sha256"].removeprefix("sha256:") or asset["size"] != engine["size"]:
        raise ValueError("Engine manifest asset mismatch")
    sdk = lock["wheels"]["candlescope-plugin-sdk"]
    for record in (sdk, engine):
        download(record["releaseUrl"], args.output / record["artifactFilename"], record["sha256"])
    bridge = lock["wheels"]["candlescope-plugin-pine-compat"]
    wheels = tuple(args.output / record["artifactFilename"] for record in (bridge, sdk, engine))
    bundle_path = args.output / f"candlescope-pine-compat-{lock['plugin']['version']}-cp312-{args.platform}.cspkg"
    bundle = build_locked_bundle(wheels, bundle_path, lock_path=args.lock)
    root = args.output / "managed-test"
    repository = Path(__file__).resolve().parents[3]
    cli = repository / "backend" / "scripts" / "candlescope_plugin.py"
    install = [sys.executable, str(cli), "--root", str(root), "--json", "install",
               str(bundle_path), "--sha256", bundle.sha256]
    check = [sys.executable, str(cli), "--root", str(root), "--json", "check", "candlescope.pine-compat"]
    for name, command in (("install", install), ("check", check)):
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        if payload.get("ok") is not True:
            raise ValueError(f"{name} failed: {payload}")
        (args.output / f"{name}-receipt.json").write_text(json.dumps(payload, indent=2) + "\n")
    subprocess.run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-index", "--no-deps",
                    *map(str, wheels)], check=True)
    subprocess.run([sys.executable, "-m", "pytest", "-o", "pythonpath=", "-q",
                    str(repository / "packages/candlescope-plugin-pine-compat/tests/test_runtime.py"),
                    str(repository / "packages/candlescope-plugin-pine-compat/tests/test_native_sessions.py")], check=True)
    print(f"Qualified {bundle_path.name}: {bundle.sha256}")


if __name__ == "__main__":
    main()
