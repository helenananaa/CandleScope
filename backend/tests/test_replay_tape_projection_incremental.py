from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from threading import Event
from time import perf_counter

import pytest
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.errors import ReplayDomainError
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.models import TimeDisclosurePolicy
from app.replay.training.tape_chart_builder import TapeChartBuilder
from app.replay.training.tape_projection import TapeDisplayProjection

from tests import test_replay_v2_training_phase5 as phase5
from tests.test_replay_tape_phases import setup_tape
from tests.test_replay_tape_projection import prepare, source

pytestmark = pytest.mark.anyio


async def dense_source(tmp_path, monkeypatch, *, blind=False):
    original = phase5._multi_trade_sources

    def dense(*args, **kwargs):
        return original(
            *args, **kwargs, trades_per_minute=256, coalesce_trade_timestamps=True
        )

    monkeypatch.setattr(phase5, "_multi_trade_sources", dense)
    service = await phase5._trade_service(
        tmp_path / "run.db", archive_root=tmp_path / "tape", symbols=("BTCUSDT",)
    )
    service.settings = replace(service.settings, controller_ttl_seconds=60)
    request = replace(
        await phase5._trade_request(service),
        time_disclosure_policy=TimeDisclosurePolicy.HIDE_ALL
        if blind
        else TimeDisclosurePolicy.NONE,
    )
    created = await service.training.create_run(request)
    run, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await phase5._acquire(
        service, run_id=run, selected_session_id=session, command_id="acquire"
    )
    await prepare(service, run, session)
    snapshot, _, frozen, terminal, trades = await source(service, session)
    common = {
        "binding": await service.training.store.history_binding(
            session_id=session, track_id="track-1"
        ),
        "persisted": await service.store.load_dataset(session),
        "archive": service.raw_trade_archive,
        "data_epoch": snapshot["data_epoch"],
        "cancelled": Event(),
    }
    return service, session, snapshot, frozen, terminal, trades, common


def ready(projection, **request):
    for _ in range(200):
        result = projection.compute(**request)
        if result["status"] == "ready":
            return result
    pytest.fail("projection preparation did not converge")


