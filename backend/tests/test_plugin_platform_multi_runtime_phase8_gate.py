from __future__ import annotations

from scripts import plugin_platform_multi_runtime_phase8 as phase8


def test_phase8_frozen_contract_matches_implementation() -> None:
    contract = phase8.validate_contract()
    assert contract["schemaVersion"] == phase8.CONTRACT_SCHEMA_VERSION
    assert contract["runtimeRegistry"]["revision"] == 5
    assert contract["provider"]["managedRuntimeOnly"] is True
    assert contract["provider"]["network"] is False
    assert contract["referencePlugin"]["reproducibleBuilds"] == 2


def test_phase8_recorded_real_gate_is_current_and_passed() -> None:
    evidence = phase8.validate_real_gate_evidence()
    assert evidence["wasmtime"]["offlineQuick"] is True
    assert evidence["runtime"]["cancelCode"] == "PLUGIN_WASM_CANCELLED"
    assert evidence["crossHost"]["sandboxClaim"] == "wasi-boundary-only"
    assert evidence["marketplace"]["sandboxStatus"] == "windows-appcontainer"
    assert evidence["marketplace"]["residualProcesses"] == 0


def test_phase8_release_gate_summary_is_fail_closed() -> None:
    result = phase8.run_gate()
    assert result["schemaVersion"] == phase8.GATE_SCHEMA_VERSION
    assert result["result"] == "pass"
    assert result["defaultsRemainOff"] is True
    assert result["linuxSandboxClaim"] == "wasi-boundary-only"


def test_phase8_contract_target_is_windows_on_every_audit_host():
    from app.plugin_core_v2.runtime_providers.wasmtime_policy import wasmtime_fixed_arguments
    windows = wasmtime_fixed_arguments("windows")
    linux = wasmtime_fixed_arguments("linux")
    assert windows[1] == "--config=NUL"
    assert linux[1] == "--config=/dev/null"
    assert windows[2:] == linux[2:]
    assert phase8.capture_contract()["provider"]["fixedArguments"] == list(windows)
