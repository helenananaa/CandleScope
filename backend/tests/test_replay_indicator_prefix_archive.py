from __future__ import annotations

import json
from time import perf_counter

import pytest
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.history_archive import (
    ReplayHistoryArchiveWriter,
    ReplayHistoryRepository,
)
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.history import MAX_HISTORY_PAGE_BARS

from tests.fixtures.replay.fakes import make_bar
from tests.fixtures.replay.service_fakes import (
    START_MS,
    SessionIdFactory,
    replay_settings,
)
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_projection_native_seam import IDENTITY, _batch
from tests.test_replay_v2_training_history import _create_run

pytestmark = pytest.mark.anyio


async def test_large_parquet_prefix_resumes_across_request_and_service_owners(tmp_path):
    root, path = tmp_path / "archive", tmp_path / "prefix.db"
    now = START_MS + 16_030 * 60_000
    writer = ReplayHistoryArchiveWriter(root, now_ms=lambda: now)
    writer.import_batches(
        IDENTITY,
        "1m",
        [
            _batch(
                [
                    make_bar(
                        START_MS + index * 60_000,
                        price=str(100 + index % 23),
                        source="binance_archive_verified",
                    )
                    for index in range(16_020)
                ],
                source_key="canonical-16020",
                digest_character="9",
            )
        ],
    )

    def owner():
        return ReplayService(
            settings=replay_settings(path),
            store=ReplaySQLiteStore(path, now_ms=lambda: now),
            repository=ReplayHistoryRepository(root),
            now_ms=lambda: now,
            session_id_factory=SessionIdFactory("adapter"),
            training_run_id_factory=SessionIdFactory("run"),
            native_intervals=lambda _: ("1m",),
        )

    service = owner()
    await service.start()
    try:
        _, snapshot = await _create_run(
            service, history_mode="ALL_AVAILABLE", requested_start_index=16_000
        )
        boundary = snapshot["cursor"]["virtual_time_ms"]
        cursor, history_rows = boundary + 1, []
        while True:
            page = await service.training.history_page(
                "adapter-1",
                track_id="track-1",
                before_ms=cursor,
                revealed_boundary_ms=boundary,
                limit=500,
                data_epoch=snapshot["data_epoch"],
                history_epoch=None,
            )
            history_rows = [*page["bars"], *history_rows]
            if not page["has_more"]:
                break
            assert page["next_before_ms"] < cursor
            cursor = page["next_before_ms"]
        assert len(history_rows) == 16_000
        args = {
            "track_id": "track-1",
            "display_interval": "1m",
            "revealed_boundary_ms": boundary,
            "data_epoch": snapshot["data_epoch"],
            "name": "RSI",
            "params": {},
            "bars": history_rows[-200:],
        }
        started, timings, reads = perf_counter(), [], []
        while True:
            tick = perf_counter()
            result = await service.training.canonical_indicator_compute(
                "adapter-1", **args
            )
            timings.append(perf_counter() - tick)
            reads.append(result["prefix_rows_read"])
            assert result["prefix_rows_read"] <= 64 * MAX_HISTORY_PAGE_BARS
            if result["status"] == "ready":
                break
            assert result["prefix_rows_read"] > 0
            assert len(timings) < 32
        cold_seconds = perf_counter() - started
        # The request count now follows elapsed work, rather than a fixed
        # eight-page batch. Every prefix row must still be consumed once.
        assert sum(reads) == 15_800
        expected = reference(
            "RSI", {}, [ReplayDisplayBar.from_dict(row) for row in history_rows]
        )
        first_time = history_rows[-200]["open_time_ms"] // 1000
        assert lines(result["payload"]) == [
            (name, [point for point in points if point["time"] >= first_time])
            for name, points in lines(expected)
        ]
    finally:
        await service.shutdown(step_timeout=1)
    reopened = owner()
    await reopened.start()
    try:
        started = perf_counter()
        restored = await reopened.training.canonical_indicator_compute(
            "adapter-1", **args
        )
        warm_seconds = perf_counter() - started
        assert (
            restored["payload"] == result["payload"]
            and restored["prefix_rows_read"] == 0
        )
        print(
            json.dumps(
                {
                    "archive_rows": 16020,
                    "prefix_rows": sum(reads),
                    "cold_seconds": cold_seconds,
                    "request_seconds": timings,
                    "request_prefix_rows": reads,
                    "restart_warm_seconds": warm_seconds,
                }
            )
        )
    finally:
        await reopened.shutdown(step_timeout=1)
