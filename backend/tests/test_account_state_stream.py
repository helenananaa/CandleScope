import asyncio
from pathlib import Path

import pytest

from app.data_engine.data_manager.core import DataManagerCore
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.service import ReadOnlyAccountService
from app.readonly_accounts.normalization import AccountDataError


def test_committed_cursor_rollback_raw_observations_and_restart(tmp_path):
    repo = AccountRepository(tmp_path)
    initial = repo.overview()['cursor']
    with pytest.raises(ValueError):
        with repo.transaction() as db:
            db.execute("INSERT INTO gap VALUES('fills',1,2,'test')")
            raise ValueError()
    assert repo.overview()['cursor'] == initial
    repo.observe('orders', [{'ordId': 'raw'}], received_ms=10)
    assert repo.overview()['cursor'] == initial
    repo.bind('uid', 'SECRET_REFERENCE', 0)
    current = repo.overview()
    assert current['cursor']['sequence'] > initial['sequence']
    assert 'SECRET_REFERENCE' not in str(current)
    assert AccountRepository(tmp_path).overview() == current


def test_snapshot_stream_commit_read_race_cross_repository_and_release(tmp_path):
    async def run():
        owner = ReadOnlyAccountService(tmp_path)
        core = DataManagerCore()
        manager = core.bind_readonly_account(owner)
        manager.heartbeat_seconds = .05
        repo = owner.repository
        original = owner.state
        calls = 0
        async def racing_state():
            nonlocal calls
            value = await original()
            calls += 1
            if calls == 1:
                await asyncio.to_thread(repo.bind, 'uid', 'secret', 0)
            return value
        owner.state = racing_state
        subscription = await manager.subscribe_state()
        events = subscription.events()
        try:
            first = await anext(events)
            assert first['state']['account'] is None
            second = await asyncio.wait_for(anext(events), 1)
            assert second['identity']['venueUid'] == 'uid'
            assert second['cursor']['sequence'] > first['cursor']['sequence']
            # An independent in-process writer shares the path namespace.
            writer = AccountRepository(tmp_path)
            await asyncio.to_thread(writer.status, 'disconnected', enabled=False)
            third = await asyncio.wait_for(anext(events), 1)
            assert third['state']['account']['status'] == 'disconnected'
            assert third['cursor']['epoch'] == second['cursor']['epoch']
            count = calls
            assert (await asyncio.wait_for(anext(events), 1))['type'] == 'heartbeat'
            assert calls == count  # transport heartbeat does not poll SQLite.
            core.close_readonly_account()
            with pytest.raises(StopAsyncIteration):
                await anext(events)
            assert not owner._closed  # releasing views never owns private sync.
            assert repo.updates.diagnostics()['subscriptions'] == 0
        finally:
            await events.aclose()
            await owner.close()
    asyncio.run(run())


def test_coalescing_rollback_notification_and_subscriber_capacity(tmp_path):
    async def run():
        owner = ReadOnlyAccountService(tmp_path)
        manager = DataManagerCore().bind_readonly_account(owner)
        manager.max_subscriptions = 1
        sub = await manager.subscribe_state()
        events = sub.events()
        try:
            await anext(events)
            with pytest.raises(AccountDataError, match='ACCOUNT_SUBSCRIPTION_CAPACITY'):
                await manager.subscribe_state()
            def writes():
                for i in range(20):
                    owner.repository.save_snapshot('balances', {'amount': str(i)}, i)
            await asyncio.to_thread(writes)
            latest = await asyncio.wait_for(anext(events), 1)
            assert latest['replacement'] is True
            assert latest['state']['snapshots']['balances']['data']['amount'] == '19'
            revision = latest['cursor']['sequence']
            with pytest.raises(ValueError):
                with owner.repository.transaction() as db:
                    db.execute("DELETE FROM snapshot")
                    raise ValueError()
            assert owner.repository.overview()['cursor']['sequence'] == revision
        finally:
            await events.aclose()
            manager.close()
            await owner.close()
        assert owner.repository.updates.diagnostics()['subscriptions'] == 0
    asyncio.run(run())


