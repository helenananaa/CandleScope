"""Keep the existing chart wire contract on the actual routed event bus."""
import asyncio
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from app.api.v1 import chart_calculation_stream
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData
from app.data_engine.bar_aggregator import BarEvent, BarEventType, BarFinality, BarState
from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_transports import wire  # noqa: F401
from tests.test_kline_revision_contract import storage  # noqa: F401


class RealBusSource(transport.Source):
    # BAR production/stream leases remain deterministic fixture ports. Queries,
    # cache, SQLite, subscription routing, delivery and disposal are real.
    subscribe = DataManager.subscribe
    unsubscribe = DataManager.unsubscribe

    async def emit(self, event):
        def source_bar(bar):
            if bar is None or isinstance(bar, BarData):
                return bar
            return BarData(**{name: getattr(bar, name) for name in (
                "time", "open", "high", "low", "close", "volume", "is_closed",
            )}, source=transport.QUALITY if bar.is_closed else "ws_native")

        # The SDK's lightweight Bar has no source-quality contract. Real bus
        # middleware requires the same BarData shape used by the fixture store.
        event = replace(event, bar=source_bar(event.bar), previous_bar=source_bar(event.previous_bar))
        await self.event_bus.emit(event)

    async def shutdown(self):
        self.bus_before_shutdown = self.event_bus.snapshot()
        await super().shutdown()
        self.bus_after_shutdown = self.event_bus.snapshot()
        assert self.bus_after_shutdown["callback_subscriptions"] == 0
        assert self.bus_after_shutdown["queue_subscriptions"] == 0
        assert self.bus_after_shutdown["callback_errors"] == 0
        output = os.environ.get("CALCULATION_TRACE_DIR")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            Path(output, "real-event-bus-shutdown.json").write_text(json.dumps({
                "before": self.bus_before_shutdown,
                "after": self.bus_after_shutdown,
            }, indent=2) + "\n")


@pytest.fixture
def real_bus_wire(monkeypatch, request):
    monkeypatch.setattr(transport, "Source", RealBusSource)
    return request.getfixturevalue("wire")


def test_real_bus_delivers_forming_updates_deletions_and_corrections(real_bus_wire, caplog):
    transport.test_http_reads_and_ws_share_one_real_calculation_and_correction_generation(real_bus_wire)
    assert not [record for record in caplog.records if record.levelno >= 40]


