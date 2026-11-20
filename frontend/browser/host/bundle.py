"""Build a static Pyodide distribution of the original CandleScope packages.

The archive is ready to import: wheels are unpacked, every module is compiled
to bytecode by the Pyodide interpreter that runs it, and the pinned CCXT
catalog is computed here instead of on each start.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
BROWSER = HERE.parent
ROOT = BROWSER.parents[1]
CACHE = BROWSER / ".host-cache"
STAGE = CACHE / "stage"
LOCK = json.loads((BROWSER / "node_modules/pyodide/pyodide-lock.json").read_text())
PINS = json.loads((HERE / "wheels.json").read_text())
HOST_MODULES = ("browser_host.py", "browser_io.py", "library_download.py")


def downloads():
    selected = {}
    version = json.loads((BROWSER / "node_modules/pyodide/package.json").read_text())["version"]
    def include(name):
        name = name.lower().replace("_", "-")
        if name in selected:
            return
        if name in PINS:
            item = PINS[name]
            selected[name] = (item["file"], item["sha256"], item["url"])
            for dep in item.get("depends", []):
                include(dep)
            return
        item = LOCK["packages"][name]
        filename = item["file_name"]
        selected[name] = (filename, item["sha256"], f"https://cdn.jsdelivr.net/pyodide/v{version}/full/{filename}")
        for dep in item["depends"]:
            include(dep)
    for name in ["aiohttp", "requests", "httpx", "tzdata", "sniffio", "cryptography", "orjson", "pydantic", *PINS]:
        include(name)
    fork = json.loads((ROOT / "backend/ccxt-fork.lock.json").read_text())
    selected["ccxt"] = (Path(urlsplit(fork["wheel_url"]).path).name, fork["wheel_sha256"], fork["wheel_url"])
    return selected.values()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire(item):
    filename, checksum, url = item
    path = CACHE / filename
    if path.is_file() and digest(path) == checksum:
        return path
    with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as temp:
        partial = Path(temp.name)
    try:
        subprocess.run(["curl", "-fsSL", "--retry", "2", "--max-time", "180", url, "-o", str(partial)], check=True)
        if digest(partial) != checksum:
            raise ValueError(f"Wheel checksum mismatch: {filename}")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


# Each CCXT package module imports all of its ~100 exchange modules. Bind each
# exchange class on first use instead; the package then behaves as before for
# ``getattr(ccxt, id)``, ``ccxt.pro.binance`` and ``from ccxt.pro.okx import okx``.
DEFERRED_CCXT_PACKAGE = '''
# CandleScope browser build: exchange classes load on first use.
import importlib as _importlib
import sys as _sys
import types as _types

_DEFERRED_EXCHANGES = frozenset({names})


class _ExchangePackage(_types.ModuleType):
    # Importing ``<package>.<id>`` binds the submodule here. Keep binding the
    # exchange class, as the eager ``from <package>.<id> import <id>`` did.
    def __setattr__(self, name, value):
        if name in _DEFERRED_EXCHANGES and isinstance(value, _types.ModuleType):
            value = getattr(value, name)
        super().__setattr__(name, value)


def __getattr__(name):
    if name not in _DEFERRED_EXCHANGES:
        raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
    value = getattr(_importlib.import_module(__name__ + "." + name), name)
    globals()[name] = value
    return value


_sys.modules[__name__].__class__ = _ExchangePackage
'''


def defer_ccxt_exchanges(packages):
    for relative, package in (("ccxt/__init__.py", "ccxt"),
                              ("ccxt/async_support/__init__.py", "ccxt.async_support"),
                              ("ccxt/pro/__init__.py", "ccxt.pro")):
        path = packages / relative
        pattern = re.compile(rf"^from {re.escape(package)}\.([a-z0-9_]+) import \1\s+# noqa: F401\s*$", re.M)
        source = path.read_text(encoding="utf-8")
        names = sorted(set(pattern.findall(source)))
        # A different CCXT layout must fail the build, not ship eager imports.
        if len(names) < 50:
            raise RuntimeError(f"Unexpected CCXT package layout in {relative}: {len(names)} exchange imports")
        source = pattern.sub("", source) + DEFERRED_CCXT_PACKAGE.format(names=repr(names))
        path.write_text(source, encoding="utf-8")


def stage(wheels):
    shutil.rmtree(STAGE, ignore_errors=True)
    packages, repo = STAGE / "packages", STAGE / "repo"
    packages.mkdir(parents=True)
    for wheel in sorted(wheels):
        with ZipFile(wheel) as archive:
            archive.extractall(packages)
    defer_ccxt_exchanges(packages)
    roots = ["backend/app", "backend/ccxt-fork.lock.json",
             "packages/candlescope-plugin-sdk/src", "packages/candlescope-backtest-sdk/src",
             "packages/candlescope-external-provider/src"]
    files = subprocess.check_output(["git", "ls-files", "-z", "--", *roots], cwd=ROOT).decode().split("\0")
    for file in filter(None, files):
        target = repo / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / file, target)
    for name in HOST_MODULES:
        shutil.copyfile(HERE / name, repo / name)


def main(output):
    CACHE.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        wheels = list(workers.map(acquire, downloads()))
    stage(wheels)
    node = os.environ.get("CANDLESCOPE_NODE") or shutil.which("node")
    subprocess.run([node, str(HERE / "prepare_engine.mjs"), str(STAGE)], check=True)
    # Fixed timestamps and order keep the archive, and so its hash, reproducible.
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(p for p in STAGE.rglob("*") if p.is_file()):
            entry = ZipInfo(path.relative_to(STAGE).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, path.read_bytes())


if __name__ == "__main__":
    main(sys.argv[1])
