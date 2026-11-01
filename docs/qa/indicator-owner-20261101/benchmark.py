"""Compare builtin execution ownership on the actual DataManager/EventBus bridge.

Controlled workload only; it is not native or exchange acceptance.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))


def percentiles(values):
    values = sorted(values)
    return {**{f'p{p}': values[min(len(values) - 1, math.ceil(len(values) * p / 100) - 1)]
               for p in (50, 95, 99)}, 'max': max(values), 'samples': len(values)} if values else {}


async def case(instances, history, events, isolated, execution_mode="thread", pace_ms=2, history_mode="thread"):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
    from app.indicator import data_manager_bridge as bridge
    from app.indicator.serial_owner import call_engine
    from app.indicator.range_result_service import IndicatorRangeResultService
    from app.indicator.history_worker import run_builtin_history, history_executor_snapshot, shutdown_builtin_history
    from app.indicator import create_engine
    from app.indicator.events import IndicatorEventType
    from app.core.executors import run_indicator, executors_snapshot

    dm = DataManager()
    result_service = IndicatorRangeResultService.from_config()
    bars = [BarData(time=(i + 1) * 60, open=100 + math.sin(i / 13), high=102,
                    low=98, close=100 + math.sin(i / 13), volume=10, is_closed=True)
            for i in range(600)]
    definitions = [('EMA', {'period': 10 + i}) if i % 3 == 0 else
                   ('RSI', {'period': 10 + i}) if i % 3 == 1 else
                   ('BOLL', {'period': 100 + i, 'mult': 2}) for i in range(instances)]
    records, sent, notifications = [], {}, Counter()
    done, stop = asyncio.Event(), asyncio.Event()
    loop_thread = threading.get_ident()
    loop_lags, listener_threads, delivery_ms = [], set(), []

    def wrapped(kind, original):
        def call(*args, **kwargs):
            start = time.perf_counter()
            original(*args, **kwargs)
            finish = time.perf_counter()
            records.append(dict(kind=kind, thread=threading.get_ident(),
                                run_ms=(finish - start) * 1000,
                                queue_ms=(start - sent[kind, args[2].time]) * 1000,
                                ready_ms=(finish - sent[kind, args[2].time]) * 1000))
        return call

    def factory():
        raw = create_engine()
        raw.on_bar_closed = wrapped('closed', raw.on_bar_closed)
        raw.on_bar_updated = wrapped('preview', raw.on_bar_updated)
        return raw
    original_factory = bridge.create_engine
    bridge.create_engine = factory
    try:
        engine = bridge.bridge_indicator_engine(dm, result_service=result_service, isolate_realtime=isolated, execution_mode=execution_mode)
    finally:
        bridge.create_engine = original_factory
    keys = []
    started = time.perf_counter()
    for name, params in definitions:
        key, result = await call_engine(engine, 'subscribe', 'BTCUSDT', '1m', 'spot', name, params, bars=bars, data_revision=result_service.data_revision_for_meta({'exchange':'binance', 'market_type':'spot', 'symbol':'BTCUSDT', 'interval':'1m'}))
        assert result is not None and not result.error
        keys.append(key)
    seed_ms = (time.perf_counter() - started) * 1000

    def listener(event):
        listener_threads.add(threading.get_ident())
        notifications[event.event_type.value] += 1
        assert event.event_type != IndicatorEventType.INDICATOR_ERROR
        if event.event_type in {IndicatorEventType.INDICATOR_UPDATED, IndicatorEventType.INDICATOR_PREVIEW}:
            kind = 'closed' if event.event_type == IndicatorEventType.INDICATOR_UPDATED else 'preview'
            delivery_ms.append((time.perf_counter() - sent[kind, event.bar_timestamp]) * 1000)
        if sum(notifications.values()) == instances * events:
            done.set()
    engine.add_listener(listener)

    async def heartbeat():
        while not stop.is_set():
            target = time.perf_counter() + .002
            await asyncio.sleep(.002)
            loop_lags.append(max(0, (time.perf_counter() - target) * 1000))

    history_records = []
    history_source = [replace(bars[i % len(bars)], time=(i + 1) * 60) for i in range(12_000)] if history else []
    def background(index, queued):
        start = time.perf_counter()
        local = create_engine()
        source = history_source
        result = local.compute('ETHUSDT', '1m', 'spot', 'BOLL', {'period': 500}, source)
        assert result is not None and not result.error
        local.stop()
        finish = time.perf_counter()
        history_records.append(dict(job=index, thread=threading.get_ident(),
                                    queue_ms=(start - queued) * 1000,
                                    run_ms=(finish - start) * 1000))

    async def process_background(index, queued):
        result = await run_builtin_history('BOLL', {'symbol': 'ETHUSDT', 'interval': '1m',
            'market_type': 'spot', 'exchange': 'binance', 'params': {'period': 500}}, history_source)
        assert result is not None and not result.error
        state = history_executor_snapshot()
        history_records.append({'job': index, 'pid': state['worker']['pid'],
                                'ready_ms': (time.perf_counter() - queued) * 1000})

    heart = asyncio.create_task(heartbeat())
    work = [asyncio.create_task(process_background(i, time.perf_counter())
            if history_mode == 'process' else run_indicator(background, i, time.perf_counter()))
            for i in range(2 if history else 0)]
    closed_bars = []
    worker_cpu_start = engine.snapshot().get("worker", {}).get("cpu_seconds", 0)
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        for i in range(events):
            closed = i % 2 == 1
            at = 60 * (601 + i // 2)
            price = 100 + math.sin((600 + i // 2) / 13)
            bar = BarData(time=at, open=price, high=102, low=98, close=price,
                          volume=10, is_closed=closed)
            kind = 'closed' if closed else 'preview'
            if closed:
                closed_bars.append(bar)
            scheduled = wall + i * pace_ms / 1000
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            sent[kind, at] = scheduled
            await dm.event_bus.emit(DataEvent(
                event_type=DataEventType.BAR_CLOSED if closed else DataEventType.BAR_UPDATED,
                key=SeriesKey('BTCUSDT', '1m'), bar=bar))
            await asyncio.sleep(0)
        await asyncio.wait_for(done.wait(), timeout=30)
        await asyncio.gather(*work)
        elapsed, cpu_time = time.perf_counter() - wall, time.process_time() - cpu
        worker_at_completion = engine.snapshot().get("worker", {})
        state = dm.event_bus.snapshot()
        assert state['events_dropped'] == state['callback_errors'] == state['recovery_required_total'] == 0
        assert notifications[IndicatorEventType.INDICATOR_ERROR.value] == 0
        assert notifications[IndicatorEventType.INDICATOR_UPDATED.value] == instances * events // 2
        assert notifications[IndicatorEventType.INDICATOR_PREVIEW.value] == instances * events // 2
        assert all(row['last_committed'] == closed_bars[-1].time for row in engine.snapshot()['instances'])
        reference = create_engine()
        values = []
        for key, (name, params) in zip(keys, definitions):
            result = reference.compute('BTCUSDT', '1m', 'spot', name, params, bars + closed_bars)
            actual = (await call_engine(engine, 'get_result', key)).get_latest()
            expected = reference._instances[result.key].get_latest()
            assert actual.keys() == expected.keys()
            for field in actual:
                a, b = actual[field], expected[field]
                assert (a is None and b is None) or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)
            values.append(actual)
        reference.stop()
        assert len(records) == (0 if execution_mode == 'process' else events)
        assert listener_threads == {loop_thread}
        assert all((r['thread'] != loop_thread) == isolated for r in records)
        if execution_mode == 'process':
            assert engine.snapshot()['worker']['pid'] != os.getpid()
        report = dict(instances=instances, history_jobs=len(work), events=events, isolated=isolated, execution_mode=execution_mode,
                      delivery_ms=percentiles(delivery_ms), listener_threads=sorted(listener_threads),
                      runtime=engine.snapshot(),
                      history_mode=history_mode, history_executor=history_executor_snapshot(),
                      pace_ms=pace_ms, seed_ms=seed_ms, wall_ms=elapsed * 1000, process_cpu_ms=cpu_time * 1000,
                      worker_cpu_ms=(worker_at_completion.get("cpu_seconds", 0) - worker_cpu_start) * 1000 if execution_mode == "process" else 0,
                      worker_peak_rss_bytes=worker_at_completion.get("peak_rss_bytes"),
                      event_loop_thread=loop_thread, callback_threads=sorted({r['thread'] for r in records}),
                      all_callbacks_on_event_loop=False if execution_mode == "process" else all(r['thread'] == loop_thread for r in records),
                      loop_lag_ms=percentiles(loop_lags), notifications=dict(notifications),
                      final_values_sha256=hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
                      full_recompute_parity=True, history=history_records,
                      event_bus=state, executors=executors_snapshot())
        for kind in ('preview', 'closed'):
            selected = [r for r in records if r['kind'] == kind]
            report[kind] = {metric: percentiles([r[metric] for r in selected])
                            for metric in ('run_ms', 'queue_ms', 'ready_ms')}
    finally:
        stop.set()
        await heart
        await asyncio.gather(*work, return_exceptions=True)
        result_service.unbind_all()
        await shutdown_builtin_history()
        await engine.shutdown_bridge()
        if isolated:
            await engine.aclose()
        else:
            engine.stop()
        # The probe starts only the subscription workers, not ingestion or
        # the full manager service; it therefore owns the bus shutdown.
        await dm.event_bus.close()
        await dm.shutdown()
    report['subscriptions_after_shutdown'] = dm.event_bus.snapshot()['callback_subscriptions']
    assert report['subscriptions_after_shutdown'] == 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/indicator-owner-20261101/benchmark.json')
    parser.add_argument('--events', type=int, default=200)
    parser.add_argument('--history-mode', choices=['thread', 'process'], default='thread')
    parser.add_argument('--pace-ms', type=float, default=20)
    parser.add_argument('--isolated', action='store_true')
    parser.add_argument('--execution-mode', choices=['thread', 'process'], default='thread')
    args = parser.parse_args()
    if args.events < 2 or args.events % 2:
        parser.error('--events must be an even number >= 2')
    with tempfile.TemporaryDirectory(prefix='indicator-p0-') as tmp:
        os.environ['CANDLE_DATA_DIR'] = tmp
        async def run():
            return [await case(n, background, args.events, args.isolated, args.execution_mode, args.pace_ms, args.history_mode)
                    for n, background in ((1, False), (16, False), (64, False), (64, True))]
        results = asyncio.run(run())
    report = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  python=platform.python_version(), machine=platform.machine(), platform=platform.platform(),
                  workload=f'600 seed bars, fixed {args.pace_ms}ms input cadence; delay measured from scheduled emission; revision/result service enabled; optional 2 x 12000-row BOLL history jobs (source prepared before timed section)',
                  rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
                  cases=results,
                  isolated=args.isolated,
                  working_diff_sha256=hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD'], cwd=ROOT)).hexdigest(),
                  limitations='Controlled builtin/EventBus workload only. No real exchange, Pine/Python runtime, backtest or native UI workload.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps([dict(instances=r['instances'], history_jobs=r['history_jobs'],
                           event_loop=r['all_callbacks_on_event_loop'], lag=r['loop_lag_ms'],
                           closed_run_ms=r['closed']['run_ms']) for r in results], indent=2))


if __name__ == '__main__':
    main()
