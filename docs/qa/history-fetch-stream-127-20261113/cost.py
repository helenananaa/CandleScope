"""Controlled native REST/SQLite cost, separate from installed-app acceptance.

Run this same file in fresh processes against base and product source roots.
Input tape, database/schema, engine construction and diagnostics are outside
the timing/allocation window. No network, RSS, archive or sustained-load claim.
"""
import argparse
import asyncio
from contextlib import contextmanager
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mode', choices=['full','receipt'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0,str(args.source/'backend'))
    import pytest
    from app.core import config as core_config
    from app.data_engine.storage import klines_repo
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.config import DataManagerConfig
    from app.data_engine.memory_budget import retained_size
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.ingestion.config import IngestionConfig
    from tests.test_mixed_backfill_plan import engine_for
    from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows
    results = []
    for count in [1024,8192]:
        trials = []
        # Two warmups, five timed trials, then a separate allocation trial.
        for attempt in range(8):
            with tempfile.TemporaryDirectory(prefix='history-stream-cost-') as temp, pytest.MonkeyPatch.context() as patch:
                database = Path(temp)/'history.sqlite'
                patch.setattr(klines_repo,'KLINES_DB_PATH',database)
                patch.setattr(core_config,'KLINES_DB_PATH',database)
                klines_repo.init_klines_storage()
                cfg = DataManagerConfig()
                cfg.query.auto_backfill = False
                dm = DataManager(cfg)
                dm.set_storage(klines_repo.KlinesRepoAdapter())
                engine = engine_for(dm.query_engine)
                engine.config.fetch_batch_size = 1000
                engine.config.fetch_concurrency = engine.config.fetch_global_concurrency = 1
                engine.config.fetch_rate_limit_delay = 0
                engine.config.fetch_binance_futures_rate_limit_delay = 0
                tape = _make_binance_rows(count,60_000)
                transport = _FakeBinanceTransport(tape,page_cap=1000)
                engine._fetcher = HistoricalFetcher(engine.config,transport,IngestionConfig())
                peak_reserved = writes = write_rows = 0
                reserve = dm.memory_budget.reserve
                @contextmanager
                def measured_reserve(*params,**kwargs):
                    nonlocal peak_reserved
                    with reserve(*params,**kwargs) as lease:
                        peak_reserved = max(peak_reserved,dm.memory_budget.snapshot()['reserved_bytes'])
                        yield lease
                patch.setattr(dm.memory_budget,'reserve',measured_reserve)
                original = engine._storage.upsert_bars
                async def counted(*params,**kwargs):
                    nonlocal writes, write_rows
                    writes += 1
                    write_rows += len(params[2])
                    return await original(*params,**kwargs)
                patch.setattr(engine._storage,'upsert_bars',counted)
                run = engine.run if args.mode == 'full' else engine.run_receipt
                gc.collect()
                if attempt == 7: tracemalloc.start()
                cpu, wall = time.process_time_ns(),time.perf_counter_ns()
                report = asyncio.run(run('BTCUSDT',intervals=['1m'],range_start_ms=0,
                    range_end_ms=(count-1)*60_000,exchange='binance',market_type='futures'))
                cpu_ms = (time.process_time_ns()-cpu)/1e6
                wall_ms = (time.perf_counter_ns()-wall)/1e6
                allocations = tracemalloc.get_traced_memory() if attempt == 7 else None
                if attempt == 7: tracemalloc.stop()
                assert report.status.value == 'completed', report.errors
                assert sum(item.bars_count for item in report.fetch_results) == report.reconcile_result.bars_written == count
                rows = dm.query_engine.storage.query_bars('BTCUSDT','1m',0,(count-1)*60_000,market_type='futures')
                fields = ['open_time','close_time','open','high','low','close','volume',
                          'quote_volume','trades','taker_buy_base','taker_buy_quote']
                digest = hashlib.sha256(json.dumps([[row.get(k) for k in fields] for row in rows],
                    separators=(',',':')).encode()).hexdigest()
                assert len(rows) == count
                assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
                value = dict(cpu_ms=cpu_ms,wall_ms=wall_ms,report_retained_bytes=retained_size((report,))[0],
                    raw_bars_retained=sum(len(getattr(item,'bars',())) for item in report.fetch_results),
                    physical_requests=len(transport.requests),writer_calls=writes,writer_input_rows=write_rows,
                    peak_reserved_bytes=peak_reserved,canonical_sha256=digest,canonical_rows=len(rows),
                    fetch_payload_mode=report.metadata.get('fetch_payload_mode','full'),
                    allocation_current_peak=allocations)
                if attempt >= 2: trials.append(value)
                asyncio.run(dm.shutdown())
                print(json.dumps(dict(count=count,attempt=attempt,**value)),flush=True)
        measured = trials[:5]
        results.append(dict(count=count,timed=measured,allocation=trials[-1],
            cpu_median_ms=statistics.median(item['cpu_ms'] for item in measured),
            wall_median_ms=statistics.median(item['wall_ms'] for item in measured)))
    args.output.write_text(json.dumps(dict(source=str(args.source),mode=args.mode,results=results),indent=2)+'\n')


if __name__ == '__main__':
    main()
