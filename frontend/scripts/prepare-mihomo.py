"""Install the platform-specific, checksum-pinned proxy core into the staged desktop runtime."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import platform
from pathlib import Path
import shutil
import sys
from urllib.request import Request, urlopen
from zipfile import ZipFile

VERSION = "v1.19.34"
UPSTREAM = "https://github.com/MetaCubeX/mihomo"
ASSETS = {
    ("darwin", "arm64"): ("darwin-arm64", "gz", "1a7a20eca63fbbaec90137717465bfde488d0db2a3a79b8fadebf9b2545b6e4c"),
    ("darwin", "x86_64"): ("darwin-amd64-v1", "gz", "84af3a9ffd4699e02f14b89859c58b4fc380f6a2135037c6e88e6822347ae657"),
    ("win32", "amd64"): ("windows-amd64-v1", "zip", "703e325bfeee582f874b06d054eaae55ab7c194645d1835411685aafa85da5ea"),
    ("win32", "arm64"): ("windows-arm64", "zip", "076cb04a21377675bcf009b8d1dd83006ce2464aa537e37bce1faf6d3504f554"),
}
LICENSE_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def verified(url, digest, cache):
    path = cache / digest
    if path.exists():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            return data
    with urlopen(Request(url, headers={"User-Agent": "CandleScope-build"}), timeout=90) as reply:
        data = reply.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Mihomo artifact checksum mismatch")
    path.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    target, extension, digest = ASSETS[sys.platform, platform.machine().lower()]
    asset = f"mihomo-{target}-{VERSION}.{extension}"
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    raw = verified(f"{UPSTREAM}/releases/download/{VERSION}/{asset}", digest, args.cache)
    exe = args.output / ("mihomo.exe" if sys.platform == "win32" else "mihomo")
    if extension == "zip":
        with ZipFile(io.BytesIO(raw)) as archive:
            (filename,) = [name for name in archive.namelist() if name.endswith(".exe")]
            with archive.open(filename) as src, exe.open("wb") as dest:
                shutil.copyfileobj(src, dest)
    else:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as src, exe.open("wb") as dest:
            shutil.copyfileobj(src, dest)
    exe.chmod(0o755)
    license_url = f"https://raw.githubusercontent.com/MetaCubeX/mihomo/{VERSION}/LICENSE"
    (args.output / "LICENSE").write_bytes(verified(license_url, LICENSE_SHA256, args.cache))
    (args.output / "SOURCE.txt").write_text(
        f"Mihomo {VERSION}\n{UPSTREAM}/tree/{VERSION}\n{UPSTREAM}/archive/refs/tags/{VERSION}.tar.gz\n"
        f"Unmodified release artifact: {asset}\nSHA-256: {digest}\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
