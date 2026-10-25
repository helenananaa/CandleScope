"""Qualify current bridge/SDK sources against an unchanged published engine.

This is PR compatibility evidence, not a published bridge release.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

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
    path = output / "source-candidate-lock.json"
    path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).with_name("qualify_release.py")),
                    "--lock", str(path), "--platform", args.platform,
                    "--output", str(output)], check=True)
    original = output / f"candlescope-pine-compat-{lock['plugin']['version']}-cp312-{args.platform}.cspkg"
    bundle = original.with_name(original.stem + "-source-candidate.cspkg")
    original.rename(bundle)
    receipt = {"qualification": "current-source-compatibility-with-published-engine",
               "releaseStatus": candidate["releaseStatus"], "bundle": str(bundle),
               "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
               "engine": lock["wheels"]["pine-compat-runtime"],
               "event_series_qualification": "covered by test_event_strategy when the pinned engine advertises the contract"}
    (output / "source-candidate-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
