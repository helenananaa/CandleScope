"""Bounded source receipts only; full cold recovery is a separate consumer gate."""

from dataclasses import replace, FrozenInstanceError
import json

import pytest

from app.data_engine.aggregation.blocks import BlockUnavailable, BlockRevisionChanged
from app.data_engine.aggregation.source_window import (
    SourceWindowVersion,
    MAX_SOURCE_DATA_BYTES,
)
from app.data_engine.ingestion.models import (
    MarketEvent,
    StreamType,
    DataSource,
    StreamDescriptor,
)
from app.data_engine.storage import klines_repo, kline_sources, source_retention

W = 60000
DESC = StreamDescriptor(
    "BTCUSDT", StreamType.KLINE, interval="1m", market_type="futures"
)
KEY = kline_sources.series(DESC)


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "source.sqlite")
    klines_repo.init_klines_storage()


def record(index, *, quote=2.0, closed=True, sequence=None, conn=None, high=20.0):
    opened = index * W
    seq = opened + W + 1 if sequence is None else sequence
    envelope = dict(
        open="10",
        high=str(high),
        low="5",
        close="11",
        volume="1",
        quoteVolume=str(quote),
        trades=1,
        takerBuyBaseVolume="0.5",
        takerBuyQuoteVolume="1",
        closeTime=opened + W - 1,
        eventTime=seq,
    )
    data = dict(
        interval="1m",
        open_time=opened,
        close_time=opened + W - 1,
        is_closed=closed,
        open=10.0,
        high=high,
        low=5.0,
        close=11.0,
        volume=1.0,
        quote_volume=quote,
        trades=1,
        taker_buy_base=0.5,
        taker_buy_quote=1.0,
        source_candle=envelope,
    )
    event = MarketEvent(
        event_type=StreamType.KLINE,
        symbol="BTCUSDT",
        event_time_ms=seq,
        received_at_ms=seq + 1,
        source=DataSource.WEBSOCKET,
        exchange="binance",
        market_type="futures",
        data=data,
    )
    return kline_sources.record(event, DESC, _connection=conn)


def test_large_source_only_window_reads_finite_immutable_pages_and_no_canonical_rows(
    database, monkeypatch
):
    with klines_repo._connect() as conn:
        kline_sources._schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        for i in range(257):
            record(i, conn=conn)
        conn.commit()
    version = kline_sources.capture_source_window(KEY, 0, 257 * W, W)
    assert version.closed_count == version.revision_sum == 257
    statements = []
    connect = klines_repo._connect

    def traced():
        conn = connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(klines_repo, "_connect", traced)
    pages = []
    position = 0
    while position is not None:
        page = kline_sources.read_source_window_page(version, position)
        pages.append(page)
        position = page.next_position_ms
    assert [len(p.components) for p in pages] == [128, 128, 1]
    assert [x["data"]["open_time"] for p in pages for x in p.components] == list(
        range(0, 257 * W, W)
    )
    with pytest.raises(TypeError):
        pages[0].components[0]["data"]["volume"] = 999
    with pytest.raises(FrozenInstanceError):
        version.revision_sum = 999
    selects = [s for s in statements if "o.data_json" in s]
    assert len(selects) == 3 and all("LIMIT 128" in s for s in selects)
    assert not klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")


def test_partial_source_window_keeps_gap_and_excludes_future_forming_tail(database):
    record(0)
    record(1, closed=False)
    record(2)
    record(3, closed=False)
    version = kline_sources.capture_source_window(KEY, 0, 7 * W, W)
    assert (
        version.through_ms == 3 * W
        and version.closed_count == version.revision_sum == 2
    )
    page = kline_sources.read_source_window_page(version, max_rows=1)
    assert [x["data"]["open_time"] for x in page.components] == [0]
    assert page.next_position_ms == W
    page = kline_sources.read_source_window_page(
        version, page.next_position_ms, max_rows=1
    )
    assert [x["data"]["open_time"] for x in page.components] == [
        2 * W
    ] and page.next_position_ms is None
    # Former gap becomes confirmed, so old source content proof is stale.
    record(1, closed=True, sequence=9 * W)
    with pytest.raises(BlockRevisionChanged):
        kline_sources.read_source_window_page(version)


