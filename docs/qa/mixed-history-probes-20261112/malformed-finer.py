"""Controlled default-query regression for an offline malformed finer deletion.

Run with PYTHONPATH selecting baseline or product backend and a fresh output
directory. The script imports only fixture seeding helpers from that checkout.
"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=False)
os.environ["CANDLE_DATA_DIR"] = str(root)
os.environ["KLINES_DB_PATH"] = str(root / "canonical.sqlite")
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.storage import klines_repo
from tests.test_default_mixed_history_query import seed
from tests.test_mixed_history_reader import row, MINUTE
import app.data_engine.data_manager.mixed_query as owner

config = DataManagerConfig()
config.query.auto_backfill = False
klines_repo.init_klines_storage()
dm = DataManager(config)
dm.set_storage(klines_repo.KlinesRepoAdapter())
try:
    engine = dm.query_engine
    _, stop, _ = seed(engine, count=2)
    engine.storage.upsert_bars("BTCUSDT", "3m", [{**row(99 * MINUTE, 3 * MINUTE), "close_time": 0}],
                              source="data_manager_closed", market_type="futures")
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM klines WHERE interval='3m' AND open_time=? AND market_type='futures'",
                     (99 * MINUTE,))
    result = engine.query("BTCUSDT", "89m", start_ms=89 * MINUTE, end_ms=stop - 1, limit=1,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    target_rows = engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures")
    output = dict(owner=owner.__file__, complete=result.complete, retryable=result.retryable,
                  bars=[asdict(bar) for bar in result.bars], target_rows=target_rows, metadata=result.metadata)
    (root / "receipt.json").write_text(json.dumps(output, default=str, indent=2) + "\n")
    if sys.argv[2] == "baseline":
        assert result.complete and target_rows == 1, "baseline failure was not reproduced"
    else:
        assert not result.complete and not any(bar.trusted_final for bar in result.bars) and target_rows == 0
    print(json.dumps(dict(complete=result.complete, target_rows=target_rows, owner=owner.__file__)))
finally:
    asyncio.run(dm.shutdown())
