"""Build a static Pyodide distribution of the original CandleScope packages."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

HERE = Path(__file__).resolve().parent
BROWSER = HERE.parent
ROOT = BROWSER.parents[1]
CACHE = BROWSER / ".host-cache"
LOCK = json.loads((BROWSER / "node_modules/pyodide/pyodide-lock.json").read_text())
PINS = json.loads((HERE / "wheels.json").read_text())


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


def main(output):
    CACHE.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        wheels = list(workers.map(acquire, downloads()))
    # Keep wheels as wheels. Several WASM extension packages use sibling .so files.
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=4) as archive:
        for wheel in sorted(wheels):
            archive.write(wheel, "wheels/" + wheel.name)
        roots = ["backend/app", "backend/ccxt-fork.lock.json",
                 "packages/candlescope-plugin-sdk/src", "packages/candlescope-backtest-sdk/src",
                 "packages/candlescope-external-provider/src"]
        files = subprocess.check_output(["git", "ls-files", "-z", "--", *roots], cwd=ROOT).decode().split("\0")
        for file in sorted(filter(None, files)):
            archive.write(ROOT / file, "repo/" + file)
        for name in ("browser_host.py", "browser_io.py", "library_download.py"):
            archive.write(HERE / name, "repo/" + name)


if __name__ == "__main__":
    main(sys.argv[1])
