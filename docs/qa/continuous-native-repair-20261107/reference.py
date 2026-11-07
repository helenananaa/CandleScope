"""Recompute from the revised canonical BARs using an empty, separate strategy store."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.continuous_source_identity import new_source_owner
from app.backtest.continuous_store import ContinuousStrategyStore
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo
from app.local_data.service import LocalDatasetService

actual_path, scratch = (Path(value).resolve(strict=True) for value in sys.argv[1:])
assert klines_repo.KLINES_DB_PATH.resolve() == scratch / "market.db"
assert not actual_path.with_name(actual_path.name + "-wal").exists()
before = hashlib.sha256(actual_path.read_bytes()).hexdigest()
with sqlite3.connect(actual_path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
    run_id, through, sequence, phase, raw_definition, wire = db.execute(
        "SELECT r.id,r.event_time_ms,r.sequence,r.phase,r.definition_json,c.wire"
        " FROM runs r JOIN checkpoints c ON c.run_id=r.id AND c.revision=r.checkpoint_revision"
    ).fetchone()
assert phase == "PAUSED"
actual = json.loads(wire)
definition = json.loads(raw_definition)
definition.pop("initial_snapshot", None)
definition["source_owner"] = new_source_owner(run_id)
exchange, market_type, symbol, interval, *semantics = definition["source_series"]
key = SeriesKey.create(symbol, interval, exchange=exchange, market_type=market_type,
                       identity=KlineSeriesIdentity(*semantics))
start = through + 1 - sequence * 60000
manager = DataManager()
manager.set_storage(klines_repo.KlinesRepoAdapter())
source = ContinuousMarketBarSource(manager, LocalDatasetService(scratch / "local-data"), key,
                                   clock_ms=lambda: through + 1)
factory = ContinuousProviderFactory()
private = ContinuousStrategyStore(scratch / "reference.sqlite3")
host = None
try:
    point = source.register(run_id, from_ms=start, definition=definition)
    ContinuousBarHost.create_run(private, run_id, definition=definition, mode="HISTORY_LIVE",
                                 data_revision=point.incarnation, event_time_ms=start - 1,
                                 provider_factory=factory, source_receipt=point)
    host = ContinuousBarHost.resume(private, run_id, factory)
    while True:
        batch = source.acquire(host, revealed_through_ms=through)
        batch.apply(host, manager)
        if batch.caught_up:
            break
    expected = private.load(run_id)
    assert expected["run"]["sequence"] == sequence
    assert expected["checkpoint"]["engine"] == actual["engine"]
    def provider_state(checkpoint):
        return {key: value for key, value in checkpoint["provider"].items() if key != "generation"}
    assert provider_state(expected["checkpoint"]) == provider_state(actual)
finally:
    if host:
        host.close()
        manager.bars.prefixes.release(host.source_receipt)
    source.close()
    private.close()
assert hashlib.sha256(actual_path.read_bytes()).hexdigest() == before
print(json.dumps({"runId": run_id, "sequence": sequence, "throughMs": through,
                  "financialStateEqual": True, "providerStateEqual": True,
                  "actualReadOnlySha256": before}))
