"""Retired scripts must not execute or be silently translated to Pine."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.indicators import router
from app.backtest.native_contracts import NativeRunRequest
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.workspace import compile_revision
from app.indicator.custom_store import CustomIndicatorStore
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes, IndicatorRuntimeRoutesError
from app.plugin_runtime.bootstrap import build_runtime_host_from_environment


def test_first_party_script_routes_reject_pyne():
    routes = IndicatorRuntimeRoutes.first_party_sidecar_default()
    assert [route.language for route in routes.routes] == ["pine", "python"]
    with pytest.raises(IndicatorRuntimeRoutesError, match="unsupported"):
        IndicatorRuntimeRoute("pyne", "sidecar", "candlescope.pyne")


@pytest.mark.parametrize("language", ["PYNE", "PYNE_CHART_V1", "PYNE_ORDER_DSL"])
def test_retired_strategy_compilers_are_rejected(language):
    with pytest.raises(StrategyProviderError, match="unsupported strategy language"):
        compile_revision({"language": language, "name": "old", "source_text": "plot(close)"}, now_ms=1)


def test_native_contract_rejects_retired_language_before_running():
    with pytest.raises(ValidationError) as error:
        NativeRunRequest.model_validate({"language": "pyne"})
    assert any(item["loc"] == ("language",) and item["type"] == "literal_error" for item in error.value.errors())


def test_retired_indicator_api_is_absent_and_compute_fails_closed():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        assert client.get("/api/v1/indicators/pyne/security").status_code == 404
        response = client.post("/api/v1/indicators/compute", json={
            "mode": "script", "language": "pyne", "script": "plot(close)",
            "symbol": "BTCUSDT", "interval": "1m", "market_type": "spot",
            "ohlcv": [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        })
        assert not response.json().get("ok", False)


def test_saved_scripts_use_explicit_language_and_reject_retired_code(tmp_path):
    store = CustomIndicatorStore(tmp_path / "scripts.json")
    saved = store.upsert({"name": "Pine", "kind": "script", "language": "pine", "script": "plot(close)"})
    assert store.get(saved["id"])["language"] == "pine"
    with pytest.raises(ValueError, match="Unsupported"):
        store.upsert({"name": "Old", "kind": "script", "language": "pyne", "script": "plot(close)"})


def test_retired_installed_runtime_cannot_autostart(monkeypatch):
    from app.plugin_runtime.registry import RuntimeRegistry, RuntimeProcessSpec
    registry = RuntimeRegistry(plugins=tuple(
        RuntimeProcessSpec(runtime_id=name, expected_package="test-plugin", expected_version="1.0.0",
                           executable=Path(sys.executable), auto_start=True)
        for name in ("candlescope.pyne", "candlescope.pine-compat", "community.runtime")
    ))
    monkeypatch.setattr("app.plugin_runtime.bootstrap.load_runtime_registry", lambda *args, **kwargs: registry)
    host = build_runtime_host_from_environment(host_name="test", host_version="1", environ={})
    assert [spec.runtime_id for spec in host.registry.plugins] == ["candlescope.pine-compat", "community.runtime"]


# ── Upgrade from builds before PR #105 (2026-10-26) ─────────────────────────
# Those builds defaulted to Pyne and left ``language`` out of a saved Pyne
# record. The 0.3.0 build of 2026-10-25 is one of them, so its profiles hold
# such records. They must list as retired, never run, never become Pine, and
# stay in the file exactly as stored.

import json

from app.api.v1 import indicators as indicators_api
from app.api.v1 import stream_script_subscriptions as stream_scripts

_LEGACY_ID = "custom-0123456789ab"
_LEGACY_RECORD = {
    "schemaVersion": 1,
    "id": _LEGACY_ID,
    "kind": "script",
    "name": "Mein Pyne Skript",
    "description": "saved by 0.3.0",
    "script": "ema = ta.ema(close, 20)\nplot(ema)\n",
    "params": {"length": 20},
    "paramSchema": [{"key": "length", "type": "int", "default": 20}],
    "renderHints": {},
    "securityMode": "safe",
    "created_at": 1761000000,
    "updated_at": 1761000000,
}


class _RuntimeTripwire:
    """Any use of the script runtime fails the test."""

    def __bool__(self):
        return True

    def __getattr__(self, name):
        raise AssertionError(f"a retired Pyne script reached the runtime ({name})")


def _legacy_store_bytes() -> bytes:
    # The exact serialisation pre-#105 ``CustomIndicatorStore._save`` used.
    payload = {"schemaVersion": 1, "items": [_LEGACY_RECORD]}
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@pytest.fixture
def legacy_store(tmp_path, monkeypatch):
    path = tmp_path / "custom_indicators.json"
    path.write_bytes(_legacy_store_bytes())
    monkeypatch.setattr(indicators_api, "_custom_store", CustomIndicatorStore(path))
    monkeypatch.setattr(stream_scripts, "_stream_custom_store", CustomIndicatorStore(path))
    monkeypatch.setattr(indicators_api, "_resolve_indicator_runtime_service", lambda _request: _RuntimeTripwire())
    return path


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.data_manager = object()
    return TestClient(app)


def _range_body(**fields):
    return {
        "clientId": "legacy-client", "kind": "custom", "customId": _LEGACY_ID,
        "exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "1m",
        "start": 1_700_000_000, "end": 1_700_003_600, **fields,
    }


def test_language_less_saved_record_lists_as_retired_pyne(legacy_store):
    original = legacy_store.read_bytes()
    with _client() as client:
        items = client.get("/api/v1/indicators/custom").json()
    assert [(item["id"], item["language"], item["retired"]) for item in items] == [(_LEGACY_ID, "pyne", True)]
    assert items[0]["script"] == _LEGACY_RECORD["script"]
    assert legacy_store.read_bytes() == original


@pytest.mark.parametrize("fields", [
    {},                                                # language taken from the record
    {"language": "pine"},                              # a request cannot relabel it
    {"script": _LEGACY_RECORD["script"], "language": "pine"},  # nor run its source inline
])
def test_language_less_saved_record_range_is_rejected_before_any_runtime(legacy_store, fields):
    original = legacy_store.read_bytes()
    with _client() as client:
        single = client.post("/api/v1/indicators/range", json=_range_body(**fields)).json()
        batch = client.post("/api/v1/indicators/range/batch", json={"requests": [_range_body(**fields)]}).json()
    for payload in (single, batch):
        assert payload["ok"] is False
        assert payload["code"] == "PYNE_RETIRED"
        assert "retired" in payload["error"]
    assert legacy_store.read_bytes() == original


def test_explicit_pyne_compute_is_rejected_before_any_runtime(legacy_store):
    body = {
        "mode": "script", "language": "pyne", "script": _LEGACY_RECORD["script"],
        "symbol": "BTCUSDT", "interval": "1m", "market_type": "spot",
        "ohlcv": [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    }
    with _client() as client:
        single = client.post("/api/v1/indicators/compute", json=body).json()
        batch = client.post("/api/v1/indicators/compute/batch", json={
            "schemaVersion": 1,
            "context": {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "1m"},
            "ohlcv": body["ohlcv"],
            "requests": [{"jobKey": "j", "clientId": "c", "mode": "script", "language": "pyne", "script": body["script"]}],
        }).json()
    assert single["code"] == "PYNE_RETIRED"
    assert batch["results"][0]["payload"]["code"] == "PYNE_RETIRED"


@pytest.mark.anyio
@pytest.mark.parametrize("language,script", [(None, ""), ("pine", ""), ("pine", _LEGACY_RECORD["script"])])
async def test_language_less_saved_record_stream_is_rejected_before_any_runtime(legacy_store, language, script):
    original = legacy_store.read_bytes()
    sent: list[dict] = []

    async def send_json(message):
        sent.append(message)

    async def never(*_args, **_kwargs):
        raise AssertionError("a retired Pyne subscription must not reach the stream")

    await stream_scripts.handle_script_indicator_subscribe(
        dm=_RuntimeTripwire(), custom_handles={}, custom_tasks={}, queue=None, client_meta={},
        client_id="legacy-client", symbol="BTCUSDT", interval="1m", exchange="binance", market_type="spot",
        name="", language=language, custom_id=_LEGACY_ID, script=script, params={}, security_mode=None,
        history_limit=500, send_json=send_json, stream_consumer_id="consumer", unsubscribe_client=never,
        queue_message=never, runtime_service=_RuntimeTripwire(),
    )
    assert [(message["type"], message["code"]) for message in sent] == [("error", "PYNE_RETIRED")]
    assert legacy_store.read_bytes() == original


def test_unrelated_save_keeps_the_legacy_record_as_stored(legacy_store):
    with _client() as client:
        saved = client.post("/api/v1/indicators/custom", json={
            "name": "New Pine", "language": "pine", "script": "indicator('x')\nplot(close)",
        }).json()
        assert saved["language"] == "pine"
        listed = {item["id"]: item for item in client.get("/api/v1/indicators/custom").json()}
    assert (listed[saved["id"]]["retired"], listed[_LEGACY_ID]["retired"]) == (False, True)

    stored = json.loads(legacy_store.read_text(encoding="utf-8"))["items"]
    legacy = next(item for item in stored if item["id"] == _LEGACY_ID)
    assert legacy == _LEGACY_RECORD and "language" not in legacy and "retired" not in legacy
    # Byte-for-byte: the record's serialised block is unchanged inside the new file. The store
    # is written in text mode, so Windows ends lines with CRLF (as 0.3.0 did); compare the block
    # with line endings normalised.
    block = json.dumps(_LEGACY_RECORD, ensure_ascii=False, indent=2).replace("\n", "\n    ")
    assert ("    " + block).encode("utf-8") in legacy_store.read_bytes().replace(b"\r\n", b"\n")


def test_a_legacy_record_cannot_be_overwritten_or_relabelled(legacy_store):
    original = legacy_store.read_bytes()
    with _client() as client:
        for language in (None, "pine", "python"):
            response = client.post("/api/v1/indicators/custom", json={
                "id": _LEGACY_ID, "name": "Relabelled", "language": language, "script": "plot(close)",
            })
            assert response.status_code == 400
            assert "retired Pyne" in response.json()["detail"]
    assert legacy_store.read_bytes() == original
