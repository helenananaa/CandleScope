"""Same accepted input trace, batch vs 129-A; includes slow corrections.

Setup is excluded from warm update timing. State-executor and public-publisher
paths are measured separately; neither includes network, SQLite or frontend
work. The independent public-recording oracle is separate.
"""
from copy import deepcopy
import asyncio
from dataclasses import asdict, replace
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.data_engine.bar_aggregator import BarAggregator, BarInput, BarInputSource, BarAggregatorConfig, BarStateEngine, TimeBucketEngine, MergeMode
from app.data_engine.bar_aggregator.component_accumulator import ComponentAccumulator
from app.data_engine.bar_aggregator.bar_state import has_complete_closed_component_coverage
from app.data_engine.memory_budget import retained_size
from tests.test_component_incremental import component, apply, engine

FIELDS = ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')


def compare(left, right):
    for field in FIELDS:
        a, b = left[field], right[field]
        if a is None or b is None:
            assert a is None and b is None, field
        else:
            assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8), (field, a, b)


def summary(samples):
    ordered = sorted(samples)
    return dict(median_ms=statistics.median(samples), p95_ms=ordered[math.ceil(len(samples) * .95) - 1],
                max_ms=max(samples), samples=len(samples))


def run(size):
    seed_count = size - 16
    owner = engine(size)
    for i in range(seed_count):
        seed, _ = apply(owner, component(i, closed=i < seed_count - 1))
    initial = component(seed_count - 1, closed=False)
    trace = [('tail', replace(initial, sequence=s, high=initial.high + s / 100,
                             low=initial.low - s / 100, volume=initial.volume + s / 10,
                             quote_volume=initial.quote_volume + s * 12)) for s in range(2, 34)]
    trace.append(('tail', replace(trace[-1][1], sequence=34, is_closed=True)))
    for i in range(seed_count, size):
        trace.extend([('append', component(i, closed=False)), ('tail', component(i, sequence=2))])
    trace.append(('historical_correction', component(size // 2, sequence=3, high=101, low=99,
                                                     volume=.1, source=BarInputSource.CORRECTION)))
    trace_hash = hashlib.sha256(repr([asdict(row) for _, row in trace]).encode()).hexdigest()
    runs, outputs = {'batch': [], 'incremental': []}, {}
    for repetition in range(3):
        for label in (('batch', 'incremental') if repetition % 2 == 0 else ('incremental', 'batch')):
            executor = engine(size, incremental=label == 'incremental')
            state = deepcopy(seed)
            executor._active[next(iter(owner._active))] = state
            if label == 'incremental':
                index = ComponentAccumulator()
                row = state.source_snapshots[initial.input_key]
                index.update(state.source_snapshots, initial.input_key, row)
                state._component_accumulator = index
            samples, result_trace = {}, []
            for kind, row in trace:
                started = time.perf_counter()
                state, change = apply(executor, row)
                closed = has_complete_closed_component_coverage(state)
                samples.setdefault(kind, []).append((time.perf_counter() - started) * 1000)
                result_trace.append((state.to_storage_dict(), change.value, closed))
            runs[label].append({kind: summary(values) for kind, values in samples.items()})
            outputs[label] = result_trace
            if label == 'incremental':
                diagnostics = state._component_accumulator.snapshot()
                memory = retained_size((state._component_accumulator,))[0]
                assert memory <= diagnostics['estimated_bytes']
            executor.clear()
    for (a, ac, af), (b, bc, bf) in zip(outputs['batch'], outputs['incremental']):
        compare(a, b)
        assert (ac, af) == (bc, bf)
    medians = {label: {kind: statistics.median(r[kind]['median_ms'] for r in values)
                       for kind in values[0]} for label, values in runs.items()}
    return dict(target_minutes=size, seed_components=seed_count, trace_events=len(trace),
                trace_sha256=trace_hash, parity=True, runs=runs, median_of_trial_medians_ms=medians,
                speedup={kind: medians['batch'][kind] / medians['incremental'][kind] for kind in medians['batch']},
                index=diagnostics, index_retained_bytes=memory)


