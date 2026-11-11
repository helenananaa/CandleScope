"""Exercise both sides of the chart publication boundary with the real Pine worker."""
import asyncio
from contextlib import closing
import json
import sqlite3

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.v1 import stream_indicators
from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_real_bus import real_bus_wire, storage, wire  # noqa: F401


def open_chart(wire):
    initial = wire.client.post('/indicators/calculations', json=transport.open_request()).json()
    assert initial['ok'] and transport.value(initial) == 500
    return initial


def join(ws, position):
    transport.subscribe(ws, transport.ref(position))
    assert transport.receive(ws, 'indicator.subscribed')['ok']
    return transport.receive(ws, 'indicator.snapshot')


def journal_sequences(wire):
    path = wire.tmp_path / 'wire.sqlite'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        return dict(connection.execute('SELECT id, seq FROM journal_sessions'))


def test_applied_worker_response_lost_rebuilds_before_serving_projection(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    initial = open_chart(wire)
    first_journal = journal_sequences(wire)
    assert len(first_journal) == 1
    fault = {}

    async def arm_loss():
        runtime = next(iter(wire.host._supervisors.values()))
        process = runtime._process
        original = process.stdout.readline

        async def discard_successful_response():
            line = await original()
            response = json.loads(line)
            assert response['result']['ok'] is True
            assert response['result'].get('outputPatch') is not None
            fault['journal'] = journal_sequences(wire)
            fault['process'] = process
            raise ConnectionResetError('test fault after reading the applied response')

        monkeypatch.setattr(process.stdout, 'readline', discard_successful_response)

    with wire.client.websocket_connect('/ws') as ws:
        assert transport.ref(join(ws, initial)) == transport.ref(initial)
        wire.client.portal.call(arm_loss)
        assert wire.client.post('/fixture/tick/501').json()['ok']
        lost = transport.receive(ws, 'error')
        assert lost['code'] == 'INDICATOR_CALCULATION_EXECUTION_FAILED'
        assert fault['journal'].keys() == first_journal.keys()
        assert all(fault['journal'][key] == seq + 1 for key, seq in first_journal.items())
        assert fault['process'].returncode is not None
        diagnostics = wire.host.diagnostics()['runtimes'][0]
        assert diagnostics['lastFailure']['code'] == 'PLUGIN_IO_FAILED'

    # The first HTTP read triggers canonical recovery. It must not expose the
    # worker's unseen forming observation or present it as the old generation.
    rebuilt = transport.view(wire, transport.ref(initial))
    assert rebuilt['type'] == 'indicator.snapshot' and transport.value(rebuilt) == 500
    assert rebuilt['calculation']['origin'] == initial['calculation']['origin']
    assert rebuilt['calculation']['generation'] == initial['calculation']['generation'] + 1
    assert rebuilt['calculation']['sequence'] == initial['calculation']['sequence'] + 1
    assert wire.source.query_windows[-1][0] == initial['calculation']['origin'] * 1000
    assert wire.host.diagnostics()['runtimes'][0]['starts'] == diagnostics['starts'] + 1
    before_read = wire.host.diagnostics()['runtimes'][0]['requests']
    assert transport.value(transport.view(wire, transport.ref(rebuilt))) == 500
    assert wire.host.diagnostics()['runtimes'][0]['requests'] == before_read
    with wire.client.websocket_connect('/ws') as ws:
        assert transport.value(join(ws, rebuilt)) == 500
        assert wire.client.post('/fixture/tick/501?close=103').json()['ok']
        after = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(after) == 501
        assert after['calculation']['generation'] == rebuilt['calculation']['generation']
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_reconnect_reads_admitted_projection_after_ws_frame_loss(real_bus_wire, monkeypatch):
    wire = real_bus_wire
    initial = open_chart(wire)
    dropped = []
    send = stream_indicators._send_json_with_timeout

    async def lose_first_delta(websocket, data):
        if data['type'] == 'indicator.replace_range' and not dropped:
            dropped.append(data)
            await websocket.close(code=1011)
            raise ConnectionResetError('test fault after host admission, before WS send')
        await send(websocket, data)

    monkeypatch.setattr(stream_indicators, '_send_json_with_timeout', lose_first_delta)
    with wire.client.websocket_connect('/ws') as ws:
        assert transport.value(join(ws, initial)) == 500
        assert wire.client.post('/fixture/tick/501').json()['ok']
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1011

    async def wait_for_detach():
        async with asyncio.timeout(5):
            while wire.service.calculations.snapshot()['holders']:
                await asyncio.sleep(0.01)

    wire.client.portal.call(wait_for_detach)
    assert len(dropped) == 1 and transport.value(dropped[0]) == 501
    before_reconnect = wire.host.diagnostics()['runtimes'][0]['requests']
    with wire.client.websocket_connect('/ws') as ws:
        restored = join(ws, initial)
        assert transport.ref(restored) == transport.ref(dropped[0])
        assert transport.value(restored) == 501
        assert wire.host.diagnostics()['runtimes'][0]['requests'] == before_reconnect
        assert wire.client.post('/fixture/tick/501?close=103').json()['ok']
        next_frame = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(next_frame) == 502
        assert next_frame['calculation']['generation'] == initial['calculation']['generation']
        assert next_frame['calculation']['sequence'] == dropped[0]['calculation']['sequence'] + 1
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


def test_reconnect_fences_forming_observations_missed_while_detached(real_bus_wire):
    wire = real_bus_wire
    initial = open_chart(wire)
    with wire.client.websocket_connect('/ws') as ws:
        assert transport.value(join(ws, initial)) == 500
        for close in (101, 102):
            assert wire.client.post('/fixture/tick/501', params={'close': close}).json()['ok']
            observed = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(observed) == 502
        ws.send_json({'action': 'unsubscribe', 'clientId': 'chart-a'})
        transport.receive(ws, 'indicator.unsubscribed')
    assert wire.service.calculations.snapshot()['holders'] == 0

    # The same forming bar returns to its old OHLCV. A latest-row comparison
    # alone cannot see either of the two missed execution opportunities.
    for close in (103, 102):
        assert wire.client.post('/fixture/tick/501', params={'close': close}).json()['ok']

    with wire.client.websocket_connect('/ws') as ws:
        recovered = join(ws, observed)
        assert recovered['calculation']['domainId'] == observed['calculation']['domainId']
        assert recovered['calculation']['generation'] == observed['calculation']['generation'] + 1
        assert recovered['calculation']['closedThrough'] == observed['calculation']['closedThrough']
        assert recovered['dataRevision']['revisionToken'] == observed['dataRevision']['revisionToken']
        assert recovered['meta']['sessionReset'] is True
        assert recovered['meta']['sessionRecovered'] is False
        assert transport.value(recovered) == 501
        assert wire.client.post('/fixture/tick/501?close=104').json()['ok']
        next_frame = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(next_frame) == 502
        assert next_frame['calculation']['generation'] == recovered['calculation']['generation']
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'


@pytest.mark.parametrize('journal_fault', [None, 'wrong_commit', 'missing_slot'])
def test_worker_restart_proves_the_last_admitted_observation(real_bus_wire, journal_fault):
    journal_matches = journal_fault is None
    wire = real_bus_wire
    initial = open_chart(wire)
    with wire.client.websocket_connect('/ws') as ws:
        join(ws, initial)
        for close in (101, 102):
            assert wire.client.post('/fixture/tick/501', params={'close': close}).json()['ok']
            admitted = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(admitted) == 502
        before = journal_sequences(wire)
        wire.extra_processes.extend(s._process for s in wire.host._supervisors.values() if s._process is not None)
        wire.client.portal.call(wire.host.stop)
        if journal_fault:
            with closing(sqlite3.connect(wire.tmp_path / 'wire.sqlite')) as db, db:
                if journal_fault == 'wrong_commit':
                    # A commit token can differ even if the operation count did not change.
                    row, = db.execute('SELECT state FROM journal_sessions').fetchone()
                    state = json.loads(row)
                    state['chartCommit'] = 'a' * 32
                    db.execute('UPDATE journal_sessions SET state=?', (json.dumps(state),))
                else:
                    db.execute('UPDATE journal_operations SET seq=seq+100 WHERE seq=(SELECT MAX(seq) FROM journal_operations)')
        # This distinct observation has the same BAR and price as the last
        # acknowledged one. It must advance varip exactly once after restore.
        assert wire.client.post('/fixture/tick/501?close=102').json()['ok']
        restored = transport.receive(ws, 'indicator.snapshot')
        assert restored['calculation']['domainId'] == admitted['calculation']['domainId']
        assert restored['calculation']['generation'] == admitted['calculation']['generation'] + 1
        assert restored['calculation']['sequence'] == admitted['calculation']['sequence'] + 1
        assert restored['range']['start'] == admitted['calculation']['origin']
        assert restored['meta']['sessionRecovered'] is journal_matches
        assert restored['meta']['sessionReset'] is not journal_matches
        assert transport.value(restored) == (503 if journal_matches else 501)
        if journal_matches:
            assert journal_sequences(wire) == {key: seq + 1 for key, seq in before.items()}
        assert wire.client.post('/fixture/tick/501?close=104').json()['ok']
        next_frame = transport.receive(ws, 'indicator.replace_range')
        assert transport.value(next_frame) == (504 if journal_matches else 502)
        assert next_frame['calculation']['generation'] == restored['calculation']['generation']
    assert wire.client.delete('/indicators/calculations/' + transport.ref(initial)['domainId']).json()['state'] == 'closed'
