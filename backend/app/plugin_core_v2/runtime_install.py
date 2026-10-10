"""Dispatch legacy script bundles without relaxing the platform trust flow."""
from pathlib import Path
import zipfile

from app.core.config import runtime_environment
from app.plugin_runtime.installer import PluginInstaller
from app.plugin_runtime.registry import default_runtime_registry_path


def is_runtime_bundle(path: Path) -> bool:
    # This is routing only. The runtime installer still strictly verifies the
    # entire archive, manifest, wheels, interpreter and execution probe.
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            return "manifest.json" in names and "bundle.json" not in names
    except zipfile.BadZipFile:
        return False


def install_runtime_bundle(path: Path, expected_sha256: str, host_version: str):
    env = runtime_environment()
    registry = Path(env.get("CANDLESCOPE_RUNTIME_REGISTRY") or default_runtime_registry_path(env))
    installer = PluginInstaller(registry_path=registry, host_version=host_version)
    return installer.install(path, expected_sha256=expected_sha256)
