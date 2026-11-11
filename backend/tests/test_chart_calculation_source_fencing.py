"""Real DataManager/SQLite source proofs through HTTP, WS and actual Pine."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import threading

import pytest

from app.api.v1 import chart_calculation
from app.data_engine.storage import klines_repo
from tests.test_kline_revision_contract import storage as storage
from tests.test_chart_calculation_transports import (
    wire as wire, bars, open_request, ref, value, view, subscribe, receive, TRACE,
)
from app.data_engine.data_manager.models import SeriesKey


SUM_SOURCE = open_request()['script'] + '\nplot(ta.cum(close), title="source-sum")\n'


def source_sum(payload):
    assert payload.get('ok') is True, payload
    result = next(line for line in payload['lines'] if line.get('title',line.get('name')) == 'source-sum')['data'][-1]['value']
    trace = TRACE.get()
    if trace is not None:
        trace.append({'type':payload.get('type'),'sourceSum':result,'calculation':payload.get('calculation'),
            'range':payload.get('range'),'dataRevision':payload.get('dataRevision')})
    return result


def silent_write(wire):
    """Physical writer does not notify the in-process transport or cache."""
    subprocess.run([sys.executable,'-B','-c',
        'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); '
        'c.execute("UPDATE klines SET close=close+1 WHERE interval=? AND open_time=?", ("1m",int(sys.argv[2]))); '
        'c.commit(); c.close()',str(klines_repo.KLINES_DB_PATH),str(wire.source.rows[10].time*1000)],check=True)


@pytest.mark.parametrize('transport',['http','ws'])
def test_unannounced_physical_repair_rebuilds_cached_prefix_at_fixed_origin(wire,transport):
    initial = wire.client.post('/indicators/calculations',json=open_request(script=SUM_SOURCE)).json()
    old_sum = source_sum(initial)
    # Prevent a coincidental periodic poll from concealing a missing min_revision.
    wire.source.cache.revision_consumer.poll_seconds = 3600
    silent_write(wire)
    if transport == 'http':
        repaired = view(wire,ref(initial))
    else:
        with wire.client.websocket_connect('/ws') as ws:
            subscribe(ws,ref(initial),script=SUM_SOURCE)
            assert receive(ws,'indicator.subscribed')['ok']
            repaired = receive(ws,'indicator.snapshot')
    assert source_sum(repaired) == old_sum+1
    assert value(repaired) == 500
    assert repaired['calculation']['generation'] == 2
    assert repaired['calculation']['origin'] == initial['calculation']['origin']
    assert repaired['dataRevision']['revisionToken'] == initial['dataRevision']['revisionToken']
    assert wire.source.query_windows[-1][0] == initial['calculation']['origin']*1000


def test_physical_repair_during_execution_cannot_publish_and_releases_source_watch(wire):
    observations = []
    async def arm():
        entered,allowed = asyncio.Event(),asyncio.Event()
        async def prepare(request,_host,_runtime_id):
            entered.set();await allowed.wait();return request,None
        async def observe(*args):observations.append(args)
        wire.service.prepare_inputs,wire.service.observe_result = prepare,observe
        return entered,allowed
    entered,allowed = wire.client.portal.call(arm)
    async def wait():await asyncio.wait_for(entered.wait(),8)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(wire.client.post,'/indicators/calculations',json=open_request())
        try:
            wire.client.portal.call(wait)
            silent_write(wire)
        finally:wire.client.portal.call(allowed.set)
        failed = pending.result(timeout=10).json()
    assert failed['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED' and not observations
    assert wire.service.calculations.snapshot()['entries'] == 0
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT count(*) FROM kline_prefix_watches WHERE owner LIKE 'indicator:%'").fetchone()[0] == 0


def test_physical_repair_during_read_serialization_rejects_stale_projection(wire,monkeypatch):
    initial = wire.client.post('/indicators/calculations',json=open_request(script=SUM_SOURCE)).json()
    old_sum = source_sum(initial)
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    entered,allowed = threading.Event(),threading.Event()
    serialize = chart_calculation._snapshot_payload
    def blocked(*args):
        payload = serialize(*args)
        entered.set()
        assert allowed.wait(8)
        return payload
    monkeypatch.setattr(chart_calculation,'_snapshot_payload',blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(view,wire,ref(initial))
        try:
            assert entered.wait(8)
            silent_write(wire)
        finally:allowed.set()
        failed = pending.result(timeout=10)
    assert failed['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED'
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
    repaired = view(wire,ref(initial))
    assert source_sum(repaired) == old_sum+1
    assert repaired['calculation']['generation'] == 2


def test_other_series_rollback_noop_and_unprotected_tail_do_not_reexecute(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    with klines_repo._connect() as conn:
        conn.execute('UPDATE klines SET close=close+1');conn.rollback()
        conn.execute('UPDATE klines SET close=close');conn.commit()
    # A valid closed append outside the protected prefix is harmless to reads.
    wire.source.rows = list(bars(501))
    restored = view(wire,ref(initial))
    assert value(restored) == 500 and ref(restored) == ref(initial)
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before


def test_unmaterialized_custom_interval_is_fenced_by_its_base_family(wire):
    step = 7*60
    start = ((wire.source.rows[0].time+step-1)//step)*step
    end = ((wire.source.rows[-1].time+60)//step-1)*step
    initial = wire.client.post('/indicators/calculations',json=open_request(
        script=SUM_SOURCE,interval='7m',start=start,end=end)).json()
    old_sum = source_sum(initial)
    # Change the final child of a complete target candle, without a target
    # event. Both cache and lazily materialized target must be invalidated.
    child = start+step-60
    subprocess.run([sys.executable,'-B','-c',
        'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); '
        'c.execute("UPDATE klines SET close=close+1 WHERE interval=? AND open_time=?", ("1m",int(sys.argv[2]))); '
        'c.commit(); c.close()',str(klines_repo.KLINES_DB_PATH),str(child*1000)],check=True)
    repaired = view(wire,ref(initial),start=start,end=end)
    assert source_sum(repaired) == old_sum+1
    assert repaired['calculation']['generation'] == 2
    assert repaired['calculation']['origin'] == initial['calculation']['origin']
    assert repaired['dataRevision']['revisionToken'] == initial['dataRevision']['revisionToken']


def test_failed_source_release_retains_capacity_and_retry_preserves_foreign_watch(wire,monkeypatch):
    api = wire.source.bars.prefixes
    foreign = api.register('strategy:foreign',SeriesKey('BTCUSDT','1m'),
        from_ms=bars(1)[0].time*1000,committed_through_ms=bars(1)[0].time*1000-1)
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    assert initial['ok']
    wire.service.calculations.max_entries = 1
    release = api.release
    def failed(receipt):raise OSError('injected source release failure')
    monkeypatch.setattr(api,'release',failed)
    try:
        failed = wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()
        assert failed['code'] == 'INDICATOR_CALCULATION_CLOSE_FAILED'
        assert 'source release failure' in failed['error']
        assert wire.service.calculations.snapshot()['retiring'] == 1
        blocked = wire.client.post('/indicators/calculations',json=open_request(clientId='chart-b')).json()
        assert blocked['code'] == 'INDICATOR_CALCULATION_CAPACITY'
    finally:monkeypatch.setattr(api,'release',release)
    assert wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()['state'] == 'closed'
    assert wire.service.calculations.snapshot()['entries'] == 0
    assert api.inspect(foreign.owner)['incarnation'] == foreign.incarnation
    api.release(foreign)


def test_lost_source_watch_fails_closed_and_domain_can_still_be_deleted(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    assert initial['ok']
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM kline_prefix_watches WHERE owner LIKE 'indicator:%'")
        conn.commit()
    failed = view(wire,ref(initial))
    assert failed['code'] == 'INDICATOR_CALCULATION_SOURCE_UNAVAILABLE'
    assert wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()['state'] == 'closed'
