"""Pinned official readers avoid discovery without hiding new or invalid data."""

import pytest
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    ReplayHistoryRepository,
)
from app.replay.official_chart_archive import OfficialChartArchive

from tests.fixtures.replay.fakes import make_bar
from tests.test_replay_projection_native_seam import _batch

IDENTITY = ReplaySeriesIdentity("binance", "futures", "LTCUSDT")
START = 1_735_689_600_000
QUERY = {"exchange": "binance", "market_type": "futures", "limit": 1}


def publish(root, price="100", digest="a"):
    return ReplayHistoryArchiveWriter(root).import_batches(
        IDENTITY,
        "1m",
        [
            _batch(
                [make_bar(START, price=price)],
                source_key="day",
                digest_character=digest,
            )
        ],
    )


def read(repo, revision):
    return repo.query_bars_at_revision(revision, "LTCUSDT", "1m", **QUERY)


def test_lazy_reader_discovers_current_on_demand_and_keeps_old_pin(tmp_path):
    first = publish(tmp_path)
    eager = ReplayHistoryRepository(tmp_path)
    assert eager._metrics["refreshes"] == 1
    lazy = ReplayHistoryRepository(tmp_path, discover_current=False)
    assert read(lazy, first.catalog_epoch) == read(eager, first.catalog_epoch)
    assert lazy._metrics["refreshes"] == 0

    second = publish(tmp_path, "900", "b")
    assert lazy.list_all_series()[0]["source_revision"] == second.catalog_epoch
    assert lazy.query_bars("LTCUSDT", "1m", **QUERY)[0]["close"] == 900.5
    assert read(lazy, first.catalog_epoch)[0]["close"] == 100.5

    third = publish(tmp_path, "700", "c")
    assert lazy.query_bars("LTCUSDT", "1m", **QUERY)[0]["close"] == 700.5
    assert lazy.diagnostics()["catalog_epochs"] == (third.catalog_epoch,)
    assert read(lazy, first.catalog_epoch)[0]["close"] == 100.5


def test_official_eviction_reopens_exact_revision_without_current_discovery(
    tmp_path, monkeypatch
):
    root = tmp_path / "first"
    first = publish(root)
    publish(root, "900", "b")
    # A current-catalog outage must not affect an already selected immutable
    # revision, even after bounded repository eviction or process restart.
    current = root / "catalogs/binance/futures/LTCUSDT/1m/current.json"
    current.write_text("incomplete current publication")
    refreshes = []
    original = ReplayHistoryRepository._refresh

    def refresh(owner):
        refreshes.append(owner.root)
        return original(owner)

    monkeypatch.setattr(ReplayHistoryRepository, "_refresh", refresh)
    archive = OfficialChartArchive(tmp_path, 60)
    initial_owner = archive.repository(root)
    expected = read(initial_owner, first.catalog_epoch)
    assert expected[0]["close"] == 100.5
    for number in range(17):
        other_root = tmp_path / f"other-{number}"
        manifest = publish(other_root)
        assert read(archive.repository(other_root), manifest.catalog_epoch) == expected
    assert len(archive._repositories) == 16
    reopened = archive.repository(root)
    assert reopened is not initial_owner
    assert read(reopened, first.catalog_epoch) == expected
    restarted = OfficialChartArchive(tmp_path, 60).repository(root)
    assert read(restarted, first.catalog_epoch) == expected
    assert not refreshes

    # Explicit discovery still observes the bad pointer and reports it.
    assert restarted.list_all_series() == []
    assert len(restarted.diagnostics()["series_errors"]) == 1


@pytest.mark.parametrize("damage", ["manifest", "object", "different_revision"])
def test_pinned_reader_still_rejects_invalid_selected_files(tmp_path, damage):
    manifest = publish(tmp_path)
    if damage == "manifest":
        catalog = tmp_path / "catalogs/binance/futures/LTCUSDT/1m"
        (catalog / f"{manifest.catalog_epoch[7:]}.json").write_text("{}")
    elif damage == "object":
        (tmp_path / manifest.objects[0].relative_path).unlink()
    else:
        newer = publish(tmp_path, "900", "b")
        catalog = tmp_path / "catalogs/binance/futures/LTCUSDT/1m"
        # Valid content at the wrong revision path must never change an old
        # run's selected prices. The manifest's own checksum alone is not enough.
        (catalog / f"{manifest.catalog_epoch[7:]}.json").write_bytes(
            (catalog / f"{newer.catalog_epoch[7:]}.json").read_bytes()
        )
    repo = OfficialChartArchive(tmp_path, 60).repository(tmp_path)
    with pytest.raises(ReplayHistoryArchiveError):
        read(repo, manifest.catalog_epoch)


@pytest.mark.parametrize("objects,selected", [(1, 1), (2, 1), (2, 2)])
def test_background_lane_only_needed_for_unselected_objects(
    tmp_path, monkeypatch, objects, selected
):
    from app.replay.shared_market_index import index_path

    manifest = ReplayHistoryArchiveWriter(tmp_path).import_batches(
        IDENTITY,
        "1m",
        [
            _batch(
                [make_bar(START + n * 60_000)],
                source_key=f"minute-{n}",
                digest_character=str(n + 1),
            )
            for n in range(objects)
        ],
    )
    assert len(manifest.objects) == objects
    repo = OfficialChartArchive(tmp_path, 60).repository(tmp_path)
    backfills = []
    original = repo._backfill_shared_market

    def backfill(*args):
        backfills.append(True)
        original(*args)

    monkeypatch.setattr(repo, "_backfill_shared_market", backfill)
    try:
        market = repo.shared_market_at_revision(
            manifest.catalog_epoch,
            "LTCUSDT",
            "1m",
            start_ms=START,
            end_ms=START + selected * 60_000,
            exchange="binance",
            market_type="futures",
        )
        assert market is not None and market.count == selected
        assert backfills == ([True] if selected < objects else [])
        assert index_path(tmp_path / manifest.objects[0].relative_path).is_file()
    finally:
        repo.close_shared_market_backfill()
