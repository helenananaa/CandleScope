from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from app import main as main_module
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

    state = SimpleNamespace(
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

    assert stopped == (["preparation", "backtest", "offline", "lag"] if offline else
                       ["preparation", "backtest", "catalog", "lag", "data", "replay"])
    assert "unable to open database file" in caplog.text
