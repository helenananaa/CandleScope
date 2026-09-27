"""Extend an isolated replay_smoke_fixture with aligned synthetic chart archives.

These are deterministic test bars, never exchange-native market evidence.
Run after replay_smoke_fixture has started, before creating the workspace run.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from app.replay.catalog import ReplaySeriesIdentity
from app.replay.history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch


def seed(root: Path) -> list[dict[str, object]]:
    database = root / "candlescope.db"
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    writer = ReplayHistoryArchiveWriter(root / "replay-history")
    evidence = []
    try:
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            rows = [dict(row) for row in connection.execute(
                "SELECT open_time, close_time, open, high, low, close, volume, "
                "quote_volume, trades, taker_buy_base, taker_buy_quote, source "
                "FROM klines WHERE symbol=? AND market_type='spot' AND interval='1m' "
                "ORDER BY open_time", (symbol,),
            )]
            if not rows or len(rows) > 100_000:
                raise ValueError("expected a bounded isolated smoke fixture")
            first = rows[0]
            start = first["open_time"] // 900_000 * 900_000
            prefix = [dict(first, open_time=time, close_time=time + 59_999)
                      for time in range(start, first["open_time"], 60_000)]
            rows = prefix + rows
            # All three archives start on one complete 15-minute boundary.
            rows = rows[:len(rows) // 15 * 15]
            for minutes in (1, 5, 15):
                buckets = defaultdict(list)
                for row in rows:
                    buckets[row["open_time"] // (minutes * 60_000) * minutes * 60_000].append(row)
                bars = []
                for timestamp, bucket in sorted(buckets.items()):
                    bar = dict(bucket[0], open_time=timestamp,
                               close_time=timestamp + minutes * 60_000 - 1,
                               high=max(row["high"] for row in bucket),
                               low=min(row["low"] for row in bucket), close=bucket[-1]["close"])
                    for field in ("volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote"):
                        bar[field] = sum(row[field] for row in bucket)
                    bars.append(bar)
                digest = "sha256:" + hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest()
                manifest = writer.import_batches(ReplaySeriesIdentity("binance", "spot", symbol), f"{minutes}m", [
                    ReplayHistoryImportBatch(rows=bars, source_provider="synthetic-workspace-qa-v1",
                        source_object_key=f"{symbol}/{minutes}m", source_period="bounded-synthetic-test",
                        source_content_sha256=digest, source_row_count=len(bars)),
                ], merge_current=False, listing_boundary_source="verified_fixture_first_bar")
                evidence.append({"symbol": symbol, "interval": f"{minutes}m", "rows": len(bars),
                                 "catalog_epoch": manifest.catalog_epoch, "synthetic": True})
    finally:
        connection.close()
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seed(args.qa_root.resolve()), indent=2))
