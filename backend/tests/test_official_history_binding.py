"""Bounded immutable day pins shared by ordinary and indexed source readers."""

import json
from pathlib import Path
from threading import Event

import pytest
from app.replay.history_archive import ReplayHistoryArchiveError
from app.replay.official_chart_archive import OfficialChartArchive
from app.replay.official_trade_history import OfficialTradeHistoryRepository

from tests.test_official_trade_history import DAY, MINUTE, START, Archive, loader


def query(repo, revision, day=START):
    return repo.query_bars_at_revision(
        revision,
        "BTCUSDT",
        "1m",
        exchange="binance",
        market_type="futures",
        start_ms=day,
        end_ms=day + 2 * MINUTE,
        limit=3,
    )


def indexed(repo, revision, cancelled):
    return repo.tape_context_market_at_revision(
        revision,
        "BTCUSDT",
        "1m",
        exchange="binance",
        market_type="futures",
        start_ms=START,
        end_ms=START + 3 * MINUTE,
        cancelled=cancelled,
    )


def count_bindings(monkeypatch):
    reads = []
    original = Path.read_text

    def read(path, *args, **kwargs):
        if "bindings" in path.parts:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    return reads


def test_normal_and_indexed_reads_share_pin_and_restart_reloads_it(
    tmp_path, monkeypatch
):
    calls = []
    repo = OfficialTradeHistoryRepository(tmp_path, Archive(), day_loader=loader(calls))
    revision = repo.list_all_series()[0]["source_revision"]
    expected = query(repo, revision)
    reads = count_bindings(monkeypatch)
    market = indexed(repo, revision, Event())
    assert market is not None and market.count == 3
    assert [float(value) for value in market.closes_at((0, 1, 2))] == [
        row["close"] for row in expected
    ]
    repo._day_rows.clear()
    assert query(repo, revision) == expected
    assert indexed(repo, revision, Event()).count == 3
    assert len(reads) == 1 and calls == [START]
    stop = Event()
    stop.set()
    with pytest.raises(InterruptedError):
        indexed(repo, revision, stop)
    assert len(reads) == 1
    restarted = OfficialTradeHistoryRepository(
        tmp_path, Archive(), day_loader=lambda *_: pytest.fail("unexpected download")
    )
    assert query(restarted, revision) == expected
    assert len(reads) == 2


def test_pin_cache_is_bounded_and_eviction_preserves_source(tmp_path, monkeypatch):
    import app.replay.official_chart_archive as module

    monkeypatch.setattr(module, "DAY_BINDING_CACHE_SIZE", 2)
    calls = []
    repo = OfficialTradeHistoryRepository(tmp_path, Archive(), day_loader=loader(calls))
    revision = repo.list_all_series()[0]["source_revision"]
    rows = [query(repo, revision, START + n * DAY) for n in range(3)]
    reads = count_bindings(monkeypatch)
    repo._day_rows.clear()
    for n in range(3):
        assert query(repo, revision, START + n * DAY) == rows[n]
    assert len(repo._archives._day_bindings) == 2
    repo._day_rows.clear()
    assert query(repo, revision) == rows[0]
    assert len(reads) == 4 and len(calls) == 3


@pytest.mark.parametrize("bad", [{"month": "2025-02"}, {"catalog_epoch": "invalid"}])
def test_missing_and_invalid_pins_are_not_cached(tmp_path, bad):
    archive = OfficialChartArchive(tmp_path, 60)
    day = "2025-01-01"
    path = tmp_path / "pin.json"
    assert archive.day_binding(path, day) is None
    good = {"catalog_epoch": "sha256:" + "b" * 64, "month": "2025-01"}
    path.write_text(json.dumps({**good, **bad}))
    with pytest.raises(ReplayHistoryArchiveError):
        archive.day_binding(path, day)
    assert not archive._day_bindings
    path.write_text(json.dumps(good))
    assert archive.day_binding(path, day) == (good["catalog_epoch"], good["month"])
    # The same day in another source revision has its own independent pin.
    second = tmp_path / "another-revision.json"
    second.write_text(json.dumps({"catalog_epoch": "sha256:" + "c" * 64}))
    assert archive.day_binding(second, day) == ("sha256:" + "c" * 64, None)
