"""Production strategy owner gate and application shutdown ordering."""
import asyncio
from types import SimpleNamespace

import pytest

from app.backtest.continuous_runtime import ContinuousStrategyRuntime
from app.backtest.errors import BacktestError
from app.data_engine.data_manager.core import DataManagerCore
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_bar_source import source_setup,create_frozen,END
from tests.test_continuous_strategy_runtime import leases,wait_row


def test_core_rejects_offline_or_foreign_market_owner(storage,tmp_path,monkeypatch):
    service,_,_,factory,store,manager,source,_=source_setup(storage,tmp_path,monkeypatch)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    try:
        offline=DataManagerCore().bind_strategy(service)
        with pytest.raises(BacktestError,match="live DataManager"):offline.bind_continuous(runtime)
        gate=manager.bind_strategy(service)
        assert gate.bind_continuous(runtime) is runtime
        assert gate.bind_continuous(runtime) is runtime
        other=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
        with pytest.raises(RuntimeError,match="already bound"):gate.bind_continuous(other)
        other.manager=object()
        with pytest.raises(BacktestError,match="live DataManager"):gate.bind_continuous(other)
        gate.close()
        with pytest.raises(BacktestError,match="closed"):gate.bind_continuous(runtime)
    finally:asyncio.run(runtime.shutdown());source.close();store.close();service.shutdown()


@pytest.mark.parametrize("release_fails",[False,True])
def test_application_drains_actual_owner_and_closes_store_before_dependencies(storage,tmp_path,monkeypatch,release_fails):
    from app import main as module
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    if release_fails:
        release=manager.release_stream;attempts=[]
        async def once(*args,**kwargs):
            attempts.append(1)
            if len(attempts)==1:raise RuntimeError("release-failed")
            return await release(*args,**kwargs)
        monkeypatch.setattr(manager,"release_stream",once)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    gate=manager.bind_strategy(service);gate.bind_continuous(runtime)
    stopped=[]
    def dependency(name):
        assert store.closed and not active and not runtime.actors
        stopped.append(name)
    state=SimpleNamespace(data_manager_core=manager,
        backtest_runtime=SimpleNamespace(shutdown=lambda:dependency("backtest")),
        local_offline_runtime=SimpleNamespace(shutdown=lambda:dependency("data")))
    monkeypatch.setattr(module,"app",SimpleNamespace(state=state))
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            if release_fails:
                with pytest.raises(BacktestError,match="CONTINUOUS_SHUTDOWN_FAILED"):
                    await module.shutdown_event()
                assert not store.closed and active and not stopped
            await module.shutdown_event()
            assert gate.diagnostics()["closed"] and stopped==["backtest","data"]
            assert runtime.closed and store.closed
        finally:await runtime.close();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_close_reclaims_setup_cancelled_before_its_first_step(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,calls=leases(monkeypatch,manager)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    async def scenario():
        request=asyncio.create_task(runtime.start_existing("cs_source"))
        await asyncio.sleep(0)
        assert runtime.starts and not runtime.actors
        await runtime.close()
        with pytest.raises(asyncio.CancelledError):await request
        assert not runtime.starts and not runtime.actors and not active and not calls
        assert store.closed
        await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_startup_failure_drains_bound_owner_before_stopping_extensions(storage,tmp_path,monkeypatch):
    from app import main as module
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    manager.bind_strategy(service).bind_continuous(runtime)
    monkeypatch.setattr(module,"app",SimpleNamespace(state=SimpleNamespace(data_manager_core=manager)))
    stopped=[]
    async def later_failure():raise ValueError("later startup failure")
    async def extensions(_app):
        assert store.closed and not active and not runtime.actors
        stopped.append("extensions")
    monkeypatch.setattr(module,"_startup_event_impl",later_failure)
    monkeypatch.setattr(module,"stop_extensions",extensions)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            with pytest.raises(ValueError,match="later startup failure"):
                await module.startup_event()
            assert stopped==["extensions"]
        finally:await runtime.close();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()
