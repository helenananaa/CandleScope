from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.maintenance import MaintenanceService
from app.data_engine.history.calendar import SessionCalendar
from app.data_engine.history.models import HistoryAvailability
from app.data_engine.storage import klines_repo


MINUTE = 60_000
SERIES = ("binance", "spot", "BTCUSDT", "1m")


def _write(opens, *, symbol="BTCUSDT", interval="1m"):
    return klines_repo.upsert_klines(symbol, interval, [
        {"open_time": value, "close_time": value + MINUTE - 1,
         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
         "volume": 1.0, "quote_volume": 1.0, "trades": 1,
         "taker_buy_base": 0.0, "taker_buy_quote": 0.0}
        for value in opens
    ], source="test")


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


async def _ignore(*args, **kwargs):
    pass


def _coordinator(storage, engine=None):
    return BackfillCoordinator(
        storage=storage, engine=engine, bars_backfilled=_ignore, emit_event=_ignore,
        loop=asyncio.get_running_loop(), max_retries=1, base_delay_seconds=0,
    )


def _maintenance(storage, active=()):
    return MaintenanceService(
        storage_provider=lambda: storage, aggregator_config_snapshot=dict,
        cache_invalidator=lambda *args, **kwargs: None, bars_backfilled=_ignore,
        active_targets=lambda: active, seed_active_bar=_ignore,
    )


async def _scan(storage, coordinator, active=()):
    return await _maintenance(storage, active).scan_and_fill_gaps(
        symbols_filter=["btcusdt", "ETHUSDT"], backfill_coordinator=coordinator,
    )


def test_empty_inventory_and_failed_reads_never_report_complete(storage, monkeypatch):
    async def scenario():
        coordinator = _coordinator(storage)
        assert (await _scan(storage, coordinator))["status"] == "empty"
        _write([0, MINUTE])
        monkeypatch.setattr(storage, "scan_gaps", lambda **kwargs: {"error": "database is locked"})
        failed = await _scan(storage, coordinator)
        assert failed["status"] == "error"
        assert failed["results"][0]["status"] == "error"
        assert "database is locked" in failed["results"][0]["message"]
        monkeypatch.setattr(storage, "list_series", lambda *args: (_ for _ in ()).throw(OSError("inventory unreadable")))
        inventory = await _scan(storage, coordinator)
        assert inventory["status"] == "error"
        assert inventory["errors"] == ["inventory unreadable"]
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_partial_read_failure_preserves_successful_range_and_error(storage, monkeypatch):
    _write([0, MINUTE])
    _write([0, MINUTE], symbol="ETHUSDT")
    scan = storage.scan_gaps
    def fail_one(**kwargs):
        if kwargs["symbol"] == "ETHUSDT":
            raise OSError("ETH series unavailable")
        return scan(**kwargs)
    monkeypatch.setattr(storage, "scan_gaps", fail_one)
    async def scenario():
        coordinator = _coordinator(storage)
        result = await _scan(storage, coordinator)
        assert result["status"] == "partial"
        assert result["verified_ranges"] == 1
        assert result["failed_ranges"] == 1
        assert {page["symbol"] for page in result["results"]} == {"BTCUSDT", "ETHUSDT"}
        assert result["results"][0]["scanned_from_ms"] == 0
        assert result["results"][0]["scanned_to_ms"] == MINUTE
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_shared_cursor_finds_history_gap_outside_recent_2000_bars(storage):
    _write(value * MINUTE for value in range(5_000) if value != 2_500)
    async def scenario():
        coordinator = _coordinator(storage)
        first = await coordinator.audit_storage_series([SERIES], scan_limit=2_000, repair=False, detailed=True)
        assert first.pages[0]["truncated"] is True
        assert first.pages[0]["scanned_to_ms"] == 1_999 * MINUTE
        assert first.pages[0]["next_cursor_ms"] == 2_000 * MINUTE
        # A background audit continues from the very same cursor.
        second = await coordinator.audit_storage_series([SERIES], scan_limit=2_000, repair=False)
        assert second.repaired == 1  # legacy dry-run detected-gap counter
        third = await coordinator.audit_storage_series([SERIES], scan_limit=2_000, repair=False, detailed=True)
        assert third.pages[0]["scanned_from_ms"] == 4_001 * MINUTE
        assert third.pages[0]["truncated"] is False
        assert third.pages[0]["next_cursor_ms"] is None
        await coordinator.shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize("fill_both,expected_status,remaining", [(False, "gap_found", 1), (True, "filled", 0)])
