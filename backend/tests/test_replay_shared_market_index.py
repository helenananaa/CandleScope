from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
import random

import pytest

from app.replay.shared_market_index import build, open_object, MarketRange, summarize
from app.replay.broker.shared_prepared import SharedPreparedInterval, account_sample
from app.replay.bars.builder import ReplayBarBuilder
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.dataset import ReplayBar
from app.replay.broker.models import LedgerAccount, LedgerKind
from tests.fixtures.replay.broker_fakes import make_broker, request


def market(tmp_path, count=2049):
    rng = random.Random(942)
    rows = []
    for i in range(count):
        close = str(rng.randrange(90, 120))
        rows.append(
            {
                "open_time": i * 60000,
                "close_time": (i + 1) * 60000 - 1,
                "open": close,
                "high": str(int(close) + 2),
                "low": str(int(close) - 2),
                "close": close,
                "volume": "0.1",
                "source": "fixture",
            }
        )
    source = tmp_path / "source.parquet"
    source.write_bytes(b"immutable-test-source")
    digest = "sha256:" + sha256(source.read_bytes()).hexdigest()
    build(
        source,
        digest,
        "1m",
        ReplaySeriesIdentity("binance", "futures", "BTCUSDT"),
        rows,
    )
    obj = open_object(source, digest)
    return obj, MarketRange([(obj, 0, count)])


def test_shared_ranges_match_linear_summaries_and_touches(tmp_path):
    obj, view = market(tmp_path)
    rng = random.Random(943)
    for _ in range(80):
        a = rng.randrange(view.count)
        b = rng.randrange(a + 1, view.count + 1)
        assert view.summary(a, b) == summarize(
            [view.row(i) for i in range(a, b)], 60000
        )
        assert view.summary(a, b, prices_only=True)[1:] == view.summary(a, b)[1:]
        price = Decimal(rng.randrange(85, 125))
        below = rng.choice([True, False])
        expected = (
            next((i for i in range(a, b) if Decimal(view.row(i)[4]) <= price), b)
            if below
            else next((i for i in range(a, b) if Decimal(view.row(i)[3]) >= price), b)
        )
        assert view.first_touch(price, below, a, b) == expected
    assert obj.bound(0) == 0
    assert obj.bound(0, right=True) == 1


def test_whole_block_query_does_not_read_rows(tmp_path, monkeypatch):
    obj, view = market(tmp_path, 4096)
    monkeypatch.setattr(obj, "block", lambda *_: pytest.fail("full range scanned rows"))
    assert view.summary(0, 4096)[0][9] == 4096


@pytest.mark.parametrize("count", [4096, 3001])
def test_prepared_small_tree_does_not_issue_per_node_queries(tmp_path, monkeypatch, count):
    obj, view = market(tmp_path, count)
    view.prepare_nodes()
    assert 1 in obj._nodes and len(obj._nodes) <= obj.metadata["size"]*2-1
    original = obj._fetch
    def fetch(table,key):
        assert table != "nodes", "warm range repeated a node SELECT"
        return original(table,key)
    monkeypatch.setattr(obj,"_fetch",fetch)
    for start,end in ((256,768),(1024,2048),(1280,2816)):
        assert view.summary(start,end) == summarize([view.row(i) for i in range(start,end)],60000)