def test_stale_duplicate_identical_and_unrelated_activity_do_not_invalidate_content(
    database,
):
    first = record(0)
    record(1)
    version = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    record(0, sequence=4 * W)  # Identical values, newer selected observation.
    record(0, quote=999, sequence=1)  # Audited, but not selected.
    record(9)
    with klines_repo._connect() as conn:
        assert kline_sources.source_window_current(conn, version)
    assert kline_sources.rest_watermark() > version.revision_sum
    assert kline_sources.read_source_window_page(version).version == version
    kline_sources.acknowledge(first["ref"])
    source_retention.compact(retention_days=1, now_ms=3 * 86400000)
    with klines_repo._connect() as conn:
        assert kline_sources.source_window_current(conn, version)


def test_opposite_corrections_change_proof_even_when_total_is_equal(database):
    record(0)
    record(1)
    version = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    record(0, quote=1.0, sequence=4 * W)
    record(1, quote=3.0, sequence=4 * W)
    new = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    assert (
        new.closed_count == version.closed_count
        and new.revision_sum == version.revision_sum + 2
    )
    with pytest.raises(BlockRevisionChanged):
        kline_sources.read_source_window_page(version)
    assert (
        sum(
            x["data"]["quote_volume"]
            for x in kline_sources.read_source_window_page(new).components
        )
        == 4
    )


def test_source_transaction_rollback_does_not_expire_committed_receipt(database):
    record(0)
    version = kline_sources.capture_source_window(KEY, 0, W, W)
    with klines_repo._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        record(0, quote=1.0, sequence=4 * W, conn=conn)
        assert not kline_sources.source_window_current(conn, version)
        conn.rollback()
        assert kline_sources.source_window_current(conn, version)
    assert (
        kline_sources.read_source_window_page(version).components[0]["data"][
            "quote_volume"
        ]
        == 2
    )


def test_change_after_page_read_is_rejected_before_return(database, monkeypatch):
    record(0)
    record(1)
    version = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    current = kline_sources.source_window_current
    calls = []

    def check(conn, proof):
        calls.append(1)
        if len(calls) == 2:
            record(0, quote=1.0, sequence=4 * W)
        return current(conn, proof)

    monkeypatch.setattr(kline_sources, "source_window_current", check)
    with pytest.raises(BlockRevisionChanged):
        kline_sources.read_source_window_page(version)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "variant", ["oversize", "malformed", "off-grid", "unclosed-json", "close-time"]
)
def test_unusable_selected_json_never_becomes_a_successful_page(database, variant):
    record(0)
    version = kline_sources.capture_source_window(KEY, 0, W, W)
    with klines_repo._connect() as conn:
        row = conn.execute(
            "SELECT data_json FROM kline_source_observations WHERE id=1"
        ).fetchone()
        data = json.loads(row[0])
        if variant == "oversize":
            data["extra"] = "x" * MAX_SOURCE_DATA_BYTES
        elif variant == "off-grid":
            data["open_time"] = 1
        elif variant == "unclosed-json":
            data["is_closed"] = False
        elif variant == "close-time":
            data["close_time"] += 1
        payload = "{" if variant == "malformed" else json.dumps(data)
        conn.execute(
            "UPDATE kline_source_observations SET data_json=? WHERE id=1", (payload,)
        )
        conn.commit()
    with pytest.raises(BlockUnavailable):
        kline_sources.read_source_window_page(version)


@pytest.mark.parametrize("max_rows", [0, 129, True, -1])
def test_page_limit_is_enforced_before_read(database, max_rows):
    record(0)
    version = kline_sources.capture_source_window(KEY, 0, W, W)
    with pytest.raises(ValueError):
        kline_sources.read_source_window_page(version, max_rows=max_rows)