def public_recording():
    archive = ROOT / 'docs/qa/h127-20261031/public-okx-daily.json.gz'
    rows = json.loads(gzip.decompress(archive.read_bytes()))
    day, width = 86400000, 17 * 86400000
    groups = {}
    for row in rows:
        groups.setdefault(row['open_time'] // width * width, []).append(row)
    compared, unknown = 0, 0
    max_error = {name: 0.0 for name in FIELDS}
    for start, source in groups.items():
        if [r['open_time'] for r in source] != list(range(start, start + width, day)):
            continue
        executor = BarStateEngine(BarAggregatorConfig(), TimeBucketEngine(width), '17d')
        for row in source:
            payload = {f: row[f] for f in FIELDS}
            value = BarInput(symbol='BTC-USDT-SWAP', exchange='okx', market_type='futures',
                source_interval='1d', open_time_ms=row['open_time'], close_time_ms=row['close_time'],
                source=BarInputSource.BACKFILL, is_closed=True, sequence=1, merge_mode=MergeMode.COMPONENT,
                enhanced_fields=frozenset(f for f in FIELDS[5:] if row[f] is not None),
                **payload)
            state, _ = apply(executor, value, start=start)
        norm = lambda v: Decimal(str(round(float(v), 8)))
        expected = dict(open=norm(source[0]['open']), close=norm(source[-1]['close']),
                        high=max(norm(r['high']) for r in source), low=min(norm(r['low']) for r in source))
        for name in FIELDS[4:]:
            vals = [r[name] for r in source]
            expected[name] = None if any(v is None for v in vals) else (
                sum(int(v) for v in vals) if name == 'trades' else sum(norm(v) for v in vals))
        output = state.to_storage_dict()
        assert has_complete_closed_component_coverage(state)
        for field, wanted in expected.items():
            actual = output[field]
            if wanted is None:
                assert actual is None
                unknown += 1
            else:
                error = abs(float(wanted) - actual)
                max_error[field] = max(max_error[field], error)
                assert math.isclose(actual, float(wanted), rel_tol=1e-12, abs_tol=1e-8)
        compared += 1
    assert compared >= 25
    return dict(fixture_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                compared_closed_buckets=compared, unknown_fields_preserved=unknown,
                max_absolute_error=max_error, passed=True,
                oracle='Independent Decimal reduction of recorded canonical daily inputs on actual epoch-aligned 17d bounds')


async def pipeline():
    size = 10007
    seed_owner = engine(size)
    for i in range(size - 1):
        seed, _ = apply(seed_owner, component(i, closed=i < size - 2))
    initial = component(size - 2, closed=False)
    rows = [replace(initial, sequence=s, volume=initial.volume + s,
                    quote_volume=initial.quote_volume + s * 100) for s in range(2, 34)]
    all_runs, outputs = {'batch': [], 'incremental': []}, {}
    for repetition in range(3):
        for label in (('batch', 'incremental') if repetition % 2 == 0 else ('incremental', 'batch')):
            aggregator = BarAggregator(BarAggregatorConfig(incremental_components=label == 'incremental',
                                                          update_throttle_ms=0))
            aggregator.add_target('BTCUSDT', '10007m')
            owner = aggregator.get_pipeline('10007m').bar_state
            state = deepcopy(seed)
            owner._active[next(iter(seed_owner._active))] = state
            if label == 'incremental':
                index = ComponentAccumulator()
                index.update(state.source_snapshots, initial.input_key, state.source_snapshots[initial.input_key])
                state._component_accumulator = index
            captures = []
            async def capture(event):
                assert event.bar._component_accumulator is None
                captures.append((event.event_type.value, event.bar.to_storage_dict()))
            aggregator.publisher.on_bar_event(capture)
            samples = []
            for row in rows:
                started = time.perf_counter()
                await aggregator.ingest_bar_input('binance', 'spot', 'BTCUSDT', '10007m', row)
                samples.append((time.perf_counter() - started) * 1000)
            assert len(captures) == len(rows)
            all_runs[label].append(summary(samples))
            outputs[label] = captures
            aggregator.remove_target('BTCUSDT', '10007m')
            assert aggregator.memory_usage()['component_index_bytes'] == 0
            await aggregator.stop()
    for (ae, a), (be, b) in zip(outputs['batch'], outputs['incremental']):
        assert ae == be
        compare(a, b)
    return dict(target_minutes=size, events_per_trial=len(rows), same_published_events=True,
                trials=all_runs, boundary='public ingest_bar_input through lifecycle/finalizer/publisher callback; throttle disabled for both; no storage/network/UI',
                remaining_cost='Published immutable snapshots still copy the component dictionary; 129-B/C address ownership/window retention separately.')


if __name__ == '__main__':
    report = dict(cases=[run(size) for size in (89, 97, 101, 10007)], public_recording=public_recording(),
                  pipeline=asyncio.run(pipeline()),
                  limitations='Warm state-executor benchmark; no claim about complete app speedup. Historical correction fallback still sorts/scans the bucket; metadata and its cost are included.')
    out = ROOT / 'output/r129-20261101/benchmark.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps([dict(target=c['target_minutes'], medians=c['median_of_trial_medians_ms'],
                           speedup=c['speedup'], retained=c['index_retained_bytes']) for c in report['cases']], indent=2))
    print(json.dumps(report['public_recording'], indent=2))