@pytest.mark.parametrize('boundary_gap', [False, 'repair', 'close'])
def test_actual_aggregator_preview_provenance_keeps_six_live_observations(real_bus_wire, boundary_gap):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    assert transport.value(initial) == 500
    preview = transport.bars(501, forming=True)[-1]

    @wire.client.app.post('/fixture/aggregator-preview/{observation}')
    async def publish(observation: int, bucket: int = 0, closed: bool = False):
        # Admit only the real bridge lifecycle here; stream acquisition remains
        # the deterministic fixture port, so this does not open a public feed.
        source = wire.source
        source._started = True
        opening = preview.time + bucket * 60
        source.now_ms = max(source.now_ms, opening * 1000 + 30_000)
        state = BarState(symbol='BTCUSDT', interval='1m',
            bucket_start_ms=opening * 1000, bucket_end_ms=(opening + 60) * 1000,
            open=100, high=110, low=90, close=100 + observation, volume=10)
        assert state.quality_source == ''
        if closed:
            state.finality = BarFinality.AUTHORITATIVE
            state.close_reason = 'source_close'
        try:
            return {'status': await source.aggregator_bridge.on_bar_event(
                BarEvent(BarEventType.CLOSED if closed else BarEventType.UPDATED, state))}
        finally:
            source._started = False

    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        for observation in range(1, 7):
            assert wire.client.post('/fixture/aggregator-preview/' + str(observation)).json() == {'status': 'accepted'}
            live = transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
            assert transport.value(live) == 500 + observation
            assert live['calculation']['generation'] == initial['calculation']['generation']
            assert live['calculation']['origin'] == initial['calculation']['origin']
        if boundary_gap:
            # The next forming bucket cannot turn an unconfirmed predecessor
            # into a valid closed prefix. Recovery must wait for the real close.
            assert wire.client.post('/fixture/aggregator-preview/1?bucket=1').json()['status'] == 'accepted'
            error = transport.receive(ws, 'error')
            assert error['code'] == 'INDICATOR_CALCULATION_RECOVERY_REQUIRED'
            assert error['error'] == 'Chart calculation input is not contiguous'
            assert wire.service.calculations.snapshot()['holders'] == 1
            requests = wire.host.diagnostics()['runtimes'][0]['requests']
            blocked = transport.view(wire, transport.ref(live), end=preview.time + 60)
            assert blocked['ok'] is False
            assert wire.host.diagnostics()['runtimes'][0]['requests'] == requests
            if boundary_gap == 'close':
                assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'
                assert transport.receive(ws, 'error')['code'] == 'INDICATOR_CALCULATION_CLOSED'
                assert wire.service.calculations.snapshot()['holders'] == 0
                assert not wire.source.leases
                return
            assert wire.client.post('/fixture/aggregator-preview/6?closed=true').json()['status'] == 'accepted'
            # Recovery belongs to the same live writer, without an HTTP read or
            # a new subscribe command from the renderer.
            recovered = transport.receive(ws, 'indicator.snapshot')
            assert transport.value(recovered) == 501
            assert recovered['calculation']['generation'] == initial['calculation']['generation'] + 1
            # Durable revision adoption may evict the ephemeral next preview;
            # admit it again through the publisher, never by cache injection.
            assert wire.client.post('/fixture/aggregator-preview/2?bucket=1').json()['status'] == 'accepted'
            advanced = transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
            assert transport.value(advanced) == 502
            assert wire.client.post('/fixture/aggregator-preview/3?bucket=1').json()['status'] == 'accepted'
            resumed = transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
            assert transport.value(resumed) == 503
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'



