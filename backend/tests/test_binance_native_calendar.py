import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.data_engine.history.calendar import AlwaysOpenCalendar, latest_closed_expected_open_ms
from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
from app.data_engine.history.service import HistoryAvailabilityService
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator, RepairRequest
from app.data_engine.data_manager.bar_delivery import source_recovery_handler
from app.exchanges.plugins.binance.calendar import BinanceFuturesCalendar


def test_official_openings_and_transition():
    fixture = json.loads((Path(__file__).parent / "fixtures/binance_usdm_3d_opens.json").read_text())
    calendar = BinanceFuturesCalendar()
    start, end = fixture["range"]
    assert list(calendar.expected_opens(start, end, "3d")) == fixture["opens"]
    assert calendar.count_expected(start, end, "3d") == 499
    old, new = 1691971200000, 1692144000000
    assert calendar.next_expected_open(old, "3d") == new
    assert calendar.previous_expected_open(new, "3d") == old
    assert list(calendar.expected_opens(old + 1, new - 1, "3d")) == []
    # The old bar still has its provider-declared full three-day duration.
    assert latest_closed_expected_open_ms(calendar, new, "3d") == old - calendar.WIDTH


def test_resolver_scopes_native_calendar_and_preserves_other_intervals():
    resolver = ExchangeHistoryPolicyResolver(HistoryAvailabilityService())
    for exchange, market, interval, native in [
        ("binance", "futures", "3d", True),
        ("binance", "spot", "3d", False),
        ("binance", "futures", "30m", False),
        ("binance", "futures", "72h", False),
    ]:
        context = resolver.resolve(resolver.series_key(exchange=exchange, market_type=market,
                                                      symbol="BTCUSDT", variant=interval))
        assert isinstance(context.calendar, BinanceFuturesCalendar) is native
        assert resolver.service.calendars.get(context.availability.calendar_id) is context.calendar
    for interval in ["30m", "1d", "1w", "1M", "72h"]:
        assert list(BinanceFuturesCalendar().expected_opens(1691712000000, 1692921600000, interval)) == list(
            AlwaysOpenCalendar().expected_opens(1691712000000, 1692921600000, interval))


def test_real_rows_verify_but_a_missing_or_untrusted_bar_does_not():
    async def run():
        fixture = json.loads((Path(__file__).parent / "fixtures/binance_usdm_3d_opens.json").read_text())
        rows = [{"open_time": value, "source": "backfill"} for value in fixture["opens"]]
        async def ignore(*args, **kwargs):
            pass

        coordinator = BackfillCoordinator(
            storage=SimpleNamespace(query_bars=lambda **kwargs: rows),
            bars_backfilled=ignore,
            emit_event=ignore,
        )
        request = RepairRequest(symbol="BTCUSDT", interval="3d", market_type="futures",
                                start_ms=fixture["range"][0], end_ms=fixture["range"][1],
                                metadata={"requires_trusted_finality": True})
        context = SimpleNamespace(calendar=BinanceFuturesCalendar())
        result = await coordinator._verify_request_range(request, context=context)
        assert result["verified_contiguous"] is True
        removed = rows.pop(200)
        result = await coordinator._verify_request_range(request, context=context)
        assert result["remaining_missing_bars"] == 1
        rows.append({**removed, "source": "unknown"})
        result = await coordinator._verify_request_range(request, context=context)
        assert result["remaining_missing_bars"] == 1
        await coordinator.shutdown()
    asyncio.run(run())


def test_recovery_end_uses_native_closed_edge():
    async def run():
        requests = []
        async def request_and_wait(request):
            requests.append(request)
            return SimpleNamespace(status="completed", verified_contiguous=True, error=None)
        recover = source_recovery_handler(SimpleNamespace(request_and_wait=request_and_wait))
        await recover({"watch_id": "test", "series": {"symbol": "BTCUSDT", "interval": "3d",
                      "exchange": "binance", "market_type": "futures"},
                      "from_ms": 1660953600000, "through_ms": 1790677885564})
        assert requests[0].end_ms == 1790380800000
    asyncio.run(run())
