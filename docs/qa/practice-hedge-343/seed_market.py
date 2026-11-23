"""Two controlled minute-bar inputs for the installed application's isolated QA database."""
import os
import time
from pathlib import Path

from app.data_engine.storage.klines_repo import KLINES_DB_PATH, init_klines_storage, upsert_klines

root = Path(os.environ["CANDLESCOPE_BATCH1_QA_ROOT"]).resolve()
assert KLINES_DB_PATH.resolve() == root / "profile/data/candlescope.db"
assert not KLINES_DB_PATH.exists()
init_klines_storage()
end = int(time.time() // 60) * 60_000
for symbol, price in [("BTCUSDT", 100_000), ("ETHUSDT", 3000)]:
    rows = [{
        "open_time": at, "close_time": at + 59_999, "open": price, "high": price + 1, "low": price - 1,
        "close": price, "volume": 1, "quote_volume": price, "trades": 1,
        "taker_buy_base": 0, "taker_buy_quote": 0,
    } for at in range(end - 1000 * 60_000, end, 60_000)]
    assert upsert_klines(symbol, "1m", rows, source="practice_qa_fixture", market_type="futures") == len(rows)
