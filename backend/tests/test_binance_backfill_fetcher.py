from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import (
    BackfillStatus,
    BackfillTask,
    GapInfo,
    GapType,
)
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType, TransportRequest


class _FakeBinanceTransport:
    def __init__(self, bars: list[list[object]], page_cap: int = 1_000) -> None:
        self._bars = list(bars)
        self._page_cap = page_cap
        self.requests: list[TransportRequest] = []

    async def http_fetch(self, req: TransportRequest) -> list[RawMessage]:
        self.requests.append(req)
        start_ms = req.start_ms if req.start_ms is not None else -1
        end_ms = req.end_ms if req.end_ms is not None else 2**63 - 1
        limit = min(int(req.limit or 1), self._page_cap)
        eligible = [
            row for row in self._bars
            if start_ms <= int(row[0]) <= end_ms
        ]
        eligible.sort(key=lambda row: int(row[0]))
        return [
            RawMessage(
                payload=row,
                source=DataSource.HTTP,
                stream_type=StreamType.KLINE,
                received_at_ms=end_ms,
                endpoint="https://api.binance.com",
            )
            for row in eligible[:limit]
        ]


def _make_binance_rows(count: int, interval_ms: int) -> list[list[object]]:
    return [
        [
            idx * interval_ms,
            "100",
            "110",
            "90",
            "105",
            "1.5",
            (idx + 1) * interval_ms - 1,
            "157.5",
            10,
            "0.75",
            "78.75",
            "0",
        ]
        for idx in range(count)
    ]


def test_binance_backfill_advances_start_time_past_first_page() -> None:
    interval_ms = 60_000
    total_bars = 2_050
    transport = _FakeBinanceTransport(
        _make_binance_rows(total_bars, interval_ms),
        page_cap=1_000,
    )
    fetcher = HistoricalFetcher(
        BackfillConfig(
            fetch_batch_size=1_000,
            fetch_rate_limit_delay=0,
            fetch_concurrency=1,
        ),
        transport,
        IngestionConfig(),
    )
    task = BackfillTask(
        symbol="BTCUSDT",
        interval="1m",
        start_ms=0,
        end_ms=(total_bars - 1) * interval_ms,
        estimated_bars=total_bars,
        exchange="binance",
        market_type="spot",
    )

    results = asyncio.run(fetcher.fetch([task]))

    assert len(results) == 1
    assert results[0].bars_count == total_bars
    assert len(transport.requests) == 3
    assert [request.start_ms for request in transport.requests] == [
        0,
        999 * interval_ms + 1,
        1_999 * interval_ms + 1,
    ]
    assert [bar.open_time for bar in results[0].bars] == [
        idx * interval_ms for idx in range(total_bars)
    ]


