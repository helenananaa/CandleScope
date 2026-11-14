"""Range permission for the windows a routed Binance USD-M history run writes.

A cold chart keeps writing to the same symbol while a routed run downloads its
archive days and REST edges. The run may keep what it fetched when its own
windows are unchanged and undeleted, and only then.
"""
from __future__ import annotations

import asyncio
from contextvars import Context
from types import SimpleNamespace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher, planned_write_windows
from app.data_engine.backfill.models import BackfillPlan, BackfillTask, FetchedBar, FetchResult
from app.data_engine.backfill.reconciler import Reconciler, _split_rest_edges
from app.data_engine.backfill.source_router import ArchiveRoutePlan
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo
from app.data_engine.storage.native_history_fence import (
    MAX_PLANNED_SLOTS,
    MAX_SLOTS,
    capture_planned_write_views,
)
from app.data_engine.storage.revisions import StaleAcquisition, acquisition_scope, prepare_planned_write_views

MINUTE = 60_000
DAY = 1_440 * MINUTE
DAY0 = 1_793_491_200_000  # 2026-11-01 00:00 UTC, the first archive day
EDGE = (DAY0 - 69 * MINUTE, DAY0 - MINUTE)  # the REST edge before it
ARCHIVE = "backfill_archive_verified"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def rows(opens, width=MINUTE, close=10.0):
    return [dict(open_time=open_time, close_time=open_time + width - 1, open=10, high=20, low=1, close=close,
                 volume=1, quote_volume=10, trades=1, taker_buy_base=0, taker_buy_quote=0) for open_time in opens]


def minutes(start, end):
    return range(start, end + 1, MINUTE)


def window(start, end, *, archive=False, **overrides):
    return SimpleNamespace(**{**dict(exchange="binance", market_type="futures", symbol="BTCUSDT", interval="1m",
                                     start_ms=start, end_ms=end, archive=archive, metadata={}), **overrides})


def day(index):
    return window(DAY0 + index * DAY, DAY0 + (index + 1) * DAY - 1, archive=True)


def capture(store, *windows):
    scope = store.revision_store.acquisition()
    capture_planned_write_views(store.revision_store, scope, list(windows))
    return scope


def write(opens, *, source="backfill", interval="1m", width=MINUTE, close=10.0, **series):
    return klines_repo.upsert_klines("BTCUSDT", interval, rows(opens, width, close), source=source,
                                    **{"market_type": "futures", **series})


def receipt(start, count):
    return dict(object_key=f"binance:futures:BTCUSDT:1m:daily:{start}", content_sha256=f"{start:064x}",
                exchange="binance", market_type="futures", symbol="BTCUSDT", interval="1m", row_count=count,
                start_ms=start, end_ms=start + DAY - 1, provider_id="binance-public-kline-v1",
                granularity="daily", period=str(start), source_url="local://test")


def import_day(index):
    start = DAY0 + index * DAY
    payload = rows(minutes(start, start + DAY - MINUTE))
    return klines_repo.import_history_archive("BTCUSDT", "1m", payload, receipt(start, len(payload)),
                                              source=ARCHIVE, exchange="binance", market_type="futures")


def stored(store, start, end):
    return len(store.query_bars("BTCUSDT", "1m", start_ms=start, end_ms=end, market_type="futures"))


def writes_elsewhere_in_the_family():
    """What a cold chart commits while the run is still downloading."""
    write([DAY0 + 20 * DAY], source="source_snapshot_verified")
    write([DAY0 + 20 * DAY], source="backfill_aggregated", interval="89m", width=89 * MINUTE)


def test_routed_windows_keep_their_data_when_the_rest_of_the_family_moves(store):
    scope = capture(store, window(*EDGE), day(0), day(1))
    writes_elsewhere_in_the_family()
    with acquisition_scope(scope):
        assert write(minutes(*EDGE)) == 69
        assert import_day(0)["written"] == 1_440
    write([DAY0 + 21 * DAY], source="source_snapshot_verified")  # after the run's own commits, too
    with acquisition_scope(scope):
        assert import_day(1)["written"] == 1_440
    assert stored(store, EDGE[0], DAY0 + 2 * DAY) == 69 + 2 * 1_440


def test_without_captured_windows_the_family_check_still_rejects(store):
    scope = store.revision_store.acquisition()
    writes_elsewhere_in_the_family()
    with acquisition_scope(scope):
        with pytest.raises(StaleAcquisition):
            write(minutes(*EDGE))
        with pytest.raises(StaleAcquisition):
            import_day(0)
    assert stored(store, EDGE[0], DAY0 + DAY) == 0


