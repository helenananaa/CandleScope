#!/usr/bin/env python3
"""Build the immutable fork source, then install its wheel into this Python venv.

Generated CCXT Python files are build output, never maintained patches. Run
after requirements.txt; installing vanilla CCXT later removes the extension.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

BACKEND = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path, env: dict | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def build(lock: dict, destination: Path, source_repo: str) -> Path:
    commit = lock["source_commit"]
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("fork source must be pinned to a full immutable SHA")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="candlescope-ccxt-build-") as scratch:
        root = Path(scratch)
        source = root / "source"
        source.mkdir()
        run("git", "init", "--quiet", cwd=source)
        run("git", "remote", "add", "origin", source_repo, cwd=source)
        run("git", "sparse-checkout", "init", "--cone", cwd=source)
        run("git", "sparse-checkout", "set", "ts", "build", "python", "js", cwd=source)
        run(
            "git",
            "fetch",
            "--depth=1",
            "--filter=blob:none",
            "origin",
            commit,
            cwd=source,
        )
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        if actual != commit:
            raise RuntimeError("checked-out source does not match lock")
        package = json.loads((source / "package.json").read_text())
        if package["version"] != lock["upstream_version"]:
            raise RuntimeError("upstream version does not match lock")
        run("npm", "ci", "--ignore-scripts", cwd=source)
        # Use tsc directly: upstream's tsBuild script can swallow a compiler error.
        run("node", "node_modules/typescript/bin/tsc", cwd=source)
        run(
            "node",
            "--input-type=module",
            "-e",
            "import fs from 'node:fs'; import ccxt from './js/ccxt.js'; fs.writeFileSync('exchanges.json', JSON.stringify({ids:ccxt.exchanges,ws:ccxt.pro.exchanges}));",
            cwd=source,
        )
        run(
            "node",
            "node_modules/tsx/dist/cli.mjs",
            "build/transpile.ts",
            "--python",
            "--noTests",
            "binance",
            cwd=source,
        )
        run("node", "--test", "js/src/test/candlescope/binance.test.js", cwd=source)
        build_env = root / "build-env"
        venv.EnvBuilder(with_pip=True).create(build_env)
        python = build_env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *lock["build_requirements"],
            cwd=source,
        )
        metadata = {
            "source_commit": commit,
            "upstream_version": lock["upstream_version"],
            "schema": lock["schema"],
        }
        (source / "python/ccxt/candlescope_build.json").write_text(
            json.dumps(metadata, sort_keys=True) + "\n"
        )
        with (source / "python/MANIFEST.in").open("a") as manifest:
            manifest.write("\ninclude ccxt/candlescope_build.json\n")
        epoch = subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=source, text=True
        ).strip()
        env = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
        dist = root / "dist"
        run(
            str(python),
            "setup.py",
            "bdist_wheel",
            "--dist-dir",
            str(dist),
            cwd=source / "python",
            env=env,
        )
        wheels = list(dist.glob("ccxt-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("expected exactly one CCXT wheel")
        target = destination / wheels[0].name
        shutil.copyfile(wheels[0], target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != lock["wheel_sha256"]:
            raise RuntimeError(
                "rebuilt wheel differs from the qualified SHA-256; do not install"
            )
        metadata["wheel_sha256"] = digest
        (destination / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (destination / "requirements.lock").write_text(
            f"./{target.name} --hash=sha256:{digest}\n"
        )
        return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-repo",
        help="optional complete local Git mirror; the locked SHA is still enforced",
    )
    parser.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if not args.build_only and sys.prefix == sys.base_prefix:
        parser.error(
            "activate an isolated Python virtual environment before installing"
        )
    lock = json.loads((BACKEND / "ccxt-fork.lock.json").read_text())
    destination = (
        args.wheel_dir or BACKEND / ".cache/ccxt-fork" / lock["source_commit"]
    ).resolve()
    wheel = build(lock, destination, args.source_repo or lock["repository"])
    if not args.build_only:
        run(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            "--require-hashes",
            "-r",
            "requirements.lock",
            cwd=destination,
        )
    print(f"Pinned fork wheel: {wheel}")
    print(f"Build provenance and SHA-256: {destination / 'build.json'}")


if __name__ == "__main__":
    main()
