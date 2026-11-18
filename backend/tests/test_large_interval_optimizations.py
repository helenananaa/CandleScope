"""Regression tests for large-interval (e.g. 10007m) K-line loading optimizations.

Covers:
1. Per-series coalesced grid range proofs surviving >1024 global row revisions.
2. Multi-edge composed archive routing for disjoint boundary tasks in one month.
3. One-pass budget-aware mixed chunk splitting when near-tail 1m rows exceed 16,384.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import config as core_config
from app.data_engine.aggregation.source_window import SourceWindowVersion
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus, BackfillTask
from app.data_engine.backfill.source_router import (
    HistoricalSourceRouter,
    _bounded_usdm_archive_candidates,
    _task_runs,
)
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamDescriptor, StreamType
from app.data_engine.storage import kline_sources, klines_repo
from app.data_engine.storage.gap_ledger import GapLedger
from app.data_engine.storage.mixed_history_fence import (
    MixedComputation,
    MixedTarget,
)
from app.data_engine.storage.native_history_fence import fingerprint
from app.data_engine.storage.range_changes import check_store_range
from app.data_engine.storage.revisions import (
    BLOCK_CHANGE_WINDOW,
    StaleAcquisition,
    acquisition_scope,
    block_change_receipts,
    current_revision,
    guarded_write,
    series_values,
)
from app.data_engine.storage.warmup_revision_fence import make_warmup_view
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from app.exchanges.rate_limits import RateLimitManager
from tests.test_history_archive_routing import (
    _ArchiveHttpMany,
    _RestTransport,
    _archive_payload,
    _ms,
)
from tests.test_mixed_backfill_composed_admission import CONTRACT, WIDTH, ClosingUpstream, options
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import MINUTE, row


UTC = timezone.utc
HOUR = 60 * MINUTE
DAY = 1440 * MINUTE


def _storage_for(tmp_path, monkeypatch, name: str = "opt.sqlite"):
    database = tmp_path / name
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter(), database


def test_per_series_range_spans_prove_non_overlap_beyond_block_window(tmp_path, monkeypatch):
    storage, _ = _storage_for(tmp_path, monkeypatch, "range_proof.sqlite")
    store = storage.revision_store
    key_1m = series_values("BTCUSDT", "1m", "binance", "futures")
    key_5m = series_values("BTCUSDT", "5m", "binance", "futures")

    storage.upsert_bars("BTCUSDT", "1m", [row(0, MINUTE)], source="backfill", market_type="futures")
    base_rev = store.head()

    # Commit 1,500 disjoint 1m bars in one guarded transaction so the global
    # revision gap exceeds BLOCK_CHANGE_WINDOW (1024), while kline_series_range_changes
    # coalesces the contiguous grid into a single span.
    far_start = 50_000 * MINUTE
    storage.upsert_bars(
        "BTCUSDT",
        "1m",
        [row(far_start + idx * MINUTE, MINUTE) for idx in range(1_500)],
        source="backfill",
        market_type="futures",
    )
    head_rev = store.head()
    assert head_rev - base_rev == 1_500 > BLOCK_CHANGE_WINDOW

    with closing(store.connect()) as conn:
        assert block_change_receipts(conn, base_rev, head_rev) == ()
        span_count = conn.execute(
            "SELECT COUNT(*) FROM kline_series_range_changes WHERE symbol='BTCUSDT' AND interval='1m' "
            "AND last_revision > ?",
            (base_rev,),
        ).fetchone()[0]
        assert span_count == 1

    # Non-overlapping range succeeds without range_receipt_suffix_unavailable.
    check_store_range(store, (key_1m,), 0, 100 * MINUTE, base_rev)

    # Overlapping range still raises canonical_range_changed.
    with pytest.raises(StaleAcquisition) as exc_info:
        check_store_range(store, (key_1m,), far_start + 10 * MINUTE, far_start + 20 * MINUTE, base_rev)
    assert exc_info.value.fence_details["reason"] == "canonical_range_changed"

    # WarmupView succeeds across >1024 unrelated/disjoint revisions AND subsequent owned commits.
    scope = store.acquisition(revision=base_rev)
    scope.revision = base_rev
    windows = [
        BackfillTask(
            "BTCUSDT",
            "1m",
            0,
            4 * MINUTE,
            exchange="binance",
            market_type="futures",
            metadata={"custom_interval": "5m"},
        )
    ]
    scope.warmup_view = make_warmup_view(windows)
    assert scope.warmup_view is not None
    with acquisition_scope(scope):
        storage.upsert_bars(
            "BTCUSDT",
            "1m",
            [row(idx * MINUTE, MINUTE) for idx in range(5)],
            source="backfill",
            market_type="futures",
        )
        storage.upsert_bars(
            "BTCUSDT",
            "5m",
            [row(0, 5 * MINUTE)],
            source="backfill_aggregated",
            market_type="futures",
        )

    # MixedComputation check succeeds across >1024 disjoint tail writes and rejects overlap.
    mixed_scope = store.acquisition()
    with closing(store.connect()) as conn:
        target = MixedTarget(
            key=key_5m,
            dependencies=(key_1m,),
            start=100 * MINUTE,
            end=100 * MINUTE,
            duration=5 * MINUTE,
            digest=fingerprint(conn, key_5m, 100 * MINUTE, 100 * MINUTE),
        )
        comp = MixedComputation(target=target, revision=current_revision(conn))

    storage.upsert_bars(
        "BTCUSDT",
        "1m",
        [row(80_000 * MINUTE + idx * MINUTE, MINUTE) for idx in range(1_200)],
        source="backfill",
        market_type="futures",
    )
    with closing(store.connect()) as conn:
        comp.check(conn, mixed_scope)

    storage.upsert_bars(
        "BTCUSDT",
        "1m",
        [row(102 * MINUTE, MINUTE)],
        source="backfill",
        market_type="futures",
    )
    with closing(store.connect()) as conn:
        with pytest.raises(StaleAcquisition) as mixed_exc:
            comp.check(conn, mixed_scope)
    assert mixed_exc.value.fence_details["reason"] == "mixed_overlapping_change"


def test_source_window_canonical_current_survives_disjoint_bulk_commits(tmp_path, monkeypatch):
    storage, _ = _storage_for(tmp_path, monkeypatch, "source_window.sqlite")
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", exchange="binance", market_type="futures")
    event = MarketEvent(
        event_type=StreamType.KLINE,
        symbol="BTCUSDT",
        exchange="binance",
        event_time_ms=MINUTE,
        received_at_ms=MINUTE,
        source=DataSource.WEBSOCKET,
        market_type="futures",
        data={
            "open_time": 0,
            "close_time": MINUTE - 1,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "quote_volume": 100.0,
            "trades": 1,
            "taker_buy_base": 0.5,
            "taker_buy_quote": 50.0,
            "is_closed": True,
            "source_candle": {
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "1",
                "quoteVolume": "100",
                "takerBuyBaseVolume": "0.5",
                "takerBuyQuoteVolume": "50",
                "closeTime": MINUTE - 1,
                "trades": 1,
                "eventTime": MINUTE,
            },
        },
    )
    kline_sources.record(event, descriptor)
    matching_row = {
        "open_time": 0,
        "close_time": MINUTE - 1,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1.0,
        "quote_volume": 100.0,
        "trades": 1,
        "taker_buy_base": 0.5,
        "taker_buy_quote": 50.0,
    }
    assert storage.upsert_bars("BTCUSDT", "1m", [matching_row], source="backfill", market_type="futures") == 1
    version = kline_sources.capture_source_window(kline_sources.series(descriptor), 0, 5 * MINUTE, MINUTE)
    assert isinstance(version, SourceWindowVersion)
    assert version.acquisition_revision >= 1

    # Disjoint 1,300-row bulk write evicts kline_block_changes but preserves source_window_current.
    assert storage.upsert_bars(
        "BTCUSDT",
        "1m",
        [row(20_000 * MINUTE + idx * MINUTE, MINUTE) for idx in range(1_300)],
        source="backfill",
        market_type="futures",
    ) == 1_300
    with closing(klines_repo._connect()) as conn:
        assert kline_sources.source_window_current(conn, version) is True

    # Overlapping canonical deletion inside [0, 5 * MINUTE) invalidates source_window_current.
    assert klines_repo.delete_klines("BTCUSDT", "1m", 0, 0, exchange="binance", market_type="futures") == 1
    with closing(klines_repo._connect()) as conn:
        assert kline_sources.source_window_current(conn, version) is False


def test_composed_10007m_multi_edge_tasks_group_into_monthly_archives(tmp_path, monkeypatch):
    class _ArchivePlugin:
        @staticmethod
        def history_archive_provider(_config=None):
            return BinanceKlineArchiveProvider()

    class _ArchiveRegistry:
        @staticmethod
        def get_plugin(exchange: str):
            assert exchange == "binance"
            return _ArchivePlugin()

    monkeypatch.setattr(
        "app.data_engine.backfill.fetcher.get_shared_rate_limit_manager",
        lambda: RateLimitManager(),
    )
    monkeypatch.setattr(
        "app.data_engine.backfill.source_router.get_exchange_registry",
        lambda: _ArchiveRegistry(),
    )

    jan_start = _ms(datetime(2024, 1, 1, tzinfo=UTC))
    jan_end = _ms(datetime(2024, 2, 1, tzinfo=UTC)) - 1
    now_ms = _ms(datetime(2024, 4, 1, tzinfo=UTC))
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: now_ms / 1_000)

    # Four disjoint 20-bar 1h boundary windows in Jan 2024 (~7 days apart, matching 10007m seams).
    offsets_hours = (10, 178, 346, 514)
    tasks_1h = [
        BackfillTask(
            symbol="BTCUSDT",
            interval="1h",
            start_ms=jan_start + h * HOUR,
            end_ms=jan_start + (h + 19) * HOUR,
            estimated_bars=20,
            exchange="binance",
            market_type="futures",
            metadata={
                "requester": "klines_history",
                "reason": "initial_history",
                "custom_interval": "10007m",
                "history_composition_contract": CONTRACT,
                "mixed_fetch_windows": [(jan_start + h * HOUR, jan_start + (h + 19) * HOUR)],
                "ledger_range": {"start_ms": jan_start + 10 * HOUR, "end_ms": jan_start + 533 * HOUR},
            },
        )
        for h in offsets_hours
    ]
    runs = _task_runs(tasks_1h, "1h")
    assert len(runs) == 1 and len(runs[0]) == 4

    provider = BinanceKlineArchiveProvider()
    month_ref = next(
        ref
        for ref in provider.plan_objects(
            market_type="futures",
            symbol="BTCUSDT",
            interval="1h",
            start_ms=jan_start,
            end_ms=jan_end,
            now_ms=now_ms,
        )
        if ref.granularity.value == "monthly" and ref.period == "2024-01"
    )
    assert _bounded_usdm_archive_candidates([month_ref], tasks_1h, "1h") == [month_ref]

    # Pathological 4 single-bar 1h edges (needed=4) still reject full 744-bar month.
    tiny_edges = [
        BackfillTask(
            symbol="BTCUSDT",
            interval="1h",
            start_ms=jan_start + h * HOUR,
            end_ms=jan_start + h * HOUR,
            estimated_bars=1,
            exchange="binance",
            market_type="futures",
            metadata={
                "custom_interval": "10007m",
                "history_composition_contract": CONTRACT,
                "mixed_fetch_windows": [(jan_start + h * HOUR, jan_start + h * HOUR)],
            },
        )
        for h in offsets_hours
    ]
    assert _bounded_usdm_archive_candidates([month_ref], tiny_edges, "1h") == []

    # Verify full HistoricalFetcher + HistoricalSourceRouter execution downloads the monthly ZIP once
    # and issues zero REST requests when archive is ready.
    async def _run():
        cfg = BackfillConfig(
            history_archive_enabled=True,
            history_archive_cache_dir=str(tmp_path),
            history_archive_cache_max_bytes=10_000_000,
            history_archive_min_rest_pages=2,
            fetch_rate_limit_delay=0,
            fetch_batch_size=1_500,
            fetch_max_retries=0,
            fetch_concurrency=2,
            reconcile_generate_custom=False,
            reconcile_enable_cache_push=False,
        )
        http = _ArchiveHttpMany({
            month_ref.expected_filename: _archive_payload(month_ref, 31 * 24, interval_ms=HOUR),
        })
        router = HistoricalSourceRouter(
            cfg,
            cache=HistoricalArchiveCache(tmp_path, max_bytes=cfg.history_archive_cache_max_bytes),
            http=http,
        )
        router._foreground_archive_ready = True
        rest = _RestTransport([])
        fetcher = HistoricalFetcher(cfg, rest, IngestionConfig(), source_router=router)
        try:
            results = await fetcher.fetch(tasks_1h)
            assert all(res.status is BackfillStatus.COMPLETED for res in results)
            assert len(http.downloads) == 1
            assert rest.requests == []
            assert sum(res.metadata.get("archive_object_count", 0) for res in results) == 1
        finally:
            await router.close()

    asyncio.run(_run())


def test_near_tail_1m_bars_split_16_bar_10007m_chunk_in_one_pass(tmp_path, monkeypatch):
    database = tmp_path / "split_one_pass.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()

    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())

    # Pre-populate the last two 10007m buckets (bars 14 and 15) with 1m bars (20,014 > 16,384 rows).
    # Previously:
    #   1) choose_cold_sources got max_rows=0 -> failed with source_row_budget
    #   2) scheduler bisected 4 times serially: 16 -> 8+8 -> 4+4 -> 2+2 -> 1+1.
    # Now:
    #   build_mixed_backfill_plan computes exact per-target refined rows and partitions in ONE pass!
    tail_start = 14 * WIDTH
    manager.query_engine.storage.upsert_bars(
        "BTCUSDT",
        "1m",
        [row(opened, MINUTE) for opened in range(tail_start, 16 * WIDTH, MINUTE)],
        source="backfill",
        market_type="futures",
    )
    manager.query_engine._cache.revision_consumer.sync(force=True)

    engine = engine_for(manager.query_engine)
    upstream = ClosingUpstream()
    engine._fetcher = upstream

    async def _run():
        coordinator = BackfillCoordinator(
            storage=manager.query_engine.storage,
            bars_backfilled=manager.on_bars_backfilled,
            emit_event=manager.emit_event,
            source_available=manager.source_storage_available,
            engine=engine,
            loop=asyncio.get_running_loop(),
            gap_ledger=GapLedger(database),
            max_concurrency=1,
            chunk_bars=1_000,
            max_retries=1,
        )
        manager.set_backfill_trigger(coordinator.trigger)
        try:
            initial = manager.query_composed(
                "BTCUSDT",
                "10007m",
                **{
                    **options(manager),
                    "end_ms": 16 * WIDTH - 1,
                    "limit": 16,
                    "auto_backfill": True,
                    "backfill_reason": "initial_history",
                    "backfill_requester": "klines_history",
                    "backfill_metadata": {"history_calendar_id": "crypto.24x7.utc"},
                },
            )
            assert not initial.complete and initial.backfill_triggered
            outcome = await asyncio.wait_for(
                coordinator.wait_for_request(initial.metadata["backfill_request_ids"][0]),
                timeout=30,
            )
            assert outcome.verified_contiguous is True and outcome.remaining_missing_bars == 0, outcome.error
            assert coordinator._scheduler.mixed_chunk_refinements == 1

            receipts = coordinator.snapshot()["recent_chunks"]
            refined = [r for r in receipts if r["status"] == "refined"]
            completed = [r for r in receipts if r["status"] == "completed"]
            assert len(refined) == 1
            # Expect 2 or 3 clean partitions (e.g. [0..14*WIDTH] + [15*WIDTH] or [0..13*WIDTH] + [14*WIDTH] + [15*WIDTH]),
            # never 4 cascading bisections!
            assert 2 <= len(completed) <= 3

            final = manager.query_composed(
                "BTCUSDT",
                "10007m",
                **{**options(manager), "end_ms": 16 * WIDTH - 1, "limit": 16},
            )
            assert final.complete and len(final.bars) == 16
            assert all(bar.trusted_final and bar.volume == bar.trades == 10007 for bar in final.bars)
        finally:
            await coordinator.shutdown()
            await engine.close()
            await manager.shutdown()

    asyncio.run(_run())
