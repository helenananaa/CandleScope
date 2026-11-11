"""Real Pine retained projections: reading output must never replay a warmup.

Use the qualified core/SDK test interpreter, preserving its venv launcher.
This does not wire chart HTTP/WS ownership or qualify the Native counter fix.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys

import pytest
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext
from app.plugin_runtime.registry import RuntimeProcessSpec
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from app.plugin_runtime.supervisor import RuntimeSupervisor, MAX_OUTPUT_STREAMS
from app.plugin_runtime.errors import PluginRequestError

FIXTURES = Path(__file__).parent / 'fixtures' / 'plugin_runtime'
SOURCE = '''//@version=6
indicator("owned counter")
varip int ticks = 0
ticks += 1
plot(ticks, title="counter")
plot(ticks % 2 == 0 ? close : na, title="old point", offset=-2)
plotshape(ticks % 2 == 0, style=shape.circle, offset=-2)
bgcolor(ticks % 2 == 0 ? color.green : na, offset=-2)
'''
CONTEXT = MarketContext(exchange='binance', market_type='spot', symbol='BTCUSDT', interval='1m')


def owner(path):
    return RuntimeSupervisor(RuntimeProcessSpec(runtime_id='candlescope.pine-compat',
        expected_package='candlescope-plugin-pine-compat', expected_version='0.4.0',
        executable=Path(sys.executable).absolute(), arguments=('-I', '-B', '-u', str(FIXTURES/'run_pine_runtime.py'), str(path)),
        working_directory=FIXTURES, startup_timeout_seconds=30, request_timeout_seconds=30, shutdown_timeout_seconds=5),
        host_name='CandleScope', host_version='0.3.0')


def bars(count, *, forming=False, close=102):
    return tuple(Bar(time=1700000040 + i*60, open=100, high=104, low=99, close=close, volume=10,
        is_closed=not(forming and i == count-1)) for i in range(count))


def request(rows, stream='chart-a'):
    return ExecuteBatchRequest(source=SOURCE, context=CONTEXT, bars=rows,
        options={'pineSessionId': stream}, output_stream=stream, bars_stream=stream)


def counter(output):
    return output.series[0].points[-1].value


@pytest.mark.anyio
async def test_owned_read_preserves_opaque_500_bar_state_instead_of_200_bar_replay(tmp_path):
    # No provider/math mock: the actual repository plugin runs its qualified core.
    live, historical = owner(tmp_path/'live.sqlite'), owner(tmp_path/'history.sqlite')
    try:
        assert await live.read_output('chart-a') is None
        assert live.snapshot()['starts'] == 0
        seeded = await live.execute_batch(request(bars(500)))
        assert seeded.ok, seeded.diagnostics
        assert counter(seeded.output) == 500
        held = await live.read_output('chart-a')
        assert held.output is seeded.output  # one SDK replica, no full-history clone
        count = live.snapshot()['requests']
        for _ in range(5):
            assert (await live.read_output('chart-a', expected=held.reference)).output is seeded.output
        assert live.snapshot()['requests'] == count

        first = await live.execute_batch(request(bars(501, forming=True)))
        assert first.ok and not first.meta['sessionReset']
        assert counter(first.output) == 501
        current = await live.read_output('chart-a')
        assert current.reference != held.reference
        assert await live.read_output('chart-a', expected=held.reference) is None
        standalone = await historical.execute_batch(replace(request(bars(501, forming=True)[-201:]),
            options={}, output_stream=None, bars_stream=None))
        assert standalone.ok and counter(standalone.output) == 201
        # Narrow chart views must read this projection, not publish the valid
        # but mathematically different standalone historical response above.
        assert counter(current.output) == 501
        assert live.snapshot()['requests'] == count + 1

        repeated = bars(501, forming=True)
        repeated = (*repeated[:-1], replace(repeated[-1], close=103))
        second = await live.execute_batch(request(repeated))
        assert second.ok and not second.meta['sessionReset']
        assert counter(second.output) == 502
        assert (await live.read_output('chart-a')).output == second.output
    finally:
        await live.stop(); await historical.stop()


@pytest.mark.anyio
async def test_projection_reference_fences_streams_restarts_and_supervisor_instances(tmp_path):
    live = owner(tmp_path/'live.sqlite')
    try:
        await live.execute_batch(request(bars(20)))
        old = await live.read_output('chart-a')
        await live.execute_batch(request(bars(7), 'chart-b'))
        other = await live.read_output('chart-b')
        assert counter(other.output) == 7 and counter(old.output) == 20
        assert await live.read_output('chart-b', expected=old.reference) is None
        assert await live.read_output('chart-a', expected=replace(old.reference, owner_epoch='another-backend')) is None
        def forming_request(close):
            rows = bars(21, forming=True)
            return request((*rows[:-1], replace(rows[-1], close=close)))

        first_tick = await live.execute_batch(forming_request(101))
        second_tick = await live.execute_batch(forming_request(102))
        assert first_tick.ok and second_tick.ok
        assert (counter(first_tick.output), counter(second_tick.output)) == (21, 22)
        observed = await live.read_output('chart-a')
        before = live.snapshot()['starts']
        await live.stop()
        assert await live.read_output('chart-a') is None
        assert live.snapshot()['starts'] == before
        resumed = await live.execute_batch(forming_request(103))
        assert resumed.ok and resumed.meta['sessionRecovered'] and not resumed.meta['sessionReset']
        assert counter(resumed.output) == 23
        assert live.snapshot()['starts'] == before + 1
        assert await live.read_output('chart-a', expected=observed.reference) is None
        new = await live.read_output('chart-a')
        assert new.reference.generation != old.reference.generation
        assert await live.read_output('chart-a', expected=old.reference) is None
        replacement = owner(tmp_path/'other-process.sqlite')
        try:
            await replacement.execute_batch(request(bars(20)))
            assert await replacement.read_output('chart-a', expected=new.reference) is None
        finally:
            await replacement.stop()
    finally:
        await live.stop()


@pytest.mark.anyio
async def test_projection_eviction_and_read_cancellation_do_not_reseed_or_send_ipc(tmp_path):
    live = owner(tmp_path/'live.sqlite')
    try:
        for i in range(MAX_OUTPUT_STREAMS + 1):
            assert (await live.execute_batch(request(bars(i+2), f'chart-{i}'))).ok
        before = live.snapshot()['requests']
        assert await live.read_output('chart-0') is None
        assert live.snapshot()['requests'] == before
        async with live._lock:
            waiting = asyncio.create_task(live.read_output('chart-1'))
            await asyncio.sleep(0)
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError): await waiting
        assert (await live.read_output('chart-1')).output is not None
        assert live.snapshot()['requests'] == before
        for value in ['', 'x'*129, None]:
            with pytest.raises(PluginRequestError): await live.read_output(value)
    finally:
        await live.stop()


@pytest.mark.anyio
async def test_registered_host_service_reads_same_replica_and_keeps_registration_gates(tmp_path):
    spec = owner(tmp_path/'host.sqlite').spec
    service = RuntimeHostService(RuntimeRegistry(plugins=(spec,)), host_name='CandleScope', host_version='0.3.0')
    try:
        assert await service.read_output(spec.runtime_id, 'chart-a') is None
        result = await service.execute_batch(spec.runtime_id, request(bars(20)))
        held = await service.read_output(spec.runtime_id, 'chart-a')
        assert held.output is result.output
        assert await service.read_output(spec.runtime_id, 'chart-a', expected=held.reference) == held
        with pytest.raises(PluginRequestError) as missing:
            await service.read_output('unregistered', 'chart-a')
        assert missing.value.code == 'PLUGIN_NOT_FOUND'
    finally: await service.stop()
    disabled = RuntimeHostService.disabled(host_name='CandleScope', host_version='0.3.0')
    with pytest.raises(PluginRequestError) as denied:
        await disabled.read_output(spec.runtime_id, 'chart-a')
    assert denied.value.code == 'PLUGIN_HOST_DISABLED'
