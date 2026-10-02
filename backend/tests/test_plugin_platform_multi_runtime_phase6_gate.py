from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import plugin_platform_multi_runtime_phase6 as phase6


@pytest.fixture(scope="module")
def gate_result() -> dict[str, object]:
    return phase6.run_gate()


def test_phase6_historical_v1_fixture_is_not_rewritten() -> None:
    historical = phase6.validate_historical_contract_v1()

    assert historical["schemaVersion"] == phase6.HISTORICAL_CONTRACT_SCHEMA_VERSION
    assert historical["ui"]["runtimeAndPermissionDiff"] is True
    assert historical["ui"]["verifiedPublisherNotSafeOrOfficial"] is True


def test_phase6_previous_v2_fixture_is_not_rewritten() -> None:
    previous = phase6.validate_previous_contract_v2()

    assert previous["schemaVersion"].endswith("/2")
    assert previous["previousContractSha256"] == (
        "sha256:" + phase6.HISTORICAL_CONTRACT_FILE_SHA256
    )


def test_phase6_v3_only_migrates_ui_contract() -> None:
    previous = phase6.validate_previous_contract_v2()
    current = phase6.validate_contract()
    changed = {key for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)}
    assert changed == {"schemaVersion", "migratedOn", "previousContractSha256", "ui"}


def test_phase6_rejects_rewritten_v2_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = phase6.validate_previous_contract_v2()
    previous["trust"]["singleUseTokens"] = False
    path = tmp_path / "phase6-rewritten-v2.json"
    path.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(phase6, "PREVIOUS_CONTRACT_PATH", path)
    with pytest.raises(phase6.Phase6GateError, match="v2 was rewritten"):
        phase6.validate_contract()


def test_phase6_contract_freezes_trust_grants_sandbox_and_jre_migration() -> None:
    contract = phase6.validate_contract()

    assert contract["schemaVersion"] == phase6.CONTRACT_SCHEMA_VERSION
    assert contract["previousContractSha256"] == (
        "sha256:" + phase6.PREVIOUS_CONTRACT_FILE_SHA256
    )
    assert contract["realGateEvidenceContractSha256"] == (
        phase6._canonical_sha256(phase6.validate_historical_contract_v1())
    )
    assert contract["trust"]["localMode"] == "trusted-local"
    assert contract["trust"]["marketplaceDefaultMode"] == "marketplace-sandboxed"
    assert contract["trust"]["itemizedAcknowledgements"] is True
    assert contract["trust"]["distinctUserActions"] is True
    assert contract["trust"]["singleUseTokens"] is True
    assert contract["grantStore"]["runtimeBoundSchemaVersion"] == 2
    assert (
        contract["grantStore"][
            "runtimePublisherSignatureAndPathChangeRevokeInheritance"
        ]
        is True
    )
    assert contract["sandbox"]["phase6AttackKinds"] == [
        "java-jar",
        "native-executable",
        "python-module",
    ]
    assert contract["sandbox"]["signedMarketplaceLifecycleKinds"] == ["python-module"]
    assert contract["sandbox"]["multiRuntimeMarketplaceDistributionPhase"] == 10
    assert all(
        item["sandboxMode"] == "windows-appcontainer"
        and item["limits"]["maxProcesses"] == 1
        and item["networkDefault"] == "denied"
        for item in contract["sandbox"]["windowsProfiles"]
    )
    registry = contract["runtimeRegistryMigration"]
    assert registry["revision"] == 3
    assert registry["previousRevision"] == 2
    assert registry["runtimeId"] == phase6.JAVA_RUNTIME_ID
    assert registry["retainsTemurin25ForRollback"] is True
    assert registry["appContainerCompatibilityIssue"] == "JDK-8352728"
    assert contract["ta4jRuntimeMigration"] == {
        "pluginVersion": "0.1.1",
        "adapterVersion": "0.1.0",
        "adapterJarSha256": "sha256:19c60a36d178d9e9340c4133ed0d60f4d80e4c19c3e17e01aaca6231bdcd6060",
        "runtimeId": phase6.JAVA_RUNTIME_ID,
        "runtimeLockMatchesManifest": True,
        "adapterJarReused": True,
    }
    assert contract["rollout"]["trustUxDefault"] is False
    assert contract["rollout"]["liveDefaults"] == [False] * 5
    assert contract["ui"]["runtimeAndPermissionDiff"] is True
    assert contract["ui"]["verifiedPublisherNotSafeOrOfficial"] is True
    assert contract["ui"]["catalogScope"] == ["plugin.", "pc."]
    assert set(contract["ui"]["managementSurfaceSha256"]) == {
        "PluginCenter.tsx",
        "PluginInstallFlow.tsx",
        "PluginDetail.tsx",
        "PluginManagementSections.tsx",
    }


def _replace_source(
    monkeypatch: pytest.MonkeyPatch, relative: str, old: str, new: str
) -> None:
    target = (phase6.REPOSITORY_ROOT / relative).resolve()
    original = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        source = original(path, *args, **kwargs)
        if path.resolve() == target:
            assert old in source
            return source.replace(old, new)
        return source

    monkeypatch.setattr(Path, "read_text", read_text)


@pytest.mark.parametrize(
    ("marker", "field"),
    [
        ('data-plugin-trust-flow="itemized-double-confirmation"', "itemizedDoubleConfirmation"),
        ('t("plugin.host.runtimeDiff")', "runtimeAndPermissionDiff"),
        ("useState<PluginTrustReview | null>", "tokenKeptInReactMemory"),
        ('t("plugin.market.notCodeSafety")', "verifiedPublisherNotSafeOrOfficial"),
    ],
)
def test_phase6_reads_actual_management_surface_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch, marker: str, field: str
) -> None:
    _replace_source(
        monkeypatch,
        "frontend/src/features/plugins/PluginManagementSections.tsx",
        marker,
        "REMOVED_TRUST_BOUNDARY",
    )
    assert phase6.capture_contract()["ui"][field] is False
    with pytest.raises(phase6.Phase6GateError, match="contract drift"):
        phase6.validate_contract()