@pytest.mark.parametrize("target", ["edge", "archive"])
@pytest.mark.parametrize("change", ["insert", "correct", "delete", "empty-delete"])
def test_a_changed_or_deleted_window_still_rejects_the_fetched_data(store, target, change):
    inside = EDGE[0] + 5 * MINUTE if target == "edge" else DAY0 + 5 * MINUTE
    if change in {"correct", "delete"}:
        write([inside])
    scope = capture(store, window(*EDGE), day(0))
    if change in {"delete", "empty-delete"}:
        store.delete_bars("BTCUSDT", "1m", inside, inside, market_type="futures")
    else:
        write([inside], close=19.0)
    def fetched(kind):
        return write(minutes(*EDGE)) if kind == "edge" else import_day(0)["written"]

    other = "archive" if target == "edge" else "edge"
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        fetched(target)
    if change in {"delete", "empty-delete"}:
        # A deletion anywhere in the series withdraws every window of it.
        with acquisition_scope(scope), pytest.raises(StaleAcquisition):
            fetched(other)
    else:
        with acquisition_scope(scope):
            assert fetched(other) > 0


def test_permission_does_not_cross_provenance_or_leave_its_window(store):
    scope = capture(store, window(*EDGE), day(0))
    writes_elsewhere_in_the_family()
    with acquisition_scope(scope):
        with pytest.raises(StaleAcquisition):  # REST rows inside an archive object's window
            write(minutes(DAY0, DAY0 + 9 * MINUTE))
        with pytest.raises(StaleAcquisition):  # one batch joining the edge and the archive day
            write(minutes(EDGE[1] - MINUTE, DAY0 + MINUTE))
        with pytest.raises(StaleAcquisition):  # just outside the edge
            write([EDGE[0] - MINUTE])
        with pytest.raises(StaleAcquisition):  # an archive day that was not planned
            import_day(1)
        with pytest.raises(StaleAcquisition):  # a derived bar gains nothing from native windows
            write([EDGE[0]], source="backfill_aggregated", interval="89m", width=89 * MINUTE)
    assert stored(store, EDGE[0] - MINUTE, DAY0 + 2 * DAY) == 0


@pytest.mark.parametrize("overrides", [
    dict(market_type="spot"),
    dict(exchange="okx"),
    dict(interval="89m"),
    dict(start_ms=EDGE[0] + 1),
    dict(end_ms=EDGE[0] + MAX_SLOTS * MINUTE),
    dict(metadata={"series_identity": KlineSeriesIdentity.for_exchange("binance", provider_id="foreign").to_dict()}),
])
def test_other_markets_identities_and_shapes_get_no_planned_views(store, overrides):
    assert capture(store, window(*EDGE, **overrides)).native_history_views == []