def test_91m_engine_fetches_page_bounded_components_and_persists_target() -> None:
    class _Detector:
        async def detect(self, **kwargs):
            assert kwargs["intervals"] == ["91m"]
            return [GapInfo(
                symbol="BTCUSDT",
                interval="91m",
                gap_type=GapType.INTERIOR,
                start_ms=0,
                end_ms=14 * 91 * 60_000,
                missing_bars=15,
                exchange="binance",
                market_type="spot",
            )]

    class _MemoryStorage:
        def __init__(self) -> None:
            self.rows: dict[tuple[str, str, str, str], dict[int, dict]] = {}

        async def get_existing_open_times(
            self,
            symbol,
            interval,
            start_ms,
            end_ms,
            *,
            exchange,
            market_type,
        ):
            series = self.rows.get(
                (exchange, market_type, symbol, interval),
                {},
            )
            return {
                open_time for open_time in series
                if start_ms <= open_time <= end_ms
            }

        async def query_time_range(self, symbol, interval, start_ms, end_ms, *, exchange, market_type):
            series = self.rows.get((exchange, market_type, symbol, interval), {})
            return [series[at] for at in sorted(series) if start_ms <= at <= end_ms]

        async def upsert_bars(
            self,
            symbol,
            interval,
            rows,
            *,
            source,
            exchange,
            market_type,
        ):
            series = self.rows.setdefault(
                (exchange, market_type, symbol, interval),
                {},
            )
            for row in rows:
                stored = dict(row)
                stored["source"] = source
                series[int(stored["open_time"])] = stored
            return len(rows)

    async def _run() -> None:
        interval_ms = 60_000
        component_count = 15 * 91
        transport = _FakeBinanceTransport(
            _make_binance_rows(component_count, interval_ms),
        )
        storage = _MemoryStorage()
        engine = BackfillEngine(
            config=BackfillConfig(
                fetch_batch_size=1_000,
                fetch_rate_limit_delay=0,
                fetch_concurrency=1,
                reconcile_generate_custom=True,
                reconcile_enable_cache_push=False,
                publish_mode="log",
            ),
            storage=storage,
            transport=transport,
            ingestion_config=IngestionConfig(),
        )
        engine._detector = _Detector()

        async def _no_rate_limit() -> None:
            return None

        engine.fetcher.set_rate_limiter(_no_rate_limit)
        report = await engine.run(
            symbol="BTCUSDT",
            intervals=["91m"],
            range_start_ms=0,
            range_end_ms=14 * 91 * interval_ms,
            exchange="binance",
            market_type="spot",
        )

        one_minute = storage.rows[
            ("binance", "spot", "BTCUSDT", "1m")
        ]
        ninety_one_minute = storage.rows[
            ("binance", "spot", "BTCUSDT", "91m")
        ]
        assert report.status is BackfillStatus.COMPLETED
        assert report.plan is not None
        assert [task.estimated_bars for task in report.plan.tasks] == [1_000, 365]
        assert len(transport.requests) == 2
        assert [request.start_ms for request in transport.requests] == [
            0,
            1_000 * interval_ms,
        ]
        assert len(one_minute) == component_count
        assert len(ninety_one_minute) == 15
        assert sorted(ninety_one_minute) == [
            index * 91 * interval_ms for index in range(15)
        ]
        assert report.reconcile_result is not None
        assert report.reconcile_result.bars_written == component_count
        assert report.reconcile_result.custom_bars_written == 15
        assert {
            written.interval for written in report.reconcile_result.written_ranges
        } == {"1m", "91m"}

    asyncio.run(_run())


def test_server_clock_and_kline_pages_share_weight_without_legacy_deferral() -> None:
    """Three source pages need a server clock observation before each fetch.

    A clock falling back to the one-token legacy bucket discards all progress
    at page two, even though the documented IP weight budget is available.
    """
    from app.exchanges.ccxt_ext.admission import PublicCcxtAdmissionMixin
    from app.exchanges.public_admission import PublicDemand, public_demand
    from app.exchanges.rate_limits import RateLimitManager

    class PhysicalResponse:
        async def fetch(self, url, method="GET", headers=None, body=None):
            return []

    class Client(PublicCcxtAdmissionMixin, PhysicalResponse):
        id = "binance"
        _candlescope_public_market_type = "spot"

    class AdmittedTransport(_FakeBinanceTransport):
        def manages_physical_admission(self, req):
            return True

        async def http_fetch(self, req):
            await client.fetch("https://api.binance.com/api/v3/time")
            await client.fetch("https://api.binance.com/api/v3/klines?limit=1000")
            return await super().http_fetch(req)

    async def run():
        nonlocal client
        client = Client()
        client._candlescope_rate_limit_manager = RateLimitManager()
        transport = AdmittedTransport(_make_binance_rows(2321, 60000))
        fetcher = HistoricalFetcher(BackfillConfig(fetch_concurrency=1), transport, IngestionConfig())
        fetcher._rate_limit_manager = client._candlescope_rate_limit_manager
        with public_demand(PublicDemand(defer=True)):
            results = await fetcher.fetch([BackfillTask(
                "BTCUSDT", "1m", 0, 2320 * 60000, estimated_bars=2321,
            )])
        assert results[0].bars_count == 2321
        assert len(transport.requests) == 3
        assert set(client._candlescope_rate_limit_manager.snapshot()) == {"binance:spot:request_weight:ip"}

    client = None
    asyncio.run(run())


