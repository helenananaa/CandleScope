"""Actual public runtime service/sidecar, not a second producer for chart math."""
from dataclasses import replace
import asyncio
import sqlite3

import pytest

from app.indicator.calculation_owner import CalculationOwnerError
from app.indicator.pine_calculation import PineCalculationRuntime
from app.indicator.runtime_routes import IndicatorRuntimeRoutes, IndicatorRuntimeRoute
from app.indicator.runtime_service import IndicatorRuntimeService, IndicatorRuntimeRequest
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from tests.test_runtime_owned_output import owner, bars, counter, SOURCE

SERIES = 'binance:spot:BTCUSDT:1m'


def raw(rows, **changes):
    return replace(IndicatorRuntimeRequest(language='pine', source=SOURCE, exchange='binance', market_type='spot',
        symbol='BTCUSDT', interval='1m', bars=rows), **changes)


@pytest.mark.anyio
async def test_real_service_read_does_not_execute_observe_or_replace_source_domain(tmp_path):
    spec = owner(tmp_path/'service.sqlite').spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine', 'sidecar', spec.runtime_id),)), host=host)
    observations, releases = [], []
    async def observe(request, result): observations.append((request, result))
    async def release(): releases.append('closed')
    async def release_inputs(key): releases.append(key)
    service.observe_result = observe
    service.release_inputs = release_inputs
    calculation = None
    try:
        calculation = await PineCalculationRuntime.open(service, raw(bars(500)), owner_id='service-chart-a',
            series_reference=SERIES, start=bars(1)[0].time)
        first = await calculation.advance(raw(bars(500)), series_reference=SERIES, input_revision='revision:1', expected=None,
            rebuild=False, is_current=lambda: True)
        second = await calculation.advance(raw(bars(501, forming=True)), series_reference=SERIES,
            input_revision='revision:1', expected=first, rebuild=False, is_current=lambda: True)
        assert counter((await calculation.read(expected=second)).output) == 501
        before = host.diagnostics()['runtimes'][0]['requests']
        for _ in range(5): assert counter((await calculation.read(expected=second)).output) == 501
        assert host.diagnostics()['runtimes'][0]['requests'] == before and len(observations) == 2
        assert all(request.options['pineLeaseId'] == 'service-chart-a' for request, _ in observations)
        # Changed code/parameters/market semantics never inherit this state.
        for candidate, series in [(raw(bars(501, forming=True), source=SOURCE+'\n// changed'), SERIES),
            (raw(bars(501, forming=True), params={'changed':1}), SERIES),
            (raw(bars(501, forming=True)), 'series:other-adjustment')]:
            with pytest.raises(CalculationOwnerError, match='INPUT_INVALID'):
                await calculation.advance(candidate, series_reference=series, input_revision='revision:1',
                    expected=second, rebuild=False, is_current=lambda: True)
        assert host.diagnostics()['runtimes'][0]['requests'] == before
        checks = iter([True, False])
        with pytest.raises(CalculationOwnerError, match='SOURCE_CHANGED'):
            await calculation.advance(raw(bars(501, forming=True)), series_reference=SERIES,
                input_revision='revision:1', expected=second, rebuild=False, is_current=lambda: next(checks))
        assert len(observations) == 2, 'A source-fenced result must not reach alert/result observers'
        rebuilt = await calculation.advance(raw(bars(501, forming=True)), series_reference=SERIES,
            input_revision='revision:2', expected=second, rebuild=True, is_current=lambda: True)
        assert rebuilt.generation == 2 and counter((await calculation.read(expected=rebuilt)).output) == 501
        async def broken_observer(*_args): raise RuntimeError('notification fault')
        service.observe_result = broken_observer
        changed = bars(501, forming=True)
        changed = (*changed[:-1], replace(changed[-1], close=103))
        after_fault = await calculation.advance(raw(changed), series_reference=SERIES,
            input_revision='revision:2', expected=rebuilt, rebuild=False, is_current=lambda: True)
        assert after_fault.generation == rebuilt.generation
        assert counter((await calculation.read(expected=after_fault)).output) == 502
    finally:
        if calculation is not None: await calculation.close(release=release)
        await service.stop(); await host.stop()
    assert releases == ['service-chart-a', 'closed']


