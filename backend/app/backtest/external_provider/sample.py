"""Read bundled example identity as data; never import or execute model code."""

import hashlib
import os
import platform
import shlex
import sys
from pathlib import Path

import tomllib

from app.backtest.strategy.protocol import StrategyProviderError

from .contracts import parse_manifest
from .wire import decode, encode


def descriptor() -> dict:
    root = Path(__file__).resolve().parents[4] / "packages" / "candlescope-external-provider"
    source = root / "src" / "candlescope_external_provider" / "example.py"
    launcher = root / "run_example.py"
    try:
        with source.open("rb") as stream:
            artifact = stream.read(65_537)
        with source.with_name("example_manifest.json").open("rb") as stream:
            metadata = decode(stream.read(16_385), max_bytes=16_384)
        with (root / "pyproject.toml").open("rb") as stream:
            version = tomllib.loads(stream.read(16_385).decode("utf-8"))["project"]["version"]
        if len(artifact) > 65_536 or not launcher.is_file() or type(version) is not str:
            raise ValueError("invalid example package")
        manifest = parse_manifest(encode({**metadata, "artifact_sha256": "sha256:" + hashlib.sha256(artifact).hexdigest(),
                                          "runtime_lock": "python/" + platform.python_version() + ";candlescope-external-provider/" + version}))
    except (OSError, ValueError, KeyError, TypeError):
        raise StrategyProviderError("EXTERNAL_EXAMPLE_UNAVAILABLE", "matching standalone example source is unavailable") from None
    return {"manifest": manifest.model_dump(mode="json"), "manifest_hash": manifest.identity()["manifest_hash"],
            "argv": [sys.executable, "-I", "-S", "-B", str(launcher)]}


def command(argv: list[str]) -> str:
    if os.name == "nt":
        # Explicit PowerShell invocation; single quotes escape by doubling.
        return "& " + " ".join("'" + part.replace("'", "''") + "'" for part in argv)
    return shlex.join(argv)
