"""D126 contracts against real SQLite, including a separate writer process."""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from copy import deepcopy
import subprocess
import sys

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.memory_budget import MemoryBudget, MemoryBudgetExceeded, retained_size
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import acquisition_scope, StaleAcquisition
from tests.test_bar_delivery_journal import payload
from tests.test_query_cache_fencing import START, STEP, SOURCE, _row


@pytest.fixture
def storage(tmp_path, monkeypatch):
    path = tmp_path / "revision.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def write(close=100, *, symbol="BTCUSDT", interval="1m", identity=None):
    return klines_repo.upsert_klines(symbol, interval, [_row(START, close)], source=SOURCE,
                                   series_identity=identity)


def query(dm, **kwargs):
    return dm.query("BTCUSDT", "1m", start_ms=START, end_ms=START, limit=1,
                    auto_backfill=False, **kwargs)


def test_cache_only_hit_observes_commit_and_min_revision(storage):
    write()
    dm = DataManager()
    dm.set_storage(storage)
    old = query(dm)
    assert old.bars[0].close == 100
    assert query(dm).cache_hit
    write(200)
    revision = storage.revision_store.head()
    fresh = query(dm, min_revision=revision)
    assert fresh.bars[0].close == 200
    assert fresh.metadata["storage_revision"] >= revision
    assert old.bars[0].close == 100
    pending = query(dm, min_revision=revision + 1)
    assert pending.retryable and not pending.complete and not pending.bars
    assert pending.metadata["min_revision_pending"]


def test_cross_process_sql_changes_and_rollback_are_observable(storage):
    write()
    dm = DataManager()
    dm.set_storage(storage)
    query(dm)
    original = storage.revision_store.head()
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET close=300")
        conn.rollback()
    assert storage.revision_store.head() == original
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('UPDATE klines SET close=200'); c.commit()",
                    str(klines_repo.KLINES_DB_PATH)], check=True)
    current = storage.revision_store.head()
    assert current > original
    assert query(dm, min_revision=current).bars[0].close == 200
    changes = storage.revision_store.changes_since(original)["changes"]
    assert len(changes) == 1 and changes[0]["operation"] == "update"


def test_failed_adoption_does_not_advance_watermark(storage, monkeypatch):
    write()
    dm = DataManager()
    dm.set_storage(storage)
    query(dm)
    old = dm.cache.revision_consumer.revision
    write(200)
    invalidate = dm.cache.invalidate
    monkeypatch.setattr(dm.cache, "invalidate", lambda key: (_ for _ in ()).throw(OSError("injected")))
    result = query(dm, min_revision=storage.revision_store.head())
    assert result.retryable and not result.bars
    assert dm.cache.revision_consumer.revision == old
    monkeypatch.setattr(dm.cache, "invalidate", invalidate)
    assert query(dm, min_revision=storage.revision_store.head()).bars[0].close == 200


@pytest.mark.parametrize("change", ["amend", "delete", "delete-empty"])
def test_old_acquisition_cannot_write_after_newer_revision(storage, change):
    if change != "delete-empty":
        write()
    scope = storage.revision_store.acquisition()
    if change == "amend":
        write(200)
    else:
        storage.delete_bars("BTCUSDT", "1m")
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write(50)
    expected = [200] if change == "amend" else []
    assert [row["close"] for row in storage.query_bars("BTCUSDT", "1m")] == expected
    # A new explicit request has fresh permission to reacquire deleted data.
    with acquisition_scope(storage.revision_store.acquisition()):
        assert write(250) == 1


def test_scope_allows_own_batches_but_not_other_series_identity_changes(storage):
    from app.data_engine.series_identity import KlineSeriesIdentity
    scope = storage.revision_store.acquisition()
    identity = KlineSeriesIdentity.for_exchange("binance", series_variant="other")
    write(300, identity=identity)
    with acquisition_scope(scope):
        write(100)
        write(200)
        write(150, interval="5m")
    assert storage.query_bars("BTCUSDT", "1m")[0]["close"] == 200


