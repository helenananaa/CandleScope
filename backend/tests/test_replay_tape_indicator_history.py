from __future__ import annotations

import asyncio
from dataclasses import replace
from threading import Event

import pytest
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.history_archive import (
    ReplayHistoryArchiveWriter,
    ReplayHistoryRepository,
)
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.models import TimeDisclosurePolicy, VisibleHistoryLookback
from app.replay.training.tape_projection import TapeDisplayProjection

from tests.fixtures.replay.fakes import make_bar
from tests.fixtures.replay.service_fakes import SessionIdFactory, replay_settings
from tests.fixtures.replay.trade_service_fakes import (
    TRADE_NOW_MS,
    TRADE_REPLAY_START_MS,
)
from tests.replay_frontend_probe import frontend_probe
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_projection_native_seam import _batch
from tests.test_replay_tape_projection import prepare, source
from tests.test_replay_v2_training_api import _app, _request
from tests.test_replay_v2_training_phase5 import (
    _acquire,
    _multi_trade_sources,
    _trade_request,
)

pytestmark = pytest.mark.anyio


async def ready(service, session, **args):
    for _ in range(80):
        result = await service.training.tape_projection(session, **args)
        if result["status"] == "ready":
            return result
    pytest.fail("chart preparation did not finish within its bounded fixture")


