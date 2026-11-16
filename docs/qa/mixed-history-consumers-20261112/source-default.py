"""Compare the ordinary default query on isolated official-source databases.

Usage: PYTHONPATH=/checkout/backend python source-default.py INPUT_ROOT OUTPUT_ROOT LABEL
Use separate fresh output roots for baseline/candidate. This is source/SQLite
evidence, not a native package test or a public-network latency measurement.
"""
from __future__ import annotations

import asyncio
import csv
from decimal import Decimal
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc
import zipfile

inputs_root, root = (Path(p).resolve() for p in sys.argv[1:3])
label = sys.argv[3]
root.mkdir(parents=True, exist_ok=False)
os.environ["CANDLE_DATA_DIR"] = str(root / "isolated-data")
os.environ["KLINES_DB_PATH"] = str(root / "isolated-data/initial.sqlite")
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource, plan_fixed_target
from app.data_engine.storage import klines_repo

FIELDS = ("open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
COLS = (1, 2, 3, 4, 5, 7, 8, 9, 10)
WIDTHS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
inputs = json.loads((inputs_root / "inputs.json").read_text())
raw = {}
for item in inputs:
    path = inputs_root / "archives" / Path(item["url"]).name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as stream:
        raw[item["interval"]] = {int(r[0]): r for r in csv.reader(io.TextIOWrapper(stream))
                                  if r and r[0].isdigit()}
start = min(raw["1m"])
end = start + 16 * 86_400_000


def oracle(opened, width):
    rows = [raw["1m"][t] for t in range(opened, opened + width, 60_000)]
    return dict(zip(FIELDS, [Decimal(rows[0][1]), max(Decimal(r[2]) for r in rows),
        min(Decimal(r[3]) for r in rows), Decimal(rows[-1][4]),
        *[sum((Decimal(r[c]) for r in rows), Decimal(0)) for c in (5, 7, 8, 9, 10)]]))


def query(dm, key, first, stop, count):
    return dm.query_engine.query(key.symbol, key.interval, start_ms=first, end_ms=stop - 1,
        limit=count, exchange=key.exchange, market_type=key.market_type, auto_backfill=False,
        min_revision=dm.query_engine.storage.revision_store.head())


reports = []
for period in (89, 97, 101, 10007):
    width = period * 60_000
    count = 1 if period == 10007 else 12
    first = (start + width - 1) // width * width
    stop = first + count * width
    assert stop <= end
    key = SeriesKey("BTCUSDT", f"{period}m", market_type="futures")
    expected = {t: oracle(t, width) for t in range(first, stop, width)}
    for mode in ("mixed_only", "fine_only"):
        wanted = {interval: set() for interval in WIDTHS}
        if mode == "fine_only":
            wanted["1m"].update(range(first, stop, 60_000))
        else:
            sources = tuple(FixedHistorySource(SeriesKey("BTCUSDT", interval, market_type="futures"),
                w, 0, ((start, end),), frozenset(FIELDS), "official-202610-decimal")
                for interval, w in WIDTHS.items())
            for opened in expected:
                plan = plan_fixed_target(key, opened, opened + width, sources)
                for span in plan.spans:
                    wanted[span.source.series.interval].update(
                        range(span.start_ms, span.end_ms, span.source.width_ms))
        for repeat in range(3):
            database = root / f"{period}-{mode}-{repeat}.sqlite"
            assert not database.exists()
            core_config.KLINES_DB_PATH = klines_repo.KLINES_DB_PATH = database
            klines_repo.init_klines_storage()
            for interval, times in wanted.items():
                rows = []
                for t in sorted(times):
                    r = raw[interval][t]
                    values = {f: int(r[c]) if f == "trades" else float(r[c]) for f, c in zip(FIELDS, COLS)}
                    reference = oracle(t, WIDTHS[interval])
                    assert all(math.isclose(values[f], float(reference[f]), rel_tol=1e-12, abs_tol=1e-8) for f in FIELDS)
                    rows.append(dict(open_time=t, close_time=int(r[6]), **values))
                if rows:
                    klines_repo.upsert_klines("BTCUSDT", interval, rows,
                        source="backfill_archive_verified", market_type="futures")
            config = DataManagerConfig()
            config.query.auto_backfill = False
            dm = DataManager(config)
            dm.set_storage(klines_repo.KlinesRepoAdapter())
            try:
                for phase in ("target_absent", "repeat_target"):
                    tracemalloc.start()
                    wall, cpu = time.perf_counter(), time.process_time()
                    result = query(dm, key, first, stop, count)
                    elapsed = (time.perf_counter() - wall) * 1000
                    cpu_ms = (time.process_time() - cpu) * 1000
                    current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    complete_values = len(result.bars) == count and result.complete and not result.retryable
                    max_delta = {f: 0.0 for f in FIELDS}
                    partial_untrusted_rows = 0
                    for bar in result.bars:
                        if not complete_values and not bar.trusted_final:
                            # Baseline may display a provisional fragment when
                            # minute history is missing. It is not a complete
                            # target and cannot be compared as final OHLCV.
                            assert not bar.is_closed
                            partial_untrusted_rows += 1
                            continue
                        assert bar.trusted_final and bar.is_closed
                        for f in FIELDS:
                            a, b = getattr(bar, f), float(expected[bar.time_ms][f])
                            assert a is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8), (period, mode, f, a, b)
                            max_delta[f] = max(max_delta[f], abs(a - b))
                    if label == "candidate" or (mode == "fine_only" and period != 10007):
                        assert complete_values, (period, mode, result.metadata)
                    elif mode == "mixed_only":
                        assert not complete_values  # baseline never fabricates the missing minute history
                    else:
                        assert result.retryable and result.metadata.get("memory_budget_deferred")
                    fine_rows = dm.query_engine.storage.count_bars("BTCUSDT", "1m", first, stop - 1,
                                                                  market_type="futures")
                    assert fine_rows == len(wanted["1m"])
                    reports.append(dict(label=label, period=period, mode=mode, repeat=repeat, phase=phase,
                        range=[first, stop], requested=count, returned=len(result.bars), complete=complete_values,
                        partial_untrusted_rows=partial_untrusted_rows,
                        max_abs_delta=max_delta, elapsed_ms=elapsed, cpu_ms=cpu_ms,
                        tracemalloc_current_bytes=current, tracemalloc_peak_bytes=peak,
                        input_rows={k: len(v) for k, v in wanted.items()}, metadata=result.metadata,
                        blocks=dm.shared_blocks.snapshot(), memory=dm.memory_budget.snapshot()))
                    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0
            finally:
                asyncio.run(dm.shutdown())
summary = []
for period in (89, 97, 101, 10007):
    for mode in ("mixed_only", "fine_only"):
        for phase in ("target_absent", "repeat_target"):
            subset = [r for r in reports if (r["period"], r["mode"], r["phase"]) == (period, mode, phase)]
            summary.append(dict(period=period, mode=mode, phase=phase, n=len(subset),
                median_ms=statistics.median(r["elapsed_ms"] for r in subset),
                max_ms=max(r["elapsed_ms"] for r in subset),
                max_tracemalloc_peak=max(r["tracemalloc_peak_bytes"] for r in subset)))
(root / "report.json").write_text(json.dumps(dict(label=label, platform=platform.platform(),
    python=sys.version, tolerance=dict(rel=1e-12, abs=1e-8), source_window=[start, end],
    inputs=inputs, limitation="local SQLite/source only; seeded records, OS cache not cold; no native or network timing",
    summary=summary, results=reports), default=str, indent=2) + "\n")
print(json.dumps(dict(label=label, query_calls=len(reports), summary=summary)))