@pytest.mark.parametrize(
    "args",
    [
        (KEY, 0, 65537 * W, W),
        ("x" * 1025, 0, W, W),
        ("[]", 0, W, W),
        (KEY, 1, W, W),
        (KEY, 0, W, 1000),
        (KEY, 0, True, W),
        (KEY, 0, W, True),
    ],
)
def test_invalid_or_unbounded_window_is_rejected(database, args):
    with pytest.raises(ValueError):
        kline_sources.capture_source_window(*args)


def test_empty_window_does_not_manufacture_zero_data(database):
    record(1, closed=False)
    with pytest.raises(BlockUnavailable):
        kline_sources.capture_source_window(KEY, 0, 2 * W, W)


def test_missing_source_journal_is_unavailable_without_creating_schema(database):
    with pytest.raises(BlockUnavailable):
        kline_sources.capture_source_window(KEY, 0, W, W)
    with klines_repo._connect() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='kline_source_heads'"
            ).fetchone()
            is None
        )


def incoming(index, *, quote=2.0, closed=True, ref=None):
    from app.data_engine.bar_aggregator.models import (
        BarInput,
        BarInputSource,
        MergeMode,
    )
    from app.data_engine.market_data.kline_metrics import declared_enhanced_fields

    values = dict(
        open=10.0,
        high=20.0,
        low=5.0,
        close=11.0,
        volume=1.0,
        quote_volume=quote,
        trades=1,
        taker_buy_base=0.5,
        taker_buy_quote=1.0,
    )
    return BarInput(
        symbol="BTCUSDT",
        exchange="binance",
        market_type="futures",
        source_interval="1m",
        source=BarInputSource.CORRECTION,
        merge_mode=MergeMode.COMPONENT,
        open_time_ms=index * W,
        close_time_ms=(index + 1) * W - 1,
        is_closed=closed,
        enhanced_fields=declared_enhanced_fields("binance", "futures", values),
        extra={"source_ref": ref or dict(series=KEY, open_time=index * W, revision=1)},
        **values,
    )


def fold(count, index=0, *, cancel=None, source=None):
    from threading import Event
    from app.data_engine.storage.source_window_summary import fold_source_window

    return fold_source_window(
        KEY, 0, count * W, W, source or incoming(index), cancel or Event()
    )


def test_folding_large_source_only_window_keeps_summary_and_one_leaf(database):
    from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge

    with klines_repo._connect() as conn:
        kline_sources._schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        for i in range(2048):
            record(i, conn=conn)
        conn.commit()
    summary = fold(2048)
    assert len(summary.parts) == 1 and summary.pages == 16
    assert summary.estimated_bytes < 32768
    assert not summary.covers(0) and summary.covers(W) and summary.covers(2047 * W)
    result = summary.merge(
        [ComponentSnapshotOHLCVMerge._snapshot_from_input(incoming(0))]
    )
    assert result.count == 2048 and result.values.quote_volume == 4096
    assert result.coverage(0, 2048 * W).closed
    assert not klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")


def test_sparse_closed_runs_merge_interior_forming_hole_in_time_order(database):
    from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge

    record(0)
    record(1, closed=False)
    record(2)
    record(3)
    summary = fold(4, index=3)
    assert [part.first for part in summary.parts] == [0, 2 * W]
    hole = replace(incoming(1, closed=False), close=19.0)
    latest = replace(incoming(3), close=12.0)
    rows = [ComponentSnapshotOHLCVMerge._snapshot_from_input(v) for v in (hole, latest)]
    result = summary.merge(rows)
    assert result.values.open == 10.0 and result.values.close == 12.0
    assert result.count == 4 and result.values.volume == 4
    assert not result.coverage(0, 4 * W).closed
    assert not summary.covers(W)
    with pytest.raises(ValueError):
        summary.merge([ComponentSnapshotOHLCVMerge._snapshot_from_input(incoming(2))])