@pytest.mark.parametrize("blind", [False, True])
async def test_forward_windows_reduce_only_new_trades_and_match_cold_reconstruction(
    tmp_path, monkeypatch, blind
):
    service, session, snapshot, _, _, trades, common = await dense_source(
        tmp_path, monkeypatch, blind=blind
    )
    original = TapeChartBuilder.apply_trades_final_state
    original_validation = service.raw_trade_archive.validate_dataset
    counts = {"warm": 0, "cold": 0, "warm_validations": 0, "cold_validations": 0}
    mode = "warm"

    def counted(builder, rows):
        counts[mode] += len(rows)
        return original(builder, rows)

    monkeypatch.setattr(TapeChartBuilder, "apply_trades_final_state", counted)

    def validated(reference):
        counts[mode + "_validations"] += 1
        return original_validation(reference)

    monkeypatch.setattr(service.raw_trade_archive, "validate_dataset", validated)
    measurements = []
    try:
        for interval in ("1m", "90m", "1M"):
            counts.update(warm=0, cold=0, warm_validations=0, cold_validations=0)
            projection = TapeDisplayProjection(page_rows=64, pages_per_call=2)
            elapsed = {"warm": 0.0, "cold": 0.0}
            saved = {}
            for sequence in range(64, 513, 32):
                request = dict(
                    **common,
                    display_interval=interval,
                    source_sequence=sequence,
                    revealed_boundary_ms=trades[sequence - 1].trade_time_ms,
                    limit=3,
                )
                mode = "warm"
                started = perf_counter()
                actual = ready(projection, **request)
                elapsed[mode] += perf_counter() - started
                mode = "cold"
                started = perf_counter()
                expected = ready(TapeDisplayProjection(), **request)
                elapsed[mode] += perf_counter() - started
                assert actual == expected
                saved[sequence] = (request, expected)
            measurements.append(
                dict(interval=interval, blind=blind, **counts, seconds=elapsed)
            )
            # A newer cached builder cannot mutate an earlier prefix, including
            # a same-millisecond cursor, after it has been evicted/reconstructed.
            for sequence in (64, 256, 512, 128):
                request, expected = saved[sequence]
                assert ready(projection, **request) == expected
            assert len(projection._cache) <= projection.capacity
            assert len(projection._selections) <= projection.capacity * 4
        assert (await service.get_session(session))["snapshot"] == snapshot
        print("FORWARD_WINDOW_WORK=" + json.dumps(measurements))
        assert all(row["warm"] <= 512 for row in measurements), measurements
        assert all(row["cold"] > 4000 for row in measurements), measurements
        assert all(row["warm_validations"] == 1 for row in measurements), measurements
        assert all(row["cold_validations"] == 15 for row in measurements), measurements
    finally:
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("completed_window_churn", [False, True])
async def test_changed_forming_targets_continue_partial_context_without_restarting(
    tmp_path,
    completed_window_churn,
):
    service, run, session = await setup_tape(tmp_path)
    try:
        await prepare(service, run, session)
        snapshot, _, frozen, _, trades = await source(service, session)
        stop = frozen.warmup_rows[0].open_time_ms
        reads = []

        class Context:
            origin_ms = stop - 40 * 60000
            history_epoch = "sha256:" + "d" * 64

            def read(self, start, end):
                reads.append((start, end))
                end = min(end, start + 10 * 60000)
                rows = tuple(
                    ReplayDisplayBar(
                        open_time_ms=at,
                        close_time_ms=at + 59999,
                        open="100",
                        high="102",
                        low="99",
                        close="101",
                        volume="2",
                        quote_volume=None,
                        trades=None,
                        taker_buy_base=None,
                        taker_buy_quote=None,
                        first_base_open_ms=at,
                        last_base_open_ms=at,
                        component_count=1,
                        expected_components=1,
                        is_closed=True,
                        synthetic=False,
                    )
                    for at in range(start, end, 60000)
                )
                return IndicatorHistoryChunk(start, end, rows, ())

        common = {
            "binding": await service.training.store.history_binding(
                session_id=session, track_id="track-1"
            ),
            "persisted": await service.store.load_dataset(session),
            "archive": service.raw_trade_archive,
            "data_epoch": snapshot["data_epoch"],
            "cancelled": Event(),
            "context_history": Context(),
            "display_interval": "90m",
            "limit": 500,
        }
        clock = [0.0]
        projection = TapeDisplayProjection(
            pages_per_call=1, capacity=3, clock=lambda: clock[0]
        )
        for sequence in range(1, 5):
            result = projection.compute(
                **common,
                source_sequence=sequence,
                revealed_boundary_ms=trades[sequence - 1].trade_time_ms,
            )
            assert (
                result["context_prepared_before_ms"] == stop - (4 - sequence) * 600000
            )
            if completed_window_churn:
                # Other chart/indicator origin probes are cheap completed
                # windows. They must not discard an in-progress cold chart.
                for limit in (1, 2, 3):
                    empty = projection.compute(
                        **{**common, "limit": limit},
                        source_sequence=sequence,
                        revealed_boundary_ms=trades[sequence - 1].trade_time_ms,
                        before_ms=result["history_boundary_ms"],
                    )
                    assert empty["status"] == "ready" and empty["bars"] == []
                    assert len(projection._cache) <= projection.capacity
        final_request = dict(
            **common, source_sequence=4, revealed_boundary_ms=trades[3].trade_time_ms
        )
        final = ready(projection, **final_request)
        assert len(reads) == 4
        assert final == ready(TapeDisplayProjection(), **final_request)
        # A different history identity must reconstruct rather than borrowing
        # an old generation's prepared values.
        common["context_history"].history_epoch = "sha256:" + "e" * 64
        changed = projection.compute(
            **common, source_sequence=4, revealed_boundary_ms=trades[3].trade_time_ms
        )
        assert changed["context_prepared_before_ms"] == stop - 30 * 60000
        assert changed["history_epoch"] != final["history_epoch"]
        if completed_window_churn:
            # An abandoned observer eventually loses its grace period, so a
            # cache full of cancelled charts cannot disable ready-window reuse.
            clock[0] += 121
            for limit in (1, 2, 3):
                ready(
                    projection,
                    **{
                        **final_request,
                        "limit": limit,
                        "before_ms": changed["history_boundary_ms"],
                    },
                )
            restarted = projection.compute(**final_request)
            assert (
                restarted["context_prepared_before_ms"]
                == changed["context_prepared_before_ms"]
            )
            assert len(projection._cache) <= projection.capacity
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)


