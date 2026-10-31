from copy import deepcopy
import pytest
from app.backtest.pine_request_updates import RequestedObservationFeed


def streams():
    return [dict(symbol="B", timeframe="1", bars=[dict(time=i*60,open=i+1,high=i+1,low=i+1,close=i+1,volume=1) for i in range(4)],
                 closes=[(i+1)*60_000-1 for i in range(4)], metadata={"pointValue":50})]


def test_updates_emit_only_observed_tails_and_own_their_frozen_data():
    source = streams()
    feed = RequestedObservationFeed(source)
    source[0]["bars"][0]["close"] = 999
    assert feed.advance(59_998) == []
    first = feed.advance(59_999)
    assert len(first)==1 and first[0]["bar"]["close"]==1
    first[0]["bar"]["close"] = 999
    assert feed.advance(59_999) == []
    assert [item["bar"]["close"] for item in feed.advance(179_999)] == [2,3]
    assert [item["bar"]["close"] for item in feed.advance(239_999)] == [4]


def test_restore_preserves_remaining_tail_without_duplicate_updates():
    feed = RequestedObservationFeed(streams())
    feed.advance(119_999)
    restored = RequestedObservationFeed(streams())
    restored.restore(feed.snapshot())
    assert restored.advance(239_999) == feed.advance(239_999)
    assert restored.snapshot() == feed.snapshot()


def test_replaying_corrupt_transcript_rolls_back_the_entire_feed():
    feed = RequestedObservationFeed(streams())
    expected = RequestedObservationFeed(streams())
    groups = [dict(observed_at_ms=clock, updates=expected.advance(clock)) for clock in [59_999,119_999]]
    corrupt = deepcopy(groups)
    corrupt[1]["updates"][0]["bar"]["close"] = 999
    before = feed.snapshot()
    with pytest.raises(ValueError,match="transcript differs"):
        feed.replay(corrupt)
    assert feed.snapshot()==before
    feed.replay(groups)
    assert feed.snapshot()==expected.snapshot()


@pytest.mark.parametrize("clock", [True, 1.0, "1", 59_998])
def test_invalid_clock_preserves_the_checkpoint(clock):
    feed = RequestedObservationFeed(streams())
    feed.advance(59_999)
    before = feed.snapshot()
    with pytest.raises(ValueError):
        feed.advance(clock)
    assert feed.snapshot() == before


@pytest.mark.parametrize("change", [dict(cursors=[0]),dict(cursors=[True]),dict(observed_at_ms=True),
                                    dict(source_hash="changed"),dict(contract="unknown"),dict(extra=1)])
def test_invalid_restore_preserves_existing_state(change):
    feed = RequestedObservationFeed(streams())
    feed.advance(119_999)
    before = feed.snapshot()
    with pytest.raises(ValueError):
        feed.restore({**deepcopy(before),**change})
    assert feed.snapshot()==before