def test_phase6_rejects_disconnected_install_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    _replace_source(
        monkeypatch,
        "frontend/src/features/plugins/PluginCenter.tsx",
        "<PluginInstallFlow ",
        "<DisconnectedInstallFlow ",
    )
    with pytest.raises(phase6.Phase6GateError, match="contract drift"):
        phase6.validate_contract()


def test_phase6_ignores_unrelated_catalog_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    before = phase6.validate_contract()
    _replace_source(
        monkeypatch,
        "frontend/src/i18n/catalogs/en.ts",
        '"settings.language.reload": "Refresh page"',
        '"settings.language.reload": "Reload this page"',
    )
    assert phase6.validate_contract() == before


@pytest.mark.parametrize(
    "relative",
    ["frontend/src/i18n/catalogs/en.ts", "frontend/src/i18n/catalogs/zh-CN.ts"],
)
def test_phase6_rejects_plugin_catalog_copy_drift(
    monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    _replace_source(
        monkeypatch, relative, '"plugin.market.notCodeSafety":', '"plugin.market.removedWarning":'
    )
    assert phase6.capture_contract()["ui"]["verifiedPublisherNotSafeOrOfficial"] is False
    with pytest.raises(phase6.Phase6GateError, match="contract drift"):
        phase6.validate_contract()


@pytest.mark.parametrize(
    "source",
    [
        '"plugin.message": computedCopy,',
        '"plugin.message": "first",\n"plugin.message": "duplicate",',
        '"plugin.message": "first", "plugin.message": "duplicate",',
        '"settings.message": "unrelated",',
    ],
)
def test_phase6_catalog_capture_fails_closed_on_unrecognized_entries(source: str) -> None:
    with pytest.raises(phase6.Phase6GateError, match="plugin catalog"):
        phase6._plugin_catalog_entries(source)


def test_phase6_contract_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = json.loads(phase6.CONTRACT_PATH.read_text(encoding="utf-8"))
    drifted["trust"]["singleUseTokens"] = False
    path = tmp_path / "phase6-drifted.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    monkeypatch.setattr(phase6, "CONTRACT_PATH", path)

    with pytest.raises(phase6.Phase6GateError, match="contract drift"):
        phase6.validate_contract()


def test_phase6_recorded_windows_gate_covers_every_executable_kind() -> None:
    evidence = phase6.validate_real_gate_evidence()

    assert evidence["schemaVersion"] == phase6.REAL_GATE_SCHEMA_VERSION
    assert evidence["result"] == "pass"
    assert evidence["managedJre"]["runtimeId"] == phase6.JAVA_RUNTIME_ID
    assert evidence["managedJre"]["offlineQuick"] is True
    assert evidence["managedJre"]["downloadedEvidenceFiles"] == 5
    assert set(evidence["attacks"]) == {
        "python-module",
        "java-jar",
        "native-executable",
    }
    for result in evidence["attacks"].values():
        assert result["sandboxMode"] == "windows-appcontainer"
        assert result["appContainerSidPresent"] is True
        assert result["activeProcessLimit"] == 1
        assert result["networkCapabilities"] == []
        assert result["exitCode"] == 0
        assert result["result"] == phase6.EXPECTED_ATTACK_RESULT
    lifecycle = evidence["signedMarketplaceLifecycle"]
    assert set(lifecycle["kinds"]) == {"python-module"}
    assert lifecycle["residualProcesses"] == 0
    assert lifecycle["residualSupervisors"] == 0
    python = lifecycle["kinds"]["python-module"]
    assert python["trustMode"] == "marketplace-sandboxed"
    assert python["sandboxStatus"] == "windows-appcontainer"
    assert python["processTreeControl"] is True
    assert python["generation"] == 2
    assert all(
        evidence["defaults"][key] is False
        for key in (
            "trustUxEnabled",
            "liveBrokerFoundationEnabled",
            "liveAccountReadonlyEnabled",
            "liveReconciliationShadowEnabled",
            "liveNativeControlEnabled",
            "liveTestnetExecutionEnabled",
        )
    )


def test_phase6_gate_binds_real_evidence_to_frozen_contract(
    gate_result: dict[str, object],
) -> None:
    assert gate_result["schemaVersion"] == phase6.GATE_SCHEMA_VERSION
    assert gate_result["result"] == "pass"
    assert gate_result["attackKinds"] == [
        "java-jar",
        "native-executable",
        "python-module",
    ]
    assert gate_result["signedMarketplaceKinds"] == ["python-module"]
    assert gate_result["residualProcesses"] == 0
    assert gate_result["trustUxDefault"] is False
    assert gate_result["liveDefaultsRemainOff"] is True
    assert gate_result["realEvidenceContractSha256"] == (
        phase6._canonical_sha256(phase6.validate_historical_contract_v1())
    )
    assert gate_result["realEvidenceContractSha256"] != gate_result["contractSha256"]


def test_phase6_cli_prints_and_atomically_writes_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "nested" / "phase6-contract.json"
    assert phase6.main(["--print-contract", "--output", str(output)]) == 0
    captured = capsys.readouterr()

    assert captured.err == ""
    assert json.loads(captured.out) == phase6.capture_contract()
    assert json.loads(output.read_text(encoding="utf-8")) == phase6.capture_contract()
    assert list(output.parent.glob(f".{output.name}.*")) == []
