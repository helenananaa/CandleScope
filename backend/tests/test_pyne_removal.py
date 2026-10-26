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


def test_only_pine_is_a_default_first_party_script_route():
    routes = IndicatorRuntimeRoutes.first_party_sidecar_default()
    assert [route.language for route in routes.routes] == ["pine"]
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
