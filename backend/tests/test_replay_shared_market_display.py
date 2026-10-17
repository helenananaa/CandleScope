"""Chart-only summaries preserve the full immutable index's display contract."""

import sqlite3
from decimal import localcontext
from random import Random

import pytest
from app.replay import shared_market_index as module
from app.replay.shared_market_display import summarize_display

from tests.test_replay_shared_market_index import market


@pytest.mark.parametrize("offset", [0, -946_684_800_000])
def test_display_ranges_equal_full_summary_with_partial_blocks_and_gaps(
    tmp_path, offset
):
    obj, _ = market(tmp_path, 2049)
    view = module.MarketRange([(obj, 23, 900), (obj, 980, 2049)], offset_ms=offset)
    rng = Random(275)
    bounds = [(0, view.count), (0, 1), (233, 489), (876, 878)]
    for _ in range(70):
        start = rng.randrange(view.count)
        bounds.append((start, rng.randrange(start + 1, view.count + 1)))
    with localcontext() as context:
        context.prec = 9
        for start, end in bounds:
            assert view.display_summary(start, end) == view.summary(start, end)[0]
    assert view.display_summary(0, view.count)[12] is False
    assert view.display_summary(2, 2) is None
    with pytest.raises(ValueError):
        view.display_summary(-1, 2)
    with pytest.raises(ValueError):
        obj.display_summary(0, obj.count + 1)


@pytest.mark.parametrize("missing", [None, 7, 8, 9, 10])
def test_display_columns_preserve_optional_nulls_and_extreme_exact_decimals(missing):
    rows = [
        (
            i * 60000,
            (i + 1) * 60000 - 1,
            "9.12e-75",
            "1.23456789e+150",
            "1e-90",
            "3.14159e-20",
            "1.23456789e+200" if i % 2 else "1.23456789e-200",
            "0.000123456789123456789",
            10**30 + i,
            "1.01",
            "0.00004",
            "test",
        )
        for i in range(256)
    ]
    if missing is not None:
        row = list(rows[150])
        row[missing] = None
        rows[150] = tuple(row)
    with localcontext() as context:
        context.prec = 7
        expected = module.summarize(rows, 60000)[0]
        assert summarize_display(rows, 60000) == expected
        assert summarize_display(rows, 60000, include_auxiliary=False) == (
            *expected[:5], None, None, None, None, *expected[9:]
        )


def test_display_partial_blocks_do_not_compute_financial_price_paths(
    tmp_path, monkeypatch
):
    obj, view = market(tmp_path, 2049)
    bounds = [(3, 20), (249, 263), (41, 2010), (0, 2049)]
    expected = [view.summary(a, b)[0] for a, b in bounds]

    def forbidden(*_):
        pytest.fail("chart request computed account price extrema")

    monkeypatch.setattr(module, "summarize", forbidden)
    monkeypatch.setattr(module, "merge", forbidden)
    for (start, end), value in zip(bounds, expected):
        assert view.display_summary(start, end) == value
    for start in range(150):
        view.display_summary(start, start + 2)
    assert len(obj._summaries) <= 128


def test_display_partial_block_repairs_corrupt_derived_index(tmp_path):
    from app.replay.history_archive import (
        ReplayHistoryArchiveWriter,
        ReplayHistoryRepository,
    )

    from tests.test_replay_history_archive import IDENTITY, START_MS, _batch

    manifest = ReplayHistoryArchiveWriter(tmp_path).import_batches(
        identity=IDENTITY,
        interval="1m",
        batches=[
            _batch(
                list(range(512)),
                price_base=100,
                source_key="display-repair",
                digest_character="e",
            )
        ],
    )
    view = ReplayHistoryRepository(tmp_path).shared_market_at_revision(
        manifest.catalog_epoch,
        IDENTITY.symbol,
        "1m",
        exchange=IDENTITY.exchange,
        market_type=IDENTITY.market_type,
        start_ms=START_MS,
        end_ms=START_MS + 512 * 60000,
    )
    expected = view.summary(17, 201)[0]
    obj = view.parts[0][0]
    with sqlite3.connect(obj.path) as connection:
        connection.execute("UPDATE blocks SET value=? WHERE id=0", (b"broken",))
    connection.close()
    obj._blocks.clear()
    assert view.display_summary(17, 201) == expected
    assert view.summary(0, 512)[0] == view.display_summary(0, 512)
