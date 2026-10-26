"""Qualify current bridge/SDK sources against an unchanged published engine.

This is PR compatibility evidence, not a published bridge release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

if __package__:
    from .build_bundle import inspect_wheel, load_release_lock
    from .canonicalize_wheel import canonicalize
else:
    from build_bundle import inspect_wheel, load_release_lock
    from canonicalize_wheel import canonicalize


def source_candidate_lock(release_lock, bridge, sdk):
    candidate = deepcopy(release_lock)
    for package, path in (("candlescope-plugin-pine-compat", bridge), ("candlescope-plugin-sdk", sdk)):
        wheel = inspect_wheel(path)
        record = candidate["wheels"][package]
        if wheel.package != package or wheel.version != record["version"]:
            raise ValueError(f"Source candidate wheel identity mismatch: {package}")
        record.update(artifactFilename=path.name, sha256=wheel.sha256,
                      size=path.stat().st_size, releaseUrl=path.resolve().as_uri(),
                      source="current-checkout-candidate")
    candidate["releaseStatus"] = "source-candidate-unpublished"
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine-wheel", type=Path, help="Optional isolated incremental engine candidate; never changes the published lock")
    args = parser.parse_args()
    if os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
        raise ValueError("Source candidates cannot qualify tagged releases")
    repository = Path(__file__).resolve().parents[3]
    lock = load_release_lock(args.lock)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                    "--outdir", str(output), str(repository / "packages/candlescope-plugin-sdk")], check=True)
    sdk = output / lock["wheels"]["candlescope-plugin-sdk"]["artifactFilename"]
    canonicalize(sdk)
    bridge = output / lock["wheels"]["candlescope-plugin-pine-compat"]["artifactFilename"]
    candidate = source_candidate_lock(lock, bridge, sdk)
    if args.engine_wheel is not None:
        wheel = inspect_wheel(args.engine_wheel)
        if wheel.package != "pine-compat-runtime" or wheel.version != "0.3.2+external.1":
            raise ValueError("Expected the isolated 0.3.2+external.1 engine candidate")
        candidate["releaseStatus"] = "host-incremental-candidate-unpublished"
        manifest = {"version": wheel.version, "commit": "uncommitted-host-incremental-candidate",
                    "assets": [{"filename": args.engine_wheel.name, "sha256": wheel.sha256.removeprefix("sha256:"), "size": args.engine_wheel.stat().st_size}]}
        manifest_path = output / "candidate-engine-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidate["wheels"]["pine-compat-runtime"].update(
            version=wheel.version, source="isolated-source-candidate", artifactFilename=args.engine_wheel.name,
            sha256=wheel.sha256, size=args.engine_wheel.stat().st_size, releaseUrl=args.engine_wheel.resolve().as_uri(),
            releaseCommit=manifest["commit"], manifestUrl=manifest_path.as_uri(),
            manifestSha256="sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    path = output / "source-candidate-lock.json"
    path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).with_name("qualify_release.py")),
                    "--lock", str(path), "--platform", args.platform,
                    "--output", str(output)], check=True)
    original = output / f"candlescope-pine-compat-{lock['plugin']['version']}-cp312-{args.platform}.cspkg"
    bundle = original.with_name(original.stem + "-source-candidate.cspkg")
    original.rename(bundle)
    receipt = {"qualification": "isolated-host-incremental-candidate" if args.engine_wheel else "current-source-compatibility-with-published-engine",
               "releaseStatus": candidate["releaseStatus"], "bundle": str(bundle),
               "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
               "engine": candidate["wheels"]["pine-compat-runtime"],
               "event_series_qualification": "not covered by the published engine"}
    (output / "source-candidate-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
