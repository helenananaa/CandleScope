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
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.cache = args.cache.resolve()
    recipe = json.loads(RECIPE.read_text())
    target = f"{platform.system()}-{platform.machine()}"
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if python_version != recipe["pythonVersion"] or target not in recipe["numpy"]:
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
        if stamp.exists():
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
                out = root / "built"
                out.mkdir()
                if name == "pine-compat-runtime":
                    run([args.uv, "tool", "run", "--from", "maturin==1.13.0", "maturin", "build",
                         "--release", "--locked", "--interpreter", sys.executable, "--out", out], cwd=source)
                else:
                    run([args.uv, "build", "--wheel", "--python", sys.executable, "--out-dir", out, source])
                built = list(out.glob("*.whl"))
                if len(built) != 1:
                    raise ValueError(f"expected one built engine wheel for {name}")
                wheel = engine_cache / built[0].name
                shutil.copy2(built[0], wheel)
                stamp.write_text(json.dumps({"filename": wheel.name, "sha256": sha(wheel)}))
        engine_wheels[name] = wheel

    # Current SDK/bridge source is always built, so source edits cannot be
    # hidden by a same-version cached wheel from an earlier package.
    with tempfile.TemporaryDirectory(prefix="bridges-", dir=args.cache) as temporary:
        built = Path(temporary)
        packages = ["candlescope-plugin-sdk", *(e["bridge"] for e in recipe["engines"].values())]
        for name in packages:
            run([args.uv, "build", "--wheel", "--python", sys.executable, "--out-dir", built, REPO / "packages" / name])
        numpy = download(recipe["numpy"][target], downloads)
        tzdata = download(recipe["tzdata"], downloads)
        entries = []
        for name, engine in recipe["engines"].items():
            bridge = REPO / "packages" / engine["bridge"]
            builder = module(bridge / "scripts" / "build_bundle.py", f"desktop_builder_{name.replace('-', '_')}")
            lock = json.loads((bridge / "release" / "release-lock.json").read_text())
            records = {r.package: r for r in (builder.inspect_wheel(p) for p in built.glob("*.whl"))}
            engine_record = builder.inspect_wheel(engine_wheels[name])
            records[name] = engine_record
            if name == "pyne-runtime":
                for wheel in (numpy, tzdata):
                    record = builder.inspect_wheel(wheel)
                    records[record.package] = record
            lock["releaseStatus"] = "desktop-source-build-unpublished"
            # Published locks remain immutable; source builds get a new lock.
            lock["plugin"]["version"] = records[engine["bridge"]].version
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
