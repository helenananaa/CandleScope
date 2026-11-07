"""Actual HTTP/WS/runtime, with a deterministic authoritative BAR source.

Only the source and source-event delivery are controlled. No script execution,
SDK reply, output, protocol transport or projection reducer is mocked.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import inspect
import json
import os
from pathlib import Path
import queue
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.api.v1 import indicators
from app.api.v1.stream_indicators import stream_indicators
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
from app.data_engine.data_manager.models import BarData
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager import query as query_module
from app.data_engine.storage import klines_repo
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import SOURCE as QUALITY
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes
from app.indicator.runtime_service import IndicatorRuntimeService
from app.indicator.pine_host import PineHostInputs
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from tests.test_runtime_owned_output import owner, bars as runtime_bars, SOURCE


def bars(count, *, forming=False):
    return tuple(replace(bar,time=(bar.time//60)*60) for bar in runtime_bars(count,forming=forming))

TRACE = ContextVar('chart_calculation_wire_trace', default=None)


class Source(DataManager):
    def __init__(self, storage):
        super().__init__()
        self.set_storage(storage)
        self.callbacks, self.leases = {}, set()
        self.queries = 0
        self.query_windows = []
        self.rows = list(bars(500))

    @property
    def rows(self): return self._rows

    @rows.setter
    def rows(self, rows):
        self._rows = list(rows)
        self.now_ms = rows[-1].time*1000 + (60_000 if rows[-1].is_closed else 30_000)
        klines_repo.upsert_klines('BTCUSDT','1m',[dict(open_time=bar.time*1000,
            close_time=(bar.time+60)*1000-1,quote_volume=0,trades=0,taker_buy_base=0,taker_buy_quote=0,
            **{name:getattr(bar,name) for name in
                ('open','high','low','close','volume')}) for bar in rows if bar.is_closed],source=QUALITY)
        self.cache.revision_consumer.sync(force=True)
        for bar in rows:
            if not bar.is_closed:
                self.cache.upsert(SeriesKey('BTCUSDT','1m'),BarData(**{name:getattr(bar,name)
                    for name in ('time','open','high','low','close','volume','is_closed')},source='ws_native'))

    def replace_bar(self, index, bar):
        rows = list(self.rows);rows[index] = bar;self.rows = rows

    def query(self, _symbol, _interval, **kwargs):
        self.queries += 1
        self.query_windows.append((kwargs['start_ms'],kwargs['end_ms']))
        return super().query(_symbol,_interval,**kwargs)

    def query_latest(self, _symbol, _interval, **kwargs):
        return super().query_latest(_symbol,_interval,**kwargs)

    async def ensure_stream(self, *_args, **kwargs): self.leases.add(kwargs['consumer_id'])
    async def release_stream(self, *_args, **kwargs): self.leases.discard(kwargs['consumer_id'])
    def subscribe(self, **kwargs):
        key = object();self.callbacks[key] = kwargs;return key
    def unsubscribe(self, handle): self.callbacks.pop(handle,None)

    async def emit(self, event):
        ticket = self.event_bus.stream_versions.begin(event)
        try:
            for entry in list(self.callbacks.values()):
                if event.event_type not in entry['event_types']: continue
                if entry.get('symbol') and entry['symbol'] != event.key.symbol: continue
                if entry.get('interval') and entry['interval'] != event.key.interval: continue
                result = entry['callback'](event)
                if inspect.isawaitable(result): await result
        finally: self.event_bus.stream_versions.finish(ticket)


@pytest.fixture
def wire(tmp_path,request,storage,monkeypatch):
    source = Source(storage)
    monkeypatch.setattr(query_module,'time',SimpleNamespace(time=lambda:source.now_ms/1000,monotonic=time.monotonic))
    ranges = IndicatorRangeResultService(server_epoch='chart-wire')
    spec = owner(tmp_path/'wire.sqlite').spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)),host_name='CandleScope',host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine','sidecar',spec.runtime_id),)),host=host)
    pine_inputs = PineHostInputs(lambda: source)
    service.prepare_inputs = pine_inputs.prepare
    service.release_inputs = pine_inputs.release
    service.stop_inputs = pine_inputs.stop
    service.pine_data_manager = lambda: source
    engine = SimpleNamespace(indicator_range_service=ranges,add_listener=lambda callback:None,
                             remove_listener=lambda callback:None)
    trace, extra_processes = [], []
    trace_token = TRACE.set(trace)
    process_receipts = []
    @asynccontextmanager
    async def lifespan(_app):
        yield
        processes = extra_processes + [supervisor._process for supervisor in host._supervisors.values()
            if supervisor._process is not None]
        await service.stop()
        await host.stop()
        await source.shutdown()
        for process in {process.pid:process for process in processes}.values():
            try: os.kill(process.pid,0); absent=False
            except ProcessLookupError: absent=True
            process_receipts.append({'pid':process.pid,'returncode':process.returncode,'absent':absent})
        assert all(item['returncode'] == 0 and item['absent'] for item in process_receipts)
    app = FastAPI(lifespan=lifespan)
    app.state.data_manager = source
    app.state.indicator_runtime_service = service
    app.state.indicator_range_service = ranges
    app.include_router(indicators.router)
    @app.websocket('/ws')
    async def websocket(socket: WebSocket):
        await socket.accept()
        await stream_indicators(socket,source,engine,runtime_service=service)
    @app.post('/fixture/tick/{count}')
    async def tick(count:int, close:float=100):
        rows = list(bars(count,forming=True))
        rows[-1] = replace(rows[-1],close=close,high=max(rows[-1].high,close))
        source.rows = rows
        await source.emit(DataEvent(DataEventType.BAR_UPDATED,SeriesKey('BTCUSDT','1m'),bar=rows[-1]))
        return {'ok':True}
    @app.post('/fixture/amend')
    async def amend():
        old = source.rows[10]
        source.replace_bar(10,replace(old,close=101))
        await source.emit(DataEvent(DataEventType.BAR_AMENDED,SeriesKey('BTCUSDT','1m'),
            bar=source.rows[10],previous_bar=old))
        return {'ok':True}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client,source=source,host=host,service=service,ranges=ranges,
                              tmp_path=tmp_path,extra_processes=extra_processes,engine=engine)
    assert not source.callbacks and not source.leases
    with klines_repo._connect() as conn:
        remaining_watches = conn.execute("SELECT count(*) FROM kline_prefix_watches WHERE owner LIKE 'indicator:%'").fetchone()[0]
    assert remaining_watches == 0
    directory = os.environ.get('CALCULATION_TRACE_DIR')
    if directory:
        path = Path(directory);path.mkdir(parents=True,exist_ok=True)
        (path/(request.node.name+'.json')).write_text(json.dumps({'case':request.node.name,
            'scope':'Actual TestClient HTTP/WS ASGI + repository runtime/SDK + pinned core; controlled BAR source; no renderer/Native/package claim',
            'counterObservations':trace,'queryWindows':source.query_windows,'processes':process_receipts,
            'callbacksAfterStop':len(source.callbacks),'leasesAfterStop':len(source.leases),
            'registryAfterStop':service.calculations.snapshot(),'sourceWatchesAfterStop':remaining_watches},indent=2)+'\n')
    TRACE.reset(trace_token)


def open_request(**changes):
    return {'schemaVersion':1,'clientId':'chart-a','kind':'script','language':'pine',
        'exchange':'binance','marketType':'spot','symbol':'BTCUSDT','interval':'1m',
        'script':SOURCE,'start':bars(1)[0].time,'end':bars(500)[-1].time,**changes}


def ref(payload):
    position = payload['calculation']
    return {key:position[key] for key in ('schemaVersion','domainId','generation','sequence')}


def value(payload):
    line = next(line for line in payload['lines'] if line.get('title',line.get('name')) == 'counter')
    value = line['data'][-1]['value']
    trace = TRACE.get()
    if trace is not None:
        trace.append({'type':payload.get('type'),'counter':value,
                      'calculation':payload.get('calculation'),'range':payload.get('range')})
    return value


def output_times(collection):
    if isinstance(collection,list): return {time for item in collection for time in output_times(item)}
    if isinstance(collection,dict):
        return ({collection['time']} if 'time' in collection else set()) | {
            time for value in collection.values() for time in output_times(value)}
    return set()


def receive(ws, *types):
    deadline = time.monotonic()+8
    while True:
        try: frame = ws._send_queue.get(timeout=max(0.01,deadline-time.monotonic()))
        except queue.Empty: pytest.fail('Timed out waiting for actual WS frame: ' + repr(types))
        if isinstance(frame,BaseException): raise frame
        assert frame['type'] == 'websocket.send',frame
        payload = json.loads(frame['text'])
        if payload['type'] in types: return payload
        assert payload['type'] in ('heartbeat','connected'),payload


def subscribe(ws, reference, **changes):
    request = open_request(**changes)
    for key in ('schemaVersion','start','end'):request.pop(key)
    ws.send_json({**request,'action':'subscribe','calculation':reference})


def view(wire, reference, start=None, end=None, **changes):
    body = {'calculation':reference,'clientId':'chart-a','start':start or bars(1)[0].time,
            'end':end or bars(500)[-1].time,**changes}
    return wire.client.post('/indicators/calculations/'+reference['domainId']+'/range',json=body).json()


def test_http_reads_and_ws_share_one_real_calculation_and_correction_generation(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    assert initial.get('ok') is True,initial
    assert initial['type'] == 'indicator.snapshot' and value(initial) == 500
    assert initial['dataRevision']['closedThrough'] == bars(500)[-1].time
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    queries = wire.source.queries
    assert value(view(wire,ref(initial),start=bars(500)[-1].time)) == 500
    assert wire.source.queries == queries and wire.host.diagnostics()['runtimes'][0]['requests'] == before
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial))
        ack = receive(ws,'indicator.subscribed')
        assert ack['ok'],ack
        seeded = receive(ws,'indicator.snapshot')
        assert value(seeded) == 500 and ref(seeded) == ref(initial)
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
        wire.client.post('/fixture/tick/501')
        live = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert live['calculation']['domainId'] == ref(initial)['domainId'] and value(live) == 501
        stale = view(wire,ref(initial))
        assert stale['ok'] is False and stale['code'] == 'INDICATOR_CALCULATION_CHANGED'
        assert ref(stale) == ref(live)
        before = wire.host.diagnostics()['runtimes'][0]['requests']
        current = view(wire,ref(live),start=bars(500)[-1].time)
        assert current['calculation']['sequence'] == live['calculation']['sequence']
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
        wire.client.post('/fixture/tick/501?close=103')
        second = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert value(second) == 502
        shifted = bars(501)[-3].time
        assert second['range']['start'] <= shifted <= second['range']['end']
        assert shifted in output_times(second.get('markers',[]))
        assert shifted in output_times(second.get('bgcolors',[]))
        wire.client.post('/fixture/tick/501?close=104')
        deleted = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert value(deleted) == 503 and deleted['type'] == 'indicator.replace_range'
        assert deleted['range']['start'] <= shifted <= deleted['range']['end']
        old_points = [line for line in deleted['lines'] if line.get('name',line.get('title')) == 'old point']
        assert shifted not in output_times(old_points)
        assert shifted not in output_times(deleted.get('markers',[]))
        assert shifted not in output_times(deleted.get('bgcolors',[]))
        wire.client.post('/fixture/amend')
        repaired = receive(ws,'indicator.snapshot')
        assert value(repaired) == 501 and repaired['calculation']['generation'] == 2
        assert repaired['calculation']['origin'] == initial['calculation']['origin']
        assert repaired['range']['start'] == initial['calculation']['origin']
        assert repaired['dataRevision']['closedThrough'] == bars(500)[-1].time
        assert repaired['meta']['sessionReset'] is True
        assert repaired['meta']['sessionResetReason'] == 'sourceRebuild'
        assert repaired['meta']['sessionRecovered'] is False
        assert repaired['calculation']['sequence'] > deleted['calculation']['sequence']
        ws.send_json({'action':'unsubscribe','clientId':'chart-a'})
        receive(ws,'indicator.unsubscribed')

    runtime_calls = wire.host.diagnostics()['runtimes'][0]['requests']
    cached = view(wire, ref(repaired))
    assert cached['meta']['sessionReset'] is True
    assert cached['meta']['sessionResetReason'] == 'sourceRebuild'
    assert cached['meta']['sessionRecovered'] is False
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws, ref(repaired))
        assert receive(ws, 'indicator.subscribed')['ok']
        reattached = receive(ws, 'indicator.snapshot')
        assert value(reattached) == 501 and ref(reattached) == ref(repaired)
        assert reattached['meta']['sessionReset'] is True
        assert reattached['meta']['sessionResetReason'] == 'sourceRebuild'
        assert reattached['meta']['sessionRecovered'] is False
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == runtime_calls
        async def next_observation():
            # Advance the forming BAR without undoing the confirmed correction.
            latest = replace(wire.source.rows[-1], close=105, high=105)
            wire.source.rows = [*wire.source.rows[:-1], latest]
            await wire.source.emit(DataEvent(DataEventType.BAR_UPDATED, SeriesKey('BTCUSDT', '1m'), bar=latest))

        wire.client.portal.call(next_observation)
        continued = receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert value(continued) == 502
        assert continued['calculation']['generation'] == repaired['calculation']['generation']
        assert continued['meta']['sessionReset'] is False
        ws.send_json({'action':'unsubscribe','clientId':'chart-a'})
        receive(ws,'indicator.unsubscribed')
    assert not wire.source.callbacks and not wire.source.leases
    closed = wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()
    assert closed['state'] == 'closed' and wire.service.calculations.snapshot()['entries'] == 0


def test_http_closed_catchup_keeps_origin_and_domains_do_not_share_math(wire):
    first = wire.client.post('/indicators/calculations',json=open_request()).json()
    other = wire.client.post('/indicators/calculations',json=open_request(clientId='chart-b',end=bars(50)[-1].time)).json()
    assert value(first) == 500 and value(other) == 50
    wire.source.rows = list(bars(501))
    caught = view(wire,ref(first),start=bars(501)[-1].time,end=bars(501)[-1].time)
    assert value(caught) == 501 and caught['type'] == 'indicator.snapshot'
    assert caught['calculation']['origin'] == first['calculation']['origin']
    assert wire.source.query_windows[-1][0] == bars(500)[-1].time*1000
    assert value(view(wire,ref(other),end=bars(50)[-1].time)) == 50
    expanded = view(wire,ref(caught),start=bars(1)[0].time-60)
    assert expanded['code'] == 'INDICATOR_CALCULATION_ORIGIN_REQUIRED'


def test_complete_projection_read_is_atomic_and_does_not_clip_or_execute(wire):
    initial=wire.client.post('/indicators/calculations',json=open_request()).json()
    before=wire.host.diagnostics()['runtimes'][0]['requests'];queries=wire.source.queries
    sliced=view(wire,ref(initial),start=bars(500)[-1].time)
    assert sliced['type']=='indicator.replace_range'
    complete=view(wire,ref(initial),start=bars(500)[-1].time,complete=True)
    assert complete['type']=='indicator.snapshot' and ref(complete)==ref(initial)
    line=lambda payload:next(line['data'] for line in payload['lines'] if line.get('title',line.get('name'))=='counter')
    assert len(line(sliced))==1 and len(line(complete))==500
    assert complete['range']==initial['range']
    assert wire.source.queries==queries and wire.host.diagnostics()['runtimes'][0]['requests']==before
    bad=wire.client.post('/indicators/calculations/'+ref(initial)['domainId']+'/range',json={
        'clientId':'chart-a','calculation':ref(initial),'start':bars(1)[0].time,'end':bars(500)[-1].time,'complete':'true'})
    assert bad.status_code==422


def test_active_writer_is_unique_and_http_delete_disposes_its_idle_ws_hold(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    with wire.client.websocket_connect('/ws') as ws, wire.client.websocket_connect('/ws') as duplicate:
        subscribe(ws,ref(initial));assert receive(ws,'indicator.subscribed')['ok']
        receive(ws,'indicator.snapshot')
        subscribe(duplicate,ref(initial))
        rejected = receive(duplicate,'indicator.subscribed')
        assert rejected['ok'] is False and rejected['code'] == 'INDICATOR_CALCULATION_WRITER_BUSY'
        assert wire.service.calculations.snapshot()['holders'] == 1
        closed = wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()
        assert closed['state'] == 'closed'
        assert receive(ws,'error')['code'] == 'INDICATOR_CALCULATION_CLOSED'
        assert not wire.source.callbacks and not wire.source.leases


def test_changed_definition_cannot_attach_and_bad_wire_values_never_execute(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial),script=SOURCE+'\n// other definition')
        rejected = receive(ws,'indicator.subscribed')
        assert rejected['ok'] is False and rejected['code'] == 'INDICATOR_CALCULATION_INPUT_INVALID'
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
    for position in [{**ref(initial),'sequence':True},{**ref(initial),'schemaVersion':2},
                     {**ref(initial),'sequence':0},{**ref(initial),'extra':1}]:
        assert wire.client.post('/indicators/calculations/'+ref(initial)['domainId']+'/range',
            json={'calculation':position,'clientId':'chart-a','start':1,'end':2}).status_code == 422
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before


def test_lost_worker_read_never_launches_and_only_explicit_full_origin_rebuild_recovers(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    wire.extra_processes.extend(supervisor._process for supervisor in wire.host._supervisors.values()
                               if supervisor._process is not None)
    wire.client.portal.call(wire.host.stop)
    starts = wire.host.diagnostics()['runtimes'][0]['starts']
    lost = view(wire,ref(initial),start=bars(500)[-1].time)
    assert lost['code'] == 'INDICATOR_CALCULATION_OUTPUT_LOST'
    assert wire.host.diagnostics()['runtimes'][0]['starts'] == starts
    recovered = view(wire,ref(initial),start=bars(500)[-1].time,rebuild=True)
    assert recovered['ok'] is True and value(recovered) == 500
    assert recovered['type'] == 'indicator.snapshot' and recovered['calculation']['generation'] == 2
    assert wire.source.query_windows[-1][0] == initial['calculation']['origin']*1000


def test_ws_reconnect_reuses_retained_observations_instead_of_reseeding_or_advancing(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial));assert receive(ws,'indicator.subscribed')['ok']
        receive(ws,'indicator.snapshot')
        wire.client.post('/fixture/tick/501')
        live = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert value(live) == 501
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial))
        ack = receive(ws,'indicator.subscribed');assert ack['ok']
        restored = receive(ws,'indicator.snapshot')
        assert value(restored) == 501 and ref(restored) == ref(live)
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
        wire.client.post('/fixture/tick/501?close=103')
        next_tick = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert value(next_tick) == 502 and next_tick['calculation']['generation'] == 1


def test_subscribe_catches_closed_prefix_admitted_between_http_and_ws(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    wire.source.rows = list(bars(501))
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial));assert receive(ws,'indicator.subscribed')['ok']
        caught = receive(ws,'indicator.snapshot')
        assert value(caught) == 501 and caught['calculation']['generation'] == 1
        assert wire.source.query_windows[-1][0] == bars(500)[-1].time*1000


def test_missing_new_source_bar_cannot_advance_cursor_or_execute_an_old_prefix_as_success(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    before = wire.host.diagnostics()['runtimes'][0]['requests']
    pending = view(wire,ref(initial),start=bars(501)[-1].time,end=bars(501)[-1].time)
    assert pending['code'] == 'INDICATOR_RANGE_NOT_READY' and ref(pending) == ref(initial)
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
    assert value(view(wire,ref(initial))) == 500


def test_source_changes_during_real_execution_cannot_publish_or_notify_and_open_cleans_its_orphan(wire):
    observations = []
    async def arm():
        entered, allowed = asyncio.Event(), asyncio.Event()
        async def prepare(request, _host, _runtime_id):
            entered.set()
            await allowed.wait()
            return request, None
        async def observe(*args): observations.append(args)
        wire.service.prepare_inputs, wire.service.observe_result = prepare, observe
        return entered, allowed
    entered, allowed = wire.client.portal.call(arm)
    async def wait_entered(): await asyncio.wait_for(entered.wait(),8)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(wire.client.post,'/indicators/calculations',json=open_request())
        try:
            wire.client.portal.call(wait_entered)
            wire.source.replace_bar(10,replace(wire.source.rows[10],close=101))
            wire.ranges.note_correction(series_key='binance:spot:BTCUSDT:1m',
                start=wire.source.rows[10].time,end=wire.source.rows[10].time,event_id='during-real-runtime')
        finally:
            wire.client.portal.call(allowed.set)
        failed = pending.result(timeout=10).json()
    assert failed['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED' and not observations
    assert wire.service.calculations.snapshot()['entries'] == 0
    retry = wire.client.post('/indicators/calculations',json=open_request()).json()
    assert retry['ok'] is True and value(retry) == 500


def test_invalid_script_keeps_actual_compiler_diagnostic_and_releases_failed_domain(wire):
    response = wire.client.post('/indicators/calculations',json=open_request(
        script='//@version=6\nindicator("bad")\nplot(nonexistent_identifier)')).json()
    assert response['ok'] is False
    assert response['code'] != 'INDICATOR_CALCULATION_EXECUTION_FAILED'
    assert 'nonexistent_identifier' in response['error']
    assert response['errorDetail']['line'] == 3
    assert wire.service.calculations.snapshot()['entries'] == 0


def test_source_delivery_gap_forces_new_origin_generation_even_without_primary_revision_change(wire):
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial));assert receive(ws,'indicator.subscribed')['ok']
        receive(ws,'indicator.snapshot')
        wire.client.post('/fixture/tick/501')
        receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        wire.client.post('/fixture/tick/501?close=103')
        before_gap = receive(ws,'indicator.replace_range','indicator.patch','indicator.snapshot')
        assert value(before_gap) == 502
        async def gap():
            callback = next(entry['on_recovery'] for entry in wire.source.callbacks.values() if entry.get('symbol'))
            await callback(RuntimeError('source delivery gap'))
        wire.client.portal.call(gap)
        assert receive(ws,'error')['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED'
        assert not wire.source.callbacks and not wire.source.leases
        subscribe(ws,ref(before_gap));assert receive(ws,'indicator.subscribed')['ok']
        rebuilt = receive(ws,'indicator.snapshot')
        assert value(rebuilt) == 501 and rebuilt['calculation']['generation'] == 2
        assert rebuilt['dataRevision']['revisionToken'] == before_gap['dataRevision']['revisionToken']
        assert rebuilt['calculation']['inputRevision'].endswith(':delivery:1')
        assert wire.source.query_windows[-1][0] == rebuilt['calculation']['origin']*1000


@pytest.mark.parametrize('close_during_wait',[False,True])
def test_http_cannot_bypass_ws_parent_repair_barrier_and_close_cancels_only_source_wait(wire,close_during_wait):
    async def arm():
        class Coordinator:
            def __init__(self): self.entered,self.allowed = asyncio.Event(),asyncio.Event()
            async def wait_for_request(self, request_id):
                assert request_id == 'parent-owned-chart'
                self.entered.set()
                await self.allowed.wait()
                return SimpleNamespace(verified_contiguous=True,retryable=False,bars_loaded=1)
        coordinator = Coordinator()
        wire.engine.backfill_coordinator = coordinator
        return coordinator
    coordinator = wire.client.portal.call(arm)
    initial = wire.client.post('/indicators/calculations',json=open_request()).json()
    with wire.client.websocket_connect('/ws') as ws:
        subscribe(ws,ref(initial));assert receive(ws,'indicator.subscribed')['ok']
        receive(ws,'indicator.snapshot')
        dirty = wire.source.rows[10].time
        event = DataEvent(DataEventType.BACKFILL_COMPLETED,SeriesKey('BTCUSDT','1m'),detail={
            'request_id':'parent-owned-chart','bars_count':1,'request_start_ms':dirty*1000,
            'request_end_ms':dirty*1000,'range_start_ms':dirty*1000,'range_end_ms':dirty*1000})
        async def start_repair():
            wire.source.replace_bar(10,replace(wire.source.rows[10],close=101))
            await wire.source.emit(event)
            await asyncio.wait_for(coordinator.entered.wait(),8)
        wire.client.portal.call(start_repair)
        before = wire.host.diagnostics()['runtimes'][0]['requests']
        blocked = view(wire,ref(initial))
        assert blocked['code'] == 'INDICATOR_RANGE_NOT_READY'
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
        if close_during_wait:
            assert wire.client.delete('/indicators/calculations/'+ref(initial)['domainId']).json()['state'] == 'closed'
            assert not coordinator.allowed.is_set()
            assert receive(ws,'error')['code'] == 'INDICATOR_CALCULATION_CLOSED'
            assert not wire.source.callbacks and not wire.source.leases
        else:
            wire.client.portal.call(coordinator.allowed.set)
            repaired = receive(ws,'indicator.snapshot')
            assert value(repaired) == 500 and repaired['calculation']['generation'] == 2
            assert wire.source.query_windows[-1][0] == initial['calculation']['origin']*1000
            before = wire.host.diagnostics()['runtimes'][0]['requests']
            wire.client.portal.call(wire.source.emit,event)
            repeated = receive(ws,'indicator.snapshot')
            assert ref(repeated) == ref(repaired)
            assert wire.host.diagnostics()['runtimes'][0]['requests'] == before


def test_http_tail_rebuilds_from_origin_after_runtime_state_is_released(wire):
    initial = wire.client.post('/indicators/calculations', json=open_request()).json()
    reference = ref(initial)
    assert value(initial) == 500
    route = wire.service.route_for('pine')
    wire.client.portal.call(wire.host.release_stream, route.runtime_id, reference['domainId'])
    wire.source.rows = list(bars(501))
    rebuilt = view(wire, reference, end=bars(501)[-1].time)
    assert value(rebuilt) == 501
    assert rebuilt['type'] == 'indicator.snapshot'
    assert rebuilt['calculation']['origin'] == initial['calculation']['origin']
    assert rebuilt['calculation']['generation'] == initial['calculation']['generation'] + 1
    assert rebuilt['calculation']['sequence'] == initial['calculation']['sequence'] + 1
    assert rebuilt['meta']['sessionResetReason'] == 'runtimeRebuild'
    assert rebuilt['meta']['sessionRecovered'] is False
    assert wire.client.delete('/indicators/calculations/' + reference['domainId']).json()['state'] == 'closed'


@pytest.mark.parametrize('amend_between_pages', [False, True])
def test_long_chart_origin_uses_bounded_coherent_source_pages(wire, monkeypatch, amend_between_pages):
    history = 12_001
    wire.source.rows = bars(history)
    original_query = wire.source.query
    limits = []

    def query(symbol, interval, **kwargs):
        if amend_between_pages and len(limits) == 1:
            first_page = wire.source.query_windows[-1]
            bar = wire.source.rows[10]
            assert first_page[0] <= bar.time * 1000 <= first_page[1]
            wire.source.replace_bar(10, replace(bar, close=106, high=107))
        limits.append(kwargs['limit'])
        return original_query(symbol, interval, **kwargs)

    monkeypatch.setattr(wire.source, 'query', query)
    script = ('//@version=6\nindicator("Long chart input")\n'
              'varip int ticks = 0\nticks += 1\nplot(ticks, "counter")\nplot(close, "source")')
    request = open_request(end=wire.source.rows[-1].time, script=script)
    response = wire.client.post('/indicators/calculations', json=request).json()
    assert len(limits) == 2
    assert max(limits) <= wire.source.query_row_limit == 10_000
    if amend_between_pages:
        assert response['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED', response
        assert wire.service.calculations.snapshot()['entries'] == 0
        assert all(runtime['requests'] == 0 for runtime in wire.host.diagnostics()['runtimes'])
        response = wire.client.post('/indicators/calculations', json=request).json()
    assert response['ok'] is True
    assert value(response) == history
    assert response['calculation']['origin'] == request['start']
    prices = next(line['data'] for line in response['lines'] if line.get('name') == 'source')
    assert len(prices) == history
    assert prices[10]['value'] == wire.source.rows[10].close

    # An explicit rebuild must read the same origin, including the prefix that
    # no single bounded DataManager query can return.
    query_count = len(limits)
    rebuilt = view(wire, ref(response), start=prices[-1]['time'], end=prices[-1]['time'], rebuild=True)
    assert rebuilt['type'] == 'indicator.snapshot'
    assert rebuilt['calculation']['generation'] == response['calculation']['generation'] + 1
    assert rebuilt['calculation']['origin'] == request['start']
    assert value(rebuilt) == history and len(limits) == query_count + 2
    assert wire.client.delete('/indicators/calculations/' + ref(response)['domainId']).json()['state'] == 'closed'


def test_long_chart_origin_does_not_seed_across_an_interior_gap(wire):
    wire.source.rows = bars(12_001)
    missing = wire.source.rows[7_000].time * 1000
    assert klines_repo.delete_klines('BTCUSDT', '1m', missing, missing) == 1
    request = open_request(end=wire.source.rows[-1].time)
    response = wire.client.post('/indicators/calculations', json=request).json()
    assert response['code'] == 'INDICATOR_RANGE_NOT_READY', response
    assert wire.service.calculations.snapshot()['entries'] == 0
    assert all(runtime['requests'] == 0 for runtime in wire.host.diagnostics()['runtimes'])