def test_folding_rejects_correction_after_final_page_and_cancel(database, monkeypatch):
    from threading import Event

    record(0)
    record(1)
    read = kline_sources.read_source_window_page

    def changed(*a, **kw):
        page = read(*a, **kw)
        record(1, quote=1.0, sequence=4 * W)
        return page

    monkeypatch.setattr(kline_sources, "read_source_window_page", changed)
    with pytest.raises(BlockRevisionChanged):
        fold(2)
    cancel = Event()
    cancel.set()
    with pytest.raises(BlockUnavailable, match="cancelled"):
        fold(2, cancel=cancel)


def test_excessive_source_fragmentation_has_explicit_bounded_failure(database):
    from app.data_engine.memory_budget import MemoryBudgetExceeded

    for i in range(0, 70, 2):
        record(i)
    with pytest.raises(MemoryBudgetExceeded, match="fragmented"):
        fold(70)


def test_source_summary_rejects_stale_incoming_ref_or_mismatched_value(database):
    record(0)
    record(1)
    with pytest.raises(BlockRevisionChanged):
        fold(2, source=incoming(0, ref=dict(series=KEY, open_time=0, revision=9)))
    with pytest.raises(BlockUnavailable):
        fold(2, source=incoming(0, quote=999))


@pytest.mark.parametrize("count", [2, 2048, 10007])
def test_default_manager_cold_rebuild_has_no_native_rows_and_compact_durable_proof(
    database, count
):
    import asyncio
    from app.data_engine.data_manager import DataManager

    async def run():
        with klines_repo._connect() as conn:
            kline_sources._schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            for i in range(count):
                record(i, conn=conn)
            conn.commit()
        manager = DataManager()
        manager.set_storage(klines_repo.KlinesRepoAdapter())
        manager._started = True
        aggregator = manager.bar_aggregator
        interval = str(count) + "m"
        aggregator.add_target("BTCUSDT", interval, market_type="futures")
        try:
            ref = record(0, quote=1.0, sequence=2 * count * W)["ref"]
            await aggregator.ingest_bar_input(
                "binance",
                "futures",
                "BTCUSDT",
                interval,
                incoming(0, quote=1.0, ref=ref),
            )
            await manager.aggregator_bridge.delivery.flush_pending()
            state = aggregator.get_pipeline(interval).bar_state.get_state(
                "binance", "futures", "BTCUSDT", 0
            )
            assert state._source_recovery is not None and state._history_prefix is None
            assert len(state.source_snapshots) == len(state.source_refs) == 1
            assert state.quote_volume == 2 * count - 1 and state.tick_count == count
            assert (
                state.status.value == "closed"
                and state.finality.value == "authoritative"
            )
            stored = klines_repo.query_klines(
                "BTCUSDT", interval, market_type="futures"
            )
            assert len(stored) == 1 and stored[0]["quote_volume"] == 2 * count - 1
            assert stored[0]["source"] == "source_snapshot_verified"
            assert not klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")
            with klines_repo._connect() as conn:
                payloads = [
                    json.loads(r[0])
                    for r in conn.execute("SELECT payload FROM bar_delivery")
                ]
            assert payloads and max(len(json.dumps(p)) for p in payloads) < 6000
            assert all(
                len(p["storage_row"].get("source_refs", [])) <= 1 for p in payloads
            )
            assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
            assert aggregator.memory_usage()["source_recovery_bytes"] > 0
            ref = record(0, quote=3.0, sequence=2 * count * W + 1)["ref"]
            await aggregator.ingest_bar_input(
                "binance",
                "futures",
                "BTCUSDT",
                interval,
                incoming(0, quote=3.0, ref=ref),
            )
            await manager.aggregator_bridge.delivery.flush_pending()
            assert state.quote_volume == 2 * count + 1 and state.tick_count == count
            assert len(state.source_refs) == len(state.source_snapshots) == 1
            stored = klines_repo.query_klines(
                "BTCUSDT", interval, market_type="futures"
            )
            assert len(stored) == 1 and stored[0]["quote_volume"] == 2 * count + 1
        finally:
            await manager.shutdown()

    asyncio.run(run())


