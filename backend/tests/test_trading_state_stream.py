import asyncio
from decimal import Decimal
import threading

import pytest

from app.data_engine.data_manager.core import DataManagerCore
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.test_trading_accounts import bar, T0, FUTURES, INSTRUMENT


def make_fixture(tmp_path):
    store = TradingStore(tmp_path/'accounts.db')
    service = TradingAccountService(store, snapshot_dir=tmp_path/'images', clock=lambda:T0)
    aid = service.create_account({'kind':'practice','name':'fixture','settings':{'initialBalance':'1000','slippageBps':'0'}})['id']
    core=DataManagerCore();manager=core.bind_trading(service)
    manager.heartbeat_seconds=.03;manager.min_snapshot_interval_seconds=0
    return store,service,aid,core,manager


def test_revision_rollback_restart_and_financial_snapshot_race(tmp_path, monkeypatch):
    store,service,aid,core,manager=make_fixture(tmp_path)
    initial=store.state_cursor()
    try:
        with pytest.raises(ValueError):
            with store.transaction() as db:
                db.execute("UPDATE cash_flows SET amount='2000' WHERE account_id=?",(aid,))
                raise ValueError('rollback')
        assert store.state_cursor()==initial
        before=threading.Event();committed=threading.Event()
        original=store.fills
        def fills(account):
            value=original(account);before.set();assert committed.wait(2);return value
        monkeypatch.setattr(store,'fills',fills)
        def write():
            assert before.wait(2)
            with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='2000' WHERE account_id=?",(aid,))
            committed.set()
        thread=threading.Thread(target=write);thread.start()
        state=service.account_state(aid);thread.join(2)
        assert not thread.is_alive() and state['cursor']==initial and state['summary']['balance']=='1000'
        monkeypatch.setattr(store,'fills',original)
        current=service.account_state(aid)
        assert current['cursor']['sequence']>initial['sequence'] and current['summary']['balance']=='2000'
        restarted=TradingStore(tmp_path/'accounts.db')
        try:assert restarted.state_cursor()==current['cursor']
        finally:restarted.close()
    finally:core.close_trading();store.close()


def test_snapshot_commit_race_heartbeat_no_poll_and_view_release_keeps_matching(tmp_path):
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        original=service.account_state;calls=0
        def racing(account):
            nonlocal calls
            state=original(account);calls+=1
            if calls==1:
                with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='1001' WHERE account_id=?",(aid,))
            return state
        service.account_state=racing
        sub=await manager.subscribe_state(aid);events=sub.events()
        try:
            first=await anext(events);second=await asyncio.wait_for(anext(events),1)
            assert first['state']['summary']['balance']=='1000' and second['state']['summary']['balance']=='1001'
            assert second['sequence']==first['sequence']+1 and second['connectionEpoch']==first['connectionEpoch']
            count=calls;assert (await anext(events))['type']=='heartbeat';assert calls==count
            core.close_trading()
            with pytest.raises(StopAsyncIteration):await anext(events)
            assert store.updates.diagnostics()['subscriptions']==0
            with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='1002' WHERE account_id=?",(aid,))
            assert service.account_summary(aid)['balance']=='1002'
        finally:await events.aclose();store.close()
    asyncio.run(run())


def test_unflushed_valuation_is_pushed_without_claiming_a_new_durable_cursor(tmp_path):
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        minute=T0//1000
        try:
            service.place_order(aid,{**INSTRUMENT,'side':'buy','type':'market','qty':'1','referencePrice':'100'})
            service.apply_market_bars(FUTURES,[bar(minute,'100','102','99','101')],observed_ms=T0)
            sub=await manager.subscribe_state(aid);events=sub.events();first=await anext(events)
            cursor=first['state']['cursor']
            flushed_price=store.cursor(*FUTURES)['last_close']
            service.apply_market_bars(FUTURES,[bar(minute,'100','102','99','101.5')],observed_ms=T0+100)
            second=await asyncio.wait_for(anext(events),1)
            assert second['state']['cursor']==cursor
            assert second['sequence']>first['sequence']
            summary=second['state']['summary'];trade=second['state']['trades'][0]
            assert summary['positions'][0]['markPrice']=='101.5'
            assert summary['positions'][0]['unrealizedPnl']==trade['unrealizedPnl']
            assert store.cursor(*FUTURES)['last_close']==flushed_price!=Decimal('101.5')
            await events.aclose()
        finally:core.close_trading();store.close()
    asyncio.run(run())


def test_capacity_missing_account_and_cancelled_prepare_release(tmp_path):
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        manager.max_subscriptions=1
        try:
            with pytest.raises(Exception,match='Account was not found'):
                await manager.subscribe_state('acc_00000000000000000000')
            assert not manager._subscriptions
            sub=await manager.subscribe_state(aid)
            with pytest.raises(Exception,match='Too many'):
                await manager.subscribe_state(aid)
            sub.close();assert not manager._subscriptions
            started=threading.Event();release=threading.Event();original=service.account_state
            def blocked(account):started.set();assert release.wait(2);return original(account)
            service.account_state=blocked
            task=asyncio.create_task(manager.subscribe_state(aid))
            while not started.is_set():await asyncio.sleep(.005)
            task.cancel();release.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert not manager._subscriptions and store.updates.diagnostics()['subscriptions']==0
            await asyncio.sleep(.05)
        finally:core.close_trading();store.close()
    asyncio.run(run())


