"""Binance USD-M backfills while the same symbol streams live.

A backfill takes its revision snapshot before it fetches. Open charts and the
practice account's market feed keep committing bars for the symbol while the
request is in flight: forming-bar updates, closes, other intervals. On a slow
network every request spans such a write. Before range views covered plain REST
tasks and monthly archive objects, the family-wide check rejected every batch
and the retries repeated forever (RC: "Preparing historical data · 0/20").

A run keeps what it fetched when its own window is unchanged and its series was
not deleted since capture, and only then. Live writes are committed from another
thread, as the live stream does: a write on the run's own thread would inherit
its acquisition and count as the run's own.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from app.data_engine.storage import klines_repo
from app.data_engine.storage.native_history_fence import MAX_ARCHIVE_SLOTS, MAX_SLOTS, capture_planned_write_views
from app.data_engine.storage.revisions import StaleAcquisition, acquisition_scope
from tests.test_routed_history_range_views import window

MINUTE = 60_000
DAY = 1_440 * MINUTE
GAP = (10 * MINUTE, 12 * MINUTE)  # three closed bars the run must repair
LIVE = "data_manager_exchange_closed"
NOVEMBER = 1_793_491_200_000  # 2026-11-01 00:00 UTC; the month has 30 days


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def rows(opens, width=MINUTE, close=10.0):
    return [dict(open_time=open_time, close_time=open_time + width - 1, open=10, high=20, low=1, close=close,
                 volume=1, quote_volume=10, trades=1, taker_buy_base=0, taker_buy_quote=0) for open_time in opens]


def write(opens, *, interval="1m", width=MINUTE, close=10.0, source=LIVE):
    return klines_repo.upsert_klines("BTCUSDT", interval, rows(opens, width, close), source=source,
                                    exchange="binance", market_type="futures")


def on_another_thread(change):
    """Commit as a concurrent writer does, outside the run's acquisition."""
    errors = []

    def target():
        try:
            change()
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]


def stored(store, start, end, close=None):
    bars = store.query_bars("BTCUSDT", "1m", start_ms=start, end_ms=end, market_type="futures")
    return [bar for bar in bars if close is None or bar["close"] == close]


LIVE_WRITES = {
    # Another open chart of the symbol updates its forming bar.
    "other-interval": lambda: write([0], interval="15m", width=15 * MINUTE, close=11.0),
    # The 1m chart's own forming bar, after the repaired range.
    "same-series-later-bar": lambda: write([25 * MINUTE], close=11.0),
    # The bar just before the range closes.
    "same-series-earlier-bar": lambda: write([GAP[0] - MINUTE], close=11.0),
}


def run_backfill(change, *, page_mode):
    from app.data_engine.backfill import BackfillConfig, BackfillEngine
    from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows

    class Transport(_FakeBinanceTransport):
        async def http_fetch(self, request):
            # The request is in flight while the live feed commits.
            on_another_thread(change)
            return await super().http_fetch(request)

    async def run():
        engine = BackfillEngine(BackfillConfig(fetch_rate_limit_delay=0),
                                storage=klines_repo.AsyncKlinesRepoAdapter(),
                                transport=Transport(_make_binance_rows(30, MINUTE)))
        try:
            return await engine.run("BTCUSDT", ["1m"], *GAP, exchange="binance", market_type="futures",
                                    _receipt_mode=page_mode)
        finally:
            await engine.close()

    return asyncio.run(run())


@pytest.mark.parametrize("page_mode", [True, False], ids=["page", "batch"])
@pytest.mark.parametrize("live", sorted(LIVE_WRITES))
def test_plain_rest_backfill_keeps_its_bars_while_the_symbol_streams(store, live, page_mode):
    report = run_backfill(LIVE_WRITES[live], page_mode=page_mode)
    assert not report.errors, report.errors
    assert report.reconcile_result.bars_written == 3
    assert len(stored(store, *GAP)) == 3
    if page_mode:
        # The coordinator's production path: REST pages reconciled as they arrive.
        assert report.metadata["fetch_payload_mode"] == "receipt"