def test_pending_receipt_cannot_resurrect_deleted_row_after_restart(storage):
    journal = storage.bar_delivery
    journal.enqueue("pending", payload())
    storage.delete_bars("BTCUSDT", "1m")
    restarted = klines_repo.KlinesRepoAdapter()
    assert restarted.bar_delivery.commit("pending")["phase"] == "rejected"
    assert restarted.query_bars("BTCUSDT", "1m") == []
    restarted.bar_delivery.enqueue("new", payload(3))
    assert restarted.bar_delivery.commit("new")["phase"] == "committed"


def test_receipt_predecessors_and_external_amendments(storage):
    journal = storage.bar_delivery
    journal.enqueue("a", payload(2))
    journal.enqueue("b", payload(3))
    assert journal.commit("a")["phase"] == "committed"
    assert journal.commit("b")["phase"] == "committed"
    journal.enqueue("c", payload(1))
    klines_repo.upsert_klines("BTCUSDT", "1m", [{**payload()["storage_row"], "close": 4}],
                              source="data_manager_exchange_closed")
    assert journal.commit("c")["phase"] == "rejected"
    assert storage.query_bars("BTCUSDT", "1m")[0]["close"] == 4


def test_persistent_job_delete_floor_survives_restart(storage):
    write()
    storage.revision_store.acquisition(owner="manual:example")
    storage.delete_bars("BTCUSDT", "1m")
    restarted = klines_repo.KlinesRepoAdapter()
    with acquisition_scope(restarted.revision_store.acquisition(owner="manual:example")):
        with pytest.raises(StaleAcquisition):
            write()
        with pytest.raises(StaleAcquisition):
            write(interval="17m")  # nonexistent derived target is fenced too


def test_base_mutations_invalidate_materialized_dependents(storage):
    write()
    klines_repo.upsert_klines("BTCUSDT", "5m", [_row(START)], source="backfill_aggregated")
    write(200)
    assert storage.query_bars("BTCUSDT", "5m") == []
    changed = storage.revision_store.changes_since(0)["changes"]
    assert {row["interval"] for row in changed} == {"1m", "5m"}


def test_duplicate_changes_are_coalesced_and_lagging_consumer_resets(storage):
    for close in range(40):
        write(close)
    assert len(storage.revision_store.changes_since(0)["changes"]) == 1
    write(symbol="ETHUSDT")
    assert storage.revision_store.changes_since(0, limit=1)["reset"]
    assert storage.revision_store.changes_since(storage.revision_store.head() + 1)["reset"]


def test_old_unversioned_backfill_notification_cannot_refill_deleted_data(storage):
    write()
    stale = [BarData.from_storage_row(row) for row in storage.query_bars("BTCUSDT", "1m")]
    dm = DataManager()
    dm.set_storage(storage)
    storage.delete_bars("BTCUSDT", "1m")
    asyncio.run(dm.on_bars_backfilled("BTCUSDT", "1m", stale))
    assert dm.cache.get_latest(SeriesKey("BTCUSDT", "1m"), 10) == []


def test_records_are_immutable_and_nested_factory_cache_is_ready(storage):
    write()
    bar = BarData.from_storage_row(storage.query_bars("BTCUSDT", "1m")[0])
    for name in ("close", "source", "quality_rank", "_prevalidated_aggregation_fields"):
        with pytest.raises(FrozenInstanceError):
            setattr(bar, name, 999)
    assert deepcopy(bar) is bar
    assert bar.with_closed_state(False).is_closed is False
    assert bar.with_source("backfill").source == "backfill"
    assert bar.normalized_aggregation_fields() == bar.normalized_aggregation_fields()


def test_budget_admission_release_protection_and_shared_heap():
    bar = BarData(60, 1., 2., 1., 2., 10.)
    budget = MemoryBudget(100)
    budget.register("history", limit_bytes=80, usage=lambda: {"estimated_bytes": 20}, roots=lambda: [bar])
    budget.register("blocks", limit_bytes=80, usage=lambda: {"estimated_bytes": 10}, roots=lambda: [bar])
    with budget.reserve("history", 60):
        with pytest.raises(MemoryBudgetExceeded):
            with budget.reserve("blocks", 11):
                pytest.fail("over budget admitted")
        with pytest.raises(RuntimeError):
            budget.unregister("history")
    assert budget.snapshot()["reserved_bytes"] == 0
    measured = budget.snapshot(measure_heap=True)
    assert sum(item["unique_retained_bytes"] for item in measured["owners"].values()) == retained_size([bar])[0]
    with pytest.raises(ValueError):
        with budget.reserve("history", -1):
            pass


