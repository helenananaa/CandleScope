from __future__ import annotations

import asyncio
import itertools
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest
from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
from app.replay.bars.trade_builder import TradeReplayBarBuilder
from app.replay.models import ReplaySessionConfig
from app.replay.sources.trade_reader import PagedReplayTradeReader
from app.replay.training.errors import TrainingRunError
from app.replay.training.history import _decode_bar_snapshot
from app.replay.training.models import ReplayV2CommandType, TimeDisclosurePolicy
from app.replay.training.tape_chart_builder import TapeChartBuilder
from app.replay.training.tape_projection import TapeDisplayProjection

from tests import test_replay_v2_training_phase5 as phase5
from tests.replay_frontend_probe import frontend_probe
from tests.test_replay_tape_phases import setup_tape
from tests.test_replay_v2_training_api import _app, _request
from tests.test_replay_v2_training_phase6 import _send

pytestmark = pytest.mark.anyio


async def prepare(service, run, session):
    state = await service.get_session_state(session)
    target = (state["cursor"]["virtual_time_ms"] // 60_000 + 2) * 60_000 + 1200
    await _send(
        service,
        run_id=run,
        session_id=session,
        command_id="projection-advance",
        command_type=ReplayV2CommandType.ADVANCE_TO,
        payload={"virtual_time_ms": target},
    )


async def source(service, session):
    snapshot = (await service.get_session(session))["snapshot"]
    config = ReplaySessionConfig.from_dict(snapshot["config"])
    persisted = await service.store.load_dataset(session)
    bars = _decode_bar_snapshot(persisted, config=config)
    reference = RawAggTradeDatasetRef.from_dict(
        json.loads(persisted["snapshot_blob"])["trade_dataset_ref"]
    )
    reader = PagedReplayTradeReader(service.raw_trade_archive, reference)
    offset = bars.replay_start_ms - reference.start_time_ms
    trades = tuple(trade.with_time_offset(offset) for trade in reader.iter_trades())
    return snapshot, config, bars, reference.end_time_ms + offset, trades


@pytest.mark.parametrize("number", [1, 2])
@pytest.mark.parametrize("interval", ["1m", "2m"])
@pytest.mark.parametrize("coalesced", [False, True])
async def test_clock_boundary_closes_complete_selected_tape_without_another_trade(
    tmp_path, monkeypatch, number, interval, coalesced
):
    if coalesced:
        original = phase5._multi_trade_sources

        def same_time(*args, **kwargs):
            return original(*args, **kwargs, coalesce_trade_timestamps=True)

        monkeypatch.setattr(phase5, "_multi_trade_sources", same_time)
    service, run, session = await setup_tape(tmp_path, held=True)
    try:
        await prepare(service, run, session)
        sid = f"trade-adapter-{number}"
        snapshot, _, _, _, trades = await source(service, sid)
        boundary = compute_bucket_end_ms(
            compute_bucket_start_ms(
                trades[0].trade_time_ms, parse_interval_ms(interval), interval=interval
            ),
            parse_interval_ms(interval),
            interval=interval,
        )
        sequence = sum(trade.trade_time_ms < boundary for trade in trades)
        assert sequence > 1
        assert boundary <= snapshot["cursor"]["virtual_time_ms"]
        args = {
            "track_id": f"track-{number}",
            "data_epoch": snapshot["data_epoch"],
            "display_interval": interval,
            "source_sequence": sequence,
            "limit": 5,
        }
        before = await service.training.tape_projection(
            sid, **args, revealed_boundary_ms=boundary - 1
        )
        after = await service.training.tape_projection(
            sid, **args, revealed_boundary_ms=boundary
        )
        assert before["status"] == after["status"] == "ready"
        assert not before["bars"][-1]["is_closed"]
        expected = deepcopy(before["bars"])
        expected[-1]["is_closed"] = True
        assert after["bars"] == expected
        # The same later clock must not finalize a truncated source cohort.
        partial = await service.training.tape_projection(
            sid,
            **dict(args, source_sequence=sequence - 1),
            revealed_boundary_ms=boundary,
        )
        assert partial["bars"][-1]["is_closed"] is False
        assert partial["bars"][-1]["volume"] != after["bars"][-1]["volume"]
        # Finalizing one disposable selection must not mutate the older cache.
        assert await service.training.tape_projection(
            sid, **args, revealed_boundary_ms=boundary - 1
        ) == before
        # Wider intervals can have a truthful partial oldest warmup bucket.
        selected = [row for row in after["bars"] if row["is_closed"]][-3:]
        period = min(2, len(selected))
        response = await _request(
            _app(service),
            "POST",
            f"/api/v1/replay/runs/session/{sid}/indicator-compute",
            json={
                **{k: v for k, v in args.items() if k != "limit"},
                "revealed_boundary_ms": boundary,
                "history_epoch": after["history_epoch"],
                "name": "MA",
                "params": {"period": period},
                "bars": selected,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "ready"
        last = result["payload"]["lines"][0]["data"][-1]
        assert last["time"] == selected[-1]["open_time_ms"] // 1000
        assert Decimal(str(last["value"])) == sum(
            (Decimal(row["close"]) for row in selected[-period:]), Decimal(0)
        ) / period
        assert (await service.get_session(sid))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)


def scalar_base(config, bars, terminal, trades, sequence, boundary):
    builder = TradeReplayBarBuilder(
        base_interval=config.base_interval,
        display_interval=config.base_interval,
        replay_start_ms=bars.replay_start_ms,
        replay_end_time_ms=terminal,
        warmup_bars=bars.warmup_rows,
        max_closed_bars=1000,
    )
    for trade in trades[:sequence]:
        builder.apply_trade(trade)
    if boundary == terminal and sequence == len(trades):
        builder.finalize_bars(virtual_time_ms=terminal)
    return builder.replace_projection()["bars"]


async def frontend_oracle(tmp_path, cases):
    path = tmp_path / "tape-projection-oracle.json"
    path.write_text(json.dumps(cases))
    process = await asyncio.create_subprocess_exec(
        "node",
        "--import",
        "tsx",
        "scripts/replay-tape-projection-oracle.ts",
        str(path),
        cwd=Path(__file__).resolve().parents[2] / "frontend",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    assert process.returncode == 0, stderr.decode()
    assert json.loads(stdout)["comparisons"] == len(cases)


@pytest.mark.parametrize("interval", ["1m", "2m", "7m", "90m", "1w", "1M"])
async def test_sequence_bound_projection_matches_full_scalar_builder(
    tmp_path, interval
):
    service, run, session = await setup_tape(tmp_path, held=True)
    checks = []
    try:
        await prepare(service, run, session)
        for number in (1, 2):
            sid = f"trade-adapter-{number}"
            snapshot, config, bars, terminal, trades = await source(service, sid)
            before = deepcopy(snapshot)
            for sequence in [0, 1, 2, 3, snapshot["cursor"]["source_sequence"]]:
                boundary = (
                    bars.replay_start_ms
                    if sequence == 0
                    else trades[sequence - 1].trade_time_ms
                )
                for limit in (1, 5):
                    response = await _request(
                        _app(service),
                        "GET",
                        f"/api/v1/replay/runs/session/{sid}/tape-projection",
                        params={
                            "track_id": f"track-{number}",
                            "display_interval": interval,
                            "source_sequence": sequence,
                            "revealed_boundary_ms": boundary,
                            "data_epoch": snapshot["data_epoch"],
                            "limit": limit,
                        },
                    )
                    assert response.status_code == 200, response.text
                    result = response.json()
                    assert result["status"] == "ready"
                    checks.append(
                        {
                            "base": config.base_interval,
                            "interval": interval,
                            "limit": limit,
                            "rows": scalar_base(
                                config, bars, terminal, trades, sequence, boundary
                            ),
                            "actual": result["bars"],
                        }
                    )
            assert (await service.get_session(sid))["snapshot"] == before
        assert (await service.training.audit_account(run))["status"] == "PASS"
        await frontend_oracle(tmp_path, checks)
    finally:
        await service.shutdown(step_timeout=3)


async def test_bounded_projection_resumes_and_rejects_future_and_wrong_sources(
    tmp_path,
):
    service, run, session = await setup_tape(tmp_path)
    try:
        await prepare(service, run, session)
        service.training._display_service._tape_projection = TapeDisplayProjection(
            page_rows=1, pages_per_call=1
        )
        snapshot, config, bars, terminal, trades = await source(service, session)
        args = {
            "track_id": "track-1",
            "data_epoch": snapshot["data_epoch"],
            "display_interval": "2m",
            "limit": 5,
            "source_sequence": snapshot["cursor"]["source_sequence"],
            "revealed_boundary_ms": snapshot["cursor"]["virtual_time_ms"],
        }
        progress = []
        for _ in range(20):
            result = await service.training.tape_projection(session, **args)
            progress.append(result["prepared_sequence"])
            if result["status"] == "ready":
                break
            assert result["bars"] == []
        assert len(progress) > 1 and all(a < b for a, b in itertools.pairwise(progress))
        await frontend_oracle(
            tmp_path,
            [
                {
                    "base": config.base_interval,
                    "interval": "2m",
                    "limit": 5,
                    "rows": scalar_base(
                        config,
                        bars,
                        terminal,
                        trades,
                        args["source_sequence"],
                        args["revealed_boundary_ms"],
                    ),
                    "actual": result["bars"],
                }
            ],
        )
        assert await service.training.tape_projection(session, **args) == result
        for update in [
            {"source_sequence": args["source_sequence"] + 1},
            {"revealed_boundary_ms": args["revealed_boundary_ms"] + 1},
            {"data_epoch": "sha256:" + "f" * 64},
            {"revealed_boundary_ms": bars.replay_start_ms},
        ]:
            with pytest.raises(TrainingRunError):
                await service.training.tape_projection(session, **{**args, **update})
    finally:
        await service.shutdown(step_timeout=3)


async def test_cancellation_drains_archive_reader_without_holding_account_writer(
    tmp_path, monkeypatch
):
    service, run, session = await setup_tape(tmp_path)
    entered, release = Event(), Event()
    try:
        await prepare(service, run, session)
        snapshot, *_ = await source(service, session)
        original = PagedReplayTradeReader.read_sequence_page

        def delayed(reader, **kwargs):
            if kwargs["after_sequence"] == 0:
                entered.set()
                assert release.wait(5)
            return original(reader, **kwargs)

        monkeypatch.setattr(PagedReplayTradeReader, "read_sequence_page", delayed)
        args = {
            "track_id": "track-1",
            "data_epoch": snapshot["data_epoch"],
            "display_interval": "90m",
            "limit": 5,
            "source_sequence": snapshot["cursor"]["source_sequence"],
            "revealed_boundary_ms": snapshot["cursor"]["virtual_time_ms"],
        }
        task = asyncio.create_task(service.training.tape_projection(session, **args))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert (
            await asyncio.wait_for(
                service.store.run_extension_write(
                    lambda connection: connection.execute("SELECT 42").fetchone()[0]
                ),
                1,
            )
            == 42
        )
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await service.training.tape_projection(session, **args))[
            "status"
        ] == "ready"
    finally:
        release.set()
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("blind", [False, True])
async def test_equal_millisecond_prefix_and_calendar_projection_survive_restart(
    tmp_path, monkeypatch, blind
):
    original = phase5._multi_trade_sources

    def same_time(*args, **kwargs):
        return original(
            *args, **kwargs, trades_per_minute=8, coalesce_trade_timestamps=True
        )

    monkeypatch.setattr(phase5, "_multi_trade_sources", same_time)

    async def owner():
        return await phase5._trade_service(
            tmp_path / "same-ms.db",
            archive_root=tmp_path / "tape",
            symbols=("BTCUSDT",),
        )

    service = await owner()
    try:
        request = await phase5._trade_request(service)
        if blind:
            request = replace(
                request, time_disclosure_policy=TimeDisclosurePolicy.HIDE_ALL
            )
        created = await service.training.create_run(request)
        run, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await phase5._acquire(
            service, run_id=run, selected_session_id=session, command_id="acquire"
        )
        await prepare(service, run, session)
        snapshot, config, bars, terminal, trades = await source(service, session)
        checks, outputs = [], []
        for interval in ["1m", "7m", "90m", "1w", "1M", "12M"]:
            for sequence in [1, 2, 7, 8, 9, snapshot["cursor"]["source_sequence"]]:
                boundary = trades[sequence - 1].trade_time_ms
                args = {
                    "track_id": "track-1",
                    "data_epoch": snapshot["data_epoch"],
                    "display_interval": interval,
                    "limit": 3,
                    "source_sequence": sequence,
                    "revealed_boundary_ms": boundary,
                }
                result = await service.training.tape_projection(session, **args)
                assert result["status"] == "ready"
                checks.append(
                    {
                        "base": config.base_interval,
                        "interval": interval,
                        "limit": 3,
                        "rows": scalar_base(
                            config, bars, terminal, trades, sequence, boundary
                        ),
                        "actual": result["bars"],
                    }
                )
                if interval == "1m" and sequence in (1, 2):
                    outputs.append(result["bars"][-1])
        assert outputs[0]["open_time_ms"] == outputs[1]["open_time_ms"]
        assert outputs[0]["volume"] == "1" and outputs[1]["volume"] == "2"
        await frontend_oracle(tmp_path, checks)
        await service.shutdown(step_timeout=3)
        service = await owner()
        assert await service.training.tape_projection(session, **args) == result
        assert (await service.get_session(session))["snapshot"]["cursor"][
            "source_sequence"
        ] == snapshot["cursor"]["source_sequence"]
    finally:
        await service.shutdown(step_timeout=3)


async def test_terminal_and_long_empty_spans_fold_by_display_bucket(
    tmp_path, monkeypatch
):
    service, run, session = await setup_tape(tmp_path)
    try:
        snapshot, config, bars, terminal, trades = await source(service, session)
        await _send(
            service,
            run_id=run,
            session_id=session,
            command_id="terminal",
            command_type=ReplayV2CommandType.ADVANCE_TO,
            payload={"virtual_time_ms": terminal},
        )
        snapshot = (await service.get_session(session))["snapshot"]
        checks = []
        for interval in ["1m", "2m", "7m", "90m"]:
            result = await service.training.tape_projection(
                session,
                track_id="track-1",
                data_epoch=snapshot["data_epoch"],
                display_interval=interval,
                limit=2,
                source_sequence=len(trades),
                revealed_boundary_ms=terminal,
            )
            checks.append(
                {
                    "base": config.base_interval,
                    "interval": interval,
                    "limit": 2,
                    "rows": scalar_base(
                        config, bars, terminal, trades, len(trades), terminal
                    ),
                    "actual": result["bars"],
                }
            )
        await frontend_oracle(tmp_path, checks)
        start = bars.replay_start_ms
        # A quiet year's minutes must not be materialized one at a time.
        end = start + 365 * 86400_000 - 1
        builder = TapeChartBuilder(
            base_interval="1m",
            display_interval="1w",
            replay_start_ms=start,
            replay_end_time_ms=end,
            warmup_bars=bars.warmup_rows,
            max_closed_bars=60,
        )
        feeds = 0
        original = builder._feed

        def counted(*args):
            nonlocal feeds
            feeds += 1
            return original(*args)

        monkeypatch.setattr(builder, "_feed", counted)
        builder.finalize_bars(virtual_time_ms=end)
        assert feeds <= 54
        assert all(
            row["volume"] == "0" for row in builder.replace_projection()["bars"][1:]
        )
    finally:
        await service.shutdown(step_timeout=3)


async def test_real_http_frontend_parser_progress_and_scalar_projection(tmp_path):
    service, run, session = await setup_tape(tmp_path)
    try:
        await prepare(service, run, session)
        service.training._display_service._tape_projection = TapeDisplayProjection(
            page_rows=1, pages_per_call=1
        )
        snapshot, config, bars, terminal, trades = await source(service, session)
        sequence, boundary = (
            snapshot["cursor"]["source_sequence"],
            snapshot["cursor"]["virtual_time_ms"],
        )
        cases = [
            {
                "base": config.base_interval,
                "interval": interval,
                "limit": 3,
                "actual": [],
                "sessionId": session,
                "rows": scalar_base(config, bars, terminal, trades, sequence, boundary),
                "request": {
                    "trackId": "track-1",
                    "dataEpoch": snapshot["data_epoch"],
                    "displayInterval": interval,
                    "limit": 3,
                    "sourceSequence": sequence,
                    "revealedBoundaryMs": boundary,
                },
            }
            for interval in ["1m", "7m", "90m", "1M", "12M"]
        ]
        result = await frontend_probe(
            service, tmp_path, cases, "scripts/replay-tape-projection-oracle.ts"
        )
        assert (
            result["status"] == "PASS"
            and result["comparisons"] == 5
            and result["preparing"] >= 5
        )
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("blind", [False, True])
async def test_real_http_paging_preserves_selected_tail_and_frozen_warmup(
    tmp_path, monkeypatch, blind
):
    original = phase5._multi_trade_sources

    def same_time(*args, **kwargs):
        return original(
            *args, **kwargs, trades_per_minute=8, coalesce_trade_timestamps=True
        )

    monkeypatch.setattr(phase5, "_multi_trade_sources", same_time)
    service = await phase5._trade_service(
        tmp_path / "pages.db", archive_root=tmp_path / "tape", symbols=("BTCUSDT",)
    )
    service.settings = replace(service.settings, controller_ttl_seconds=60)
    try:
        request = await phase5._trade_request(service)
        if blind:
            request = replace(
                request, time_disclosure_policy=TimeDisclosurePolicy.HIDE_ALL
            )
        created = await service.training.create_run(request)
        run, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await phase5._acquire(
            service, run_id=run, selected_session_id=session, command_id="acquire"
        )
        await prepare(service, run, session)
        snapshot, config, bars, terminal, trades = await source(service, session)
        service.training._display_service._tape_projection = TapeDisplayProjection(
            page_rows=2, pages_per_call=1
        )
        cases = []
        for sequence in (0, 1, 9, 18):
            boundary = (
                bars.replay_start_ms
                if sequence == 0
                else trades[sequence - 1].trade_time_ms
            )
            for interval in ("1m", "2m", "7m", "90m", "1w", "1M", "12M"):
                cases.append(
                    {
                        "base": config.base_interval,
                        "interval": interval,
                        "limit": 1,
                        "actual": [],
                        "rows": scalar_base(
                            config, bars, terminal, trades, sequence, boundary
                        ),
                        "sessionId": session,
                        "paginate": True,
                        "request": {
                            "trackId": "track-1",
                            "dataEpoch": snapshot["data_epoch"],
                            "displayInterval": interval,
                            "limit": 1,
                            "sourceSequence": sequence,
                            "revealedBoundaryMs": boundary,
                        },
                    }
                )
        result = await frontend_probe(
            service, tmp_path, cases, "scripts/replay-tape-projection-oracle.ts"
        )
        assert result["status"] == "PASS" and result["comparisons"] == len(cases)
        assert result["preparing"] > 0
        assert (await service.get_session(session))["snapshot"] == snapshot
        bad = await _request(
            _app(service),
            "GET",
            f"/api/v1/replay/runs/session/{session}/tape-projection",
            params={
                "track_id": "track-1",
                "data_epoch": snapshot["data_epoch"],
                "display_interval": "1m",
                "source_sequence": 18,
                "revealed_boundary_ms": snapshot["cursor"]["virtual_time_ms"],
                "before_ms": bars.replay_start_ms + 1,
            },
        )
        assert bad.status_code == 422
    finally:
        await service.shutdown(step_timeout=3)