def manager_for(interval):
    from app.data_engine.data_manager import DataManager

    manager = DataManager()
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    manager._started = True
    manager.bar_aggregator.add_target("BTCUSDT", interval, market_type="futures")
    return manager


async def feed(manager, interval, value):
    await manager.bar_aggregator.ingest_bar_input(
        "binance", "futures", "BTCUSDT", interval, value
    )
    await manager.aggregator_bridge.delivery.flush_pending()


def test_sparse_cold_builder_keeps_and_then_replaces_interior_forming_hole(
    database, monkeypatch
):
    import asyncio

    clock = [4 * W + 1000]
    monkeypatch.setattr("time.time", lambda: clock[0] / 1000)

    async def run():
        for i in (0, 2, 3):
            record(i)
        manager = manager_for("7m")
        try:
            await feed(manager, "7m", incoming(3))
            state = manager.bar_aggregator.get_pipeline("7m").bar_state.get_state(
                "binance", "futures", "BTCUSDT", 0
            )
            assert state.status.value == "forming" and state.tick_count == 3
            ref = record(1, closed=False, high=100.0)["ref"]
            await feed(
                manager, "7m", replace(incoming(1, closed=False, ref=ref), high=100.0)
            )
            assert (
                state.status.value == "forming"
                and state.high == 100.0
                and state.close == 11.0
            )
            assert state.tick_count == 4 and state.volume == 4
            assert not klines_repo.query_klines("BTCUSDT", "7m", market_type="futures")
            ref = record(1, closed=True, sequence=4 * W + 10)["ref"]
            await feed(manager, "7m", incoming(1, ref=ref))
            assert (
                state.status.value == "forming"
                and state.high == 20.0
                and state.close == 11.0
            )
            assert (
                state.quote_volume == 8
                and state.tick_count == 4
                and len(state.source_refs) == 1
            )
            for i in (4, 5, 6):
                clock[0] = (i + 1) * W + 1000
                ref = record(i)["ref"]
                await feed(manager, "7m", incoming(i, ref=ref))
            assert state.status.value == "closed" and state.tick_count == 7
            stored = klines_repo.query_klines("BTCUSDT", "7m", market_type="futures")
            assert (
                len(stored) == 1
                and stored[0]["high"] == 20.0
                and stored[0]["quote_volume"] == 14
            )
        finally:
            await manager.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["opposite", "target-delete", "source-delete"])
def test_original_writer_rejects_expired_compact_source_proof_after_enqueue(
    database, monkeypatch, mutation
):
    import asyncio

    async def run():
        for i in range(3):
            record(i)
        manager = manager_for("3m")
        journal = manager.aggregator_bridge.delivery.journal
        enqueue = journal.enqueue

        def changed(event_id, payload):
            result = enqueue(event_id, payload)
            if mutation == "opposite":
                record(1, quote=1.0, sequence=9 * W)
                record(2, quote=3.0, sequence=9 * W)
            else:
                klines_repo.delete_klines(
                    "BTCUSDT",
                    "3m" if mutation == "target-delete" else "1m",
                    market_type="futures",
                )
            return result

        monkeypatch.setattr(journal, "enqueue", changed)
        events = []
        recoveries = []

        async def collect(event):
            events.append(event)

        async def recover(error):
            recoveries.append(error)

        manager.event_bus.subscribe(collect, on_recovery=recover)
        try:
            await manager.bar_aggregator.ingest_bar_input(
                "binance", "futures", "BTCUSDT", "3m", incoming(0)
            )
            await manager.aggregator_bridge.delivery.flush()
            assert not klines_repo.query_klines("BTCUSDT", "3m", market_type="futures")
            with klines_repo._connect() as conn:
                receipt = conn.execute(
                    "SELECT phase,recovery_required FROM bar_delivery"
                ).fetchone()
            assert receipt["phase"] == "rejected"
            assert recoveries
            assert recoveries[0].to_dict()['reason'] == 'source_revision_superseded'
            assert not any(
                e.event_type.value in ("bar.closed", "bar.amended") for e in events
            )
            assert kline_sources.pending(
                DESC
            )  # Rebuild/selection never acknowledges the source owner.
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_source_content_permission_is_not_renewed_by_identical_replay(database):
    record(0)
    record(1)
    before = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    klines_repo.delete_klines("BTCUSDT", "2m", market_type="futures")
    record(0, sequence=9 * W)
    record(1, sequence=9 * W)
    same = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    assert same.permission_floor == before.permission_floor == 0
    assert same.acquisition_revision > before.acquisition_revision
    with klines_repo._connect() as conn:
        assert kline_sources.source_window_current(conn, same)
        assert not kline_sources.source_window_allows_target(conn, same, "2m")
    # Fresh changed selected values for every component can carry their own
    # actual source-owner permission; an old sibling cannot borrow this floor.
    record(0, quote=1.0, sequence=10 * W)
    partial = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    with klines_repo._connect() as conn:
        assert not kline_sources.source_window_allows_target(conn, partial, "2m")
    record(1, quote=3.0, sequence=10 * W)
    fresh = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    assert fresh.permission_floor == same.acquisition_revision
    with klines_repo._connect() as conn:
        assert kline_sources.source_window_allows_target(conn, fresh, "2m")