def test_replace_is_atomic_and_checks_the_source_read_revision(storage, monkeypatch):
    write()
    revision = storage.revision_store.head()
    write(200)
    with pytest.raises(StaleAcquisition):
        storage.replace_bars("BTCUSDT", "1m", [_row(START, 300)], start_ms=START,
                             end_ms=START, expected_revision=revision)
    revision = storage.revision_store.head()
    upsert = klines_repo.upsert_klines
    monkeypatch.setattr(klines_repo, "upsert_klines", lambda *a, **k: (_ for _ in ()).throw(OSError("replace write")))
    with pytest.raises(OSError):
        storage.replace_bars("BTCUSDT", "1m", [_row(START, 300)], start_ms=START,
                             end_ms=START, expected_revision=revision)
    assert storage.revision_store.head() == revision
    assert storage.query_bars("BTCUSDT", "1m")[0]["close"] == 200
    monkeypatch.setattr(klines_repo, "upsert_klines", upsert)
    outcome = storage.replace_bars("BTCUSDT", "1m", [_row(START, 300)], start_ms=START,
                                  end_ms=START, expected_revision=revision)
    assert outcome["deleted"] == outcome["written"] == 1
    assert storage.query_bars("BTCUSDT", "1m")[0]["close"] == 300


def test_repeated_identical_upsert_does_not_advance_data_revision(storage):
    write()
    revision = storage.revision_store.head()
    write()
    assert storage.revision_store.head() == revision


def test_aggregator_stamps_builder_before_delete_and_does_not_resurrect(storage):
    from app.data_engine.bar_aggregator.models import BarInput, BarInputSource
    async def scenario():
        dm = DataManager()
        dm.set_storage(storage)
        dm._started = True  # enable the real bridge without network/runtime startup
        agg = dm.bar_aggregator
        agg.add_target("BTCUSDT", "1m")
        def bar(closed):
            return BarInput("BTCUSDT", "1m", START, START + STEP - 1,
                100, 200, 50, 150, 10, BarInputSource.REALTIME, closed)
        await agg.ingest_bar_input("binance", "spot", "BTCUSDT", "1m", bar(False))
        snapshot = agg.get_bucket_state("BTCUSDT", "1m", START)
        assert snapshot.acquisition_revision == 0
        snapshot.close = 999
        assert agg.get_bucket_state("BTCUSDT", "1m", START).close == 150
        storage.delete_bars("BTCUSDT", "1m")
        await agg.ingest_bar_input("binance", "spot", "BTCUSDT", "1m", bar(True))
        assert storage.query_bars("BTCUSDT", "1m") == []
        assert dm.aggregator_bridge.delivery.snapshot()["rejected"] == 1
        await dm.aggregator_bridge.delivery.stop()
        await dm.event_bus.close()
    asyncio.run(scenario())


def test_registered_deep_history_defers_without_losing_active_data(storage):
    write()
    dm = DataManager()
    dm.set_storage(storage)
    query(dm)
    dm.memory_budget.total_bytes = 100
    pending = dm.query("BTCUSDT", "1m", limit=1500, auto_backfill=False)
    assert pending.metadata["memory_budget_deferred"]
    assert pending.retryable and not pending.complete
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0
    assert dm.cache.get_latest(SeriesKey("BTCUSDT", "1m"), 1)[0].close == 100


