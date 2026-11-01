"""Real SQLite receipt/commit/publication/ack benchmark, using isolated files."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import tempfile
import threading
import time

from app.data_engine.data_manager.bar_delivery import DurableBarDelivery
from app.data_engine.storage import klines_repo
from tests.test_bar_delivery_journal import payload


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))]


async def case(count, contention):
    with tempfile.TemporaryDirectory(prefix='candlescope-delivery-') as directory:
        klines_repo.KLINES_DB_PATH = Path(directory) / 'klines.sqlite'
        klines_repo.init_klines_storage()
        storage = klines_repo.KlinesRepoAdapter()
        journal = storage.bar_delivery
        connect = journal._connect
        counts, count_lock = Counter(), threading.Lock()
        def trace(sql):
            with count_lock:
                counts['traces'] += 1
                counts[sql.split(None, 1)[0].upper()] += 1
        def tracked():
            connection = connect()
            with count_lock:
                counts['connections'] += 1
            connection.set_trace_callback(trace)
            return connection
        journal._connect = tracked
        with closing(connect()) as connection:
            pragmas = {p: connection.execute('PRAGMA ' + p).fetchone()[0]
                       for p in ('journal_mode', 'synchronous', 'busy_timeout')}
        starts, delivered, delays = {}, [], []
        async def publish(event):
            # This runs only after canonical commit and checks a fresh reader.
            row = storage.query_bars(event.key.symbol, '1m', start_ms=event.bar.time_ms,
                                     end_ms=event.bar.time_ms)[0]
            assert row['close'] == event.bar.close
            identity = event.detail['delivery_id']
            delivered.append(identity)
            delays.append((time.perf_counter() - starts[identity]) * 1000)
        delivery = DurableBarDelivery(lambda: storage, publish, retry_delay=0)
        cpu_start, started = time.process_time(), time.perf_counter()
        for index in range(count):
            value = payload(close=2 + index / 10000)
            value['symbol'] = f'BENCH{index:04d}USDT'
            identity = f'close-{index}'
            starts[identity] = time.perf_counter()
            journal.enqueue(identity, value)
        enqueue_ms = (time.perf_counter() - started) * 1000
        enqueue_counts = dict(counts)
        writer_errors, writer_times = [], []
        writer_ready = threading.Event()
        def writer():
            try:
                for i in range(32):
                    at = time.perf_counter()
                    with closing(connect()) as connection, connection:
                        connection.execute('BEGIN IMMEDIATE')
                        writer_ready.set()
                        # Controlled competing short transaction; no fabricated
                        # disk-speed claim. The real database writer lock is held.
                        time.sleep(.002)
                    writer_times.append((time.perf_counter() - at) * 1000)
                    time.sleep(.002)
            except BaseException as exc:
                writer_errors.append(repr(exc))
        competing = threading.Thread(target=writer) if contention else None
        if competing:
            competing.start()
            await asyncio.to_thread(writer_ready.wait, 5)
        draining = time.perf_counter()
        while journal.pending_count():
            await delivery.flush()
            if delivery.snapshot()['last_error']:
                raise RuntimeError(delivery.snapshot()['last_error'])
        drain_ms = (time.perf_counter() - draining) * 1000
        if competing:
            await asyncio.to_thread(competing.join, 5)
            assert not competing.is_alive() and not writer_errors
        cpu_ms = (time.process_time() - cpu_start) * 1000
        assert delivered == [f'close-{i}' for i in range(count)]
        with closing(connect()) as connection:
            records = [tuple(r) for r in connection.execute(
                'SELECT symbol,open_time,open,high,low,close,volume,source FROM klines ORDER BY symbol')]
            phases = dict(connection.execute('SELECT phase,count(*) FROM bar_delivery GROUP BY phase'))
        assert phases == {'published': count}
        return dict(events=count, contention=contention, pragmas=pragmas,
                    enqueue_ms=enqueue_ms, drain_ms=drain_ms, cpu_ms=cpu_ms,
                    publication_ms={name: percentile(delays, q) for name, q in
                                    [('p50', .50), ('p95', .95), ('p99', .99)]},
                    journal_sql=dict(counts), enqueue_sql=enqueue_counts,
                    competing_transactions=len(writer_times),
                    competing_transaction_ms=writer_times,
                    canonical_sha256=hashlib.sha256(json.dumps(records).encode()).hexdigest(),
                    delivery_order_sha256=hashlib.sha256(json.dumps(delivered).encode()).hexdigest(),
                    delivery_diagnostics=delivery.snapshot(),
                    phases=phases, pending=journal.pending_count(),
                    wal_bytes=(Path(str(klines_repo.KLINES_DB_PATH) + '-wal').stat().st_size
                               if Path(str(klines_repo.KLINES_DB_PATH) + '-wal').exists() else 0))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Normalize/provider bootstrap is outside the steady-state transaction run.
    from app.api.v1.stream_utils import normalize_exchange
    normalize_exchange('binance')
    results = [await case(n, contention) for n, contention in
               [(1, False), (64, False), (256, False), (256, True)]]
    result = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=results, process_lifetime_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        limits='Controlled backlog, isolated real SQLite, one shared-host run. Publication includes fresh canonical read. Journal traces include trigger trace callbacks; competing lock-hold time is injected, not a disk-speed measurement. No native, power-loss or all-writer fairness qualification.')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
