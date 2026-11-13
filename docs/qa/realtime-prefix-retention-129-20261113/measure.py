"""Identical real SQLite/aggregator input with complete old or current backend.

Select that backend with PYTHONPATH before starting this fresh process. The new
test fixture supplies only controlled input; none of its assertions execute.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import time

import pytest
from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
from app.data_engine.memory_budget import retained_size
from tests.test_shared_blocks_integration import dm


async def window(fixture, manager):
    rows, agg, runtime, recovery, current, feed = fixture
    assert await runtime.seed(fixture_module.KEY, fixture_module.TARGET, 0, 2048 * fixture_module.WIDTH)
    counts = dict(reads=0, rows=0)
    original = manager.query_engine._read_canonical_history_rows
    def counted(*args):
        result = original(*args)
        counts['reads'] += 1
        counts['rows'] += len(result)
        return result
    manager.query_engine._read_canonical_history_rows = counted
    cpu, start = time.process_time_ns(), time.perf_counter_ns()
    peak_components = 0
    engine = next(iter(agg._pipelines.values())).bar_state
    for row in rows[2048:2306]:
        await feed(row)
        live = engine.get_state(fixture_module.KEY.exchange, fixture_module.KEY.market_type,
                                fixture_module.KEY.symbol, 0)
        peak_components = max(peak_components, len(live.source_snapshots))
    elapsed, cpu = time.perf_counter_ns()-start, time.process_time_ns()-cpu
    state = current()
    names = ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades',
             'taker_buy_base', 'taker_buy_quote', 'tick_count', 'first_input_at_ms',
             'last_input_at_ms', 'last_close_received')
    projection = {name:getattr(state, name) for name in names}
    result = dict(cpu_ns=cpu, elapsed_ns=elapsed, inputs=258,
        projection=projection, projection_sha256=hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest(),
        retained_components=len(state.source_snapshots), peak_components=peak_components,
        reachable_owner_bytes=retained_size(agg._memory_roots())[0],
        reachable_aggregator_plus_shared_bytes=retained_size([
            agg._memory_roots(), manager.shared_blocks._memory_roots()])[0],
        shared_blocks=manager.shared_blocks.snapshot(),
        budget=manager.memory_budget.snapshot(measure_heap=True),
        aggregator=agg.memory_usage(), history=runtime.snapshot(), canonical_reads_after_seed=counts)
    assert not recovery
    await runtime.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--windows', type=int, default=7)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    global fixture_module
    spec = importlib.util.spec_from_file_location('controlled_prefix_input', root/'backend/tests/test_history_prefix_retention.py')
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    # On the old backend this unused class attribute permits the same fixture
    # to choose input sizes; it adds no compaction implementation to that run.
    if not hasattr(HistoryPrefixRuntime, 'COMPACT_ROWS'):
        HistoryPrefixRuntime.COMPACT_ROWS = 128
    results = []
    for index in range(args.windows+2):
        path = args.output.parent/(args.output.stem+f'-window-{index}')
        path.mkdir(parents=True, exist_ok=False)
        with pytest.MonkeyPatch.context() as patch:
            generator = dm.__wrapped__(path, patch)
            manager = next(generator)
            try:
                fixture = fixture_module.setup.__wrapped__(manager, patch)
                patch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 2048)
                patch.setattr(HistoryPrefixRuntime, 'COMPACT_ROWS', 128)
                result = asyncio.run(window(fixture, manager))
            finally:
                try: next(generator)
                except StopIteration: pass
        results.append(result)
    measured = results[2:]
    receipt = dict(scope='controlled real SQLite + qualified 2048-prefix and 258 closed component inputs; publisher events disabled; not native/RSS/endurance',
        backend_module=__import__('app.data_engine.bar_aggregator.history_prefix_runtime', fromlist=['x']).__file__,
        warmup_windows=2, samples=measured, warmups=results[:2],
        cpu_median_ns=statistics.median(r['cpu_ns'] for r in measured),
        elapsed_median_ns=statistics.median(r['elapsed_ns'] for r in measured))
    args.output.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({key:value for key,value in receipt.items() if key not in ('samples', 'warmups')}))


if __name__ == '__main__':
    main()
