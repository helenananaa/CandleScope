"""Prepared source integration: input work follows the requested math range."""

from __future__ import annotations

import pytest

from app.data_preparation import replay_context
from app.indicator.warmup import indicator_warmup_bars
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.display_time import SourceBucketTimeMapper
from tests import test_replay_indicator_prepared_context as fixture
from tests.test_replay_indicator_prefix import lines, reference

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "progressive,disclosure", [(False, "NONE"), (True, "HIDE_ALL")]
)
@pytest.mark.parametrize(
    "interval,name,period",
    [("1m", "EMA", 200), ("1m", "RSI", 14), ("7m", "RSI", 14), ("90m", "RSI", 14)],
)
async def test_prepared_viewport_reads_bounded_requested_range(
    tmp_path, monkeypatch, interval, name, period, progressive, disclosure
):
    monkeypatch.setattr(
        fixture, "REPLAY_START", fixture.START + 120_007 * fixture.MINUTE
    )
    async with fixture.prepared_run(tmp_path, progressive, disclosure) as values:
        replay, _, session, *_ = values
        state = await replay.get_session_state(session)
        common = {
            "track_id": "track-1",
            "revealed_boundary_ms": state["cursor"]["virtual_time_ms"],
            "data_epoch": state["data_epoch"],
            "display_interval": interval,
        }
        binding = await replay.training.store.history_binding(
            session_id=session, track_id="track-1"
        )
        persisted = await replay.store.load_dataset(session)
        await replay.history_context.origin(
            binding=binding,
            persisted=persisted,
            repository=replay.prepared_history_repository(session, state["data_epoch"]),
            discover=True,
        )
        page = await replay.training.history_page(
            session,
            **common,
            before_ms=common["revealed_boundary_ms"],
            limit=80,
            history_epoch=None,
        )
        rows = page["bars"][20:40]
        assert len(rows) == 20
        params = {"period": period}
        warmup = indicator_warmup_bars(name, params)
        projected = []
        original = replay_context.project_context

        def capture(source, start, end, *args, **kwargs):
            result = original(source, start, end, *args, **kwargs)
            projected.append((len(source), len(result)))
            return result

        monkeypatch.setattr(replay_context, "project_context", capture)
        total = 0
        for _ in range(20):
            answer = await replay.training.canonical_indicator_compute(
                session,
                **common,
                history_epoch=page["history_epoch"],
                display_math="viewport-v1",
                name=name,
                params=params,
                bars=rows,
            )
            total += answer["prefix_rows_read"]
            if answer["status"] == "ready":
                break
        assert answer["status"] == "ready"
        assert total == warmup
        # One predecessor per page is sufficient to establish a left-edge gap.
        # The old paging adapter projects 1000/91 rows for even a 42-bar prefix.
        assert sum(n for _, n in projected) <= warmup + len(projected)
        assert all(n <= 8192 for n, _ in projected)
        width = int(interval[:-1]) * 60_000
        start = rows[0]["open_time_ms"] - warmup * width
        end = rows[-1]["close_time_ms"] + 1
        mapper = SourceBucketTimeMapper.create(
            interval=interval,
            actual_replay_start_ms=fixture.REPLAY_START,
            public_replay_start_ms=common["revealed_boundary_ms"] + 1,
        )
        actual_start, actual_end = (
            mapper.actual_from_public(start),
            mapper.actual_from_public(end),
        )
        expected_rows = original(
            [fixture.market_row(t) for t in range(actual_start, actual_end, 60_000)],
            actual_start,
            actual_end,
            mapper,
            ReplaySeriesIdentity("binance", "spot", "BTCUSDT"),
        )
        expected = reference(
            name, params, [ReplayDisplayBar.from_dict(row) for row in expected_rows]
        )
        first = rows[0]["open_time_ms"] // 1000
        assert lines(answer["payload"]) == [
            (title, [point for point in points if point["time"] >= first])
            for title, points in lines(expected)
        ]
        monkeypatch.setattr(replay_context, "project_context", original)