def test_http_routes_use_manager_and_release_before_headers_or_first_frame(tmp_path):
    import httpx
    import json
    from fastapi import FastAPI
    from starlette.requests import Request, ClientDisconnect
    from app.api.v1.trading_accounts import router, account_events
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        app=FastAPI();app.state.trading_accounts=service;app.state.data_manager_core=core
        app.include_router(router,prefix='/api/v1')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                assert (await client.get(f'/api/v1/trading/accounts/{aid}/summary')).status_code==200
                assert (await client.get('/api/v1/trading/accounts/unknown/events')).status_code==404
            assert manager.diagnostics()['control_requests']==2 and not manager._subscriptions
            request=Request({'type':'http','method':'GET','path':'/','app':app,'headers':[]})
            response=await account_events(request,aid)
            assert response.headers['content-encoding']=='identity'
            assert response.headers['cache-control']=='no-store'
            event=json.loads(await anext(response.body_iterator))
            assert event['identity']['accountId']==aid
            await response.body_iterator.aclose();assert not manager._subscriptions
            failed=await account_events(request,aid)
            async def send(_):raise OSError('headers failed')
            async def receive():await asyncio.Event().wait()
            try:
                await failed({'asgi':{'spec_version':'2.4'}},receive,send)
            except (OSError, ClientDisconnect):
                pass
            except BaseExceptionGroup as error:
                assert all(isinstance(item, OSError) for item in error.exceptions)
            else:
                pytest.fail('failed headers must propagate')
            assert not manager._subscriptions
            core.close_trading()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                assert (await client.get(f'/api/v1/trading/accounts/{aid}/summary')).status_code==503
        finally:core.close_trading();store.close()
    asyncio.run(run())


def test_multi_account_and_symbol_views_preserve_existing_decimal_financials(tmp_path):
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        other=service.create_account({'kind':'practice','name':'other'})['id']
        try:
            for symbol,price in [('BTCUSDT','100'),('ETHUSDT','200')]:
                service.place_order(aid,{**INSTRUMENT,'symbol':symbol,'side':'buy','type':'market','qty':'0.1234567890123456789','referencePrice':price})
            a=await manager.subscribe_state(aid);b=await manager.subscribe_state(other)
            ae,be=a.events(),b.events()
            av,bv=await anext(ae),await anext(be)
            assert len(av['state']['summary']['positions'])==2 and not bv['state']['summary']['positions']
            assert av['state']['summary']==service.account_summary(aid)
            assert av['state']['trades']==service.list_trades(aid)['trades']
            assert all(row['accountId']==aid for row in av['state']['trades'])
            assert all(row['openQty']=='0.1234567890123456789' for row in av['state']['trades'])
            a.close();assert manager.diagnostics()['subscriptions']==1
            with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='1200' WHERE account_id=?",(other,))
            changed=await asyncio.wait_for(anext(be),1)
            assert changed['identity']['accountId']==other and changed['state']['summary']['balance']=='1200'
            await ae.aclose();await be.aclose()
        finally:core.close_trading();store.close()
    asyncio.run(run())


def test_rollback_has_no_push_and_bursts_coalesce_without_heartbeat_database_reads(tmp_path):
    async def run():
        store,service,aid,core,manager=make_fixture(tmp_path)
        manager.min_snapshot_interval_seconds=.01
        original=service.account_state;calls=[]
        def count(account):calls.append(account);return original(account)
        service.account_state=count
        sub=await manager.subscribe_state(aid);events=sub.events()
        try:
            first=await anext(events)
            with pytest.raises(ValueError):
                with store.transaction() as db:
                    db.execute("UPDATE cash_flows SET amount='999' WHERE account_id=?",(aid,));raise ValueError()
            assert (await anext(events))['type']=='heartbeat' and len(calls)==1
            with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='1200' WHERE account_id=?",(aid,))
            for _ in range(1000):store.updates.notify('state')
            current=await anext(events)
            assert current['state']['summary']['balance']=='1200' and len(calls)==2
            assert current['state']['cursor']['sequence']==first['state']['cursor']['sequence']+1
            assert (await anext(events))['type']=='heartbeat' and len(calls)==2
        finally:await events.aclose();core.close_trading();store.close()
    asyncio.run(run())


def test_snapshot_reads_fills_once_and_journal_failure_keeps_financial_views(tmp_path, monkeypatch):
    store,service,aid,core,manager=make_fixture(tmp_path)
    original=store.fills;calls=[]
    def fills(account):calls.append(account);return original(account)
    monkeypatch.setattr(store,'fills',fills)
    try:
        value=service.account_state(aid)
        assert calls==[aid] and value['journalError'] is None
        def journal(_):raise ValueError('corrupt optional note')
        monkeypatch.setattr(service,'list_entries',journal)
        value=service.account_state(aid)
        assert value['summary']['balance']=='1000' and value['trades']==[]
        assert value['entries'] is None and value['journalError']
        assert calls==[aid,aid]
        assert not hasattr(service._projection_state,'trades')
    finally:core.close_trading();store.close()