@pytest.mark.parametrize(
    "action", ["cancel", "detach", "rebind", "config", "strategy", "input", "close"]
)
def test_cold_source_worker_keeps_budget_and_cannot_adopt_after_lifetime_change(
    database, monkeypatch, action
):
    import asyncio, threading
    from app.data_engine.aggregation.blocks import BlockRevisionChanged

    async def run():
        for i in range(3):
            record(i)
        manager = manager_for("3m")
        storage = manager.query_engine.storage
        original = storage.fold_source_window
        entered, released = threading.Event(), threading.Event()

        def blocked(*args):
            entered.set()
            assert released.wait(10)
            return original(*args)

        monkeypatch.setattr(storage, "fold_source_window", blocked)
        value = incoming(0)
        task = asyncio.create_task(
            manager.bar_aggregator.ingest_bar_input(
                "binance", "futures", "BTCUSDT", "3m", value
            )
        )
        closing = None
        try:
            async with asyncio.timeout(5):
                while not entered.is_set() and not task.done():
                    await asyncio.sleep(0.01)
            assert entered.is_set() and not task.done()
            assert manager.memory_budget.snapshot()["reserved_bytes"] >= 4 * 1024 * 1024
            if action == "cancel":
                task.cancel()
            elif action == "detach":
                manager.bar_aggregator.remove_target(
                    "BTCUSDT", "3m", market_type="futures"
                )
            elif action == "rebind":
                manager.set_storage(klines_repo.KlinesRepoAdapter())
            elif action == "config":
                manager.bar_aggregator._cfg = replace(
                    manager.bar_aggregator.config, update_throttle_ms=17
                )
            elif action == "strategy":
                manager.bar_aggregator.get_pipeline(
                    "3m"
                ).bar_state._component_merge_strategy.apply = lambda *a, **kw: None
            elif action == "input":
                value.volume = 999
            else:
                closing = asyncio.create_task(manager.history_prefix_runtime.close())
            await asyncio.sleep(0.02)
            assert (
                not task.done()
                and manager.memory_budget.snapshot()["reserved_bytes"] > 0
            )
            released.set()
            result = (await asyncio.gather(task, return_exceptions=True))[0]
            assert isinstance(result, (asyncio.CancelledError, BlockRevisionChanged)), (
                repr(result)
            )
            if closing is not None:
                await closing
            assert not klines_repo.query_klines("BTCUSDT", "3m", market_type="futures")
            assert (
                manager.bar_aggregator.get_pipeline("3m").bar_state.get_state(
                    "binance", "futures", "BTCUSDT", 0
                )
                is None
            )
            assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
        finally:
            released.set()
            await asyncio.gather(task, return_exceptions=True)
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await manager.shutdown()

    asyncio.run(run())


