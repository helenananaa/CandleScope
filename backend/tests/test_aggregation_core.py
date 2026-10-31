"""Independent expectations and cross-path contracts for the K130 stage."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from pathlib import Path
from decimal import Decimal
import random
import subprocess
import sys

import pytest

from app.data_engine.aggregation.core import (
    AcceptedComponent, InputRevision, combine, summarize,
)
from app.data_engine.aggregation.semantics import ClosePolicy, Coverage
from app.data_engine.bar_aggregator.bar_state import (
    ComponentSnapshotOHLCVMerge, has_complete_closed_component_coverage,
)
from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, BarState
from app.data_engine.data_manager.custom_query import (
    CustomIntervalQueryService, _aggregate_fixed_bars_to_interval, _aggregate_rows_to_interval,
)
from app.data_engine.data_manager.history_stream import FixedHistoryStream
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.interval_policy import aggregate_kline_rows, parse_interval_spec

SOURCE = SeriesKey("BTC-USDT", "1m", exchange="okx", market_type="spot")
TARGET = replace(SOURCE, interval="7m")


def bar(index, *, closed=True):
    volume = round((index + 1) * 0.123456789, 8)
    return BarData(
        time=index * 60, open=100 + index, high=103 + index, low=99 + index,
        close=101 + index, volume=volume, quote_volume=volume * 100,
        trades=index, taker_buy_base=volume / 2, taker_buy_quote=volume * 50,
        is_closed=closed, source="backfill",
    )


def accepted(bars, *, series=SOURCE, revision=17):
    spec = parse_interval_spec(series.interval)
    return [AcceptedComponent(series, value, spec.next_ms(value.time_ms),
                              InputRevision(series, "fixture-store", revision)) for value in bars]


def state_for(target=TARGET, start=0, end=420_000):
    return BarState(
        symbol=target.symbol, exchange=target.exchange, market_type=target.market_type,
        interval=target.interval, bucket_start_ms=start, bucket_end_ms=end,
        open=0, high=0, low=0, close=0, volume=0,
    )


def live_input(value, *, sequence=1, source=BarInputSource.BACKFILL):
    return BarInput(
        symbol=SOURCE.symbol, source_interval=SOURCE.interval, exchange=SOURCE.exchange,
        market_type=SOURCE.market_type, open_time_ms=value.time_ms,
        close_time_ms=value.time_ms + 59_999,
        open=value.open, high=value.high, low=value.low, close=value.close, volume=value.volume,
        is_closed=value.is_closed, quote_volume=value.quote_volume or 0,
        trades=value.trades or 0, taker_buy_base=value.taker_buy_base or 0,
        taker_buy_quote=value.taker_buy_quote or 0, enhanced_fields=value.enhanced_fields,
        sequence=sequence, source=source,
    )


@pytest.mark.parametrize("seed", range(12))
def test_arbitrary_grouping_order_and_page_boundaries_match_decimal_reference(seed):
    rng = random.Random(seed)
    bars = [bar(i) for i in range(101)]
    target = replace(TARGET, interval="101m")
    components = accepted(bars)
    shuffled = list(components)
    rng.shuffle(shuffled)
    whole = summarize(shuffled, target=target)
    # Independently computed expected additive value, not another reducer.
    expected_volume = float(sum(Decimal(str(value.volume)) for value in bars))
    assert whole.values.volume == pytest.approx(expected_volume, rel=1e-12, abs=1e-8)
    assert whole.values.open == 100
    assert whole.values.close == 201
    assert whole.values.high == 203
    assert whole.values.low == 99
    assert whole.values.trades == sum(range(101))
    assert whole.evaluate(0, 101 * 60_000).closed
    assert whole.is_authoritative(0, 101 * 60_000)
    assert whole.coverage.ranges == ((0, 101 * 60_000),)
    assert len(whole.revisions) == 1
    cuts = sorted({0, 101, *(rng.randrange(1, 101) for _ in range(15))})
    parts = [summarize(components[a:b], target=target) for a, b in zip(cuts, cuts[1:])]
    grouped = combine(parts)
    assert grouped.coverage == whole.coverage
    assert grouped.revisions == whole.revisions
    assert grouped.values.project() == whole.values.project()
    # Public blocks may be grouped again without re-rounding leaf totals.
    regrouped = combine([combine(parts[:3]), combine(parts[3:])])
    assert regrouped.values.project() == whole.values.project()


@pytest.mark.parametrize("missing", [0, 3, 6])
def test_missing_component_never_proves_complete_or_final(missing):
    summary = summarize(accepted([bar(i) for i in range(7) if i != missing]), target=TARGET)
    status = summary.evaluate(0, 420_000)
    assert not status.complete and not status.closed and not status.enhanced_complete


def test_unknown_and_known_zero_fields_and_vwap_sufficient_statistics():
    bars = [replace(bar(0), volume=1, quote_volume=10, taker_buy_base=0,
                    taker_buy_quote=0, trades=0),
            replace(bar(1), volume=9, quote_volume=180, taker_buy_base=0,
                    taker_buy_quote=0, trades=0)]
    summary = summarize(accepted(bars), target=TARGET)
    assert summary.vwap == 19  # weighted 190/10, not average(10,20)
    contracts = replace(SOURCE, volume_semantics="contracts")
    assert summarize(accepted(bars, series=contracts),
                     target=replace(contracts, interval="7m")).vwap is None
    assert summary.values.trades == 0
    assert summary.values.taker_buy_base == 0
    assert summarize(accepted([bars[0], replace(bars[1], quote_volume=None)]),
                     target=TARGET).values.quote_volume is None
    assert summarize(accepted([replace(bars[0], trades=None), bars[1]]),
                     target=TARGET).values.trades is None


def test_forming_prefix_and_explicit_successor_policy_do_not_create_authority():
    forming = summarize(accepted([bar(0), bar(1, closed=False)]), target=TARGET)
    assert forming.evaluate(0, 420_000).enhanced_complete
    assert not forming.evaluate(0, 420_000).complete
    missed_close = summarize(accepted([bar(i, closed=i != 0) for i in range(7)]), target=TARGET)
    assert missed_close.evaluate(0, 420_000).complete
    assert not missed_close.evaluate(0, 420_000).closed
    assert missed_close.evaluate(0, 420_000, close_policy=ClosePolicy.SUCCESSOR).closed
    assert not missed_close.is_authoritative(0, 420_000)
    untrusted = summarize(accepted([replace(bar(i), source="") for i in range(7)]), target=TARGET)
    assert untrusted.evaluate(0, 420_000).closed
    assert not untrusted.is_authoritative(0, 420_000)
    with pytest.raises(ValueError):
        missed_close.evaluate(0, 420_000, close_policy="unknown")


def test_explicit_session_exclusions_are_not_missing_data_or_synthetic_zero_candles():
    components = [(0, 60_000, True), (120_000, 180_000, True)]
    coverage = Coverage.from_ranges(components)
    assert not coverage.evaluate(0, 180_000).complete
    assert coverage.evaluate(0, 180_000, exclusions=((60_000, 120_000),)).closed
    assert not Coverage.from_ranges([]).evaluate(0, 180_000, exclusions=((0, 180_000),)).closed
    # A coarse source straddling a closed session is not a valid replacement.
    assert not Coverage.from_ranges([(0, 180_000, True)]).evaluate(
        0, 180_000, exclusions=((60_000, 120_000),),
    ).complete
    with pytest.raises(ValueError):
        coverage.evaluate(0, 180_000, exclusions=((60_000, 200_000),))


@pytest.mark.parametrize("interval,source,start", [
    ("89m", "1m", "2024-01-01T00:00Z"),
    ("97m", "1m", "2024-01-01T00:00Z"),
    ("10007m", "1h", "2024-01-01T00:00Z"),
    ("7m~a1~120000", "1m", "2024-01-01T00:00Z"),
    ("1w", "1d", "2024-02-01T00:00Z"),
    ("1M", "1d", "2024-02-01T00:00Z"),
    ("12M", "1M", "2024-02-01T00:00Z"),
    ("1d~c1~America/New_York", "1h", "2024-03-10T12:00Z"),
    ("1d~c1~America/New_York", "1h", "2024-11-03T12:00Z"),
])
def test_actual_half_open_boundaries_do_not_assume_nominal_calendar_width(interval, source, start):
    spec = parse_interval_spec(interval)
    source_spec = parse_interval_spec(source)
    start_ms = spec.floor_ms(int(datetime.fromisoformat(start).timestamp() * 1000))
    end_ms = spec.next_ms(start_ms)
    source_key = replace(SOURCE, interval=source)
    target = replace(TARGET, interval=interval)
    parts = []
    opened = start_ms
    while opened < end_ms:
        ended = source_spec.next_ms(opened)
        parts.append(AcceptedComponent(source_key, replace(bar(0), time=opened // 1000), ended))
        opened = ended
    summary = summarize(parts, target=target)
    # 10007m is deliberately not divisible by 1h: no clipping or false closure.
    assert summary.evaluate(start_ms, end_ms).closed is (opened == end_ms)
    assert not summary.revisions_known


def test_overlaps_duplicates_incompatible_identity_and_mixed_views_are_rejected():
    components = accepted([bar(0), bar(1)])
    with pytest.raises(ValueError, match="non-overlapping"):
        summarize([components[0], components[0]], target=TARGET)
    with pytest.raises(ValueError, match="non-overlapping"):
        summarize([replace(components[0], end_ms=90_000), components[1]], target=TARGET)
    with pytest.raises(ValueError, match="incompatible"):
        summarize(components, target=replace(TARGET, volume_semantics="contracts"))
    with pytest.raises(ValueError, match="acquisition views"):
        summarize([components[0], replace(components[1], revision=InputRevision(SOURCE, "fixture-store", 18))],
                  target=TARGET)
    other_domain = replace(components[1], revision=InputRevision(SOURCE, "other-store", 1))
    assert len(summarize([components[0], other_domain], target=TARGET).revisions) == 2
    whole = summarize(components, target=TARGET)
    with pytest.raises(ValueError, match="versions"):
        combine([whole, replace(whole, algorithm_version="other")])
    with pytest.raises(ValueError, match="non-overlapping"):
        combine([whole, whole])
    with pytest.raises(FrozenInstanceError):
        components[0].bar.volume = 99
    with pytest.raises(FrozenInstanceError):
        whole.values.volume = 99


@pytest.mark.parametrize("page_size", [1, 2, 6, 7, 11, 37])
def test_batch_generic_stream_and_live_use_same_accepted_values(page_size):
    bars = [bar(i) for i in range(35)]
    reduce = lambda values: _aggregate_fixed_bars_to_interval(values, 420, source_interval_seconds=60)
    fixed = reduce(bars)
    generic = _aggregate_rows_to_interval([b.to_aggregation_dict() for b in bars], 420,
                                         interval="7m", source_interval_seconds=60)
    assert [b.to_aggregation_dict() for b in fixed] == generic
    stream = FixedHistoryStream(420, reduce)
    for end in range(len(bars), 0, -page_size):
        stream.push(bars[max(0, end - page_size):end])
    streamed, _ = stream.finish()
    assert streamed == fixed
    for index, result in enumerate(fixed):
        components = bars[index * 7:(index + 1) * 7]
        state = state_for(start=result.time_ms, end=result.time_ms + 420_000)
        merge = ComponentSnapshotOHLCVMerge()
        for count, value in enumerate(reversed(components)):
            merge.apply(state, live_input(value), is_new=count == 0)
        summary = summarize(accepted(components), target=TARGET)
        assert summary.values.project() == {name: result.to_aggregation_dict()[name]
                                            for name in summary.values.project()}
        assert state.volume == result.volume
        assert state.quote_volume == result.quote_volume
        assert state.trades == result.trades
        assert state.open == result.open and state.close == result.close
        assert has_complete_closed_component_coverage(state)


def test_cumulative_replacement_and_authoritative_extrema_reduction_rebuild_once():
    values = [replace(bar(i), volume=10, quote_volume=1000,
                      taker_buy_base=5, taker_buy_quote=500) for i in range(7)]
    values[2] = replace(values[2], high=999, low=1)
    state = state_for()
    merge = ComponentSnapshotOHLCVMerge()
    for index, value in enumerate(values):
        merge.apply(state, live_input(value), is_new=index == 0)
    assert state.volume == 70 and state.high == 999 and state.low == 1
    # Identical redelivery cannot add cumulative volume again.
    merge.apply(state, live_input(values[2]), is_new=False)
    assert state.volume == 70
    corrected = replace(bar(2), volume=2, quote_volume=200, taker_buy_base=1, taker_buy_quote=100)
    merge.apply(state, live_input(corrected, sequence=2, source=BarInputSource.CORRECTION), is_new=False)
    values[2] = corrected
    reference = summarize(accepted(values, revision=18), target=TARGET)
    assert state.volume == 62
    assert state.high == 109 and state.low == 99
    assert state.volume == reference.values.volume
    assert state.high == reference.values.high and state.low == reference.values.low
    assert state.quote_volume == reference.values.project()["quote_volume"]


def test_crossing_source_cannot_close_history_or_realtime_target():
    bars = [replace(bar(0), time=0), replace(bar(1), time=180)]
    fixed = _aggregate_fixed_bars_to_interval(bars, 300, source_interval_seconds=180)[0]
    generic = _aggregate_rows_to_interval([b.to_aggregation_dict() for b in bars], 300,
                                         interval="5m", source_interval_seconds=180)[0]
    assert not fixed.is_closed and fixed.quote_volume is None
    assert not generic["is_closed"] and generic["quote_volume"] is None
    state = state_for(target=replace(TARGET, interval="5m"), end=300_000)
    merge = ComponentSnapshotOHLCVMerge()
    for index, value in enumerate(bars):
        item = live_input(value)
        item.source_interval = "3m"
        item.close_time_ms = item.open_time_ms + 179_999
        merge.apply(state, item, is_new=index == 0)
    assert not has_complete_closed_component_coverage(state)
    assert not state.enhanced_fields


def test_calendar_source_closed_rebuild_uses_actual_month_ends():
    source = parse_interval_spec("1M")
    target = parse_interval_spec("12M")
    start = int(datetime.fromisoformat("2024-01-01T00:00+00:00").timestamp() * 1000)
    end = target.next_ms(start)
    rows = []
    opened = start
    for index in range(12):
        next_open = source.next_ms(opened)
        rows.append(dict(open_time=opened, close_time=next_open - 1, open=100 + index,
                         high=120, low=90, close=101 + index, volume=index + 1,
                         quote_volume=(index + 1) * 100, trades=index,
                         taker_buy_base=0, taker_buy_quote=0, is_closed=True, source="backfill"))
        opened = next_open
    rebuilt = aggregate_kline_rows(rows, target_interval="12M", source_interval="1M", now_ms=end)
    assert len(rebuilt) == 1
    assert rebuilt[0]["volume"] == 78 and rebuilt[0]["close_time"] == end - 1
    assert rebuilt[0]["trades"] == 66 and rebuilt[0]["is_closed"]
    assert not aggregate_kline_rows(rows, target_interval="12M", source_interval="1M", now_ms=end - 1)
    bars = [BarData.from_storage_row(row) for row in rows]
    queried = CustomIntervalQueryService._aggregate_read_only(
        bars, "12M", target.nominal_ms // 1000, source_interval="1M",
    )
    summary = summarize(accepted(bars, series=replace(SOURCE, interval="1M")),
                        target=replace(TARGET, interval="12M"))
    assert queried[0].is_closed
    assert queried[0].volume == summary.values.volume == rebuilt[0]["volume"]


def test_raw_rebuild_and_compact_decode_share_per_component_precision():
    # Summing raw sub-precision quantities then rounding differed from the
    # query/live paths, which normalize each accepted leaf first.
    rows = [dict(open_time=i * 60_000, close_time=(i + 1) * 60_000 - 1,
                 open=1.000000001, high=2.000000001, low=1.0, close=1.1,
                 volume=0.000000001, is_closed=True, source="backfill") for i in range(100)]
    bars = [BarData.from_storage_row(row) for row in rows]
    rebuilt = aggregate_kline_rows(rows, target_interval="100m", source_interval="1m", now_ms=6_000_000)[0]
    queried = _aggregate_fixed_bars_to_interval(bars, 6000, source_interval_seconds=60)[0]
    summary = summarize(accepted(bars), target=replace(TARGET, interval="100m"))
    assert rebuilt["volume"] == queried.volume == summary.values.volume == 0
    assert rebuilt["open"] == queried.open == summary.values.open == 1
    assert rebuilt["high"] == queried.high == summary.values.high == 2


def test_semantics_import_and_evaluation_do_not_load_runtime_or_read_wall_clock():
    code = '''
import sys, time
from app.data_engine.aggregation.core import combine
from app.data_engine.aggregation.semantics import Coverage
assert "app.data_engine.data_manager.manager" not in sys.modules
assert "sqlite3" not in sys.modules
time.time = lambda: (_ for _ in ()).throw(AssertionError("hidden wall clock"))
assert Coverage.from_ranges([(0, 60, True)]).evaluate(0, 60).closed
assert not Coverage.from_ranges([(0, 60, False)]).evaluate(0, 60).closed
'''
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], check=True)
