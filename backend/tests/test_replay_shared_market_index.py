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
