"""Freeze a release from four successful native CI artifacts, without rebuilding."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


PLATFORMS = {
    "windows-amd64": "release-lock.json",
    "linux-x86_64": "release-lock.linux-x86_64.json",
    "macos-arm64": "release-lock.macos-arm64.json",
    "macos-x86_64": "release-lock.macos-x86_64.json",
}


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    release = repo / "packages/candlescope-plugin-pine-compat/release"
    recipe = json.loads((repo / "frontend/scripts/desktop-plugin-sources.json").read_text())
    provenance = recipe["engines"]["pine-compat-runtime"]
    assert digest(repo / provenance["patch"]) == provenance["patchSha256"]
    tag = "candlescope-plugin-pine-compat-v0.3.3"
    base = f"https://github.com/helenananaa/CandleScope/releases/download/{tag}"
    assets: dict[str, Path] = {}
    locks = {}
    entries = []
    qualifications = {}
    for platform, lock_name in PLATFORMS.items():
        root = args.artifacts / f"pine-host-contracts-{platform}"
        receipt = json.loads((root / "qualification-receipt.json").read_text())
        assert receipt["qualified"] is True and receipt["head"] == args.head, platform
        assert set(receipt["contracts"]) == {"host-bar-boundaries/1", "renko-event-rows/1"}
        suites = list(ET.parse(root / "host-contracts.xml").getroot().iter("testsuite"))
        assert suites and all(int(s.attrib[k]) == 0 for s in suites for k in ("errors", "failures", "skipped"))
        tests = sum(int(s.attrib["tests"]) for s in suites)
        assert tests > 0
        lock = json.loads((root / "candlescope-plugin-pine-compat.lock.json").read_text())
        assert lock["plugin"]["version"] == "0.3.3" and lock["engineProvenance"] == provenance
        manifest = json.loads((root / "manifest.json").read_text())
        assert manifest == receipt["bundle_manifest"]
        entry, = manifest["plugins"]
        for record in [*lock["wheels"].values(), entry]:
            filename = record.get("artifactFilename", record.get("filename"))
            path = root / filename
            assert digest(path) == record["sha256"] and path.stat().st_size == record["size"], path
            if filename in assets:
                assert digest(assets[filename]) == digest(path), f"Cross-platform wheel mismatch: {filename}"
            assets[filename] = path
        lock["releaseStatus"] = "pinned-downstream-engine"
        lock["qualification"] = {"head": args.head, "runUrl": args.run_url, "tests": tests, "platform": platform}
        for record in lock["wheels"].values():
            record.update(source="github-release", releaseTag=tag,
                          releaseUrl=f"{base}/{record['artifactFilename']}")
        entry["url"] = f"{base}/{entry['filename']}"
        lock["bundle"] = entry
        locks[lock_name] = lock
        entries.append(entry)
        qualifications[platform] = lock["qualification"]
    # All inputs are verified before creating output or replacing current locks.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, path in assets.items():
        shutil.copy2(path, args.output / name)
    engine_manifest = {
        "schemaVersion": 1, "version": provenance["version"], "commit": provenance["commit"],
        "downstreamSource": {"head": args.head, "patch": provenance["patch"], "patchSha256": provenance["patchSha256"]},
        "qualification": qualifications,
        "assets": [{"filename": name, "sha256": digest(path).removeprefix("sha256:"), "size": path.stat().st_size}
                   for name, path in sorted(assets.items()) if name.startswith("pine_compat_runtime-")],
    }
    manifest_path = args.output / "engine-manifest.json"
    write(manifest_path, engine_manifest)
    for name, lock in locks.items():
        lock["wheels"]["pine-compat-runtime"].update(
            releaseCommit=provenance["commit"], manifestUrl=f"{base}/engine-manifest.json",
            manifestSha256=digest(manifest_path), patchSha256=provenance["patchSha256"])
        current = release / name
        previous = json.loads(current.read_text())
        if previous["plugin"]["version"] != lock["plugin"]["version"]:
            archived = current.with_name(current.stem + "." + previous["plugin"]["version"] + ".json")
            if archived.exists():
                assert archived.read_bytes() == current.read_bytes(), archived
            else:
                shutil.copy2(current, archived)
        write(current, lock)
        write(args.output / name, lock)
    catalog = {"schemaVersion": 1, "plugins": entries}
    write(repo / "backend/app/official-plugin-releases.json", catalog)
    write(args.output / "manifest.json", catalog)
    write(args.output / "qualification.json", qualifications)
    shutil.copy2(repo / provenance["patch"], args.output / "host-contracts-v1.patch")
    shutil.copy2(repo / "frontend/scripts/desktop-plugin-sources.json", args.output / "desktop-plugin-sources.json")
    for platform in PLATFORMS:
        root = args.artifacts / f"pine-host-contracts-{platform}"
        for filename in ("qualification-receipt.json", "host-contracts.xml"):
            shutil.copy2(root / filename, args.output / f"{platform}-{filename}")
    (args.output / "SHA256SUMS").write_text("".join(
        f"{digest(p).removeprefix('sha256:')}  {p.name}\n" for p in sorted(args.output.iterdir()) if p.is_file()), encoding="utf-8")
    print(json.dumps(qualifications, indent=2))


if __name__ == "__main__":
    main()