def test_event_envelopes_and_nested_metadata_are_owned_snapshots():
    from app.data_engine.data_manager.event_bus import DataEventBus
    from app.data_engine.data_manager.models import DataEvent, DataEventType
    async def scenario():
        bus = DataEventBus()
        seen = []
        done = asyncio.Event()
        async def callback(event):
            seen.append(event)
            event.detail["nested"]["value"] = 99
            done.set()
        bus.subscribe(callback=callback)
        event = DataEvent(DataEventType.BAR_UPDATED, SeriesKey("BTCUSDT", "1m"),
                          BarData(60, 1., 2., 1., 2., 10.), detail={"nested": {"value": 1}})
        await bus.emit(event)
        await asyncio.wait_for(done.wait(), 2)
        assert event.detail["nested"]["value"] == 1
        with pytest.raises(FrozenInstanceError):
            seen[0].bar.close = 99
        await bus.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("batch", [False, True])
def test_storage_retention_does_not_delete_other_materialized_series(storage, batch):
    write()
    klines_repo.upsert_klines("BTCUSDT", "5m", [_row(START)], source="backfill_aggregated")
    method = storage.delete_oldest_batch if batch else storage.delete_oldest
    assert method("BTCUSDT", "1m", keep=0) == 1
    assert len(storage.query_bars("BTCUSDT", "5m")) == 1
    assert storage.query_bars("BTCUSDT", "1m") == []
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT mode FROM kline_mutation_context").fetchone()[0] == ""


def test_snapshot_clone_does_not_share_nested_proof_containers():
    from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
    from app.data_engine.data_manager.models import QueryResult
    original = QueryResult(metadata={"proof": {"components": [1, 2]}})
    result = CustomIntervalQueryService._clone_result(original)
    result.metadata["proof"]["components"].append(3)
    assert original.metadata["proof"]["components"] == [1, 2]


def test_builder_clone_detaches_source_revision_references():
    from app.data_engine.bar_aggregator.models import BarState
    state = BarState("BTCUSDT", "1m", START, START + STEP, 100, 100, 100, 100, 1)
    state.source_refs["component"] = {"series": "fixture", "revision": 1, "proof": {"rows": [1]}}
    clone = deepcopy(state)
    clone.source_refs["component"]["proof"]["rows"].append(2)
    clone.source_refs["component"]["revision"] = 2
    assert state.source_refs["component"] == {"series": "fixture", "revision": 1, "proof": {"rows": [1]}}


