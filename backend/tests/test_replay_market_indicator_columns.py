"""Selected immutable float64 columns, bounded reuse and legacy block fallback."""

from collections import OrderedDict
from threading import Event

import pyarrow.parquet as pq
import pytest
from app.replay import shared_market_columns as columns
from app.replay.history_archive import (
    ReplayHistoryArchiveWriter,
    ReplayHistoryRepository,
)
from app.replay.shared_market_index import MarketRange

from tests.test_replay_history_archive import IDENTITY, START_MS, _batch


@pytest.fixture(autouse=True)
def isolated_column_cache(monkeypatch):
    monkeypatch.setattr(columns, "_columns", OrderedDict())
    monkeypatch.setattr(columns, "_bytes", 0)


def source(root, first=0, count=129):
    manifest = ReplayHistoryArchiveWriter(root).import_batches(
        identity=IDENTITY,
        interval="1m",
        batches=[
            _batch(
                list(range(first, first + count)),
                price_base=100.123456789123,
                source_key="column-source",
                digest_character="a",
            )
        ],
    )
    view = ReplayHistoryRepository(root).shared_market_at_revision(
        manifest.catalog_epoch,
        IDENTITY.symbol,
        "1m",
        exchange=IDENTITY.exchange,
        market_type=IDENTITY.market_type,
        start_ms=START_MS + first * 60000,
        end_ms=START_MS + (first + count) * 60000,
    )
    return view.parts[0][0], view


def test_selected_columns_match_index_across_objects_offsets_and_repeat_reads(
    tmp_path, monkeypatch
):
    first, _ = source(tmp_path / "a")
    second, _ = source(tmp_path / "b", first=1000)
    view = MarketRange([(first, 17, 100), (second, 20, 100)], offset_ms=-946684800000)
    offsets = [0, 20, 82, 83, 161, 1, 83]
    expected = list(map(float, view.closes_at(offsets)))
    original, reads = pq.ParquetFile, []

    def opened(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(pq, "ParquetFile", opened)
    for obj in (first, second):
        monkeypatch.setattr(
            obj, "block", lambda *_: pytest.fail("decoded all OHLCV columns")
        )
    for _ in range(2):
        assert list(map(float, view.indicator_closes_at(offsets, Event()))) == expected
    assert len(reads) == 2
    assert len(columns._columns) == 2
    assert columns._bytes == sum(value.nbytes for value in columns._columns.values())
    with pytest.raises(IndexError):
        view.indicator_closes_at([view.count], Event())
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        view.indicator_closes_at(offsets, cancel)


@pytest.mark.parametrize("bound", ["bytes", "objects"])
def test_column_cache_is_bounded_and_eviction_keeps_source_identity(
    tmp_path, monkeypatch, bound
):
    views = [source(tmp_path / str(i), first=i * 1000)[1] for i in range(3)]
    if bound == "bytes":
        monkeypatch.setattr(columns, "MAX_COLUMN_BYTES", 2200)
    else:
        monkeypatch.setattr(columns, "MAX_COLUMN_OBJECTS", 2)
    for view in [*views, views[0]]:
        assert list(map(float, view.indicator_closes_at([0, 128], Event()))) == list(
            map(float, view.closes_at([0, 128]))
        )
        assert len(columns._columns) <= 2
        assert columns._bytes <= columns.MAX_COLUMN_BYTES


@pytest.mark.parametrize("unavailable", ["oversize", "column_io"])
def test_unsupported_column_read_uses_verified_blocks(
    tmp_path, monkeypatch, unavailable
):
    _, view = source(tmp_path)
    expected = view.closes_at([0, 100])
    if unavailable == "oversize":
        monkeypatch.setattr(columns, "MAX_COLUMN_ROWS", 1)
    else:

        def fail(*_):
            raise OSError("optional column unavailable")

        monkeypatch.setattr(pq, "ParquetFile", fail)
    assert view.indicator_closes_at([0, 100], Event()) == expected
    assert not columns._columns


def test_financial_closes_do_not_depend_on_indicator_column_cache(
    tmp_path, monkeypatch
):
    _, view = source(tmp_path)
    expected = view.closes_at([0, 128])
    monkeypatch.setattr(
        columns, "selected_closes", lambda *_: pytest.fail("financial column shortcut")
    )
    assert view.closes_at([0, 128]) == expected
