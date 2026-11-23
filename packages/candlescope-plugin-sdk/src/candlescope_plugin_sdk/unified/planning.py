"""Pure dependency preflight and package activation identity; no install side effects."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .manifest import Manifest, ManifestError, identifier, version

MAX_PLAN_PLUGINS = 256


class PlanError(ValueError):
    """The complete proposed enabled set cannot activate as one plan."""


def activation_order(manifests: Iterable[Manifest]) -> tuple[Manifest, ...]:
    """Validate the whole enabled set before any entry is started.

    Callers pass the proposed set after install/upgrade/disable/uninstall, not
    just the changed package. This also detects upgrades breaking dependents.
    Independent nodes are ordered by id; dependency providers always come first.
    """
    plugins: dict[str, Manifest] = {}
    claims: dict[str, str] = {}
    for manifest in manifests:
        if not isinstance(manifest, Manifest):
            raise PlanError("activation plans require validated manifests")
        if manifest.id in plugins:
            raise PlanError(f"duplicate plugin identity: {manifest.id}")
        if len(plugins) >= MAX_PLAN_PLUGINS:
            raise PlanError("activation plan exceeds 256 plugins")
        plugins[manifest.id] = manifest
        for entry in manifest.entries:
            for target in entry.startup:
                if target in claims:
                    raise PlanError(f"startup target {target} claimed by {claims[target]} and {manifest.id}/{entry.id}")
                claims[target] = f"{manifest.id}/{entry.id}"
    for manifest in plugins.values():
        for dep_id, required_version in manifest.dependencies:
            provider = plugins.get(dep_id)
            if provider is None:
                raise PlanError(
                    f"{manifest.id} requires missing dependency {dep_id}@{required_version}"
                )
            if provider.version != required_version:
                raise PlanError(
                    f"{manifest.id} requires {dep_id}@{required_version}, not {provider.version}"
                )
    result: list[Manifest] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(plugin_id: str) -> None:
        if plugin_id in visited:
            return
        if plugin_id in visiting:
            raise PlanError(f"dependency cycle includes {plugin_id}")
        visiting.add(plugin_id)
        for dep_id, _ in plugins[plugin_id].dependencies:
            visit(dep_id)
        visiting.remove(plugin_id)
        visited.add(plugin_id)
        result.append(plugins[plugin_id])

    for plugin_id in sorted(plugins):
        visit(plugin_id)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ActivationIdentity:
    """One package activation across all entries, never a permission grant.

    The lifecycle owner must allocate a fresh persisted generation on every
    activation including rollback/re-enable, and revoke it before cleanup.
    Process/window instance identities are additionally required by dispatchers.
    """

    plugin_id: str
    plugin_version: str
    package_sha256: str
    generation: int

    def __post_init__(self) -> None:
        identifier(self.plugin_id, "activation.pluginId")
        version(self.plugin_version, "activation.version")
        if (
            not isinstance(self.package_sha256, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.package_sha256) is None
        ):
            raise ManifestError("activation requires the exact package sha256")
        if type(self.generation) is not int or not 1 <= self.generation <= 9_007_199_254_740_991:
            raise ManifestError("activation generation must be a positive safe integer")

    def to_wire(self) -> dict:
        return {
            "pluginId": self.plugin_id,
            "version": self.plugin_version,
            "packageSha256": self.package_sha256,
            "generation": self.generation,
        }