def test_planned_views_are_bounded_and_not_duplicated(store):
    days = [day(index) for index in range(MAX_PLANNED_SLOTS // 1_440 + 3)]
    scope = capture(store, *days, *days)
    assert len(scope.native_history_views) == MAX_PLANNED_SLOTS // 1_440
    assert all(view.archive for view in scope.native_history_views)
    capture_planned_write_views(store.revision_store, scope, days[:2])
    assert len(scope.native_history_views) == MAX_PLANNED_SLOTS // 1_440


def test_a_deletion_before_capture_is_not_renewed_by_it(store):
    scope = store.revision_store.acquisition()
    store.delete_bars("BTCUSDT", "1m", EDGE[0], EDGE[1], market_type="futures")
    with pytest.raises(StaleAcquisition):
        capture_planned_write_views(store.revision_store, scope, [window(*EDGE)])
    assert scope.native_history_views == []


def task(start, end, **metadata):
    return BackfillTask(symbol="BTCUSDT", interval="1m", start_ms=start, end_ms=end, exchange="binance",
                        market_type="futures", estimated_bars=(end - start) // MINUTE + 1, metadata=metadata)


def ref(index):
    return SimpleNamespace(object_key=f"day-{index}", start_ms=DAY0 + index * DAY, end_ms=DAY0 + (index + 1) * DAY - 1)


def test_fetcher_reports_owned_archive_days_and_rest_edges():
    routed = task(EDGE[0], DAY0 + 2 * DAY + 30 * MINUTE)
    plain = task(DAY0 + 9 * DAY, DAY0 + 9 * DAY + 10 * MINUTE)
    refs = (ref(0), ref(1))
    plan = ArchiveRoutePlan({routed.task_key: refs}, {}, {"day-0": routed.task_key, "day-1": "a sibling task"})
    reported = [(item.start_ms, item.end_ms, item.archive) for item in planned_write_windows([routed, plain], plan)]
    # Both edges are REST; only the object this task imports is an archive window.
    assert reported == [
        (EDGE[0], EDGE[1], False),
        (DAY0 + 2 * DAY, DAY0 + 2 * DAY + 30 * MINUTE, False),
        (DAY0, DAY0 + DAY - 1, True),
    ]
    assert all((item.exchange, item.market_type, item.symbol, item.interval) == ("binance", "futures", "BTCUSDT", "1m")
               for item in planned_write_windows([routed], plan))


def test_fetcher_reports_windows_before_it_fetches_any_task():
    routed = task(EDGE[0], DAY0 + 30 * MINUTE)
    events = []

    class Router:
        async def prepare(self, tasks):
            events.append("routed")
            return ArchiveRoutePlan({routed.task_key: (ref(0),)}, {}, {"day-0": routed.task_key})

        def start_deferred_prefetch(self, plan):
            events.append("prefetch")

    fetcher = HistoricalFetcher(BackfillConfig(fetch_rate_limit_delay=0), SimpleNamespace(), IngestionConfig(),
                                source_router=Router())

    async def fetch_task(item, route_plan):
        events.append("fetched")
        return FetchResult(task=item)

    fetcher._fetch_task = fetch_task

    async def capture_windows(windows):
        events.append(("windows", [(item.start_ms, item.end_ms, item.archive) for item in windows]))

    asyncio.run(fetcher.fetch([routed], on_write_windows=capture_windows))
    assert events[:3] == ["routed", ("windows", [(EDGE[0], EDGE[1], False), (DAY0, DAY0 + DAY - 1, True)]), "fetched"]


def bar(open_time, source="backfill", object_key=None):
    return FetchedBar(symbol="BTCUSDT", interval="1m", open_time=open_time, close_time=open_time + MINUTE - 1,
                      open=10, high=20, low=1, close=10, volume=1, exchange="binance", market_type="futures",
                      quote_volume=10, trades=1, source=source, archive_object_key=object_key)


def test_rest_rows_are_grouped_by_the_edge_they_were_fetched_for():
    head = [bar(open_time) for open_time in minutes(*EDGE)]
    tail = [bar(open_time) for open_time in minutes(DAY0 + DAY, DAY0 + DAY + 9 * MINUTE)]
    stray = [bar(DAY0 + 5 * DAY)]
    groups = _split_rest_edges([*head, *tail, *stray], [EDGE, (DAY0 + DAY, DAY0 + 2 * DAY)])
    assert groups == [head, tail, stray]
    assert _split_rest_edges([*head, *tail], ()) == [[*head, *tail]]


def routed_result(store):
    """One routed task's result: a REST edge on each side of one archive day."""
    start = DAY0
    tail = (DAY0 + DAY, DAY0 + DAY + 9 * MINUTE)
    archive_bars = [bar(open_time, ARCHIVE, receipt(start, 1_440)["object_key"])
                    for open_time in minutes(start, start + DAY - MINUTE)]
    rest_bars = [bar(open_time) for edge in (EDGE, tail) for open_time in minutes(*edge)]
    item = task(EDGE[0], tail[1])
    result = FetchResult(task=item, bars=sorted([*archive_bars, *rest_bars], key=lambda value: value.open_time),
                         metadata={"archive_objects": [receipt(start, 1_440)],
                                   "rest_ranges": [list(EDGE), list(tail)]})
    windows = [window(*EDGE), window(*tail), day(0)]
    return item, result, windows, tail


@pytest.mark.parametrize("planned", [True, False])
def test_reconcile_keeps_a_routed_fetch_only_with_planned_windows(store, planned):
    item, result, windows, tail = routed_result(store)
    config = BackfillConfig(reconcile_generate_custom=False, reconcile_enable_cache_push=False,
                            reconcile_write_batch_size=500)

    async def run():
        scope = store.revision_store.acquisition()
        with acquisition_scope(scope):
            if planned:
                await prepare_planned_write_views(store, windows)
            # The download is in flight while the chart keeps writing. An
            # empty context makes these another writer's commits, not the run's.
            Context().run(writes_elsewhere_in_the_family)
            return await Reconciler(config, klines_repo.AsyncKlinesRepoAdapter()).reconcile(
                [result], BackfillPlan(gaps=[], tasks=[item]))

    outcome = asyncio.run(run())
    kept = stored(store, EDGE[0], tail[1])
    if planned:
        assert (outcome.write_errors, outcome.bars_written, kept) == (0, 69 + 1_440 + 10, 69 + 1_440 + 10)
        assert outcome.archive_objects_imported == 1
    else:
        assert outcome.write_errors == 3 and (outcome.bars_written, kept) == (0, 0)


def test_only_the_changed_edge_is_lost(store):
    item, result, windows, tail = routed_result(store)
    config = BackfillConfig(reconcile_generate_custom=False, reconcile_enable_cache_push=False,
                            reconcile_write_batch_size=500)

    async def run():
        scope = store.revision_store.acquisition()
        with acquisition_scope(scope):
            await prepare_planned_write_views(store, windows)
            # A live snapshot lands inside the recent edge during the download.
            Context().run(lambda: write([tail[0] + 2 * MINUTE], source="source_snapshot_verified"))
            return await Reconciler(config, klines_repo.AsyncKlinesRepoAdapter()).reconcile(
                [result], BackfillPlan(gaps=[], tasks=[item]))

    outcome = asyncio.run(run())
    assert outcome.write_errors == 1
    assert stored(store, EDGE[0], DAY0 + DAY - 1) == 69 + 1_440
    assert stored(store, *tail) == 1