async def test_waiting_for_a_mutating_predecessor_is_cancellable(tmp_path, monkeypatch):
    service, session, snapshot, _, _, trades, common = await dense_source(
        tmp_path, monkeypatch
    )
    projection = TapeDisplayProjection(page_rows=32, pages_per_call=1)
    request = dict(
        **common,
        display_interval="90m",
        limit=3,
        source_sequence=64,
        revealed_boundary_ms=trades[63].trade_time_ms,
    )
    entered, release, waiting, cancel = Event(), Event(), Event(), Event()
    original = TapeChartBuilder.apply_trades_final_state
    extend = projection._extend_prefix

    def held(builder, rows):
        entered.set()
        assert release.wait(5)
        return original(builder, rows)

    def watched(key, target, cancelled):
        if target.target_sequence == 128:
            waiting.set()
        return extend(key, target, cancelled)

    old = later = None
    try:
        initial = projection.compute(**request)
        assert initial["status"] == "preparing" and initial["prepared_sequence"] == 32
        monkeypatch.setattr(TapeChartBuilder, "apply_trades_final_state", held)
        monkeypatch.setattr(projection, "_extend_prefix", watched)
        old = asyncio.create_task(asyncio.to_thread(projection.compute, **request))
        assert await asyncio.to_thread(entered.wait, 3)
        later = asyncio.create_task(
            asyncio.to_thread(
                projection.compute,
                **{
                    **request,
                    "source_sequence": 128,
                    "revealed_boundary_ms": trades[127].trade_time_ms,
                    "cancelled": cancel,
                },
            )
        )
        assert await asyncio.to_thread(waiting.wait, 3)
        cancel.set()
        with pytest.raises(InterruptedError):
            await asyncio.wait_for(later, 1)
        release.set()
        final = await asyncio.wait_for(old, 2)
        assert final["status"] == "ready"
        assert final == ready(TapeDisplayProjection(), **request)
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (old, later) if task), return_exceptions=True
        )
        await service.shutdown(step_timeout=3)


async def test_reader_reuse_requires_the_whole_manifest_and_ends_with_cache_lifetime(
    tmp_path, monkeypatch
):
    service, session, snapshot, _, _, trades, common = await dense_source(
        tmp_path, monkeypatch
    )
    projection = TapeDisplayProjection()
    original = service.raw_trade_archive.validate_dataset
    validations = 0

    def counted(reference):
        nonlocal validations
        validations += 1
        return original(reference)

    monkeypatch.setattr(service.raw_trade_archive, "validate_dataset", counted)
    request = dict(
        **common,
        display_interval="90m",
        limit=3,
        source_sequence=64,
        revealed_boundary_ms=trades[63].trade_time_ms,
    )
    try:
        ready(projection, **request)
        request.update(
            source_sequence=128, revealed_boundary_ms=trades[127].trade_time_ms
        )
        ready(projection, **request)
        assert validations == 1
        corrupt = dict(common["persisted"])
        payload = json.loads(corrupt["snapshot_blob"])
        payload["trade_dataset_ref"]["objects"][0]["parquet_sha256"] = "f" * 64
        corrupt["snapshot_blob"] = json.dumps(payload).encode()
        request.update(
            source_sequence=192, revealed_boundary_ms=trades[191].trade_time_ms
        )
        with pytest.raises(ReplayDomainError, match="checksum validation"):
            ready(projection, **{**request, "persisted": corrupt})
        assert validations == 2
        projection._cache.clear()
        ready(projection, **request)
        assert validations == 3
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)
