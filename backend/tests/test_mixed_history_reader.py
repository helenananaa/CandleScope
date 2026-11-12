"""Mixed H127 execution through the actual facade, B130 and temporary SQLite."""
import asyncio
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
import threading

import pytest

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import CoverBudgetExceeded, FixedHistorySource
from app.data_engine.storage import klines_repo
from tests.test_shared_aggregation_blocks import assert_idle

MINUTE = 60_000
FIELDS = frozenset({"open", "high", "low", "close", "volume", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote"})
TARGET = SeriesKey("BTCUSDT", "89m")


def row(opened, width):
    return dict(open_time=opened, close_time=opened + width - 1,
                open=100, high=102, low=99, close=101, volume=width // MINUTE,
                quote_volume=2 * width // MINUTE, trades=width // MINUTE,
                taker_buy_base=width // MINUTE, taker_buy_quote=2 * width // MINUTE)


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    from app.core import config as core_config
    database = tmp_path / "mixed.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    grids = []
    for minutes in (60, 15, 5, 1):
        key = SeriesKey("BTCUSDT", f"{minutes}m")
        width = minutes * MINUTE
        klines_repo.upsert_klines(key.symbol, key.interval,
            [row(opened, width) for opened in range(0, 180 * MINUTE, width)], source="backfill")
        grids.append(FixedHistorySource(key, width, 0, ((0, 180 * MINUTE),), FIELDS, "fixture/fixed-v1"))
    config = DataManagerConfig()
    config.query.auto_backfill = False
    dm = DataManager(config)
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    yield dm, tuple(grids)
    asyncio.run(dm.shutdown())
    assert_idle(dm.shared_blocks, empty=True)
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0


@pytest.mark.parametrize("page_rows", [1, 3, 7, 256])
def test_facade_exact_mixed_read_is_fenced_and_hot_spans_avoid_decoding(mixed, page_rows):
    dm, grids = mixed
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, page_rows=page_rows) as read:
        with pytest.raises(BlockRevisionChanged):
            _ = read.receipt
        with pytest.raises(BlockRevisionChanged):
            _ = read.summary
    assert read.summary.is_authoritative(0, 89 * MINUTE)
    assert read.summary.values.project(enhanced_complete=True) == dict(
        open=100, high=102, low=99, close=101, volume=89, quote_volume=178,
        trades=89, taker_buy_base=89, taker_buy_quote=178,
    )
    assert read.receipt.planned_rows == read.receipt.storage_rows == 8
    assert len(read.receipt.revisions) == len(read.receipt.qualifications) == 4
    assert {revision.series for revision in read.receipt.revisions} == {grid.series for grid in grids}
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, page_rows=page_rows) as hot:
        pass
    assert hot.receipt.storage_rows == 0 and hot.receipt.cache_hits > 0
    assert hot.summary == read.summary
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0


def test_required_fields_exclude_a_coarse_route_without_its_field_qualification(mixed):
    dm, grids = mixed
    grids = tuple(replace(grid, fields=grid.fields - {"quote_volume"}) if grid.width_ms > MINUTE else grid
                  for grid in grids)
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, required_fields=FIELDS) as read:
        pass
    assert read.receipt.planned_rows == 89
    assert read.summary.values.volume == 89
    assert len(read.receipt.revisions) == 1


@pytest.mark.parametrize("when", ["between_spans", "after_last_page"])
def test_mutation_never_publishes_a_cross_revision_mixed_result(mixed, monkeypatch, when):
    dm, grids = mixed
    original = dm.query_engine.history_blocks.read
    calls = 0
    def amend():
        klines_repo.upsert_klines("BTCUSDT", "1m", [{**row(86 * MINUTE, MINUTE), "volume": 10}],
                                  source="data_manager_amended")
    @contextmanager
    def mutating(*args, **kwargs):
        nonlocal calls
        with original(*args, **kwargs) as page:
            yield page
        calls += 1
        if when == "between_spans" and calls == 1:
            amend()
    monkeypatch.setattr(dm.query_engine.history_blocks, "read", mutating)
    read = None
    with pytest.raises(BlockRevisionChanged):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids) as read:
            if when == "after_last_page":
                amend()
    if read is not None:
        with pytest.raises(BlockRevisionChanged):
            _ = read.summary
    assert_idle(dm.shared_blocks)


