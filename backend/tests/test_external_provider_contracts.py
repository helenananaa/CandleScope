from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.backtest.external_provider.contracts import parse_manifest
from app.backtest.strategy.protocol import StrategyProviderError


def manifest(**overrides: object) -> str:
    return json.dumps({
        "schema_version": "candlescope.external-provider/1",
        "provider_id": "example.zscore",
        "provider_revision": "1",
        "provider_kind": "MODEL",
        "artifact_sha256": "sha256:" + "a" * 64,
        "runtime_lock": "example-client/1;model.json/1",
        "input_modes": ["BAR_CLOSE"],
        "output_modes": ["TARGET_POSITION"],
        "required_features": ["close", "volume"],
        "warmup_bars": 3,
        "snapshot_restore": True,
        "reproducibility": "RECORDED_OUTPUT_ONLY",
        **overrides,
    })


def test_identity_is_frozen_and_does_not_certify_the_external_process() -> None:
    parsed = parse_manifest(manifest())
    assert parsed.capabilities().signal_clock == "BAR_CLOSE"
    assert parsed.capabilities().required_features == ("close", "volume")
    assert parsed.capabilities().reproducibility == ("RECORDED_OUTPUT_ONLY",)
    assert parsed.capabilities().warmup_requirement == {"kind": "FIXED_BARS", "bars": 3}
    assert isinstance(parsed.required_features, tuple)
    with pytest.raises(ValidationError):
        parsed.runtime_lock = "other-runtime"  # type: ignore[misc]


def test_feature_order_and_artifact_revision_are_part_of_identity() -> None:
    original = parse_manifest(manifest())
    formatted = json.dumps(json.loads(manifest()), indent=2, sort_keys=True)
    assert parse_manifest(formatted).identity() == original.identity()
    assert parse_manifest(manifest(required_features=["volume", "close"])).identity() != original.identity()
    assert parse_manifest(manifest(artifact_sha256="sha256:" + "b" * 64)).identity() != original.identity()


@pytest.mark.parametrize("extra", [
    {"endpoint": "https://example.invalid/model"},
    {"account_model": "EXTERNAL_ACCOUNT"},
    {"balance": "999999"},
    {"database": "/private/database"},
    {"source": "print('must not execute')"},
])
def test_manifest_cannot_grant_execution_network_or_account_authority(extra: dict) -> None:
    with pytest.raises(StrategyProviderError, match="PROVIDER_PROTOCOL_VIOLATION"):
        parse_manifest(manifest(**extra))


@pytest.mark.parametrize("change", [
    {"artifact_sha256": "latest"},
    {"input_modes": ["FUTURE_BARS"]},
    {"output_modes": ["ACCOUNT_UPDATE"]},
    {"required_features": ["close", "close"]},
    {"warmup_bars": True},
    {"snapshot_restore": 1},
    {"snapshot_restore": False},
    {"reproducibility": "DETERMINISTIC"},
])
def test_unsupported_or_ambiguous_capabilities_fail_closed(change: dict) -> None:
    with pytest.raises(StrategyProviderError):
        parse_manifest(manifest(**change))


def test_model_cannot_claim_script_order_intents() -> None:
    with pytest.raises(StrategyProviderError, match="order intents require a strategy"):
        parse_manifest(manifest(output_modes=["ORDER_INTENT"]))
    parsed = parse_manifest(manifest(provider_kind="STRATEGY", output_modes=["ORDER_INTENT"]))
    assert parsed.capabilities().output_modes == ("ORDER_INTENT",)


def test_duplicate_json_keys_and_nonfinite_values_are_rejected() -> None:
    source = manifest().replace('"provider_revision": "1"', '"provider_revision": "1", "provider_revision": "2"')
    with pytest.raises(StrategyProviderError, match="duplicate manifest field"):
        parse_manifest(source)
    with pytest.raises(StrategyProviderError, match="non-finite JSON"):
        parse_manifest(manifest(warmup_bars=float("nan")))


def test_error_does_not_echo_a_misplaced_connection_credential() -> None:
    secret = "private-test-connection-credential"
    with pytest.raises(StrategyProviderError) as failure:
        parse_manifest(manifest(connection_token=secret))
    assert secret not in str(failure.value)
