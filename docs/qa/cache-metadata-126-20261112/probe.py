from pathlib import Path
import json
import tempfile
import os

# Isolate every ancillary config/catalog path before importing the backend.
_config_root = tempfile.TemporaryDirectory()
os.environ["CANDLE_DATA_DIR"] = _config_root.name
os.environ["KLINES_DB_PATH"] = str(Path(_config_root.name) / "initial.sqlite")
from app.core import config
from app.data_engine.storage import klines_repo
from app.data_engine.data_manager import DataManager
from app.data_engine.memory_budget import retained_size
with tempfile.TemporaryDirectory() as scratch:
    path=Path(scratch)/'probe.sqlite'
    config.KLINES_DB_PATH=klines_repo.KLINES_DB_PATH=path
    klines_repo.init_klines_storage()
    manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter())
    consumer=manager.cache.revision_consumer
    consumer.readbacks_enabled=True
    for n in range(64):
        klines_repo.upsert_klines(f'ASSET{n}USDT','1m',[dict(open_time=0,close_time=59999,
            open=1,high=2,low=.5,close=1,volume=1,quote_volume=1,trades=1,taker_buy_base=1,taker_buy_quote=1)],source='backfill')
    consumer.sync(force=True)
    report=dict(cache=manager.cache.memory_usage(),recent_entries=len(consumer._recent),
        pending_readbacks=len(consumer._readbacks),
        omitted_value_bytes=retained_size([list(consumer._recent),consumer._readbacks])[0],
        budget=manager.memory_budget.snapshot(measure_heap=True)['owners']['bar-cache'])
    print(json.dumps(report,indent=2))
