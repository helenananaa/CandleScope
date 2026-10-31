"""B130 consumes real D126 commits and runs through production history paths."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import subprocess
import sys
import threading

import pytest

from app.data_engine.aggregation.blocks import BlockRevisionChanged
from app.data_engine.aggregation.history_blocks import aggregate_closed_history
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import acquisition_scope
from tests.test_custom_history_streaming import rows
from tests.test_shared_aggregation_blocks import assert_idle


DAY = 86400000
KEY = SeriesKey("BTCUSDT", "1d", market_type="futures")


def write(bars, *, symbol="BTCUSDT", interval="1d"):
    return klines_repo.upsert_klines(symbol, interval, [dict(
        open_time=bar.time_ms, close_time=bar.time_ms + DAY - 1,
        open=bar.open, high=bar.high, low=bar.low, close=bar.close,
        volume=bar.volume, quote_volume=bar.quote_volume, trades=bar.trades,
        taker_buy_base=bar.taker_buy_base, taker_buy_quote=bar.taker_buy_quote,
    ) for bar in bars], source="backfill", market_type="futures")


@pytest.fixture
def dm(tmp_path, monkeypatch):
    from app.core import config as core_config
    path = tmp_path / "blocks.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    write(rows(120, DAY // 1000))
    cfg = DataManagerConfig()
    cfg.query.auto_backfill = False
    cfg.query.max_limit = 11
    result = DataManager(cfg)
    result.set_storage(klines_repo.KlinesRepoAdapter())
    yield result
    asyncio.run(result.shutdown())
    assert_idle(result.shared_blocks, empty=True)


def public_query(dm, interval="4d", *, direction="range"):
    if direction == "range":
        return dm.query("BTCUSDT", interval, start_ms=0, end_ms=59 * DAY,
                        limit=11, market_type="futures", auto_backfill=False)
    return dm.query_before("BTCUSDT", interval, before_ms=60 * DAY,
                           limit=11, market_type="futures", auto_backfill=False)


def read_rows(dm):
    return [BarData.from_storage_row(r, market_type="futures") for r in
            dm.query_engine.storage.query_bars("BTCUSDT", "1d", limit=120, market_type="futures")]


def reduce(dm, source, factor, acquired_at=None):
    width = factor * DAY // 1000
    fallback = lambda bars: _aggregate_fixed_bars_to_interval(bars, width,
        source_interval_seconds=DAY // 1000)
    return aggregate_closed_history(dm.shared_blocks, source, source_key=KEY,
        source_seconds=DAY // 1000, width=width, phase_seconds=0,
        acquired_at=acquired_at, fallback=fallback), fallback(source)


def numeric_equal(actual, expected):
    assert len(actual) == len(expected)
    for a, b in zip(actual, expected):
        assert (a.time, a.is_closed) == (b.time, b.is_closed)
        for field in ("open", "high", "low", "close", "volume", "quote_volume",
                      "trades", "taker_buy_base", "taker_buy_quote"):
            av, bv = getattr(a, field), getattr(b, field)
            if av is None or bv is None:
                assert av is bv
            else:
                assert av == pytest.approx(bv, abs=1e-8, rel=1e-12)


@pytest.mark.parametrize("direction", ["range", "before"])
def test_actual_streaming_query_uses_shared_blocks_and_keeps_materialization_owner(dm, direction):
    first = public_query(dm, "2d", direction=direction)
    assert first.complete and not first.retryable and len(first.bars) == 11, first.metadata
    initial = dm.shared_blocks.snapshot()
    assert initial["builds"] > 0
    second = public_query(dm, "4d", direction=direction)
    assert second.complete and not second.retryable and len(second.bars) == 11, second.metadata
    assert dm.shared_blocks.snapshot()["hits"] > initial["hits"]
    assert second.metadata["target_materialized_written"] >= 11
    assert dm.query_engine.snapshot()["shared_aggregation_blocks"]["entries"] > 0
    assert "aggregation-blocks" in dm.memory_budget.snapshot()["owners"]
    assert_idle(dm.shared_blocks)


@pytest.mark.parametrize("factor", [2, 4, 5, 7, 32, 64])
@pytest.mark.parametrize("variant", ["closed", "unknown", "forming", "gap", "correction", "duplicate"])
def test_shared_history_matches_independent_existing_executor_contract(dm, factor, variant):
    source = read_rows(dm)
    if variant == "unknown":
        source[2] = replace(source[2], quote_volume=None, trades=None)
    elif variant == "forming":
        source[-1] = replace(source[-1], is_closed=False)
    elif variant == "gap":
        del source[3]
    elif variant == "correction":
        source[2] = replace(source[2], high=2, volume=1)
    elif variant == "duplicate":
        source.insert(3, source[2])
    for _ in range(2):
        actual, expected = reduce(dm, source, factor)
        numeric_equal(actual, expected)
        assert_idle(dm.shared_blocks)


def test_unrelated_writes_keep_same_source_block_versions_and_target_reuse(dm):
    before, _ = reduce(dm, read_rows(dm), 2)
    stats = dm.shared_blocks.snapshot()
    write(rows(2, DAY // 1000), symbol="ETHUSDT")
    after, expected = reduce(dm, read_rows(dm), 4)
    numeric_equal(after, expected)
    assert dm.shared_blocks.snapshot()["builds"] == stats["builds"]
    assert dm.shared_blocks.snapshot()["hits"] > stats["hits"]
    assert_idle(dm.shared_blocks)


@pytest.mark.parametrize("mutation", ["amend", "delete", "external"])
def test_real_commits_invalidate_all_dependent_blocks_and_old_views(dm, mutation):
    storage = dm.query_engine.storage
    original = read_rows(dm)
    reduce(dm, original, 4)
    floor = storage.revision_store.head()
    if mutation == "amend":
        write([replace(original[2], high=2, close=1, volume=1)])
    elif mutation == "external":
        subprocess.run([sys.executable, "-c",
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('UPDATE klines SET volume=1,high=2 WHERE open_time=? AND interval=?',(2*86400000,'1d')); c.commit()",
            str(klines_repo.KLINES_DB_PATH)], check=True)
    else:
        storage.delete_bars("BTCUSDT", "1d", start_ms=2 * DAY, end_ms=2 * DAY, market_type="futures")
    dm.shared_blocks.poll()
    assert dm.shared_blocks.snapshot()["entries"] == 0
    with pytest.raises(BlockRevisionChanged):
        reduce(dm, original, 4, acquired_at=floor)
    actual, expected = reduce(dm, read_rows(dm), 4)
    numeric_equal(actual, expected)
    assert_idle(dm.shared_blocks)


def test_rollback_does_not_invalidate_a_valid_block(dm):
    source = read_rows(dm)
    reduce(dm, source, 2)
    before = dm.shared_blocks.snapshot()
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET close=0")
        conn.rollback()
    reduce(dm, source, 4)
    assert dm.shared_blocks.snapshot()["invalidations"] == before["invalidations"]
    assert dm.shared_blocks.snapshot()["builds"] == before["builds"]


def test_canonical_change_during_build_returns_pending_and_never_materializes_old_value(dm, monkeypatch):
    import app.data_engine.aggregation.history_blocks as adapter
    entered, release = threading.Event(), threading.Event()
    original = adapter.summarize
    once = True
    def paused(*args, **kwargs):
        nonlocal once
        if once:
            once = False
            entered.set()
            assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "summarize", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(public_query, dm)
        assert entered.wait(5)
        dm.query_engine.storage.delete_bars("BTCUSDT", "1d", market_type="futures")
        dm.shared_blocks.poll()
        release.set()
        result = future.result(5)
    assert result.retryable and not result.bars
    assert not dm.query_engine.storage.query_bars("BTCUSDT", "4d", market_type="futures")
    assert_idle(dm.shared_blocks, empty=True)


def test_retention_pressure_falls_back_without_unfenced_output(dm):
    dm.shared_blocks.max_bytes = 100
    result = public_query(dm)
    assert result.complete and not result.retryable and len(result.bars) == 11
    assert dm.shared_blocks.snapshot()["entries"] == 0
    assert_idle(dm.shared_blocks)


def test_empty_deletion_token_and_process_restart_do_not_reuse_previous_blocks(dm):
    storage = dm.query_engine.storage
    source = read_rows(dm)
    reduce(dm, source, 2)
    storage.delete_bars("BTCUSDT", "1d", market_type="futures")
    head = storage.revision_store.head()
    storage.delete_bars("BTCUSDT", "1d", market_type="futures")
    assert storage.revision_store.head() > head
    fresh = DataManager()
    fresh.set_storage(klines_repo.KlinesRepoAdapter())
    assert fresh.shared_blocks.snapshot()["entries"] == 0
    assert not public_query(fresh).bars
    asyncio.run(fresh.shutdown())
    assert_idle(fresh.shared_blocks, empty=True)


def test_direct_pre_acquired_inputs_are_fenced_even_without_public_query_wrapper(dm):
    storage = dm.query_engine.storage
    scope = storage.revision_store.acquisition()
    source = read_rows(dm)
    write([replace(source[0], close=2)])
    from app.data_engine.storage.revisions import StaleAcquisition
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        dm.query_engine.custom_intervals._aggregate_fixed(source, 4 * DAY // 1000,
            source_interval_seconds=DAY // 1000, source_key=KEY)


def test_read_tokens_preserve_empty_deletion_and_unrelated_source_versions(dm):
    store = dm.query_engine.storage.revision_store
    values = (KEY.exchange, KEY.market_type, KEY.symbol, KEY.interval, *KEY.identity.storage_values)
    head, versions = store.read_versions((values,))
    write(rows(1, DAY // 1000), symbol="ETHUSDT")
    newer_head, newer = store.read_versions((values,))
    assert newer_head > head and newer == versions
    dm.query_engine.storage.delete_bars(KEY.symbol, KEY.interval, market_type=KEY.market_type)
    deleted_head, deleted = store.read_versions((values,))
    assert deleted[0] > versions[0] and deleted_head >= deleted[0]
    with pytest.raises(ValueError):
        store.read_versions((values,) * 33)


def test_storage_rebind_invalidates_old_lease_even_with_equal_numeric_revisions(dm):
    source = dm.shared_blocks.source
    with pytest.raises(BlockRevisionChanged):
        with dm.shared_blocks.view((KEY,)) as view:
            dm.set_storage(klines_repo.KlinesRepoAdapter())
    assert dm.shared_blocks.source.domain != source.domain
    assert_idle(dm.shared_blocks, empty=True)


def test_background_revision_owner_propagates_changes_to_blocks(dm):
    reduce(dm, read_rows(dm), 4)
    async def run():
        task = asyncio.create_task(dm._revision_loop())
        try:
            dm.query_engine.storage.delete_bars(KEY.symbol, KEY.interval, market_type=KEY.market_type)
            for _ in range(100):
                if dm.shared_blocks.snapshot()["entries"] == 0:
                    break
                await asyncio.sleep(.01)
            assert dm.shared_blocks.snapshot()["entries"] == 0
            assert dm._revision_loop_error is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(run())
    assert_idle(dm.shared_blocks, empty=True)