def test_written_bars_are_not_completeness_without_storage_recheck(storage, fill_both, expected_status, remaining):
    _write([0, 3 * MINUTE])
    class Engine:
        async def run(self, **kwargs):
            _write([MINUTE, 2 * MINUTE] if fill_both else [MINUTE])
            return SimpleNamespace(status="completed", errors=[], reconcile_result=SimpleNamespace(
                bars_written=2 if fill_both else 1, written_ranges=[]))
    async def scenario():
        coordinator = _coordinator(storage, Engine())
        result = await _scan(storage, coordinator)
        page = result["results"][0]
        assert page["status"] == expected_status
        assert page["remaining_missing_bars"] == remaining
        assert page["verified_after_repair"] is True
        assert page["bars_filled"] >= 1
        assert result["status"] == ("ok" if fill_both else "partial")
        assert "request_ids" not in page
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_timeout_does_not_cancel_shared_repair_or_create_duplicate_job(storage):
    _write([0, 2 * MINUTE])
    async def scenario():
        release, started = asyncio.Event(), asyncio.Event()
        calls = []
        class Engine:
            async def run(self, **kwargs):
                calls.append(kwargs)
                started.set()
                await release.wait()
                _write([MINUTE])
                return SimpleNamespace(status="completed", errors=[], reconcile_result=SimpleNamespace(bars_written=1, written_ranges=[]))
        coordinator = _coordinator(storage, Engine())
        first = await coordinator.audit_storage_series([SERIES], detailed=True, repair_wait_seconds=0.02)
        await started.wait()
        second = await coordinator.audit_storage_series([SERIES], detailed=True, repair_wait_seconds=0.02)
        assert first.pages[0]["status"] == second.pages[0]["status"] == "pending"
        assert second.queued == 0
        assert len(calls) == 1
        assert first.pages[0]["request_ids"] == second.pages[0]["request_ids"]
        release.set()
        outcome = await asyncio.wait_for(coordinator.wait_for_request(first.pages[0]["request_ids"][0]), 2)
        assert outcome is not None
        result = await _scan(storage, coordinator)
        assert result["status"] == "ok"
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_budget_marks_unscanned_ranges_instead_of_silently_omitting_them(storage):
    _write([0, 2 * MINUTE])
    _write([0, MINUTE], symbol="ETHUSDT")
    async def scenario():
        coordinator = _coordinator(storage)
        report = await coordinator.audit_storage_series(
            [SERIES, ("binance", "spot", "ETHUSDT", "1m")], max_gaps=1, detailed=True,
        )
        assert report.pages[-1]["symbol"] == "ETHUSDT"
        assert report.pages[-1]["status"] == "unscanned"
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_unknown_semantic_identity_is_not_relabelled_as_default(storage, monkeypatch):
    monkeypatch.setattr(storage, "list_series", lambda *args: [{
        "symbol": "BTCUSDT", "interval": "1m", "provider_id": "other-vendor", "total_count": 2,
    }])
    monkeypatch.setattr(storage, "scan_gaps", lambda **kwargs: pytest.fail("must not read the default series"))
    async def scenario():
        coordinator = _coordinator(storage)
        result = await _scan(storage, coordinator)
        assert result["status"] == "partial"
        assert result["scanned_ranges"] == 0
        assert result["results"][0]["status"] == "unsupported"
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_failed_repair_keeps_missing_count_and_reason(storage):
    _write([0, 2 * MINUTE])
    class Engine:
        async def run(self, **kwargs):
            raise OSError("source unavailable")
    async def scenario():
        coordinator = _coordinator(storage, Engine())
        result = await _scan(storage, coordinator)
        assert result["status"] == "partial"
        page = result["results"][0]
        assert page["remaining_gaps"] == 1
        assert page["remaining_missing_bars"] == 1
        assert any("source unavailable" in error for error in page["repair_errors"])
        await coordinator.shutdown()
    asyncio.run(scenario())


def test_manual_session_audit_skips_weekend_and_forming_candle(storage, monkeypatch):
    def timestamp(value):
        return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)
    friday = timestamp("2024-01-05T09:30:00")
    monday = timestamp("2024-01-08T09:00:00")
    now = timestamp("2024-01-08T09:45:00")
    calendar = SessionCalendar(
        calendar_id="test.weekdays", timezone_name="UTC",
        weekly_sessions={day: [("09:00", "10:00")] for day in range(5)},
    )
    storage.set_calendar_resolver(lambda *_: calendar)
    _write([friday, monday], interval="30m")
    monkeypatch.setattr("app.data_engine.data_manager.backfill_coordinator.time.time", lambda: now / 1000)
    async def scenario():
        coordinator = BackfillCoordinator(
            storage=storage, bars_backfilled=_ignore, emit_event=_ignore,
            history_policy_resolver=lambda _: SimpleNamespace(
                availability=HistoryAvailability(calendar_id=calendar.calendar_id), calendar=calendar,
            ),
        )
        key = ("binance", "spot", "BTCUSDT", "30m")
        result = await _scan(storage, coordinator, active=[key])
        assert result["status"] == "ok"
        tail = next(page for page in result["results"] if page["lane"] == "tail")
        assert tail["scanned_to_ms"] == monday
        assert tail["remaining_gaps"] == 0
        assert all(page["calendar_id"] == calendar.calendar_id for page in result["results"])
        await coordinator.shutdown()
    asyncio.run(scenario())
