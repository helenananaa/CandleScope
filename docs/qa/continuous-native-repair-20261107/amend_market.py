"""Inject one controlled REST correction into a stopped copy of the QA market database."""
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import time

from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamDescriptor, StreamType
from app.data_engine.storage import kline_sources, klines_repo
from app.data_engine.storage.revisions import current_revision

profile = Path(sys.argv[1]).resolve(strict=True)
assert (profile.parent / "controlled-repair-copy.json").is_file()
market = profile / "data/market.db"
assert klines_repo.KLINES_DB_PATH.resolve() == market
assert not market.with_name("market.db-wal").exists()
strategy = profile / "data/continuous-strategy.sqlite3"
with sqlite3.connect(strategy.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
    run_id, phase, sequence, definition = db.execute(
        "SELECT id,phase,sequence,definition_json FROM runs"
    ).fetchone()
assert phase == "LIVE" and sequence >= 20
definition = json.loads(definition)
opened = definition["initial_snapshot"]["from_ms"] + 12 * 60000
assert opened <= definition["initial_snapshot"]["through_ms"]
descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", exchange="binance", market_type="spot")
old = kline_sources.latest(descriptor, opened)
assert old["data"]["is_closed"]
data = old["data"].copy()
envelope = old["envelope"].copy()
close = (Decimal(envelope["close"]) * Decimal("1.002")).quantize(Decimal("0.01"))
high = max(Decimal(envelope["high"]), close)
envelope.update(close=str(close), high=str(high))
envelope["raw"] = json.dumps({"fixture": "isolated controlled revision", "openTime": opened,
                              "close": str(close), "high": str(high)})
data.update(close=float(close), high=float(high), source_candle=envelope)
stamp = int(time.time() * 1000)
event = MarketEvent(StreamType.KLINE, "BTCUSDT", "binance", stamp, stamp, DataSource.HTTP, data)
with sqlite3.connect(market.as_uri() + "?mode=ro", uri=True) as db:
    revision_before = current_revision(db)
recorded = kline_sources.record(event, descriptor, rest_watermark=kline_sources.rest_watermark())
assert recorded["status"] == "selected" and recorded["ref"]["revision"] == old["revision"] + 1
fields = ("open_time", "close_time", "open", "high", "low", "close", "volume",
          "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
row = {field: data.get(field) for field in fields}
row["source_refs"] = [recorded["ref"]]
assert klines_repo.upsert_klines("BTCUSDT", "1m", [row], source="http", market_type="spot") == 1
with sqlite3.connect(market.as_uri() + "?mode=ro", uri=True) as db:
    revision_after = current_revision(db)
    stored = db.execute(
        "SELECT close,source FROM klines WHERE symbol=? AND interval=? AND market_type=? AND open_time=?",
        ("BTCUSDT", "1m", "spot", opened),
    ).fetchone()
assert revision_after > revision_before and stored == (float(close), "source_snapshot_verified")
print(json.dumps({"scope": "single controlled REST source correction in a cold QA copy", "runId": run_id,
                  "openMs": opened, "oldClose": old["data"]["close"], "newClose": float(close),
                  "storageRevisionBefore": revision_before, "storageRevisionAfter": revision_after,
                  "sourceRevisionBefore": old["revision"], "sourceRevisionAfter": recorded["ref"]["revision"]}))