@pytest.mark.parametrize("defer_second", [False, True])
def test_custom_tail_warmup_fetches_only_unqualified_components(tmp_path, monkeypatch, defer_second):
    """A new subscription can rebuild missing targets from both local and repaired input."""
    from app.data_engine.storage import klines_repo
    from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred

    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "warmup.sqlite")
    klines_repo.init_klines_storage()

    minute = 60_000
    rows = _make_binance_rows(10, minute)
    transport = _FakeBinanceTransport(rows)
    admitted_fetch = transport.http_fetch

    async def limit_one_run(req):
        if req.start_ms == 7 * minute:
            raise RateLimitDeferred(RateLimitAdmission(
                allowed=False, bucket_key="test", cost=1, reason="budget", retry_after_seconds=1,
                retry_at_monotonic=None, retry_at_ms=None, rule_name="test",
            ))
        return await admitted_fetch(req)

    async def no_rate_limit():
        pass

    storage = klines_repo.AsyncKlinesRepoAdapter()
    config = BackfillConfig(
        history_archive_enabled=False, fetch_rate_limit_delay=0, reconcile_enable_cache_push=False,
    )
    engine = BackfillEngine(config, storage, transport, ingestion_config=IngestionConfig())
    engine.fetcher.set_rate_limiter(no_rate_limit)
    demand = {"requester": "warm_start_custom_tail", "history_calendar_id": "crypto.24x7.utc"}

    def storage_row(index):
        return {
            "open_time": index * minute, "close_time": (index + 1) * minute - 1,
            "open": 100, "high": 110, "low": 90, "close": 105, "volume": 2,
            "quote_volume": 210, "trades": 10, "taker_buy_base": 1, "taker_buy_quote": 105,
        }

    async def run():
        try:
            # Complete local targets surround both a missing source slot and
            # a physically present but provisional slot.
            trusted = [storage_row(i) for i in (0, 1, 2, 4, 5, 6, 8, 9)]
            assert await storage.upsert_bars("BTCUSDT", "1m", trusted, source="backfill") == len(trusted)
            assert await storage.upsert_bars("BTCUSDT", "1m", [storage_row(7)], source="manual") == 1

            local = await engine.run("BTCUSDT", ["2m"], 0, 0, metadata=demand)
            assert transport.requests == []
            assert local.status is BackfillStatus.COMPLETED
            assert local.reconcile_result.custom_bars_written == 1
            # Keep a materialized target between the two gaps so the planner
            # emits two decompositions for the same derived interval.
            separated = await engine.run("BTCUSDT", ["2m"], 4 * minute, 4 * minute, metadata=demand)
            assert separated.reconcile_result.custom_bars_written == 1
            assert transport.requests == []

            if defer_second:
                transport.http_fetch = limit_one_run
                with pytest.raises(RateLimitDeferred):
                    await engine.run("BTCUSDT", ["2m"], 2 * minute, 8 * minute, metadata=demand)
                [first] = await storage.query_time_range("BTCUSDT", "1m", 3 * minute, 3 * minute)
                assert first["source"] == "backfill"
                existing = await storage.query_time_range("BTCUSDT", "2m", 2 * minute, 8 * minute)
                assert [row["open_time"] for row in existing] == [4 * minute]
                transport.http_fetch = admitted_fetch

            repaired = await engine.run("BTCUSDT", ["2m"], 2 * minute, 8 * minute, metadata=demand)
            assert sorted((req.start_ms, req.end_ms) for req in transport.requests) == [
                (3 * minute, 3 * minute), (7 * minute, 7 * minute),
            ]
            assert repaired.status is BackfillStatus.COMPLETED
            assert repaired.reconcile_result.bars_written == (1 if defer_second else 2)
            assert repaired.reconcile_result.custom_bars_written == 3
            targets = await storage.query_time_range("BTCUSDT", "2m", 0, 8 * minute)
            assert [(row["open_time"], row["volume"], row["source"]) for row in targets] == [
                (0, 4, "backfill_aggregated"),
                (2 * minute, 3.5, "backfill_aggregated"),
                (4 * minute, 4, "backfill_aggregated"),
                (6 * minute, 3.5, "backfill_aggregated"),
                (8 * minute, 4, "backfill_aggregated"),
            ]
        finally:
            await engine.close()

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["live_tail", "fetched_open", "local_input", "target", "delete", "legacy_receipt"])
def test_custom_tail_warmup_uses_exact_committed_mutation_ranges(tmp_path, monkeypatch, mutation):
    import sqlite3
    from contextvars import Context

    from app.data_engine.storage import klines_repo

    db = tmp_path / "concurrent.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", db)
    klines_repo.init_klines_storage()

    minute = 60_000
    open_ms = 2 * minute
    missing = open_ms + minute
    transport = _FakeBinanceTransport(_make_binance_rows(16, minute))
    storage = klines_repo.AsyncKlinesRepoAdapter()
    engine = BackfillEngine(
        BackfillConfig(history_archive_enabled=False, reconcile_enable_cache_push=False),
        storage, transport, ingestion_config=IngestionConfig(),
    )
    demand = {"requester": "warm_start_custom_tail", "history_calendar_id": "crypto.24x7.utc"}

    def row(at, width=minute, volume=2):
        return {
            "open_time": at, "close_time": at + width - 1,
            "open": 100, "high": 110, "low": 90, "close": 105, "volume": volume,
            "quote_volume": 210, "trades": 10, "taker_buy_base": 1, "taker_buy_quote": 105,
        }

    async def external_write(at, *, interval="1m", width=minute, volume=2, source="data_manager_exchange_closed"):
        assert await asyncio.create_task(
            storage.upsert_bars("BTCUSDT", interval, [row(at, width, volume)], source=source),
            context=Context(),
        ) == 1

    actual_fetch = transport.http_fetch

    async def interleaved_fetch(req):
        result = await actual_fetch(req)
        if mutation == "fetched_open":
            await external_write(missing, volume=9, source="backfill")
        elif mutation == "delete":
            # Deleting a slot that is still empty must also fence its fetch.
            assert klines_repo.delete_klines("BTCUSDT", "1m", missing, missing) == 0
        elif mutation in {"live_tail", "legacy_receipt"}:
            await external_write(10 * minute)
            if mutation == "legacy_receipt":
                # Emulate an older writer whose revision had no exact receipt.
                with sqlite3.connect(db) as conn:
                    conn.execute("DELETE FROM kline_block_changes WHERE revision=(SELECT MAX(revision) FROM kline_block_changes)")
        return result

    actual_write = engine.reconciler._write_custom_materialization

    async def interleaved_materialization(**kwargs):
        if mutation == "live_tail":
            await external_write(11 * minute)
        elif mutation == "local_input":
            await external_write(open_ms, volume=9, source="backfill")
        elif mutation == "target":
            await external_write(open_ms, interval="2m", width=2 * minute, volume=9, source="backfill_aggregated")
        return await actual_write(**kwargs)

    async def no_rate_limit():
        pass

    async def run():
        try:
            await external_write(open_ms, source="backfill")
            engine.fetcher.set_rate_limiter(no_rate_limit)
            transport.http_fetch = interleaved_fetch
            engine.reconciler._write_custom_materialization = interleaved_materialization
            result = await engine.run("BTCUSDT", ["2m"], open_ms, open_ms, metadata=demand)
            assert [(req.start_ms, req.end_ms) for req in transport.requests] == [(missing, missing)]
            stored_source = await storage.query_time_range("BTCUSDT", "1m", missing, missing)
            stored_target = await storage.query_time_range("BTCUSDT", "2m", open_ms, open_ms)
            if mutation == "live_tail":
                assert result.status is BackfillStatus.COMPLETED, result.errors
                assert [r["volume"] for r in stored_source] == [1.5]
                assert [r["volume"] for r in stored_target] == [3.5]
                assert result.reconcile_result.bars_written == result.reconcile_result.custom_bars_written == 1
            else:
                assert result.status is BackfillStatus.PARTIAL, result.errors
                expected_source = {"fetched_open": [9], "local_input": [1.5], "target": [1.5]}.get(mutation, [])
                assert [r["volume"] for r in stored_source] == expected_source
                assert [r["volume"] for r in stored_target] == ([9] if mutation == "target" else [])
        finally:
            await engine.close()

    asyncio.run(run())