def test_account_namespaces_are_isolated(tmp_path):
    first, second = AccountRepository(tmp_path/'one'), AccountRepository(tmp_path/'two')
    assert first.updates is not second.updates
    assert first.overview()['cursor']['epoch'] != second.overview()['cursor']['epoch']


def test_health_wakeup_without_fabricating_a_ledger_revision(tmp_path):
    async def run():
        owner = ReadOnlyAccountService(tmp_path)
        manager = DataManagerCore().bind_readonly_account(owner)
        sub = await manager.subscribe_state()
        events = sub.events()
        try:
            first = await anext(events)
            owner.service_error = 'ACCOUNT_RESOURCE_CLEANUP_FAILED'
            owner.notify_state_changed()
            current = await asyncio.wait_for(anext(events), 1)
            assert current['cursor'] == first['cursor']
            assert current['state']['serviceError'] == 'ACCOUNT_RESOURCE_CLEANUP_FAILED'
        finally:
            await events.aclose()
            manager.close()
            await owner.close()
    asyncio.run(run())


def test_stream_route_authenticates_before_subscription_and_releases_on_disconnect(tmp_path):
    import json
    import httpx
    from fastapi import FastAPI
    from starlette.requests import Request
    from app.plugin_security_v2.management import LocalManagementGuard
    from app.readonly_accounts.api import router, stream_state

    async def run():
        app = FastAPI()
        owner = ReadOnlyAccountService(tmp_path)
        core = DataManagerCore()
        manager = core.bind_readonly_account(owner)
        app.state.data_manager_core = core
        app.state.readonly_account_service = owner
        guard = LocalManagementGuard(['http://127.0.0.1:61234'])
        app.state.plugin_platform_v2_management_guard = guard
        app.include_router(router, prefix='/api/v1')
        try:
            transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 61235))
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8000') as api:
                assert (await api.get('/api/v1/readonly-accounts/events')).status_code == 403
            assert manager.diagnostics()['subscriptions'] == 0
            assert manager.diagnostics()['control_requests'] == 0
            headers = guard.trusted_headers(user_action='account.read')
            request = Request({'type': 'http', 'method': 'GET', 'scheme': 'http', 'path': '/api/v1/readonly-accounts/events',
                'query_string': b'', 'app': app, 'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 61235),
                'headers': [(key.lower().encode(), value.encode()) for key,value in headers.items()] + [(b'host',b'127.0.0.1:8000')]})
            response = await stream_state(request)
            assert manager.diagnostics()['control_requests'] == 1
            assert manager.control_plane() is owner
            assert response.headers['content-encoding'] == 'identity'
            assert response.headers['cache-control'] == 'no-store'
            assert json.loads(await anext(response.body_iterator))['type'] == 'snapshot'
            await response.body_iterator.aclose()
            assert manager.diagnostics()['subscriptions'] == 0
            failed = await stream_state(request)
            async def send_failed(message):
                raise OSError('disconnected before first frame')
            async def receive():
                await asyncio.Event().wait()
            from starlette.requests import ClientDisconnect
            try:
                await failed({'asgi': {'spec_version': '2.4'}}, receive, send_failed)
            except ClientDisconnect:
                pass
            except BaseExceptionGroup as exc:
                # Starlette versions before 0.42 propagate send failures through
                # AnyIO's task group instead of raising ClientDisconnect.
                assert all(isinstance(error, OSError) for error in exc.exceptions)
            else:
                pytest.fail('a failed ASGI send must propagate')
            assert manager.diagnostics()['subscriptions'] == 0
        finally:
            manager.close()
            await owner.close()
    asyncio.run(run())



def test_live_manager_shutdown_closes_account_views_without_stopping_service(tmp_path):
    async def run():
        from app.data_engine.data_manager import DataManager
        owner = ReadOnlyAccountService(tmp_path)
        manager = DataManager()
        facade = manager.bind_readonly_account(owner)
        sub = await facade.subscribe_state()
        await manager.shutdown()
        assert sub._updates.closed
        assert facade.diagnostics()['subscriptions'] == 0
        assert not owner._closed
        await owner.close()
    asyncio.run(run())
