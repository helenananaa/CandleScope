from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.data_engine.data_manager.core import DataManagerCore
from app.exchanges import symbol_catalog
from tests.test_data_preparation import async_test


@pytest.mark.parametrize("offline", [False, True])
@async_test
async def test_preparation_storage_failure_does_not_skip_remaining_shutdown(monkeypatch, caplog, offline):
    stopped = []

    async def preparation_stop():
        stopped.append("preparation")
        raise sqlite3.OperationalError("unable to open database file")

    async def lag_stop():
        stopped.append("lag")

    async def data_stop(*, step_timeout):
        assert step_timeout == 5
        stopped.append("data")

    async def replay_stop(*, step_timeout):
        assert step_timeout == 5
        stopped.append("replay")

    async def catalog_stop():
        stopped.append("catalog")

    core = DataManagerCore()
    monkeypatch.setattr(core, "close_strategy", lambda: stopped.append("strategy"))
    state = SimpleNamespace(
        data_manager_core=core,
        data_preparation_service=SimpleNamespace(shutdown=preparation_stop),
        backtest_runtime=SimpleNamespace(shutdown=lambda: stopped.append("backtest")),
        event_loop_lag_monitor=SimpleNamespace(stop=lag_stop),
        data_engine_runtime=SimpleNamespace(shutdown=data_stop),
        replay_runtime=SimpleNamespace(shutdown=replay_stop),
    )
    if offline:
        state.local_offline_runtime = SimpleNamespace(shutdown=lambda: stopped.append("offline"))
    monkeypatch.setattr(main_module, "app", SimpleNamespace(state=state))
    monkeypatch.setattr(symbol_catalog, "cancel_exchange_metadata_refreshes", catalog_stop)
    monkeypatch.setattr(symbol_catalog, "configure_exchange_metadata_foreground_probe", lambda probe: None)

    await main_module.shutdown_event()

    assert stopped == (["preparation", "strategy", "backtest", "offline", "lag"] if offline else
                       ["preparation", "strategy", "backtest", "catalog", "lag", "data", "replay"])
    assert "unable to open database file" in caplog.text


@async_test
async def test_numeric_consumers_stop_before_history_and_cache_even_if_alert_stop_fails(monkeypatch):
    from app.indicator import history_worker
    stopped = []
    async def alerts():
        stopped.append('alerts')
        raise RuntimeError('injected alert stop failure')
    async def numeric():
        stopped.append('numeric')
    async def history():
        stopped.append('history')
    async def data(*, step_timeout):
        stopped.append('data')
    async def catalog():
        pass
    state = SimpleNamespace(alert_runtime=SimpleNamespace(stop=alerts),
        numeric_indicator_service=SimpleNamespace(close=numeric),
        indicator_range_service=SimpleNamespace(unbind_all=lambda: stopped.append('unbind'),
                                                clear=lambda: stopped.append('clear')),
        data_engine_runtime=SimpleNamespace(shutdown=data))
    monkeypatch.setattr(main_module, 'app', SimpleNamespace(state=state))
    monkeypatch.setattr(history_worker, 'shutdown_builtin_history', history)
    monkeypatch.setattr(symbol_catalog, 'cancel_exchange_metadata_refreshes', catalog)
    monkeypatch.setattr(symbol_catalog, 'configure_exchange_metadata_foreground_probe', lambda probe: None)
    await main_module.shutdown_event()
    assert stopped == ['alerts', 'numeric', 'history', 'unbind', 'clear', 'data']