@pytest.mark.parametrize("fault", ["missing", "ambiguous", "wrong_bounds"])
def test_unavailable_coarse_span_uses_only_a_finer_replacement(mixed, fault):
    dm, grids = mixed
    store = dm.query_engine.storage
    if fault == "missing":
        store.delete_bars("BTCUSDT", "1h", start_ms=0, end_ms=0)
    else:
        with klines_repo._connect() as conn:
            if fault == "ambiguous":
                conn.execute("UPDATE klines SET source='data_manager_closed' WHERE interval='1h' AND open_time=0")
            else:
                conn.execute("UPDATE klines SET close_time=close_time+1 WHERE interval='1h' AND open_time=0")
            conn.commit()
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids) as read:
        pass
    assert read.summary.values.volume == 89
    assert read.summary.is_authoritative(0, 89 * MINUTE)
    assert read.receipt.fallbacks == 1
    assert read.receipt.planned_rows == 8
    assert read.receipt.accepted_rows == 11
    assert not any(revision.series.interval == "1h" for revision in read.receipt.revisions)
    assert_idle(dm.shared_blocks)


def test_unavailable_finest_source_cannot_manufacture_a_zero_or_complete_target(mixed):
    dm, grids = mixed
    dm.query_engine.storage.delete_bars("BTCUSDT", "1m", start_ms=86 * MINUTE, end_ms=86 * MINUTE)
    with pytest.raises(BlockUnavailable):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids):
            pytest.fail("missing finest source returned a target")
    assert_idle(dm.shared_blocks)


def test_partial_multi_page_coarse_span_is_discarded_before_fine_replacement(mixed):
    dm, grids = mixed
    # Leave the first 5m row intact and remove the second. A page_rows=1
    # executor has already folded that first row when it detects the hole.
    dm.query_engine.storage.delete_bars("BTCUSDT", "5m", start_ms=80 * MINUTE, end_ms=80 * MINUTE)
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, page_rows=1) as read:
        pass
    assert read.summary.values.volume == 89  # No duplicate first-page volume.
    assert read.receipt.fallbacks == 1
    assert read.receipt.accepted_rows == 16
    assert read.receipt.storage_rows > read.receipt.accepted_rows  # Discarded reads remain counted.
    assert_idle(dm.shared_blocks)


def test_unknown_enhancement_uses_finer_proof_only_when_that_field_is_required(mixed):
    dm, grids = mixed
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET quote_volume=NULL WHERE interval='1h' AND open_time=0")
        conn.commit()
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids) as core_only:
        pass
    assert core_only.receipt.fallbacks == 0
    assert core_only.summary.values.quote_volume is None
    with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, required_fields=FIELDS) as enhanced:
        pass
    assert enhanced.receipt.fallbacks == 1
    assert enhanced.summary.values.quote_volume == 178
    assert enhanced.summary.values.volume == 89


def test_refinement_shares_the_original_planning_budget(mixed):
    dm, grids = mixed
    dm.query_engine.storage.delete_bars("BTCUSDT", "1h", start_ms=0, end_ms=0)
    # The initial eight-input plan fits exactly, but there is no work allowance
    # left for a replacement. This must stay pending/budget, not a source gap.
    with pytest.raises(CoverBudgetExceeded):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, max_positions=8):
            pytest.fail("refinement bypassed the total work budget")
    assert_idle(dm.shared_blocks)


def test_cancel_after_reads_does_not_publish_and_releases_shared_work(mixed):
    dm, grids = mixed
    cancel = threading.Event()
    with pytest.raises(CancelledError):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, cancel=cancel) as read:
            cancel.set()
    with pytest.raises(BlockRevisionChanged):
        _ = read.receipt
    assert_idle(dm.shared_blocks)


def test_rebind_during_caller_work_invalidates_the_whole_mixed_view(mixed):
    dm, grids = mixed
    with pytest.raises(BlockRevisionChanged):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids) as read:
            dm.set_storage(klines_repo.KlinesRepoAdapter())
    with pytest.raises(BlockRevisionChanged):
        _ = read.receipt
    assert_idle(dm.shared_blocks)


def test_planning_budget_exhaustion_does_not_read_or_report_a_source_gap(mixed):
    dm, grids = mixed
    before = dm.query_engine.history_blocks.snapshot()
    with pytest.raises(CoverBudgetExceeded):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids, max_positions=1):
            pytest.fail("over-budget plan returned a result")
    assert dm.query_engine.history_blocks.snapshot() == before


def test_declared_grid_cannot_override_a_canonical_source_boundary(mixed):
    dm, grids = mixed
    grids = (replace(grids[-1], width_ms=89 * MINUTE),)
    with pytest.raises(BlockUnavailable):
        with dm.read_mixed_history_blocks(TARGET, 0, 89 * MINUTE, grids):
            pytest.fail("misdeclared source boundary entered execution")
