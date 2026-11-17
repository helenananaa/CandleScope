from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from candlescope_plugin_sdk.platform_v2 import PlatformContractError
from candlescope_plugin_sdk.unified import (
    ActivationIdentity,
    Entry,
    Manifest,
    ManifestError,
    PlanError,
    activation_order,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "examples/unified-plugins/workbench/manifest.json"


def manifest(plugin_id="example.workbench", **overrides):
    raw = json.loads(FIXTURE.read_text())
    raw.update(id=plugin_id, **overrides)
    return raw


def test_multientry_manifest_is_an_immutable_package_identity():
    raw = manifest(dependencies={"example.provider": "1.0.0"})
    parsed = Manifest.from_wire(raw)
    raw["entries"][0]["path"] = "changed.mjs"
    raw["dependencies"]["example.provider"] = "2.0.0"
    assert parsed.entries[0].path == "frontend.mjs"
    assert parsed.dependencies == (("example.provider", "1.0.0"),)
    assert Manifest.from_json(json.dumps(parsed.to_wire())) == parsed
    with pytest.raises(AttributeError):
        parsed.version = "2.0.0"


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "ui", "kind": "frontend", "path": "main.mjs"},
        {"id": "service", "kind": "backend", "path": "main.py"},
        {"id": "desktop", "kind": "desktop", "path": "main.mjs"},
    ],
)
def test_restricted_packages_cannot_request_host_execution(entry):
    with pytest.raises(ManifestError, match="full-trust"):
        Manifest.from_wire(manifest(trust="restricted", entries=[entry]))


def test_restricted_package_may_declare_data_sandbox_and_explicit_sidecar():
    parsed = Manifest.from_wire(
        manifest(
            trust="restricted",
            entries=[
                {"id": "view", "kind": "sandbox-view", "path": "web/index.html"},
                {
                    "id": "worker",
                    "kind": "sidecar",
                    "path": "worker/main.py",
                    "runtime": "python-module",
                },
                {"id": "theme", "kind": "data", "path": "theme.json"},
            ],
            permissions=["market.read/1"],
        )
    )
    assert [e.kind for e in parsed.entries] == ["sandbox-view", "sidecar", "data"]
    # Declarations do not create capability handles or host access.
    assert parsed.permissions == ("market.read/1",)


@pytest.mark.parametrize(
    "path",
    [
        "../main.mjs",
        "/main.mjs",
        "C:/main.mjs",
        "a\\main.mjs",
        "a//main.mjs",
        "a/./main.mjs",
        "a/../main.mjs",
        "a./main.mjs",
        "NUL/main.mjs",
        "con.txt/main.mjs",
        "a/COM1.mjs",
        "main.mjs?token=1",
        "main.mjs\x00",
    ],
)
def test_cross_platform_entry_paths_are_checked_before_materialization(path):
    with pytest.raises(ManifestError):
        Entry("ui", "frontend", path)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "candlescope.extension/1"},
        {"schema": 2},
        {"hostApiVersion": True},
        {"hostApiVersion": 2},
        {"trust": "trusted-local"},
        {"trust": []},
        {"version": "^1.0.0"},
        {"version": "01.0.0"},
        {"version": "1.0.0-01"},
        {"entries": []},
        {"entries": {}},
        {"entries": [None]},
        {"entries": [{"id": "ui", "kind": "frontend", "path": "main.mjs", "runtime": None}]},
        {"dependencies": {"example.workbench": "1.0.0"}},
        {"dependencies": {"example.provider": "*"}},
        {"permissions": ["market.read/1", "market.read/1"]},
        {"permissions": ["*"]},
        {"permissions": [None]},
        {"permissions": {"market.read/1": True}},
        {"legacyCompatibility": True},
    ],
)
def test_unsupported_or_ambiguous_contracts_fail_closed(changes):
    with pytest.raises(ManifestError):
        Manifest.from_wire(manifest(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "candlescope.pyne"},
        {"language": "pyne"},
        {"language": "PYNE"},
        {"plugin": {"id": "candlescope.pyne"}, "schemaVersion": 1},
        {
            "entries": [
                {"id": "worker", "kind": "sidecar", "path": "main.pyne", "runtime": "python-module"}
            ]
        },
        {"entries": [{"id": "worker", "kind": "sidecar", "path": "main.py", "runtime": "pyne"}]},
    ],
)
def test_retired_pyne_is_explicitly_rejected_without_translation(changes):
    raw = manifest()
    raw.update(changes)
    before = copy.deepcopy(raw)
    with pytest.raises(ManifestError, match="Pyne is retired"):
        Manifest.from_wire(raw)
    assert raw == before


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema":1,"schema":2}',
        b'{"n":NaN}',
        b"\xff",
        b'{"deep":' + b"[" * 16 + b"0" + b"]" * 16 + b"}",
        b" " * (256 * 1024 + 1),
    ],
)
def test_raw_json_has_size_depth_encoding_and_duplicate_key_limits(payload):
    with pytest.raises(PlatformContractError):
        Manifest.from_json(payload)