def test_restart_in_another_process_rejects_a_pre_delete_receipt(storage):
    storage.bar_delivery.enqueue("old", payload())
    storage.delete_bars("BTCUSDT", "1m")
    code = "from app.data_engine.storage import klines_repo as r; import sys; r.KLINES_DB_PATH=sys.argv[1]; print(r.KlinesRepoAdapter().bar_delivery.commit('old')['phase'])"
    completed = subprocess.run([sys.executable, "-c", code, str(klines_repo.KLINES_DB_PATH)],
                               capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == "rejected"
    assert storage.query_bars("BTCUSDT", "1m") == []


@pytest.mark.parametrize("change", ["amend", "delete"])
def test_pending_derived_receipt_checks_source_even_without_target_row(storage, change):
    write()
    item = {**payload(), "interval": "7m", "derived": True}
    storage.bar_delivery.enqueue("derived-old", item)
    if change == "amend":
        write(200)
    else:
        storage.delete_bars("BTCUSDT", "1m")
    assert storage.bar_delivery.commit("derived-old")["phase"] == "rejected"
    assert storage.query_bars("BTCUSDT", "7m") == []
    storage.bar_delivery.enqueue("derived-fresh", item)
    assert storage.bar_delivery.commit("derived-fresh")["phase"] == "committed"


def test_pending_positional_query_preserves_identity(storage):
    from app.data_engine.series_identity import KlineSeriesIdentity
    dm = DataManager()
    dm.set_storage(storage)
    identity = KlineSeriesIdentity.for_exchange("okx", provider_id="example")
    result = dm.query_engine.query("BTCUSDT", "1m", START, START, 1,
                                   "okx", "futures", identity, min_revision=1)
    assert result.retryable and result.exchange == "okx" and result.market_type == "futures"
    assert result.provider_id == "example"


def test_custom_materialization_accepts_its_own_revision(storage):
    rows = [_row(index * STEP, index + 1) for index in range(14)]
    klines_repo.upsert_klines("BTCUSDT", "1m", rows, source=SOURCE)
    dm = DataManager()
    dm.set_storage(storage)
    result = dm.query("BTCUSDT", "7m", start_ms=0, end_ms=7 * STEP, limit=2, auto_backfill=False)
    assert len(result.bars) == 2, result.metadata
    assert result.metadata["target_materialized_written"] == 2
    assert not result.metadata.get("storage_revision_conflict")
    assert len(storage.query_bars("BTCUSDT", "7m")) == 2


def test_deleted_recovery_watch_is_retired_without_source_and_can_be_renewed(storage):
    from app.data_engine.data_manager.bar_delivery import DurableBarDelivery
    series = {"symbol": "BTCUSDT", "interval": "7m"}
    journal = storage.bar_delivery
    journal.watch("old", series, 0)
    storage.delete_bars("BTCUSDT", "1m")
    async def scenario():
        delivery = DurableBarDelivery(lambda: storage, lambda record: None)
        await delivery.recover_once()
        assert journal.recovery_pending_count(delivery.owner) == 0
        assert delivery.snapshot()["recovery_error"] is None
    asyncio.run(scenario())
    journal.watch("live", series, 60_000)
    storage.delete_bars("BTCUSDT", "1m")
    journal.watch("live", series, 120_000)
    renewed = journal.recovery_watches("new-process", 240_000)[0]
    assert renewed["from_ms"] == 120_000
    assert not journal.watch_superseded(renewed)


def test_revision_background_worker_retries_executor_failure(storage, monkeypatch):
    from app.data_engine.data_manager import manager as module
    async def scenario():
        dm = DataManager()
        dm.set_storage(storage)
        attempted = asyncio.Event()
        calls = 0
        async def storage_run(fn):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("storage admission busy")
            result = fn()
            attempted.set()
            return result
        monkeypatch.setattr(module, "run_storage", storage_run)
        task = asyncio.create_task(dm._revision_loop())
        try:
            await asyncio.wait_for(attempted.wait(), 2)
            assert calls >= 2 and not task.done()
            assert dm._revision_loop_error is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_migration_keeps_preexisting_job_older_than_new_deletes(storage):
    from app.data_engine.manual_history.repository import ManualHistoryRepository
    from tests.test_manual_history_repository import _native_spec
    with klines_repo._connect() as conn:
        conn.execute("DROP TRIGGER manual_history_acquisition")
    created = ManualHistoryRepository(klines_repo.KLINES_DB_PATH).create_collection_and_job(_native_spec())
    storage.delete_bars("BTCUSDT", "1m")
    klines_repo.init_klines_storage()
    with acquisition_scope(storage.revision_store.acquisition(owner="manual:" + created.job.job_id)):
        with pytest.raises(StaleAcquisition):
            write()


def test_architecture_rejects_a_new_literal_sql_writer(tmp_path):
    from scripts.check_architecture import kline_writer_violations
    (tmp_path / "bypass.py").write_text('sql = f"UPDATE klines SET close={value}"')
    assert len(kline_writer_violations(tmp_path)) == 1


def test_durable_inflight_memory_is_counted_and_released_on_cancel(storage, monkeypatch):
    async def scenario():
        dm = DataManager()
        dm.set_storage(storage)
        delivery = dm.aggregator_bridge.delivery
        admitted = asyncio.Event()
        async def suspended(*args):
            admitted.set()
            await asyncio.Future()
        monkeypatch.setattr(delivery, "_submit", suspended)
        task = asyncio.create_task(delivery.submit("inflight", payload(), SeriesKey("BTCUSDT", "1m")))
        try:
            await asyncio.wait_for(admitted.wait(), 2)
            measured = dm.memory_budget.snapshot(measure_heap=True)["owners"]["durable-delivery"]
            assert measured["submission_payloads"] == 1
            assert measured["estimated_bytes"] > 0 and measured["unique_retained_bytes"] > 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert delivery.memory_usage()["estimated_bytes"] == 0
    asyncio.run(scenario())