@pytest.mark.anyio
async def test_unqualified_language_is_rejected_before_start_or_relabelling(tmp_path):
    spec = owner(tmp_path/'retired.sqlite').spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine', 'sidecar', spec.runtime_id),)), host=host)
    try:
        retired = raw(bars(3), language='pyne')
        with pytest.raises(CalculationOwnerError, match='BINDING_UNSUPPORTED'):
            await PineCalculationRuntime.open(service, retired, owner_id='unsupported-chart', series_reference=SERIES, start=bars(1)[0].time)
        assert retired.language == 'pyne'
        assert host.diagnostics()['runtimes'][0]['starts'] == 0
    finally: await service.stop(); await host.stop()


@pytest.mark.anyio
async def test_application_registry_shares_real_projection_and_drains_before_global_inputs(tmp_path):
    spec = owner(tmp_path/'shared-registry.sqlite').spec
    host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine', 'sidecar', spec.runtime_id),)), host=host)
    releases = []
    entered, allowed = asyncio.Event(), asyncio.Event()
    allowed.set()
    async def observe(*_args):
        entered.set()
        await allowed.wait()
    async def release_inputs(owner_id): releases.append(owner_id)
    async def stop_inputs(): releases.append('all-inputs')
    async def create(owner_id):
        return await PineCalculationRuntime.open(service, raw(bars(500)), owner_id=owner_id,
            series_reference=SERIES, start=bars(1)[0].time)
    service.observe_result = observe
    service.release_inputs = release_inputs
    service.stop_inputs = stop_inputs
    pending = stopping = None
    try:
        owner_id = await service.calculations.open(create)
        async with service.calculations.borrow(owner_id) as initial_http:
            first = await initial_http.advance(raw(bars(500)), series_reference=SERIES,
                input_revision='revision:1', expected=None, rebuild=False, is_current=lambda: True)
        async with service.calculations.borrow(owner_id) as websocket:
            assert websocket is initial_http
            second = await websocket.advance(raw(bars(501, forming=True)), series_reference=SERIES,
                input_revision='revision:1', expected=first, rebuild=False, is_current=lambda: True)
        async with service.calculations.borrow(owner_id) as range_http:
            before = host.diagnostics()['runtimes'][0]['requests']
            for _ in range(10):
                assert counter((await range_http.read(expected=second)).output) == 501
            with pytest.raises(CalculationOwnerError, match='CHANGED'):
                await range_http.read(expected=first)
            assert host.diagnostics()['runtimes'][0]['requests'] == before
        other_id = await service.calculations.open(create)
        async with service.calculations.borrow(other_id) as other_chart:
            other = await other_chart.advance(raw(bars(50)), series_reference=SERIES,
                input_revision='revision:1', expected=None, rebuild=False, is_current=lambda: True)
            assert counter((await other_chart.read(expected=other)).output) == 50
        async with service.calculations.borrow(owner_id) as same_chart:
            assert counter((await same_chart.read(expected=second)).output) == 501
        # Cancel a transport after real execution while its observer remains
        # physically admitted. Releasing the borrow must not release its inputs.
        entered.clear()
        allowed.clear()
        rows = bars(501, forming=True)
        changed = (*rows[:-1], replace(rows[-1], close=103))
        async def live_transport():
            async with service.calculations.borrow(owner_id) as shared:
                await shared.advance(raw(changed), series_reference=SERIES,
                    input_revision='revision:1', expected=second, rebuild=False, is_current=lambda: True)
        pending = asyncio.create_task(live_transport())
        await asyncio.wait_for(entered.wait(), 10)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert service.calculations.snapshot()['borrowers'] == 0
        stopping = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not stopping.done() and owner_id not in releases and 'all-inputs' not in releases
        allowed.set()
        await asyncio.wait_for(stopping, 10)
        assert releases.count(owner_id) == releases.count(other_id) == releases.count('all-inputs') == 1
        assert releases.index(owner_id) < releases.index('all-inputs')
        assert releases.index(other_id) < releases.index('all-inputs')
        assert service.calculations.snapshot()['entries'] == 0
        with sqlite3.connect(tmp_path/'shared-registry.sqlite') as db:
            assert db.execute('SELECT sessions, bytes FROM journal_budget').fetchone() == (0, 0)
            assert db.execute('SELECT COUNT(*) FROM journal_operations').fetchone() == (0,)
    finally:
        allowed.set()
        if pending is not None: await asyncio.gather(pending, return_exceptions=True)
        if stopping is not None: await asyncio.gather(stopping, return_exceptions=True)
        await service.stop()
        await host.stop()
