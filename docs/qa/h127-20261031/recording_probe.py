"""Replay public OKX rows through the H127 facade and an independent oracle.

Run with --source-db once to capture only public daily candles. Subsequent runs
use the checked-in fixture. Every write occurs in a new temporary database.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DAY = 86_400_000
FIELDS = ("open", "high", "low", "close", "volume", "quote_volume",
          "trades", "taker_buy_base", "taker_buy_quote")


def oracle(rows):
    # Same documented per-input precision, independent Decimal reduction.
    norm = lambda v: Decimal(str(round(float(v), 8)))
    result = dict(open=norm(rows[0]["open"]), close=norm(rows[-1]["close"]),
                  high=max(norm(r["high"]) for r in rows),
                  low=min(norm(r["low"]) for r in rows))
    for name in FIELDS[4:]:
        values = [row[name] for row in rows]
        result[name] = (None if any(v is None for v in values) else
                        sum(int(v) for v in values) if name == "trades" else
                        sum(norm(v) for v in values))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "output/h127-reproduction/recording.json")
    args = parser.parse_args()
    fixture = HERE / "public-okx-daily.json.gz"
    if args.source_db:
        conn = sqlite3.connect(f"file:{args.source_db.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        columns = ",".join(("open_time", "close_time", *FIELDS, "source"))
        rows = [dict(r) for r in conn.execute(
            f"SELECT {columns} FROM klines WHERE exchange='okx' AND market_type='futures' "
            "AND symbol='BTC-USDT-SWAP' AND interval='1d' "
            "AND provider_id='okx' AND venue='okx' AND asset_class='crypto' "
            "AND series_variant='native' AND price_adjustment='raw' "
            "AND session_variant='continuous' AND volume_semantics='base_asset' "
            "ORDER BY open_time DESC LIMIT 513")][::-1]
        conn.close()
        fixture.write_bytes(gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0))
    rows = json.loads(gzip.decompress(fixture.read_bytes()))
    start, end = rows[0]["open_time"], rows[-1]["open_time"] + DAY
    assert len(rows) == 513
    assert [r["open_time"] for r in rows] == list(range(start, end, DAY))
    assert all(r["close_time"] == r["open_time"] + DAY - 1 for r in rows)
    assert all(r["source"] == "source_snapshot_verified" for r in rows)

    with tempfile.TemporaryDirectory(prefix="h127-public-replay-") as tmp:
        os.environ["CANDLE_DATA_DIR"] = tmp
        sys.path.insert(0, str(ROOT / "backend"))
        from app.data_engine.data_manager import DataManager
        from app.data_engine.data_manager.config import DataManagerConfig
        from app.data_engine.data_manager.models import SeriesKey
        from app.data_engine.aggregation.blocks import BlockRevisionChanged
        from app.data_engine.storage import klines_repo

        klines_repo.init_klines_storage()
        klines_repo.upsert_klines("BTC-USDT-SWAP", "1d", rows,
            source="source_snapshot_verified", exchange="okx", market_type="futures")
        config = DataManagerConfig()
        config.query.auto_backfill = False
        dm = DataManager(config)
        dm.set_storage(klines_repo.KlinesRepoAdapter())
        key = SeriesKey("BTC-USDT-SWAP", "1d", exchange="okx", market_type="futures")
        report = dict(passed=False, source="public OKX recording from B130 latest-main native acceptance",
                      fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                      source_rows=len(rows), requested_range=[start, end], pages=[],
                      compared_blocks=0, compared_fields=0, max_absolute_error={})

        def read(label, **options):
            before = dm.query_engine.history_blocks.snapshot()
            started = time.perf_counter()
            with dm.read_history_blocks(key, start, end, **options) as page:
                for block in page.blocks:
                    inputs = [r for r in rows if block.key.start_ms <= r["open_time"] < block.key.end_ms]
                    assert block.summary.is_authoritative(block.key.start_ms, block.key.end_ms)
                    for field, wanted in oracle(inputs).items():
                        actual = getattr(block.summary.values, field)
                        if wanted is None or actual is None:
                            assert wanted is None and actual is None, field
                        else:
                            error = abs(float(actual) - float(wanted))
                            report["max_absolute_error"][field] = max(
                                report["max_absolute_error"].get(field, 0), error)
                            assert math.isclose(float(actual), float(wanted), rel_tol=1e-12, abs_tol=1e-8), field
                        report["compared_fields"] += 1
                    report["compared_blocks"] += 1
            receipt = page.receipt
            assert receipt.complete and not receipt.unavailable_ranges and not receipt.missing_fields
            snapshot = dm.shared_blocks.snapshot()
            assert snapshot["leases"] == snapshot["views"] == snapshot["inflight"] == 0
            assert dm.memory_budget.snapshot()["reserved_bytes"] == 0
            report["pages"].append(dict(label=label, receipt=asdict(receipt),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                candle_row_reads=dm.query_engine.history_blocks.snapshot()["storage_reads"] - before["storage_reads"]))
            return receipt

        try:
            first = read("cold-first")
            warm = read("warm-first")
            assert warm.storage_rows == 0 and warm.cache_hits == warm.blocks
            assert report["pages"][-1]["candle_row_reads"] == 0
            assert warm.revisions == first.revisions
            for direction in ("asc", "desc"):
                cursor, covered = None, []
                while True:
                    receipt = read(direction, direction=direction, cursor=cursor)
                    covered.append(receipt.page_range)
                    cursor = receipt.continuation
                    if cursor is None:
                        break
                covered.sort()
                assert covered[0][0] == start and covered[-1][1] == end
                assert all(a[1] == b[0] for a, b in zip(covered, covered[1:]))

            old = first
            for mutation in ("amendment", "delete"):
                with klines_repo._connect() as conn:
                    if mutation == "amendment":
                        conn.execute("UPDATE klines SET volume=volume+1 WHERE open_time=?", (rows[10]["open_time"],))
                    else:
                        conn.execute("DELETE FROM klines WHERE open_time=?", (rows[11]["open_time"],))
                    conn.commit()
                try:
                    with dm.read_history_blocks(key, start, end, cursor=old.continuation):
                        raise AssertionError("expired cursor was accepted")
                except BlockRevisionChanged:
                    report[f"{mutation}_expires_cursor"] = True
                with dm.read_history_blocks(key, start, end) as changed:
                    pass
                old = changed.receipt
                assert old.revisions != first.revisions
                if mutation == "delete":
                    assert not old.complete
                    assert old.unavailable_ranges == ((rows[11]["open_time"], rows[11]["open_time"] + DAY),)
                    report["delete_unavailable_ranges"] = old.unavailable_ranges
            report["reader"] = dm.query_engine.history_blocks.snapshot()
            report["blocks_before_shutdown"] = dm.shared_blocks.snapshot()
        finally:
            asyncio.run(dm.shutdown())
        report["blocks_after_shutdown"] = dm.shared_blocks.snapshot()
        report["reserved_bytes_after_shutdown"] = dm.memory_budget.snapshot()["reserved_bytes"]
        for name in ("estimated_bytes", "entries", "retired_entries", "views", "leases", "inflight"):
            assert report["blocks_after_shutdown"][name] == 0, name
        assert report["reserved_bytes_after_shutdown"] == 0
        report["passed"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("passed", "source_rows", "compared_blocks", "compared_fields")}, indent=2))


if __name__ == "__main__":
    main()