def test_duplicates_and_bounds_are_rejected():
    entry = manifest()["entries"][0]
    for entries in ([entry, entry], [{**entry, "id": f"e{i}"} for i in range(33)]):
        with pytest.raises(ManifestError):
            Manifest.from_wire(manifest(entries=entries))
    with pytest.raises(ManifestError):
        Manifest.from_wire(manifest(dependencies={f"example.p{i}": "1.0.0" for i in range(33)}))


def test_dependency_order_is_deterministic_for_a_diamond_and_reversed_input():
    root = Manifest.from_wire(manifest("example.root"))
    left = Manifest.from_wire(manifest("example.left", dependencies={root.id: root.version}))
    right = Manifest.from_wire(manifest("example.right", dependencies={root.id: root.version}))
    child = Manifest.from_wire(
        manifest("example.child", dependencies={left.id: left.version, right.id: right.version})
    )
    expected = (root, left, right, child)
    assert activation_order([child, right, left, root]) == expected
    assert activation_order(reversed(expected)) == expected


def test_dependency_preflight_rejects_provider_upgrade_and_removal():
    old = Manifest.from_wire(manifest("example.provider"))
    new = Manifest.from_wire(manifest("example.provider", version="2.0.0"))
    child = Manifest.from_wire(manifest("example.child", dependencies={old.id: old.version}))
    assert activation_order([child, old]) == (old, child)
    with pytest.raises(PlanError, match="not 2.0.0"):
        activation_order([new, child])
    with pytest.raises(PlanError, match="missing dependency"):
        activation_order([child])
    assert activation_order([]) == ()


def test_cycle_and_duplicate_package_identity_cannot_start_any_entry():
    a = Manifest.from_wire(manifest("example.a", dependencies={"example.b": "1.0.0"}))
    b = Manifest.from_wire(manifest("example.b", dependencies={"example.a": "1.0.0"}))
    with pytest.raises(PlanError, match="cycle"):
        activation_order([a, b])
    with pytest.raises(PlanError, match="duplicate"):
        activation_order([a, a])


def test_bounded_planning_including_the_maximum_dependency_chain():
    plugins = [
        Manifest.from_wire(
            manifest(
                f"example.p{i}", dependencies=({f"example.p{i + 1}": "1.0.0"} if i < 255 else {})
            )
        )
        for i in range(256)
    ]
    assert len(activation_order(plugins)) == 256
    with pytest.raises(PlanError, match="256"):
        activation_order([*plugins, Manifest.from_wire(manifest("example.extra"))])


def test_activation_identity_distinguishes_digest_version_and_generation():
    first = ActivationIdentity("example.workbench", "1.0.0", "sha256:" + "a" * 64, 1)
    second = ActivationIdentity("example.workbench", "1.0.0", first.package_sha256, 2)
    replacement = ActivationIdentity("example.workbench", "1.0.0", "sha256:" + "b" * 64, 2)
    assert len({first, second, replacement}) == 3
    upgraded = ActivationIdentity(first.plugin_id, "2.0.0", first.package_sha256, 2)
    assert upgraded != second
    for invalid in (True, 0, -1, 9_007_199_254_740_992):
        with pytest.raises(ManifestError):
            ActivationIdentity(first.plugin_id, first.plugin_version, first.package_sha256, invalid)


def test_inspector_validates_metadata_without_executing_or_installing(tmp_path):
    raw = manifest(entries=[{"id": "service", "kind": "backend", "path": "main.py"}])
    marker = tmp_path / "executed.txt"
    (tmp_path / "main.py").write_text(
        f"open({str(marker)!r}, 'w').write('executed')\nraise RuntimeError()"
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw))
    result = subprocess.run(
        [sys.executable, str(REPO / "backend/scripts/inspect_unified_plugin.py"), str(path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["productionInstallable"] is False
    assert report["activationOrder"] == ["example.workbench"]
    assert not marker.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["main.py", "manifest.json"]


def test_inspector_returns_actionable_rejection_without_modifying_input(tmp_path):
    path = tmp_path / "manifest.json"
    contents = json.dumps(manifest(dependencies={"example.missing": "1.0.0"}))
    path.write_text(contents)
    result = subprocess.run(
        [sys.executable, str(REPO / "backend/scripts/inspect_unified_plugin.py"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not result.stdout
    assert "missing dependency" in json.loads(result.stderr)["error"]
    assert path.read_text() == contents