@pytest.mark.parametrize(
    "blind,gaps", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_tape_indicator_http_prefix_window_restart_and_source_progress(
    tmp_path, blind, gaps
):
    base, tape = _multi_trade_sources(
        tmp_path / "tape",
        ("BTCUSDT",),
        trades_per_minute=10,
        coalesce_trade_timestamps=True,
    )
    older = [
        make_bar(TRADE_REPLAY_START_MS + i * 60_000, price=str(100 + i % 19))
        for i in range(-2507, -2)
        if not gaps or i not in (-1200, -1199)
    ]
    existing = base.rows[("binance", "futures", "BTCUSDT", "1m")]
    execution = [
        make_bar(row["open_time"], price="9999")
        if row["open_time"] >= TRADE_REPLAY_START_MS
        else row
        for row in existing
    ]
    archive = tmp_path / "bars"
    ReplayHistoryArchiveWriter(archive, now_ms=lambda: TRADE_NOW_MS).import_batches(
        ReplaySeriesIdentity("binance", "futures", "BTCUSDT"),
        "1m",
        [
            _batch(
                older + execution,
                source_key="tape-indicator-context",
                digest_character="8",
            )
        ],
    )

    async def owner():
        service = ReplayService(
            settings=replace(
                replay_settings(tmp_path / "run.db"), controller_ttl_seconds=300
            ),
            store=ReplaySQLiteStore(tmp_path / "run.db", now_ms=lambda: TRADE_NOW_MS),
            repository=ReplayHistoryRepository(archive),
            raw_trade_archive=tape,
            now_ms=lambda: TRADE_NOW_MS,
            session_id_factory=SessionIdFactory("tape-indicator"),
            training_run_id_factory=SessionIdFactory("run"),
            native_intervals=lambda _: ("1m",),
        )
        await service.start()
        service.training._display_service._tape_projection = TapeDisplayProjection(
            page_rows=1, pages_per_call=1
        )
        return service

    service = await owner()
    observed = []
    probe_cases = []
    try:
        request = replace(
            await _trade_request(service),
            visible_history_lookback=VisibleHistoryLookback("ALL_AVAILABLE", None),
            time_disclosure_policy=TimeDisclosurePolicy.HIDE_ALL
            if blind
            else TimeDisclosurePolicy.NONE,
        )
        created = await service.training.create_run(request)
        run, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(
            service, run_id=run, selected_session_id=session, command_id="acquire"
        )
        await prepare(service, run, session)
        snapshot, _, _, _, _ = await source(service, session)
        args = {
            "track_id": "track-1",
            "data_epoch": snapshot["data_epoch"],
            "source_sequence": snapshot["cursor"]["source_sequence"],
            "revealed_boundary_ms": snapshot["cursor"]["virtual_time_ms"],
        }
        # HTTP renders windows from the chart source verified independently by
        # the full scalar/Node aggregation matrix. Canonical math must reproduce
        # a full-history builtin calculation when any shorter window is selected.
        for interval in ("1m", "7m", "90m", "1w", "1M", "12M"):
            all_bars, before = [], None
            while True:
                page = await ready(
                    service,
                    session,
                    **args,
                    display_interval=interval,
                    limit=500,
                    **({} if before is None else {"before_ms": before}),
                )
                all_bars = page["bars"] + all_bars
                if not page["has_more"]:
                    break
                before = page["next_before_ms"]
            rows = [
                ReplayDisplayBar.from_dict(bar)
                for bar in all_bars
                if bar["is_closed"]
                or bar["close_time_ms"] >= args["revealed_boundary_ms"]
            ]
            assert rows[-1].close != "9999.5"
            # The latest gap resets all recursive builtins; earlier outputs
            # cannot seed the tail. This independent math starts at that reset.
            split = max(
                (
                    i
                    for i in range(1, len(rows))
                    if rows[i].open_time_ms != rows[i - 1].close_time_ms + 1
                ),
                default=0,
            )
            segment = rows[split:]
            if interval in {"1m", "90m"}:
                selected = segment[-min(2, len(segment)) :]
                probe_cases.append(
                    {
                        "sessionId": session,
                        "identity": page["identity"],
                        "request": {
                            **args,
                            "display_interval": interval,
                            "name": "RSI",
                            "params": {"period": 5},
                            "history_epoch": page["history_epoch"],
                            "bars": [row.to_dict() for row in selected],
                        },
                        "expected": [
                            (
                                name,
                                [
                                    point
                                    for point in points
                                    if point["time"] >= selected[0].open_time_ms // 1000
                                ],
                            )
                            for name, points in lines(
                                reference("RSI", {"period": 5}, segment)
                            )
                        ],
                        # The display client explicitly uses the live bounded
                        # warmup contract. Keep the full-history HTTP oracle
                        # above independently checking legacy canonical math.
                        "displayExpected": [
                            (
                                name,
                                [
                                    point
                                    for point in points
                                    if point["time"] >= selected[0].open_time_ms // 1000
                                ],
                            )
                            for name, points in lines(
                                reference(
                                    "RSI",
                                    {"period": 5},
                                    segment[-(15 + len(selected)) :],
                                )
                            )
                        ],
                    }
                )
            for name in ("RSI", "EMA", "ATR", "MACD", "MA", "BOLL", "VOL"):
                params = {} if name in {"MACD", "VOL"} else {"period": 2}
                expected = lines(reference(name, params, segment))
                for length in (1, min(17, len(segment))):
                    selected = segment[-length:]
                    payload = {
                        **args,
                        "display_interval": interval,
                        "name": name,
                        "params": params,
                        "history_epoch": page["history_epoch"],
                        "bars": [bar.to_dict() for bar in selected],
                    }
                    # Cold per-window source preparations must also work when
                    # the page cache is lost, without invalidating fixed math.
                    if name == "RSI":
                        service.training._display_service._tape_projection._cache.clear()
                    for _ in range(80):
                        response = await _request(
                            _app(service),
                            "POST",
                            f"/api/v1/replay/runs/session/{session}/indicator-compute",
                            json=payload,
                        )
                        assert response.status_code == 200, response.text
                        result = response.json()
                        if result["status"] == "ready":
                            break
                        observed.append(result)
                    else:
                        pytest.fail("tape indicator prefix did not finish")
                    assert result["seed"]["history_epoch"] == page["history_epoch"]
                    assert lines(result["payload"]) == [
                        (
                            line,
                            [
                                point
                                for point in points
                                if point["time"] >= selected[0].open_time_ms // 1000
                            ],
                        )
                        for line, points in expected
                    ]
            if interval == "1m":
                service.training._display_service._tape_projection._cache.clear()

                async def concurrent(
                    name, interval=interval, page=page, rows=rows, segment=segment
                ):
                    request = {
                        **args,
                        "display_interval": interval,
                        "name": name,
                        "params": {"period": 3},
                        "history_epoch": page["history_epoch"],
                        "bars": [rows[-1].to_dict()],
                    }
                    for _ in range(80):
                        computed = await service.training.canonical_indicator_compute(
                            session, **request
                        )
                        if computed["status"] == "ready":
                            expected = lines(reference(name, {"period": 3}, segment))
                            assert lines(computed["payload"]) == [
                                (
                                    line,
                                    [
                                        point
                                        for point in points
                                        if point["time"]
                                        >= rows[-1].open_time_ms // 1000
                                    ],
                                )
                                for line, points in expected
                            ]
                            return
                    pytest.fail("concurrent indicators did not finish")

                await asyncio.gather(
                    *(concurrent(name) for name in ("RSI", "EMA", "ATR"))
                )
                invalid = {
                    **args,
                    "display_interval": interval,
                    "name": "RSI",
                    "params": {"period": 2},
                    "history_epoch": page["history_epoch"],
                    "bars": [rows[-1].to_dict()],
                }
                for changed in (
                    {"source_sequence": 0},
                    {"source_sequence": args["source_sequence"] + 1},
                    {"history_epoch": "sha256:" + "f" * 64},
                    {"history_epoch": None},
                ):
                    denied = await _request(
                        _app(service),
                        "POST",
                        f"/api/v1/replay/runs/session/{session}/indicator-compute",
                        json={**invalid, **changed},
                    )
                    assert denied.status_code in (409, 422), denied.text
        service.training._display_service._tape_projection._cache.clear()
        probe = await frontend_probe(
            service, tmp_path, probe_cases, "scripts/replay-tape-indicator-oracle.ts"
        )
        assert probe["status"] == "PASS" and probe["comparisons"] == 2
        assert probe["contexts"] > 0 and probe["trades"] > 0
        client = await frontend_probe(
            service, tmp_path, probe_cases, "scripts/replay-tape-client-oracle.ts"
        )
        assert client["status"] == "PASS" and client["comparisons"] == 6
        assert client["displayCommits"] == 4
        assert client["tapeGets"] > 4 and client["posts"] >= 4
        assert any(
            row.get("source_preparation", {}).get("phase") == "context"
            for row in observed
        )
        assert any(
            row.get("source_preparation", {}).get("phase") == "trades"
            for row in observed
        )
        assert (await service.get_session(session))["snapshot"] == snapshot
        await service.shutdown(step_timeout=3)
        service = await owner()
        restored = await service.training.canonical_indicator_compute(
            session, **payload
        )
        assert restored["status"] == "ready"
        assert (
            restored["payload"] == result["payload"]
            and restored["seed"] == result["seed"]
        )
        assert restored["prefix_rows_read"] == 0
    finally:
        await service.shutdown(step_timeout=3)


async def test_shared_window_ownership_serializes_only_matching_keys_and_drains_cancel():
    projection = TapeDisplayProjection()
    entered, release = Event(), Event()
    first_cancel, second_cancel = Event(), Event()

    def first():
        with projection._own(("shared",), first_cancel):
            entered.set()
            assert release.wait(3)

    first_task = asyncio.create_task(asyncio.to_thread(first))
    assert await asyncio.to_thread(entered.wait, 1)

    def second():
        with projection._own(("shared",), second_cancel):
            pytest.fail("same source window was concurrently acquired")

    second_task = asyncio.create_task(asyncio.to_thread(second))
    try:
        with projection._own(("other",), Event()):
            assert not first_task.done()
        second_cancel.set()
        with pytest.raises(InterruptedError):
            await asyncio.wait_for(second_task, 1)
    finally:
        release.set()
        await first_task
    assert not projection._owners