def test_early_final_waits_for_boundary_without_resetting_pine(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    final = transport.bars(501)[-1]
    boundary = (final.time + 60) * 1000
    observed = threading.Event()
    executions = []

    def wall_clock():
        now = wire.source.now_ms
        observed.set()
        return now / 1000

    execute = wire.service.execute

    async def track_execution(request, **kwargs):
        if request.bars[-1].time == final.time and request.bars[-1].is_closed:
            executions.append(wire.source.now_ms)
            observed.set()
        return await execute(request, **kwargs)

    monkeypatch.setattr(chart_calculation_stream, 'time', wall_clock, raising=False)
    monkeypatch.setattr(wire.service, 'execute', track_execution)
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        for close in (101, 103):
            wire.client.post('/fixture/tick/501?close=' + str(close))
            preview = transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert transport.value(preview) == 502

        async def publish_final():
            wire.source.rows = list(transport.bars(501))
            wire.source.now_ms = boundary - 250
            await wire.source.emit(transport.DataEvent(transport.DataEventType.BAR_CLOSED, transport.SeriesKey('BTCUSDT', '1m'), bar=final))

        wire.client.portal.call(publish_final)
        assert observed.wait(5), 'The ordered writer did not inspect or execute the early final'
        assert executions == [], 'The early final executed before the local close boundary'
        wire.source.now_ms = boundary
        confirmed = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert confirmed['type'] != 'error', confirmed
        assert transport.value(confirmed) == 503
        assert confirmed['calculation']['generation'] == initial['calculation']['generation']
        assert confirmed['calculation']['closedThrough'] == final.time
        assert executions == [boundary]
        wire.client.post('/fixture/tick/502?close=101')
        advanced = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert advanced['type'] != 'error', advanced
        assert transport.value(advanced) == 504
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def delay_next_execution(wire, monkeypatch):
    async def arm():
        entered, allowed = asyncio.Event(), asyncio.Event()
        execute = wire.service.execute
        first = True

        async def delayed(request, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                await allowed.wait()
            return await execute(request, **kwargs)

        monkeypatch.setattr(wire.service, 'execute', delayed)
        return entered, allowed

    return wire.client.portal.call(arm)


def test_slow_live_execution_preserves_each_varip_observation(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    assert transport.value(initial) == 500

    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        entered, allowed = delay_next_execution(wire, monkeypatch)
        try:
            wire.client.post('/fixture/tick/501?close=101')

            async def wait_entered():
                await asyncio.wait_for(entered.wait(), 5)

            wire.client.portal.call(wait_entered)
            for observation in range(2, 7):
                assert wire.client.post('/fixture/tick/501?close=' + str(100 + observation)).json()['ok']
        finally:
            wire.client.portal.call(allowed.set)
        outputs = [transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
                   for _ in range(6)]
        values = [transport.value(output) for output in outputs]
        assert values == [501, 502, 503, 504, 505, 506]
        shifted = transport.bars(501)[-3].time
        for observation, output in enumerate(outputs, 1):
            points = [point for line in output['lines'] if line.get('name', line.get('title')) == 'old point'
                      for point in line['data'] if point['time'] == shifted]
            assert [point['value'] for point in points] == ([100 + observation] if observation % 2 == 0 else [])
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_repair_during_live_execution_wakes_the_existing_writer(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        entered, allowed = delay_next_execution(wire, monkeypatch)
        try:
            wire.client.post('/fixture/tick/501?close=101')

            async def wait_entered():
                await asyncio.wait_for(entered.wait(), 5)

            wire.client.portal.call(wait_entered)
            wire.client.post('/fixture/amend')

            async def wait_correction():
                meta = dict(exchange='binance', market_type='spot', symbol='BTCUSDT', interval='1m')
                async with asyncio.timeout(5):
                    while not wire.ranges.data_revision_for_meta(meta)['correctionRevision']:
                        await asyncio.sleep(0)

            wire.client.portal.call(wait_correction)
        finally:
            wire.client.portal.call(allowed.set)
        error = transport.receive(ws, 'error')
        assert error['code'] == 'INDICATOR_CALCULATION_RECOVERY_REQUIRED'
        assert error['error'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED'
        recovered = transport.receive(ws, 'indicator.snapshot')
        assert transport.value(recovered) == 500
        assert recovered['calculation']['generation'] == initial['calculation']['generation'] + 1
        assert wire.service.calculations.snapshot()['holders'] == 1
        wire.client.post('/fixture/tick/501?close=102')
        assert transport.value(transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')) == 501
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_live_input_overflow_releases_writer_instead_of_dropping_observations(real_bus_wire, monkeypatch):
    from app.api.v1 import chart_calculation_stream
    monkeypatch.setattr(chart_calculation_stream, 'MAX_PENDING_CHART_INPUTS', 2)
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        transport.receive(ws, 'indicator.snapshot')
        entered, allowed = delay_next_execution(wire, monkeypatch)
        try:
            wire.client.post('/fixture/tick/501?close=101')

            async def wait_entered():
                await asyncio.wait_for(entered.wait(), 5)

            wire.client.portal.call(wait_entered)
            for close in (102, 103, 104):
                wire.client.post('/fixture/tick/501?close=' + str(close))
            error = transport.receive(ws, 'error')
            assert error['code'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED'
            assert error['detail']['reason'] == 'chart_input_capacity_exhausted'
        finally:
            wire.client.portal.call(allowed.set)
        async def wait_released():
            async with asyncio.timeout(5):
                while wire.service.calculations.snapshot()['holders'] or wire.source.leases:
                    await asyncio.sleep(0)
        wire.client.portal.call(wait_released)
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_queued_close_cannot_certify_superseded_canonical_prices(real_bus_wire, monkeypatch):
    import threading
    wire = real_bus_wire
    script = transport.SOURCE + '\nplot(close,title="source close")\n'
    initial = wire.client.post('/indicators/calculations', json=transport.open_request(script=script)).json()
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial), script=script)
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        transport.receive(ws, 'indicator.snapshot')
        wire.client.post('/fixture/tick/501?close=101')
        assert transport.value(transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')) == 501
        entered, allowed = threading.Event(), threading.Event()
        query = wire.source.query
        first = True

        def delayed_query(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                assert allowed.wait(5), 'Controlled canonical query was not released'
            return query(*args, **kwargs)

        monkeypatch.setattr(wire.source, 'query', delayed_query)
        before = wire.host.diagnostics()['runtimes'][0]['requests']
        try:
            async def publish_close():
                wire.source.rows = list(transport.bars(501))
                await wire.source.emit(transport.DataEvent(transport.DataEventType.BAR_CLOSED,
                    transport.SeriesKey('BTCUSDT', '1m'), bar=wire.source.rows[-1]))

            wire.client.portal.call(publish_close)
            assert entered.wait(5), 'Close did not reach the actual canonical query'
            # Correction reaches SQLite before its notification. The real query
            # sees104; the queued close still contains102.
            wire.source.replace_bar(-1, replace(wire.source.rows[-1], close=104))
        finally:
            allowed.set()
        output = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert output['type'] == 'error', {
            'type': output['type'], 'sourceClose': [line['data'][-1] for line in output.get('lines', [])
                if line.get('name', line.get('title')) == 'source close'], 'calculation': output.get('calculation')}
        assert output['code'] == 'INDICATOR_CALCULATION_RECOVERY_REQUIRED'
        assert output['error'] == 'INDICATOR_CALCULATION_SOURCE_CHANGED'
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before
        wire.client.portal.call(wire.source.emit, transport.DataEvent(transport.DataEventType.BAR_CLOSED,
            transport.SeriesKey('BTCUSDT', '1m'), bar=wire.source.rows[-1]))
        recovered = transport.receive(ws, 'indicator.snapshot')
        assert transport.value(recovered) == 501
        assert recovered['calculation']['generation'] == initial['calculation']['generation'] + 1
        assert recovered['calculation']['closedThrough'] == wire.source.rows[-1].time
        line = next(line for line in recovered['lines'] if line.get('name', line.get('title')) == 'source close')
        assert line['data'][-1]['value'] == 104
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_finalizing_current_bucket_preserves_inflight_observation(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    script = transport.SOURCE + '\nplot(close, title="captured close")\n'
    initial = wire.client.post('/indicators/calculations', json=transport.open_request(script=script)).json()
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial), script=script)
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        entered, allowed = delay_next_execution(wire, monkeypatch)
        try:
            wire.client.post('/fixture/tick/501?close=103')

            async def wait_entered():
                await asyncio.wait_for(entered.wait(), 5)

            wire.client.portal.call(wait_entered)

            async def publish_final():
                wire.source.rows = list(transport.bars(501))
                await wire.source.emit(transport.DataEvent(transport.DataEventType.BAR_CLOSED,
                    transport.SeriesKey('BTCUSDT', '1m'), bar=wire.source.rows[-1]))

            wire.client.portal.call(publish_final)
        finally:
            wire.client.portal.call(allowed.set)
        for value, close in ((501, 103), (502, 102)):
            output = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
            assert output['type'] != 'error', output
            assert transport.value(output) == value
            assert output['calculation']['generation'] == initial['calculation']['generation']
            line = next(row for row in output['lines'] if row.get('name', row.get('title')) == 'captured close')
            assert line['data'][-1]['value'] == close
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_discarded_runtime_tail_is_reseeded_from_origin_without_losing_writer(real_bus_wire):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    reference = transport.ref(initial)
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, reference)
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        assert transport.value(transport.receive(ws, 'indicator.snapshot')) == 500
        for close, value in ((101, 501), (103, 502)):
            wire.client.post('/fixture/tick/501?close=' + str(close))
            last = transport.receive(ws, 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
            assert transport.value(last) == value

        # The actual sidecar loses its retained execution and output while
        # the chart still owns its source, reference, and live subscription.
        route = wire.service.route_for('pine')
        wire.client.portal.call(wire.host.release_stream, route.runtime_id, reference['domainId'])
        wire.client.post('/fixture/tick/501?close=104')
        rebuilt = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert rebuilt['type'] == 'indicator.snapshot', rebuilt
        assert transport.value(rebuilt) == 501
        assert rebuilt['calculation']['generation'] == last['calculation']['generation'] + 1
        assert rebuilt['calculation']['sequence'] == last['calculation']['sequence'] + 1
        assert rebuilt['calculation']['origin'] == initial['calculation']['origin']
        assert rebuilt['meta']['sessionResetReason'] == 'runtimeRebuild'
        assert rebuilt['meta']['sessionRecovered'] is False
        cached = transport.view(wire, transport.ref(rebuilt))
        assert cached['meta']['sessionResetReason'] == 'runtimeRebuild'
        assert wire.service.calculations.snapshot()['holders'] == 1
        wire.client.post('/fixture/tick/501?close=105')
        continued = transport.receive(ws, 'error', 'indicator.replace_range', 'indicator.patch', 'indicator.snapshot')
        assert continued['type'] != 'error', continued
        assert transport.value(continued) == 502
        assert continued['calculation']['generation'] == rebuilt['calculation']['generation']
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.client.delete('/indicators/calculations/' + reference['domainId']).json()['state'] == 'closed'


def test_lost_cached_projection_recovers_on_the_next_confirmed_close(real_bus_wire):
    wire = real_bus_wire
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    assert transport.value(initial) == 500
    with wire.client.websocket_connect('/ws') as ws:
        transport.subscribe(ws, transport.ref(initial))
        assert transport.receive(ws, 'indicator.subscribed')['ok']
        transport.receive(ws, 'indicator.snapshot')
        wire.extra_processes.extend(supervisor._process for supervisor in wire.host._supervisors.values()
                                   if supervisor._process is not None)
        wire.client.portal.call(wire.host.stop)
        assert transport.view(wire, transport.ref(initial))['code'] == 'INDICATOR_CALCULATION_OUTPUT_LOST'

        async def close_input():
            wire.source.rows = transport.bars(501)
            await wire.source.emit(transport.DataEvent(transport.DataEventType.BAR_CLOSED, transport.SeriesKey('BTCUSDT', '1m'),
                                            bar=wire.source.rows[-1]))

        wire.client.portal.call(close_input)
        output = transport.receive(ws, 'indicator.snapshot', 'error')
        assert output['type'] == 'indicator.snapshot', output
        assert transport.value(output) == 501
        assert output['calculation']['generation'] == initial['calculation']['generation'] + 1
        assert output['meta']['sessionResetReason'] == 'runtimeRebuild'
        assert output['calculation']['sequence'] == initial['calculation']['sequence'] + 1
        assert output['calculation']['closedThrough'] == wire.source.rows[-1].time
        assert wire.source.query_windows[-1][0] == initial['calculation']['origin'] * 1000
        assert wire.client.post('/fixture/tick/502').json()['ok']
        next_update = transport.receive(ws, 'indicator.replace_range', 'error')
        assert transport.value(next_update) == 502
        assert next_update['calculation']['generation'] == output['calculation']['generation']
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_snapshot_writer_rejects_overlapping_reconnect_then_resumes_same_session(real_bus_wire):
    wire = real_bus_wire
    message = transport.open_request(historyLimit=501)
    for key in ("schemaVersion", "start", "end"):
        del message[key]
    message["action"] = "subscribe"

    def subscribe(ws, **changes):
        ws.send_json({**message, **changes})
        return transport.receive(ws, "indicator.subscribed")

    def counter(ws):
        return transport.value(transport.receive(ws, "indicator.snapshot", "indicator.replace_range", "indicator.patch"))

    with wire.client.websocket_connect("/ws") as first, wire.client.websocket_connect("/ws") as reconnect:
        assert subscribe(first)["ok"]
        assert wire.client.post("/fixture/tick/501?close=103").json()["ok"]
        assert counter(first) == 501
        assert wire.client.post("/fixture/tick/501?close=104").json()["ok"]
        assert counter(first) == 502
        requests = wire.host.diagnostics()["runtimes"][0]["requests"]
        rejected = subscribe(reconnect)
        assert not rejected["ok"] and rejected["code"] == "INDICATOR_SNAPSHOT_WRITER_BUSY"
        assert wire.host.diagnostics()["runtimes"][0]["requests"] == requests
        assert len(wire.source.leases) == 1

        with wire.client.websocket_connect("/ws") as other:
            assert subscribe(other, clientId="separate-chart")["ok"]
            assert wire.client.post("/fixture/tick/501?close=105").json()["ok"]
            assert [counter(first), counter(other)] == [503, 501]

        first.send_json({"action": "unsubscribe", "clientId": message["clientId"]})
        transport.receive(first, "indicator.unsubscribed")
        assert subscribe(reconnect)["ok"]
        assert wire.client.post("/fixture/tick/501?close=106").json()["ok"]
        assert counter(reconnect) == 504


def test_snapshot_writer_remains_claimed_until_older_shielded_work_drains(real_bus_wire, monkeypatch):
    from app.api.v1 import stream_script_subscriptions

    wire = real_bus_wire
    message = transport.open_request(historyLimit=501)
    for key in ("schemaVersion", "start", "end"):
        del message[key]
    message["action"] = "subscribe"
    entered, released = threading.Event(), asyncio.Event()
    original = stream_script_subscriptions._compute_script_snapshot_message_async

    async def delayed_snapshot(*args, **kwargs):
        if kwargs.get("bar_time") and not entered.is_set():
            entered.set()
            await released.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(stream_script_subscriptions, "_compute_script_snapshot_message_async", delayed_snapshot)

    @wire.client.app.post("/fixture/queue-snapshot-close")
    async def enqueue_close():
        closed = transport.bars(501)[-1]
        await wire.source.emit(transport.DataEvent(
            transport.DataEventType.BAR_CLOSED, transport.SeriesKey("BTCUSDT", "1m"), bar=closed,
        ))
        return {"queued": True}

    with wire.client.websocket_connect("/ws") as first, wire.client.websocket_connect("/ws") as reconnect:
        try:
            first.send_json(message)
            assert transport.receive(first, "indicator.subscribed")["ok"]
            assert wire.client.post("/fixture/tick/501?close=103").json()["ok"]
            assert entered.wait(3)
            assert wire.client.post("/fixture/queue-snapshot-close").json() == {"queued": True}
            first.send_json({"action": "unsubscribe", "clientId": message["clientId"]})

            async def wait_for_market_release():
                async with asyncio.timeout(3):
                    while wire.source.leases:
                        await asyncio.sleep(0.005)

            wire.client.portal.call(wait_for_market_release)
            reconnect.send_json(message)
            rejected = transport.receive(reconnect, "indicator.subscribed")
            assert not rejected["ok"] and rejected["code"] == "INDICATOR_SNAPSHOT_WRITER_BUSY"
        finally:
            wire.client.portal.call(released.set)
        transport.receive(first, "indicator.unsubscribed")
        reconnect.send_json(message)
        assert transport.receive(reconnect, "indicator.subscribed")["ok"]