@pytest.mark.parametrize("page_mode", [True, False], ids=["page", "batch"])
@pytest.mark.parametrize("change", ["live-close-inside", "repair-inside", "delete-elsewhere-in-series"])
def test_plain_rest_backfill_still_rejects_a_changed_or_deleted_window(store, change, page_mode):
    if change == "delete-elsewhere-in-series":
        write([30 * MINUTE])
    mutations = {
        "live-close-inside": lambda: write([GAP[0] + MINUTE], close=19.0),
        "repair-inside": lambda: write([GAP[0] + MINUTE], close=19.0, source="repair_binance_rest_verified"),
        "delete-elsewhere-in-series": lambda: store.delete_bars("BTCUSDT", "1m", 30 * MINUTE, 30 * MINUTE,
                                                               market_type="futures"),
    }
    once = []

    def mutate():
        if not once:
            once.append(True)
            mutations[change]()

    report = run_backfill(mutate, page_mode=page_mode)
    assert any(reason in error for error in report.errors
               for reason in ("changed during acquisition", "deleted after request permission",
                              "changed after acquisition began")), report.errors
    assert report.reconcile_result is None or report.reconcile_result.bars_written == 0
    # The concurrent writer's bar is never replaced by the older fetch.
    if change != "delete-elsewhere-in-series":
        assert len(stored(store, *GAP, close=19.0)) == 1
    assert len(stored(store, *GAP)) == (0 if change == "delete-elsewhere-in-series" else 1)


def month_receipt(count):
    return dict(object_key=f"binance:futures:BTCUSDT:1m:monthly:{NOVEMBER}", content_sha256=f"{NOVEMBER:064x}",
                exchange="binance", market_type="futures", symbol="BTCUSDT", interval="1m", row_count=count,
                start_ms=NOVEMBER, end_ms=NOVEMBER + 30 * DAY - 1, provider_id="binance-public-kline-v1",
                granularity="monthly", period="2026-11", source_url="local://test")


def import_month():
    payload = rows(range(NOVEMBER, NOVEMBER + 30 * DAY, MINUTE))
    return klines_repo.import_history_archive("BTCUSDT", "1m", payload, month_receipt(len(payload)),
                                              source="backfill_archive_verified", exchange="binance",
                                              market_type="futures")


def capture_month(store):
    scope = store.revision_store.acquisition()
    capture_planned_write_views(store.revision_store, scope,
                                [window(NOVEMBER, NOVEMBER + 30 * DAY - 1, archive=True)])
    assert len(scope.native_history_views) == 1
    return scope


def test_monthly_archive_object_keeps_its_rows_while_the_symbol_streams(store):
    """RC log: one run fetched a 43,200-bar month and wrote none of it."""
    scope = capture_month(store)
    on_another_thread(lambda: (write([NOVEMBER + 31 * DAY], close=11.0),
                               write([NOVEMBER + 31 * DAY], interval="15m", width=15 * MINUTE)))
    with acquisition_scope(scope):
        assert import_month()["written"] == 30 * 1_440
    assert len(stored(store, NOVEMBER, NOVEMBER + 30 * DAY - 1)) == 30 * 1_440


def test_monthly_archive_object_still_rejects_a_change_inside_its_month(store):
    scope = capture_month(store)
    on_another_thread(lambda: write([NOVEMBER + 7 * DAY], close=19.0))
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        import_month()
    assert len(stored(store, NOVEMBER, NOVEMBER + 30 * DAY - 1)) == 1


def test_archive_and_rest_windows_keep_their_own_bounds(store):
    def views(start, slots, archive):
        scope = store.revision_store.acquisition()
        capture_planned_write_views(store.revision_store, scope,
                                    [window(start, start + (slots - 1) * MINUTE, archive=archive)])
        return [view.budget for view in scope.native_history_views]

    assert views(NOVEMBER, MAX_ARCHIVE_SLOTS, True) == [MAX_ARCHIVE_SLOTS]
    assert views(NOVEMBER, MAX_ARCHIVE_SLOTS + 1, True) == []
    assert views(NOVEMBER, MAX_SLOTS, False) == [MAX_SLOTS]
    assert views(NOVEMBER, MAX_SLOTS + 1, False) == []