def test_range_time_directory_preserves_slices_gaps_offsets_without_midpoint_reads(tmp_path, monkeypatch):
    from bisect import bisect_left, bisect_right
    obj, _ = market(tmp_path, 4096)
    view = MarketRange([(obj, 50, 1300), (obj, 1800, 4000)], offset_ms=1234)
    opens = [view.row(i)[0] for i in range(view.count)]
    original = obj.block
    calls = []
    def block(number):
        calls.append(number)
        return original(number)
    monkeypatch.setattr(obj, "block", block)
    for raw in (0, 49, 50, 800, 1299, 1300, 1500, 1800, 2900, 3999, 4000, 5000):
        for shift in (-1, 0, 1):
            at = raw*60000+1234+shift
            for right in (False, True):
                expected = (bisect_right if right else bisect_left)(opens, at)
                calls.clear()
                assert view.bound(at, right=right) == expected
                assert set(calls).issubset({min(max(0, raw//256), 15)}) or raw>=4096


def test_shared_end_uses_actual_calendar_closes_and_preserves_terminal_exclusion():
    from bisect import bisect_right
    day = 86400000
    opens = [0, 28*day, 59*day]
    closes = [28*day-1, 59*day-1, 89*day-1]
    prepared = object.__new__(SharedPreparedInterval)
    prepared.market = SimpleNamespace(count=3,
        bound=lambda at,right=False:bisect_right(opens,at), row=lambda i:(opens[i],closes[i]))
    for terminal in (False, True):
        prepared.terminal = terminal
        for target in (-1, 0, 27*day, 28*day-1, 28*day, 59*day-1, 90*day):
            assert prepared.end_for_time(target) == min(bisect_right(closes,target),3-int(terminal))


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_shared_jump_financial_results_and_checkpoint_restore(tmp_path, side):
    obj, full = market(tmp_path, 4097)
    fast, slow = make_broker(), make_broker()
    for broker in (fast, slow):
        broker._bar_builder = ReplayBarBuilder(
            base_interval="1m",
            display_interval="1m",
            replay_start_ms=0,
            warmup_bars=(),
            max_closed_bars=32,
        )
        broker.place_order(
            request(client_order_id="open", side=side), command_id="open"
        )
        broker.apply_bar(ReplayBar(*full.row(0)))
    view = MarketRange([(obj, 1, full.count)])

    class Source:
        _index = 1
        _archive = SimpleNamespace(
            shared_factory=lambda a, b: MarketRange(
                [(obj, obj.bound(a), obj.bound(b))]
            ),
            open_at_index=lambda i: i * 60000,
        )

        def cursor(self):
            return SimpleNamespace(source_sequence=1)

        def snapshot_ref(self):
            return {"source_revision": "revision"}

        def shared_market_range(self):
            return view, True

    index = SharedPreparedInterval(Source(), fast, "sha256:" + "0" * 64)
    assert "samples" not in index.valuation
    index.apply(fast, 0, 4095)
    for i in range(1, 4096):
        slow.apply_bar(ReplayBar(*full.row(i)))
    a, b = fast.snapshot(), slow.snapshot()
    for key in a:
        if key not in {"bar_builder", "state_hash"}:
            assert a[key] == b[key], key
    restored = make_broker()
    restored._bar_builder = ReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=0,
        warmup_bars=(),
        max_closed_bars=32,
    )
    restored.restore(a)
    assert restored.snapshot() == a
    for i in (0, 1, 100, 4094):
        assert (
            account_sample(index.valuation["basis"], view.row(i)[5])[1]
            == fast._account.cash_balance
        )


def test_imported_index_is_reused_without_reading_parquet(tmp_path, monkeypatch):
    from app.replay.history_archive import (
        ReplayHistoryArchiveWriter,
        ReplayHistoryRepository,
    )
    from app.replay import shared_market_index as module
    from tests.test_replay_history_archive import _batch, IDENTITY, START_MS

    writer = ReplayHistoryArchiveWriter(tmp_path)
    manifest = writer.import_batches(
        identity=IDENTITY,
        interval="1m",
        batches=[
            _batch(
                list(range(600)),
                price_base=100,
                source_key="shared",
                digest_character="a",
            )
        ],
    )
    repository = ReplayHistoryRepository(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("opening a shared index reread Parquet")

    monkeypatch.setattr(module, "repair_object", forbidden)
    monkeypatch.setattr(repository, "_read_object", forbidden)
    kwargs = dict(
        exchange=IDENTITY.exchange,
        market_type=IDENTITY.market_type,
        start_ms=START_MS + 100 * 60000,
        end_ms=START_MS + 500 * 60000,
    )
    a = repository.shared_market_at_revision(
        manifest.catalog_epoch, IDENTITY.symbol, "1m", **kwargs
    )
    module._readers.clear()
    b = repository.shared_market_at_revision(
        manifest.catalog_epoch, IDENTITY.symbol, "1m", offset_ms=1234, **kwargs
    )
    assert a.count == b.count == 400
    assert b.row(0)[0] == a.row(0)[0] + 1234
    assert MarketRange.restore(a.descriptor()).summary(0, 400) == a.summary(0, 400)


def test_corrupt_derived_node_rebuilds_from_immutable_object(tmp_path):
    import sqlite3
    from app.replay.history_archive import (
        ReplayHistoryArchiveWriter,
        ReplayHistoryRepository,
    )
    from app.replay import shared_market_index as module
    from tests.test_replay_history_archive import _batch, IDENTITY, START_MS

    manifest = ReplayHistoryArchiveWriter(tmp_path).import_batches(
        identity=IDENTITY,
        interval="1m",
        batches=[
            _batch(
                list(range(512)),
                price_base=100,
                source_key="repair",
                digest_character="b",
            )
        ],
    )
    repository = ReplayHistoryRepository(tmp_path)
    view = repository.shared_market_at_revision(
        manifest.catalog_epoch,
        IDENTITY.symbol,
        "1m",
        exchange=IDENTITY.exchange,
        market_type=IDENTITY.market_type,
        start_ms=START_MS,
        end_ms=START_MS + 512 * 60000,
    )
    expected = view.summary(0, 512)
    obj = view.parts[0][0]
    with sqlite3.connect(obj.path) as c:
        c.execute("UPDATE nodes SET value=? WHERE id=1", (b"broken",))
    c.close()
    obj._nodes.clear()
    assert view.summary(0, 512) == expected
    assert module.open_object(obj.source_path, obj.object_hash).count == 512


def test_background_backfill_is_cancellable_and_deduplicated(tmp_path, monkeypatch):
    import threading
    from app.replay import shared_market_index as module

    started = threading.Event()
    calls = []

    def repair(path, digest, *, stop):
        calls.append(path)
        started.set()
        assert stop.wait(2)
        return None

    monkeypatch.setattr(module, "repair_object", repair)
    one, two = tmp_path / "one", tmp_path / "two"
    one.touch()
    two.touch()
    worker = module.BackgroundIndexBuilder()
    worker.submit([(one, "hash"), (one, "hash"), (two, "hash")])
    assert started.wait(2)
    thread = worker.thread
    worker.close()
    assert not thread.is_alive()
    assert calls == [one]


def test_optional_index_write_failure_keeps_archive_usable(tmp_path, monkeypatch):
    from app.replay.history_archive import (
        ReplayHistoryArchiveWriter,
        ReplayHistoryRepository,
    )
    from app.replay import shared_market_index as module
    from tests.test_replay_history_archive import _batch, IDENTITY, START_MS

    def fail(*args, **kwargs):
        raise OSError("read-only index storage")

    monkeypatch.setattr(module, "build", fail)
    manifest = ReplayHistoryArchiveWriter(tmp_path).import_batches(
        identity=IDENTITY,
        interval="1m",
        batches=[
            _batch(
                list(range(10)),
                price_base=100,
                source_key="readonly",
                digest_character="c",
            )
        ],
    )
    repository = ReplayHistoryRepository(tmp_path)
    assert (
        repository.shared_market_at_revision(
            manifest.catalog_epoch,
            IDENTITY.symbol,
            "1m",
            exchange=IDENTITY.exchange,
            market_type=IDENTITY.market_type,
            start_ms=START_MS,
            end_ms=START_MS + 10 * 60000,
        )
        is None
    )
    assert (
        len(
            repository.query_bars_at_revision(
                manifest.catalog_epoch,
                IDENTITY.symbol,
                "1m",
                exchange=IDENTITY.exchange,
                market_type=IDENTITY.market_type,
            )
        )
        == 10
    )


def test_ordinary_dual_leg_uses_market_summary_not_per_bar(tmp_path, monkeypatch):
    from app.replay.broker.shared_prepared import AccountRanges
    from app.replay.broker.prepared_interval import EquityRanges

    _, view = market(tmp_path, 10_000)
    cases = (
        {"legs": [["1", "100"], ["-1", "100"]], "cash": "10000"},
        {"legs": [["2", "100"], ["-0.5", "102"]], "cash": "10000"},
    )
    for basis in cases:
        expected = EquityRanges(
            [Decimal(account_sample(basis, view.row(i)[5])[0]) for i in range(10_000)]
        ).query(0, 10_000)
        calls = []
        original = view.row

        def row(i, captured=calls, inner=original):
            captured.append(i)
            return inner(i)

        monkeypatch.setattr(view, "row", row)
        result = AccountRanges(SimpleNamespace(market=view), basis).query(0, 10_000)
        assert result == expected
        assert len(calls) < 10_000
        monkeypatch.setattr(view, "row", original)


def test_prepare_valuation_cache_key_skips_full_ledger_snapshot(tmp_path, monkeypatch):
    obj, full = market(tmp_path, 513)
    broker = make_broker()
    broker._bar_builder = ReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=0,
        warmup_bars=(),
        max_closed_bars=32,
    )
    broker.place_order(request(client_order_id="open"), command_id="open")
    broker.apply_bar(ReplayBar(*full.row(0)))
    view = MarketRange([(obj, 1, full.count)])

    class Source:
        _index = 1
        _archive = SimpleNamespace(
            shared_factory=lambda a, b: MarketRange(
                [(obj, obj.bound(a), obj.bound(b))]
            ),
            open_at_index=lambda i: i * 60000,
        )

        def cursor(self):
            return SimpleNamespace(source_sequence=1)

        def snapshot_ref(self):
            return {"source_revision": "revision"}

        def shared_market_range(self):
            return view, True

    index = SharedPreparedInterval(Source(), broker, "sha256:" + "0" * 64)
    snapshots = {"count": 0}
    original_snapshot = broker._ledger.snapshot

    def counting_snapshot():
        snapshots["count"] += 1
        return original_snapshot()

    monkeypatch.setattr(broker._ledger, "snapshot", counting_snapshot)
    first = index.prepare_valuation(broker)
    second = index.prepare_valuation(broker)
    assert second is first
    assert snapshots["count"] == 0
    broker._ledger.post(
        kind=LedgerKind.FEE,
        source_sequence=2,
        event_time_ms=2,
        postings=(
            (LedgerAccount.CASH, "-1"),
            (LedgerAccount.FEE_EXPENSE, "1"),
        ),
    )
    third = index.prepare_valuation(broker)
    assert third is not first
    assert snapshots["count"] == 0


def test_index_node_and_block_fetches_reuse_thread_connection(tmp_path, monkeypatch):
    from app.replay import shared_market_index as module

    obj, _ = market(tmp_path, 2049)
    obj._reset_connection()
    obj._blocks.clear()
    obj._nodes.clear()
    connects = []
    original = module.sqlite3.connect

    def counting(*args, **kwargs):
        connects.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", counting)
    first_node = obj._fetch("nodes", 1)
    first_block = obj._fetch("blocks", 0)
    for _ in range(40):
        assert obj._fetch("nodes", 1) == first_node
        assert obj._fetch("blocks", 0) == first_block
    assert len(connects) == 1
    assert len(connects) < 80


def test_rebuild_does_not_keep_foreign_thread_on_replaced_index(tmp_path):
    import threading
    from app.replay import shared_market_index as module

    obj, _ = market(tmp_path, 256)
    original = obj._fetch("blocks", 0)
    started = threading.Event()
    release = threading.Event()
    seen = {}

    def hold():
        try:
            obj._fetch("blocks", 0)
            started.set()
            assert release.wait(5)
            seen["blocks"] = obj._fetch("blocks", 0)
        except Exception as exc:
            seen["error"] = exc

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(5)
    rows = []
    rng = random.Random(1001)
    for i in range(256):
        close = str(rng.randrange(200, 250))
        rows.append(
            {
                "open_time": i * 60000,
                "close_time": (i + 1) * 60000 - 1,
                "open": close,
                "high": str(int(close) + 2),
                "low": str(int(close) - 2),
                "close": close,
                "volume": "0.1",
                "source": "fixture",
            }
        )
    build(
        obj.source_path,
        obj.object_hash,
        "1m",
        ReplaySeriesIdentity("binance", "futures", "BTCUSDT"),
        rows,
    )
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert "error" not in seen
    assert seen["blocks"] != original
    assert open_object(obj.source_path, obj.object_hash)._fetch("blocks", 0) == seen["blocks"]


def test_index_connection_cache_evicts_idle_handles(tmp_path, monkeypatch):
    from app.replay import shared_market_index as module

    monkeypatch.setattr(module, "_MAX_INDEX_CONNECTIONS", 2)
    objects = []
    for i in range(3):
        folder = tmp_path / str(i)
        folder.mkdir()
        obj, _ = market(folder, 256)
        obj._fetch("nodes", 1)
        objects.append(obj)
        if i == 0:
            first_wrapper = module._thread_index_connections()[str(obj.path)]
    cache = module._thread_index_connections()
    assert len(cache) == 2
    assert str(objects[0].path) not in cache
    assert first_wrapper.retired
    assert first_wrapper.connection is None
    objects[0]._fetch("nodes", 1)
    assert str(objects[0].path) in cache
    assert len(cache) == 2


def test_index_connections_do_not_outlive_owner_thread(tmp_path):
    import gc
    import os
    import threading
    from app.replay import shared_market_index as module

    obj, _ = market(tmp_path, 256)
    obj._reset_connection()
    gc.collect()
    key = str(obj.path)

    def use():
        obj._fetch("nodes", 1)

    thread = threading.Thread(target=use)
    thread.start()
    thread.join()
    gc.collect()
    assert list(module._path_state(key).connections) == []
    temporary = obj.path.with_name(obj.path.name + ".swap")
    os.replace(obj.path, temporary)
    os.replace(temporary, obj.path)


def test_high_precision_account_uses_exact_scalar_fallback(tmp_path, monkeypatch):
    from app.replay.broker.shared_prepared import AccountRanges
    from app.replay.broker.prepared_interval import EquityRanges

    _, view = market(tmp_path, 512)
    basis = {"legs": [["0.000000000000000000000000000001", "100"]], "cash": "100000"}
    expected = [Decimal(account_sample(basis, view.row(i)[5])[0]) for i in range(512)]
    calls = []
    original = view.row

    def row(i):
        calls.append(i)
        return original(i)

    monkeypatch.setattr(view, "row", row)
    assert AccountRanges(SimpleNamespace(market=view), basis).query(
        0, 512
    ) == EquityRanges(expected).query(0, 512)
    assert len(calls) == 512


def test_shared_source_checks_each_verified_contiguous_segment(tmp_path):
    from app.replay.sources.bar_source import PagedBarReplaySource

    obj, view = market(tmp_path, 512)
    rows = []
    for i in range(512):
        value = ReplayBar(*view.row(i)).to_dict()
        shift = 5 * 60000 if i >= 256 else 0
        rows.append(
            {
                **value,
                "open_time": value["open_time_ms"] + shift,
                "close_time": value["close_time_ms"] + shift,
            }
        )
    build(
        obj.source_path,
        obj.object_hash,
        "1m",
        ReplaySeriesIdentity("binance", "futures", "BTCUSDT"),
        rows,
    )
    obj = open_object(obj.source_path, obj.object_hash)
    view = MarketRange([(obj, 0, 512)])
    source = object.__new__(PagedBarReplaySource)
    source._index = 0
    source._archive = SimpleNamespace(
        total_rows=512,
        interval_ms=60000,
        shared_factory=lambda a, b: view,
        open_at_index=lambda i: (i + (5 if i >= 256 else 0)) * 60000,
        _segments=[
            SimpleNamespace(start_index=0, end_index=256),
            SimpleNamespace(start_index=256, end_index=512),
        ],
    )
    assert source.shared_market_range()[0] is view
    source._archive._segments = [SimpleNamespace(start_index=0, end_index=512)]
    assert source.shared_market_range() is None


def test_prepared_source_peek_reuses_verified_rows_without_raw_page(tmp_path):
    from app.replay.sources.bar_source import PagedBarReplaySource, _PagedBarArchive, _IndexedBarSegment

    _, view = market(tmp_path, 512)
    archive = object.__new__(_PagedBarArchive)
    archive.total_rows, archive.interval_ms = 512, 60000
    archive.initial_rows = tuple(ReplayBar(*view.row(i)) for i in range(2))
    archive._segments = (_IndexedBarSegment(0, 511*60000, 0, 512),)
    archive._segment_start_indexes = (0,)
    archive._shared_ranges, archive._shared_cached_row = (), None
    archive.shared_factory = lambda a,b:view
    archive.page_loader = lambda *args:pytest.fail("prepared peek loaded a raw page")
    source = object.__new__(PagedBarReplaySource)
    source._archive, source._index = archive, 0
    assert source.shared_market_range()[1] is True
    source._index = 510
    expected = ReplayBar(*view.row(510))
    assert source.peek() == expected
    assert source.next() is archive._shared_cached_row[1]
    assert source.peek() == ReplayBar(*view.row(511))
    assert source.next() is not None
    assert source.peek() is None
    # The exact reader still checks the committed schedule, not just count.
    archive._shared_cached_row = None
    archive.open_at_index = lambda i:i*60000+1
    with pytest.raises(Exception, match="committed schedule"):
        archive.row_at(510)
