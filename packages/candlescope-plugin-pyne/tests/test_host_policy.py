from __future__ import annotations

import os

import pyne_runtime
import pytest
from candlescope_plugin_sdk import AnalyzeRequest, MarketContext

from candlescope_plugin_pyne import PyneRuntimePlugin
from candlescope_plugin_pyne.host_policy import host_settings
from candlescope_plugin_pyne.runtime import _settings_for


@pytest.fixture(autouse=True)
def clean_policy_environment(monkeypatch):
    for name in os.environ:
        if name.startswith("PYNE_"):
            monkeypatch.delenv(name)


def test_host_restrictions_do_not_inherit_standalone_unlimited_defaults():
    standalone = pyne_runtime.PyneSettings()
    assert standalone.security_mode == "unsafe"
    assert standalone.max_bars is None
    settings = host_settings()
    assert settings.security_mode == "safe"
    assert settings.executor_mode == "inline"
    assert settings.timeout_seconds == 5
    assert settings.max_bars == 50_000
    assert settings.incremental_retention_bars == 10_000
    assert settings.replay_history_bars == 50_000
    context = MarketContext(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m")
    result = PyneRuntimePlugin().analyze(
        AnalyzeRequest(source="import os\nplot(close)", context=context)
    )
    assert not result.executable


def test_explicit_operator_limits_and_script_mode_are_preserved(monkeypatch):
    monkeypatch.setenv("PYNE_SECURITY_MODE", "research")
    monkeypatch.setenv("PYNE_MAX_BARS", "7")
    monkeypatch.setenv("PYNE_EXEC_TIMEOUT_SECONDS", "none")
    monkeypatch.setenv("PYNE_REPLAY_HISTORY_BARS", "unlimited")
    settings = host_settings()
    assert settings.security_mode == "research"
    assert settings.max_bars == 7
    assert settings.timeout_seconds is None
    assert settings.replay_history_bars is None
    context = MarketContext(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m")
    selected = _settings_for(context, {"securityMode": "unsafe"})
    assert selected.security_mode == "unsafe"
    assert selected.max_bars == 7


def test_invalid_operator_limit_and_undeliverable_hard_timeout_fail(monkeypatch):
    monkeypatch.setenv("PYNE_MAX_BARS", "0")
    with pytest.raises(ValueError):
        host_settings()
    monkeypatch.delenv("PYNE_MAX_BARS")
    monkeypatch.setenv("PYNE_EXECUTOR_MODE", "process")
    monkeypatch.setenv("PYNE_REQUIRE_HARD_TIMEOUT", "true")
    with pytest.raises(ValueError, match="hard timeout"):
        host_settings()


def test_direct_strategy_execution_uses_explicit_safe_policy(monkeypatch):
    from candlescope_plugin_pyne import SMA_CROSS_SOURCE, PyneStrategyProvider

    monkeypatch.setenv("PYNE_SECURITY_MODE", "unsafe")
    observed = []

    def execute(**kwargs):
        observed.append(kwargs["settings"])
        return type("Result", (), {"output": {}})()

    monkeypatch.setattr(pyne_runtime, "execute_pyne_script", execute)
    provider = PyneStrategyProvider()
    provider.prepare({"source": SMA_CROSS_SOURCE})
    assert provider.identity()["expectedEngineVersion"] == "0.4.0"
    provider._run_engine()
    assert observed[0].security_mode == "safe"
    assert observed[0].max_bars == 50_000
