"""Deterministic slow/fast IO budgets, exact resumability and cancellation."""

from threading import Event

import pytest
from app.replay.training import indicator_prefix as prefix
from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore

from tests.test_replay_indicator_prefix import History, bar, lines, reference


@pytest.mark.parametrize(
    "read_seconds, first_pages", [(0.001, 64), (0.06, 9), (0.6, 1)]
)
def test_elapsed_budget_yields_after_complete_pages_and_resumes_exactly(
    tmp_path, monkeypatch, read_seconds, first_pages
):
    clock = [100.0]
    monkeypatch.setattr(prefix, "monotonic", lambda: clock[0])
    rows = [bar(index) for index in range(10_020)]
    history = History(rows)
    ordinary = history.read

    def read(start, stop):
        chunk = ordinary(start, stop)
        clock[0] += read_seconds
        return chunk

    history.read = read
    path = tmp_path / "math.sqlite3"
    args = {"history": history, "name": "RSI", "params": {}, "rows": tuple(rows[-20:])}
    result = prefix.CanonicalReplayIndicators(IndicatorCheckpointStore(path)).compute(
        **args
    )
    assert result["status"] == "preparing"
    assert len(history.reads) == first_pages
    assert result["prepared_before_ms"] == history.reads[-1][1]
    assert result["prefix_rows_read"] == first_pages * 127
    # Every continuation gets a new owner and its own elapsed deadline. Only
    # persisted, fully consumed mathematics may bridge these requests.
    for _ in range(100):
        result = prefix.CanonicalReplayIndicators(
            IndicatorCheckpointStore(path)
        ).compute(**args)
        if result["status"] == "ready":
            break
    assert result["status"] == "ready"
    assert all(a[1] == b[0] for a, b in zip(history.reads, history.reads[1:]))
    expected = reference("RSI", {}, rows)
    first_time = rows[-20].open_time_ms // 1000
    assert lines(result["payload"]) == [
        (name, [point for point in values if point["time"] >= first_time])
        for name, values in lines(expected)
    ]
    restored = prefix.CanonicalReplayIndicators(IndicatorCheckpointStore(path)).compute(
        **args
    )
    assert restored["prefix_rows_read"] == 0
    assert restored["payload"] == result["payload"]


@pytest.mark.parametrize("read_seconds", [0.001, 0.6])
def test_cancellation_during_a_page_wins_over_budget_yield(
    tmp_path, monkeypatch, read_seconds
):
    clock, cancelled = [100.0], Event()
    monkeypatch.setattr(prefix, "monotonic", lambda: clock[0])
    rows = [bar(index) for index in range(300)]
    history, cache = History(rows), IndicatorCheckpointStore(tmp_path / "math.sqlite3")
    ordinary = history.read

    def read(start, stop):
        chunk = ordinary(start, stop)
        clock[0] += read_seconds
        cancelled.set()
        return chunk

    history.read = read
    with pytest.raises(InterruptedError):
        prefix.CanonicalReplayIndicators(cache).compute(
            history=history,
            name="RSI",
            params={},
            rows=tuple(rows[-20:]),
            cancelled=cancelled,
        )
    assert len(history.reads) == 1
    with cache._connect() as conn:
        assert conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), float("nan")])
def test_invalid_time_budget_is_rejected(tmp_path, seconds):
    with pytest.raises(ValueError, match="positive and finite"):
        prefix.CanonicalReplayIndicators(
            IndicatorCheckpointStore(tmp_path / "math.sqlite3"),
            max_prefix_seconds=seconds,
        )
