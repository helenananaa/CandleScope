from copy import deepcopy
import json

import pytest

from app.backtest.pine_event_requests import build_renko_stream, CONTRACT
from app.backtest.pine_request_updates import RequestedObservationFeed


SYMBOL = json.dumps(dict(chart="renko", symbol="B", style="Traditional", param=1), separators=(",", ":"))


def source():
    return dict(symbol="B", timeframe="1", bars=[dict(time=i*60, open=p, high=p, low=p, close=p, volume=6)
        for i,p in enumerate((10,13,15,12))], closes=[59999,119999,179999,239999], metadata={"pointValue":50})


def test_closed_source_cohorts_keep_each_brick_and_reveal_no_partial_cohort():
    physical = source()
    stream = build_renko_stream(SYMBOL, "1", [physical])
    assert stream["source_hash"] == RequestedObservationFeed([physical]).source_hash
    feed = RequestedObservationFeed([stream])
    assert stream["event_series_contract"] == CONTRACT
    assert [bar["time"] for bar in stream["bars"]] == [60,60,60,120,120,180,180]
    assert feed.advance(119998) == []
    first = feed.advance(119999)
    assert [item["bar"]["close"] for item in first] == [11,12,13]
    assert all(item["available_at_ms"] == 119999 for item in first)
    assert feed.advance(119999) == []
    restored = RequestedObservationFeed([deepcopy(stream)])
    restored.restore(feed.snapshot())
    assert restored.advance(239999) == feed.advance(239999)
    assert feed.window_history()[0]["times_ms"][:3] == [60000]*3
    assert feed.empty_contexts()[0]["metadata"]["pointValue"] == 50


def test_source_identity_and_future_prices_do_not_rewrite_an_observed_cohort():
    physical = source()
    original = build_renko_stream(SYMBOL, "1", [physical])
    changed = deepcopy(physical)
    changed["bars"][-1].update(open=20, high=20, low=20, close=20)
    future = build_renko_stream(SYMBOL, "1", [changed])
    assert original["source_hash"] != future["source_hash"]
    assert original["recipe_hash"] != future["recipe_hash"]
    assert RequestedObservationFeed([original]).advance(179999) == RequestedObservationFeed([future]).advance(179999)
    physical["bars"][1]["close"] = 999
    assert original["bars"][0]["close"] == 11


@pytest.mark.parametrize("change", [
    {"event_series_contract":None}, {"event_series_contract":"unknown"}, {"symbol":"B"},
    {"closes":[119999,119999,120000,179999,179999,239999,239999]},
    {"closes":[119999,119999,119999,119999,119999,239999,239999]},
])
def test_event_identity_and_atomic_cohort_clock_are_required(change):
    stream = build_renko_stream(SYMBOL, "1", [source()])
    with pytest.raises(ValueError):
        RequestedObservationFeed([{**stream, **change}])


def test_restore_rejects_a_cursor_in_the_middle_of_one_time_cohort():
    stream = build_renko_stream(SYMBOL, "1", [source()])
    feed = RequestedObservationFeed([stream])
    feed.advance(119999)
    before = feed.snapshot()
    with pytest.raises(ValueError):
        feed.restore({**before, "cursors":[1]})
    assert feed.snapshot() == before


@pytest.mark.parametrize("symbol,timeframe,sources", [
    (SYMBOL,"5",[source()]), (SYMBOL,"1",[]), (SYMBOL,"1",[source(),source()]),
    ('{"chart":"other","symbol":"B"}',"1",[source()]),
])
def test_missing_ambiguous_or_non_event_sources_remain_explicit(symbol,timeframe,sources):
    with pytest.raises(ValueError):
        build_renko_stream(symbol,timeframe,sources)


@pytest.mark.parametrize("change",[{"close":True},{"volume":float("nan")},{"high":0},{"time":True}])
def test_invalid_physical_rows_cannot_be_disguised_as_synthetic_prices(change):
    physical=source()
    physical["bars"][0].update(change)
    with pytest.raises(ValueError):
        build_renko_stream(SYMBOL,"1",[physical])
