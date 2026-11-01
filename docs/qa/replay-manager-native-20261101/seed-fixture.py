import json
import os
import sqlite3
from pathlib import Path

from scripts import replay_smoke_fixture as fixture

fixture.FIXTURE_SYMBOLS = (("BTCUSDT", 30000.0), ("ETHUSDT", 2000.0))
fixture._seed_klines()
with sqlite3.connect(os.environ["KLINES_DB_PATH"]) as db:
    db.execute("UPDATE klines SET source='backfill'")
    db.commit()
manifests = fixture._seed_replay_history_archive()
Path(os.environ["CANDLE_QA_FIXTURE_RECEIPT"]).write_text(json.dumps({
    "scope": "finite synthetic OHLCV and matching synthetic instrument metadata; no online source qualification",
    "start_ms": fixture.FIXTURE_START_MS,
    "interval_ms": fixture.INTERVAL_MS,
    "rows_per_symbol": fixture.FIXTURE_ROWS,
    "symbols": [symbol for symbol, _ in fixture.FIXTURE_SYMBOLS],
    "manifests": manifests,
}, indent=2, default=str))
