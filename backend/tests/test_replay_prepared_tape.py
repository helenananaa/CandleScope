from decimal import Decimal
from types import SimpleNamespace
import random

import pytest

from app.replay.sources.prepared_tape import plan
from app.replay.sources.trade_reader import PagedReplayTradeReader
from app.replay.sources.trade_source import TradeReplaySource
from app.replay.training.multi_interval import ordered_equity_summary
from tests.fixtures.replay.trade_fakes import (
    START_MS, FakeRawAggTradeArchive, make_trade_dataset, make_trade_row,
)
from tests.test_replay_multi_interval import leg


@pytest.mark.parametrize("blind", [False, True])
@pytest.mark.parametrize("prefix", [0, 1, 4])
def test_prepared_positions_share_pages_without_consuming_again(blind, prefix, monkeypatch):
    rows = [make_trade_row(i) for i in range(20)]
    source = TradeReplaySource(PagedReplayTradeReader(
        FakeRawAggTradeArchive(rows), make_trade_dataset(20),
        page_rows=3, validate_generation=False,
    ), blind_mode=blind, time_offset_ms=1000)
    for _ in range(prefix):
        source.next()
    actor = SimpleNamespace(_source=source, _revision=7, _cursor_dict=lambda: {})
    reference = source.fork()
    prepared = plan(actor, START_MS + 1000000, 15)["prepared_tape"]
    assert len(prepared.sources) <= 6
    for i in range(16):
        actual = prepared.position(i)
        assert actual.cursor() == reference.cursor()
        assert actual.actual_cursor == reference.actual_cursor
        assert actual.peek() == reference.peek()
        if i < 15:
            assert reference.next() == prepared.trades[i]
    target = prepared.trades[6].trade_time_ms
    selected = prepared.slice(0, 7, 7, target)
    selected.validate(actor, target)
    with pytest.raises(ValueError, match="basis changed"):
        selected.validate(actor, target + 1)
    actor._revision += 1
    with pytest.raises(ValueError, match="basis changed"):
        selected.validate(actor, target)
    actor._revision -= 1
    actor._source = source.fork()
    actor._source.next()
    with pytest.raises(ValueError, match="basis changed"):
        selected.validate(actor, target)
    def forbidden(*args):
        raise AssertionError("prepared positioning rescanned the source")
    monkeypatch.setattr(TradeReplaySource, "next", forbidden)
    for i in range(16):
        prepared.position(i)


def test_prepared_slice_rejects_split_cohort_and_terminal():
    rows = [make_trade_row(i, trade_time_ms=START_MS + i // 2) for i in range(6)]
    source = TradeReplaySource(PagedReplayTradeReader(
        FakeRawAggTradeArchive(rows), make_trade_dataset(6),
        page_rows=3, validate_generation=False,
    ))
    actor = SimpleNamespace(_source=source, _revision=0, _cursor_dict=lambda: {})
    block = plan(actor, START_MS + 100000, 6)["prepared_tape"]
    with pytest.raises(ValueError, match="complete nonterminal cohort"):
        block.slice(0, 1, 0, START_MS)
    block.slice(0, 2, 0, START_MS)
    with pytest.raises(ValueError, match="complete nonterminal cohort"):
        block.slice(0, 6, 0, START_MS + 2)


@pytest.mark.parametrize("precision", ["0.01", "0.000000000000000000000000000001"])
def test_partitioned_summary_matches_independent_phase_valuation(precision):
    rng = random.Random(149)
    positions = [leg("a", quantity=precision), leg("b", "SHORT", quantity="0.7")]
    initial = {"a": Decimal("100"), "b": Decimal("100")}
    events = [(i // 3 + 1, 20, "ab"[i % 2], i + 1,
               Decimal(rng.randrange(50, 150)) + Decimal(precision)) for i in range(120)]
    args = dict(cash=Decimal("10000"), legs=positions, initial_prices=initial)
    full = ordered_equity_summary(**args, events=events, _partition_after=(0, 20))
    pivot = full["partition_time_ms"]
    for ordinal, subset in enumerate((
        [e for e in events if e[0] <= pivot], [e for e in events if e[0] > pivot],
    )):
        expected = ordered_equity_summary(**args, events=subset)
        actual = full["partitions"][ordinal]
        for key in ("first", "last", "peak", "trough", "max_drawdown"):
            assert Decimal(actual[key]) == Decimal(expected[key])
        assert actual["events"] == expected["events"]
        assert actual["trough_time_ms"] == expected["trough_time_ms"]
        for e in sorted(subset, key=lambda e: e[:4]):
            initial[e[2]] = e[4]
