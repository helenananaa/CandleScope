"""Exercise localization without importing the optional native Pyne engine."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import jsonschema
import pytest

from candlescope_plugin_sdk.platform_v2 import PluginManifest, manifest_schema
from candlescope_plugin_sdk.platform_v2.errors import PlatformContractError

ROOT = Path(__file__).resolve().parents[1] / "src" / "candlescope_plugin_pyne_workbench"
LOCALES = ("de-DE", "it-IT", "id-ID", "tr-TR", "vi-VN", "pl-PL")


def localization_namespace():
    # Compile the actual pure localization function and resource assignment only.
    # No replacement Pyne module or no-op schema validator is involved.
    source = ast.parse((ROOT / "plugin.py").read_text(encoding="utf-8"))
    nodes = [
        node for node in source.body
        if (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_CONTRACT_LOCALIZATIONS"
            for target in node.targets
        )) or (isinstance(node, ast.FunctionDef) and node.name == "_localized_contract_error")
    ]
    assert len(nodes) == 2
    namespace = {"PlatformContractError": PlatformContractError}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "plugin.py"), "exec"), namespace)
    return namespace


def test_translated_manifest_passes_real_schema_and_sdk_validation():
    raw = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    jsonschema.validate(raw, manifest_schema())
    assert PluginManifest.from_wire(raw).to_wire() == raw


@pytest.mark.parametrize("requested", LOCALES)
def test_contract_translations_preserve_tokens_codes_paths_and_regional_resolution(requested):
    namespace = localization_namespace()
    resources = namespace["_CONTRACT_LOCALIZATIONS"]
    translate = namespace["_localized_contract_error"]
    catalog = resources[requested.split("-")[0]]
    reference = resources["zh-CN"]
    assert catalog.keys() == reference.keys()
    for key, text in catalog.items():
        assert sorted(re.findall(r"\{\w+\}", text)) == sorted(re.findall(r"\{\w+\}", reference[key]))
        assert not re.search(r"[\u3400-\u9fff]", text)
        if key in ("boundedString", "capabilityUnavailable"):
            continue
        error = PlatformContractError("INVALID_CONTRACT", key, "input.value")
        localized = translate(error, requested.upper())
        assert localized.message == text
        assert localized.message != key
        assert (localized.code, localized.path) == (error.code, error.path)
    for message, key, token in (
        ("market.read capability is unavailable", "capabilityUnavailable", "permission"),
        ("paramsJson must be a bounded string", "boundedString", "key"),
    ):
        value = "market.read" if token == "permission" else "paramsJson"
        error = PlatformContractError("INVALID_CONTRACT", message, "input.value")
        assert translate(error, requested).message == catalog[key].replace("{" + token + "}", value)
    unknown = PlatformContractError("UNKNOWN", "unrecognized diagnostic", "input.value")
    assert translate(unknown, requested) is unknown
    assert translate(unknown, "qaa") is unknown
