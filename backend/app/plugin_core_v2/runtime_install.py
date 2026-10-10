"""Dispatch legacy script bundles without relaxing the platform trust flow."""
from pathlib import Path
from dataclasses import dataclass
import zipfile

from candlescope_plugin_sdk.platform_v2 import (
    PluginIdentity, PermissionSet, NormalizedEntrypoint, PythonModuleRuntime,
)

from app.core.config import runtime_environment
from app.plugin_runtime.installer import PluginInstaller
from app.plugin_runtime.registry import default_runtime_registry_path
from app.plugin_runtime.bundle import verify_plugin_bundle


@dataclass(frozen=True)
class RuntimeReviewManifest:
    plugin: PluginIdentity
    normalized_entrypoints: tuple[NormalizedEntrypoint, ...]
    permissions: PermissionSet


@dataclass(frozen=True)
class RuntimeReviewBundle:
    """Review-only projection; execution always uses the script installer.

    Keep the original archive/manifest digests. This is not a Platform v2 bundle
    and must never be recorded in the platform marketplace or activation registry.
    """

    manifest: RuntimeReviewManifest
    sha256: str
    manifest_sha256: str


def review_runtime_bundle(path: Path, *, expected_sha256: str, host_version: str):
    bundle = verify_plugin_bundle(path, expected_sha256=expected_sha256)
    original = bundle.manifest
    manifest = RuntimeReviewManifest(
        plugin=PluginIdentity(
            id=f"script-runtime.{original.runtime_id}",
            name=original.name, version=original.version,
            publisher="unsigned-script-runtime", license="NOASSERTION",
            candlescope_engine=f">={host_version}",
        ),
        normalized_entrypoints=(NormalizedEntrypoint(
            id="main", runtime=PythonModuleRuntime(module=original.module, runtime_id="python-v2-compat"),
            transport="jsonl/1", resource_profile="minimal",
            activation_events=(), source_manifest_version=1,
        ),),
        permissions=PermissionSet(required=(), optional=()),
    )
    return RuntimeReviewBundle(manifest, bundle.sha256, bundle.manifest_sha256)


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
