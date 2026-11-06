import asyncio
import threading
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.exchanges import symbol_catalog
from app.indicator import history_worker
from app.trading_accounts.models import TradingAccountError
from tests.test_trading_state_stream import make_fixture


@pytest.mark.parametrize('read_fails', [False, True])
def test_application_shutdown_drains_physical_account_read_before_closing_ledger(tmp_path, monkeypatch, read_fails):
    async def run():
        store, service, account, core, manager = make_fixture(tmp_path)
        entered, release, finished, ledger_closed = (threading.Event() for _ in range(4))
        original_read, original_close = service.account_state, store.close

        def held_read(account_id):
            try:
                # Keep the actual thread-owned WAL snapshot alive during shutdown.
                with store.read_snapshot():
                    result = original_read(account_id)
                    entered.set()
                    assert release.wait(5), 'The test must release the storage worker'
                    if read_fails:
                        raise RuntimeError('physical account read failed during shutdown')
                    return result
            finally:
                finished.set()

        def close_ledger():
            ledger_closed.set()
            original_close()

        async def noop(*args, **kwargs):
            pass

        service.account_state = held_read
        store.close = close_ledger
        monkeypatch.setattr(main_module, 'app', SimpleNamespace(state=SimpleNamespace(
            data_manager_core=core, trading_accounts=service)))
        monkeypatch.setattr(main_module, 'stop_extensions', noop)
        monkeypatch.setattr(symbol_catalog, 'cancel_exchange_metadata_refreshes', noop)
        monkeypatch.setattr(symbol_catalog, 'configure_exchange_metadata_foreground_probe', lambda _: None)
        monkeypatch.setattr(history_worker, 'shutdown_builtin_history', noop)
        reader = asyncio.create_task(manager.subscribe_state(account))
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            shutdown = asyncio.create_task(main_module.shutdown_event())
            await asyncio.sleep(.03)
            assert not ledger_closed.is_set(), 'Ledger closed while its physical reader still owns a WAL snapshot'
            assert not shutdown.done(), 'Application shutdown returned before the physical account reader'
            assert manager.diagnostics()['closed']
            release.set()
            await asyncio.wait_for(shutdown, 2)
            await asyncio.gather(reader, return_exceptions=True)
            assert finished.is_set() and ledger_closed.is_set()
            assert manager.diagnostics()['read_jobs'] == 0
            assert manager.diagnostics()['subscriptions'] == 0
            assert not manager._read_batches
        finally:
            release.set()
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)
            await asyncio.gather(reader, return_exceptions=True)
            if not ledger_closed.is_set():
                core.close_trading()
                original_close()
    asyncio.run(run())


def test_cancelled_shutdown_still_owns_physical_read_until_it_finishes(tmp_path):
    async def run():
        store, service, account, core, manager = make_fixture(tmp_path)
        entered, release, finished = (threading.Event() for _ in range(3))
        original = service.account_state

        def held_read(account_id):
            try:
                entered.set()
                assert release.wait(5)
                return original(account_id)
            finally:
                finished.set()

        service.account_state = held_read
        reader = asyncio.create_task(manager.subscribe_state(account))
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            shutdown = asyncio.create_task(core.shutdown_trading())
            await asyncio.sleep(0)
            shutdown.cancel()
            await asyncio.sleep(.02)
            shutdown.cancel()
            await asyncio.sleep(.02)
            assert not shutdown.done(), 'Cancellation must not detach a running ledger read'
            assert not finished.is_set() and manager.diagnostics()['read_jobs'] == 1
            with pytest.raises(TradingAccountError) as rejected:
                await manager.subscribe_state(account)
            assert getattr(rejected.value, 'code', None) == 'TRADING_UNAVAILABLE'
            assert store.state_cursor()['sequence'] > 0
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(shutdown, 2)
            await asyncio.gather(reader, return_exceptions=True)
            assert finished.is_set() and manager.diagnostics()['read_jobs'] == 0
            assert manager.diagnostics()['subscriptions'] == 0
            await core.shutdown_trading()
        finally:
            release.set()
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)
            await asyncio.gather(reader, return_exceptions=True)
            await core.shutdown_trading()
            store.close()
    asyncio.run(run())