def test_legacy_source_heads_keep_unknown_permission_without_a_read_migration(database):
    record(0)
    record(1)
    with klines_repo._connect() as conn:
        conn.execute("ALTER TABLE kline_source_heads DROP COLUMN permission_floor")
        conn.commit()
    legacy = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    assert legacy.permission_floor == 0
    with klines_repo._connect() as conn:
        assert "permission_floor" not in {
            r[1] for r in conn.execute("PRAGMA table_info(kline_source_heads)")
        }
        assert kline_sources.source_window_allows_target(conn, legacy, "2m")
    klines_repo.delete_klines("BTCUSDT", "2m", market_type="futures")
    after = kline_sources.capture_source_window(KEY, 0, 2 * W, W)
    with klines_repo._connect() as conn:
        assert not kline_sources.source_window_allows_target(conn, after, "2m")
    # Only the original next journal write performs its additive migration.
    record(0, sequence=9 * W)
    with klines_repo._connect() as conn:
        assert "permission_floor" in {
            r[1] for r in conn.execute("PRAGMA table_info(kline_source_heads)")
        }
        assert (
            conn.execute(
                "SELECT MIN(permission_floor) FROM kline_source_heads"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM kline_source_observations").fetchone()[0]
            == 3
        )


def test_reconstruction_budget_refusal_leaves_source_receipts_and_no_builder(
    database, monkeypatch
):
    import asyncio
    from app.data_engine.memory_budget import MemoryBudgetExceeded

    async def run():
        record(0)
        record(1)
        manager = manager_for("2m")
        manager.memory_budget.total_bytes = 1024 * 1024

        def legacy(*args):
            raise AssertionError("budget refusal fell back to the full source window")

        monkeypatch.setattr(
            manager.query_engine.storage, "read_source_components", legacy
        )
        try:
            with pytest.raises(MemoryBudgetExceeded):
                await manager.bar_aggregator.ingest_bar_input(
                    "binance", "futures", "BTCUSDT", "2m", incoming(0)
                )
            assert (
                manager.bar_aggregator.get_pipeline("2m").bar_state.get_state(
                    "binance", "futures", "BTCUSDT", 0
                )
                is None
            )
            assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
            assert manager.memory_budget.snapshot()["admission_rejections"] > 0
            assert len(kline_sources.pending(DESC)) == 2
            assert not klines_repo.query_klines("BTCUSDT", "2m", market_type="futures")
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_cold_builder_compacts_confirmed_live_tail_at_original_128_quantum(
    database, monkeypatch
):
    import asyncio

    clock = [2 * W + 1000]
    monkeypatch.setattr("time.time", lambda: clock[0] / 1000)

    async def run():
        record(0)
        record(1)
        manager = manager_for("10007m")
        events = []

        async def collect(event):
            events.append(event.event_type.value)

        manager.bar_aggregator.publisher.on_bar_event(collect)
        try:
            await feed(manager, "10007m", incoming(0))
            state = manager.bar_aggregator.get_pipeline("10007m").bar_state.get_state(
                "binance", "futures", "BTCUSDT", 0
            )
            for i in range(2, 131):
                clock[0] = (i + 1) * W + 1000
                ref = record(i)["ref"]
                await feed(manager, "10007m", incoming(i, ref=ref))
                assert len(state.source_snapshots) <= 128
            assert (
                state.status.value == "forming"
                and state.tick_count == 131
                and state.volume == 131
            )
            assert (
                state.quote_volume == 262
                and state._source_recovery.version.through_ms == 130 * W
            )
            assert len(state.source_snapshots) == len(state.source_refs) == 2
            assert events == ["bar.created"] + ["bar.updated"] * 129
            assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
        finally:
            await manager.shutdown()

    asyncio.run(run())
