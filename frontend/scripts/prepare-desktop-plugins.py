"""Build packaged first-party runtimes from pinned sources and current bridges.

Run with the packaged target CPython. No user plugin directory or QA artifact is
an input. Sources, patches, exact wheel hashes and build provenance ship beside
the bundles; published upstream release locks remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RECIPE = Path(__file__).with_name("desktop-plugin-sources.json")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, *, cwd=REPO, env=None):
    subprocess.run([str(x) for x in args], cwd=cwd, env=env, check=True)


def download(asset, cache):
    destination = cache / asset["filename"]
    if destination.exists():
        if sha(destination) != asset["sha256"]:
            raise ValueError(f"cached input digest mismatch: {destination.name}")
        return destination
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
        pending = Path(tmp.name)
        try:
            with urllib.request.urlopen(asset["url"], timeout=60) as response:
                shutil.copyfileobj(response, tmp)
            tmp.flush()
            if sha(pending) != asset["sha256"]:
                raise ValueError(f"download digest mismatch: {asset['filename']}")
        except BaseException:
            tmp.close()  # Windows cannot unlink an open temporary file.
            pending.unlink(missing_ok=True)
            raise
    pending.replace(destination)
    return destination


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def release_engine_wheel(engine, target, downloads, sources_out):
    """Ship the qualified release binary, with its exact source and manifest."""
    if engine.get("patch") or engine.get("patchSha256"):
        raise ValueError("release wheels cannot be combined with an unapplied source patch")
    asset = engine["wheels"].get(target)
    if asset is None:
        raise ValueError(f"no pinned release wheel for {target}")
    manifest_path = download(engine["manifest"], downloads)
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("commit") != engine["commit"] or manifest.get("version") != engine["version"]
            or manifest.get("tag") != "v" + engine["version"] or manifest.get("channel") != "stable"):
        raise ValueError("desktop engine release identity mismatch")
    matches = [row for row in manifest.get("assets", []) if row.get("filename") == asset["filename"]]
    if (len(matches) != 1 or "sha256:" + matches[0]["sha256"] != asset["sha256"]
            or matches[0]["size"] != asset["size"]):
        raise ValueError("desktop engine release asset mismatch")
    wheel = download(asset, downloads)
    if wheel.stat().st_size != asset["size"]:
        raise ValueError("desktop engine wheel size mismatch")
    archive = download(engine["archive"], downloads)
    for path in (archive, manifest_path):
        shutil.copy2(path, sources_out / path.name)
    return wheel


def source_digest(directory):
    digest = hashlib.sha256()
    files = [directory / "pyproject.toml", directory / "README.md"]
    files += sorted((directory / "src").rglob("*.py"))
    for file in files:
        digest.update(str(file.relative_to(directory)).encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
    return "sha256:" + digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--qualification", action="store_true", help="Export built wheels and engine tests for native release gates")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.cache = args.cache.resolve()
    recipe = json.loads(RECIPE.read_text())
    target = f"{platform.system()}-{platform.machine()}"
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if python_version != recipe["pythonVersion"] or target not in recipe["platforms"]:
        raise ValueError(f"no pinned desktop plugin inputs for {target} CPython {python_version}")
    args.cache.mkdir(parents=True, exist_ok=True)
    downloads = args.cache / "downloads"
    downloads.mkdir(exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    sources_out = args.output / "sources"
    sources_out.mkdir(exist_ok=True)
    wheelhouse = args.cache / "wheels"
    wheelhouse.mkdir(exist_ok=True)
    engine_wheels = {}
    for name, engine in recipe["engines"].items():
        if "wheels" in engine:
            engine_wheels[name] = release_engine_wheel(engine, target, downloads, sources_out)
            continue
        patch = REPO / engine["patch"]
        if sha(patch) != engine["patchSha256"]:
            raise ValueError(f"tracked patch changed without updating source lock: {patch}")
        archive = download(engine["archive"], downloads)
        shutil.copy2(archive, sources_out / archive.name)
        shutil.copy2(patch, sources_out / patch.name)
        # Source+patch+ABI key, with recorded output hash, avoids compiling Rust
        # on every UI package build. Never reuse an unverified cached wheel.
        key = hashlib.sha256(json.dumps([engine, target, python_version], sort_keys=True).encode()).hexdigest()
        engine_cache = wheelhouse / key
        engine_cache.mkdir(exist_ok=True)
        stamp = engine_cache / "wheel.json"
        if stamp.exists() and (not args.qualification or (engine_cache / "tests").is_dir()):
            saved = json.loads(stamp.read_text())
            wheel = engine_cache / saved["filename"]
            if sha(wheel) != saved["sha256"]:
                raise ValueError(f"cached engine wheel digest mismatch: {wheel}")
        else:
            with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=args.cache) as temporary:
                root = Path(temporary)
                with tarfile.open(archive) as tar:
                    tar.extractall(root, filter="data")
                source = root / f"{name}-{engine['commit']}"
                # Isolate git apply from the containing application checkout.
                run(["git", "init", "--quiet"], cwd=source)
                run(["git", "apply", "--check", patch], cwd=source)
                run(["git", "apply", patch], cwd=source)
                shutil.copytree(source / "python" / "tests", engine_cache / "tests", dirs_exist_ok=True)
                out = root / "built"
                out.mkdir()
                if name == "pine-compat-runtime":
                    run([args.uv, "tool", "run", "--from", "maturin==1.13.0", "maturin", "build",
                         "--release", "--locked", "--interpreter", sys.executable, "--out", out], cwd=source,
                        env={**os.environ, "CARGO_TARGET_DIR": str(args.cache / "cargo-target")})
                else:
                    run([args.uv, "build", "--wheel", "--python", sys.executable, "--out-dir", out, source])
                built = list(out.glob("*.whl"))
                if len(built) != 1:
                    raise ValueError(f"expected one built engine wheel for {name}")
                wheel = engine_cache / built[0].name
                shutil.copy2(built[0], wheel)
                stamp.write_text(json.dumps({"filename": wheel.name, "sha256": sha(wheel)}))
        engine_wheels[name] = wheel
        if args.qualification:
            # Preserve the upstream python/tests -> ../../tests/fixtures layout.
            suite = args.output / "engine-source"
            shutil.copytree(engine_cache / "tests", suite / "python/tests", dirs_exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="fixtures-", dir=args.cache) as temporary:
                with tarfile.open(archive) as tar:
                    prefix = f"{name}-{engine['commit']}/tests/fixtures/"
                    tar.extractall(temporary, members=[m for m in tar.getmembers() if m.name.startswith(prefix)], filter="data")
                shutil.copytree(Path(temporary) / f"{name}-{engine['commit']}" / "tests/fixtures",
                                suite / "tests/fixtures", dirs_exist_ok=True)

    # Current SDK/bridge source is always built, so source edits cannot be
    # hidden by a same-version cached wheel from an earlier package.
    with tempfile.TemporaryDirectory(prefix="bridges-", dir=args.cache) as temporary:
        built = Path(temporary)
        packages = ["candlescope-plugin-sdk", *(e["bridge"] for e in recipe["engines"].values())]
        for name in packages:
            run([args.uv, "build", "--wheel", "--python", sys.executable, "--out-dir", built, REPO / "packages" / name])
        canonicalizer = module(REPO / "packages/candlescope-plugin-pine-compat/scripts/canonicalize_wheel.py", "desktop_canonicalizer")
        for wheel in built.glob("*.whl"):
            canonicalizer.canonicalize(wheel)
        if args.qualification:
            for wheel in [*built.glob("*.whl"), *engine_wheels.values()]:
                shutil.copy2(wheel, args.output / wheel.name)
        entries = []
        for name, engine in recipe["engines"].items():
            bridge = REPO / "packages" / engine["bridge"]
            builder = module(bridge / "scripts" / "build_bundle.py", f"desktop_builder_{name.replace('-', '_')}")
            lock = json.loads((bridge / "release" / "release-lock.json").read_text())
            records = {r.package: r for r in (builder.inspect_wheel(p) for p in built.glob("*.whl"))}
            engine_record = builder.inspect_wheel(engine_wheels[name])
            records[name] = engine_record
            lock["releaseStatus"] = "desktop-source-build-unpublished"
            # Published locks remain immutable; source builds get a new lock.
            source_probe = recipe.get("bridgeProbes", {}).get(engine["bridge"])
            if source_probe is not None:
                probe_path = REPO / source_probe["path"]
                if sha(probe_path) != source_probe["sha256"]:
                    raise ValueError("source bridge probe changed without updating its digest")
                lock["probe"] = json.loads(probe_path.read_text())
            elif records[engine["bridge"]].version != lock["plugin"]["version"]:
                raise ValueError("a new source bridge version requires its own pinned probe")
            lock["plugin"]["version"] = records[engine["bridge"]].version
            lock.pop("bundle", None)
            lock.pop("qualification", None)
            lock["engineProvenance"] = engine
            lock["bridgeSourceSha256"] = source_digest(bridge)
            lock["sdkSourceSha256"] = source_digest(REPO / "packages" / "candlescope-plugin-sdk")
            for package in lock["wheels"]:
                record = records[package]
                lock["wheels"][package] = {
                    "version": record.version, "artifactFilename": record.path.name,
                    "sha256": record.sha256, "size": record.path.stat().st_size,
                }
            lock_path = args.output / f"{engine['bridge']}.lock.json"
            lock_path.write_text(json.dumps(lock, indent=2) + "\n")
            bundle = args.output / f"{engine['bridge']}-{lock['plugin']['version']}-{target}.cspkg"
            result = builder.build_locked_bundle([records[p].path for p in lock["wheels"]], bundle, lock_path=lock_path)
            entries.append({
                "runtimeId": lock["plugin"]["id"], "package": lock["plugin"]["package"],
                "version": lock["plugin"]["version"], "filename": bundle.name,
                "sha256": result.sha256, "size": result.size,
                "platform": {"system": platform.system(), "machine": platform.machine(),
                             "implementation": platform.python_implementation(), "pythonVersion": python_version},
            })
        manifest = {"schemaVersion": 2, "releaseStatus": "desktop-source-build-unpublished", "plugins": entries}
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.copy2(RECIPE, sources_out / RECIPE.name)
    # Check both installers/protocol probes before publishing the runtime stage.
    # The isolated root is temporary; no acceptance/user activation is changed.
    sys.path[:0] = [str(REPO / "backend"), str(REPO / "packages" / "candlescope-plugin-sdk" / "src")]
    from app.plugin_runtime.installer import PluginInstaller
    with tempfile.TemporaryDirectory(prefix="probe-", dir=args.cache) as temporary:
        installer = PluginInstaller(root=Path(temporary), python_executable=Path(sys.executable),
                                    host_name="CandleScope", host_version="0.3.0")
        installer.install_many(tuple((args.output / e["filename"], e["sha256"]) for e in entries),
                               enabled=True, auto_start=True, required=True)
    print(f"Built and verified bundled runtimes for {target}: {args.output}")


if __name__ == "__main__":
    main()
