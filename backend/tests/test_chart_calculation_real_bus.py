"""Keep the existing chart wire contract on the actual routed event bus."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

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
