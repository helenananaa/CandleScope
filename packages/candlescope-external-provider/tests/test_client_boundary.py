from __future__ import annotations

import ast
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from candlescope_external_provider.client import (
    ENDPOINT_SCHEMA,
    PROTOCOL,
    ExternalClient,
)
from candlescope_external_provider.errors import ExternalProviderError
from candlescope_external_provider.example import RollingMeanModel, manifest
from candlescope_external_provider.wire import decode, digest, encode


def document(tmp_path, model_manifest, *, host="127.0.0.1"):
    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text(encode({"schema_version": ENDPOINT_SCHEMA, "host": host, "port": 8000, "instance_id": "host_one"}))
    path = tmp_path / "connection.json"
    path.write_text(encode({"schema_version": PROTOCOL, "connection_id": "epc_" + "a" * 32,
                            "token": "private-test-capability-credential", "host_endpoint_file": str(endpoint),
                            "scope": {"manifest_hash": digest(model_manifest)}}))
    path.chmod(0o600)
    return path


def test_client_construction_does_not_read_a_file_or_open_a_connection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("constructor must not open a transport")
    monkeypatch.setattr("http.client.HTTPConnection", forbidden)
    client = ExternalClient(tmp_path / "does-not-exist.json", manifest(), RollingMeanModel)
    assert client._document is None and client._http is None


@pytest.mark.parametrize("host", ["8.8.8.8", "0.0.0.0", "::", "example.invalid", "127.0.0.1.example.invalid"])
def test_numeric_loopback_validation_precedes_transport_or_credential_delivery(tmp_path, monkeypatch, host):
    parsed = manifest()
    client = ExternalClient(document(tmp_path, parsed, host=host), parsed, RollingMeanModel)
    client._load_document()
    monkeypatch.setattr("http.client.HTTPConnection", lambda *_a, **_kw: pytest.fail("must not connect"))
    with pytest.raises(ExternalProviderError, match="numeric loopback"):
        client._transport()


def test_a_different_model_manifest_cannot_use_an_existing_connection(tmp_path):
    parsed = manifest()
    path = document(tmp_path, parsed)
    client = ExternalClient(path, {**parsed, "provider_revision": "another"}, RollingMeanModel)
    with pytest.raises(ExternalProviderError, match="IDENTITY_MUTATION") as failure:
        client._load_document()
    assert "private-test-capability-credential" not in str(failure.value)


def test_unicode_canonical_hash_is_ascii_escaped_and_matches_declared_algorithm():
    value = {"中文": [True, None, 1], "decimal": "1.25"}
    expected = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    assert digest(value) == "sha256:" + hashlib.sha256(expected).hexdigest()
    assert decode(encode({"decimal": Decimal("1.25")})) == {"decimal": "1.25"}


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"secret":NaN}', '{"n":1e999}',
                                 '{"n":9007199254740992}', '[' * 40 + '0' + ']' * 40])
def test_invalid_wire_data_is_rejected_without_a_raw_input_exception_chain(raw):
    with pytest.raises(ExternalProviderError) as failure:
        decode(raw)
    assert failure.value.__cause__ is None
    assert raw not in str(failure.value)


def packet(client, operation, cursor, *, state=None, observation=None):
    payload = {"context": {"parameters": {}}} if operation == "prepare" else {"observation": observation}
    if operation == "close":
        payload = {}
    call = {"connection_id": client._document["connection_id"], "client_generation": 1,
            "run_id": "run_one", "host_generation": 1, "cursor": cursor,
            "call_id": "epcall_" + "b" * 32, "operation": operation, "payload": payload,
            "bootstrap": {"context": {"provider": {"manifest_hash": digest(client.manifest)}, "context": {"parameters": {}}},
                          "model_state": state, "model_state_hash": None if state is None else digest(state)}}
    call["input_hash"] = digest({**{key: call[key] for key in ("run_id", "cursor", "operation", "payload")},
                                 "model_state_before_hash": call["bootstrap"]["model_state_hash"]})
    return call


def test_example_restores_causal_warmup_state_and_never_reads_future_bars(tmp_path):
    parsed = manifest()
    client = ExternalClient(document(tmp_path, parsed), parsed, RollingMeanModel)
    client._load_document()
    client._generation = 1
    prepared = client._dispatch(packet(client, "prepare", 1))
    assert prepared["model_state"] == {"closes": [], "quantity": "0.001"}
    state = {"closes": ["10", "9", "8"], "quantity": "0.001"}
    observation = {"run_id": "run_one", "sequence": 4, "event_time_ms": 100, "watermark_ms": 100,
                   "phase": "EVALUATION", "features": {"close": "12"}}
    result = client._dispatch(packet(client, "step", 2, state=state, observation=observation))
    assert result["decision"] == {"sequence": 4, "kind": "TARGET_POSITION", "payload": {"targetExposure": "0.001"}}
    assert result["model_state"]["closes"] == ["9", "8", "12"]
    assert state["closes"] == ["10", "9", "8"]
    invalid = client._dispatch(packet(client, "step", 3, state=state, observation={**observation, "event_time_ms": 101}))
    assert invalid["error"]["code"] == "PROVIDER_PROTOCOL_VIOLATION"


def test_client_package_has_no_host_database_or_plugin_dependency():
    root = Path(__file__).parents[1] / "src" / "candlescope_external_provider"
    forbidden = ("app", "sqlite3", "candlescope_plugin_sdk", "candlescope_plugin_pyne", "candlescope_backtest_sdk")
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(module == item or module.startswith(item + ".") for module in modules for item in forbidden)


def test_host_retirement_closes_only_the_retired_model_between_calls(tmp_path):
    parsed = manifest()
    client = ExternalClient(document(tmp_path, parsed), parsed, RollingMeanModel)

    class TrackedModel:
        closed = False

        def close(self):
            self.closed = True

    cancelled, active = TrackedModel(), TrackedModel()
    client._models = {"cancelled": {"model": cancelled, "generation": 1}, "active": {"model": active, "generation": 2}}
    assert client._reconcile_sessions([{"run_id": "active", "host_generation": 2}]) == {("active", 2)}
    assert cancelled.closed and not active.closed
    assert set(client._models) == {"active"}
