import asyncio
import threading
from dataclasses import replace

import pytest

from app.replay.constants import CommandType
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.training.models import ReplayV2CommandType as C
from app.replay.training import tape_phases
from tests.fixtures.replay.service_fakes import replay_config, INTERVAL_MS
from tests.test_replay_service import _service, _command as adapter_command
from tests.test_replay_v2_training_phase5 import (
    _trade_service,
    _trade_request,
    _command,
    _acquire,
)
from tests.test_replay_v2_training_phase6 import _send

pytestmark = pytest.mark.anyio


async def test_durable_command_cache_eviction_preserves_success_failure_and_conflict(
    tmp_path,
):
    path = tmp_path / "cache.db"
    service = await _service(path)
    try:
        created = await service.create_session(replay_config())
        sid = created["session_id"]
        actor = service._sessions[sid].actor
        actor._command_history._max_records = 3
        acquire = adapter_command("acquire", CommandType.ACQUIRE_CONTROLLER, revision=0)
        first = await service.command(sid, acquire)
        bad = adapter_command(
            "bad", CommandType.SET_SPEED, revision=1, payload={"speed": -1}
        )
        with pytest.raises(ReplayDomainError) as rejected:
            await service.command(sid, bad)
        for i in range(10):
            state = await service.get_session_state(sid)
            await service.command(
                sid,
                adapter_command(
                    "speed-" + str(i),
                    CommandType.SET_SPEED,
                    revision=state["revision"],
                    payload={"speed": 1},
                ),
            )
        assert len(actor._command_history._records) == 3
        state = await service.get_session_state(sid)
        assert await service.command(sid, acquire) == first
        # Also exercise a request already queued at the actor, past the service lookup.
        replay = await actor.submit(acquire)
        assert replay.revision == first["revision"]
        with pytest.raises(ReplayDomainError) as replayed:
            await actor.submit(bad)
        assert replayed.value.code == rejected.value.code
        with pytest.raises(ReplayDomainError) as conflict:
            await service.command(
                sid, replace(acquire, expected_revision=state["revision"])
            )
        assert conflict.value.code is ReplayErrorCode.COMMAND_ID_REUSED
        assert (await service.get_session_state(sid))["revision"] == state["revision"]
        await service.shutdown(step_timeout=3)
        service = await _service(path)
        assert await service.command(sid, acquire) == first
    finally:
        await service.shutdown(step_timeout=3)


async def setup_tape(path, *, held=False, quantity="1", track_count=2):
    service = await _trade_service(
        path / "run.db",
        archive_root=path / "tape",
        symbols=("BTCUSDT", "ETHUSDT"),
        symbol_time_offset_ms=200,
    )
    service.settings = replace(
        service.settings,
        replay_fast_forward_optimization_enabled=True,
        controller_ttl_seconds=60,
    )
    created = await service.training.create_run(await _trade_request(service))
    run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    if track_count == 2:
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="add",
            command_type=C.ADD_TRACK,
            payload=dict(
                exchange="binance",
                market_type="futures",
                symbol="ETHUSDT",
                settlement_asset="USDT",
                subscription_tier="FULL",
            ),
        )
    await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
    if held:
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="buy",
            command_type=C.PLACE_ORDER,
            payload=dict(
                client_order_id="buy",
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
                reduce_only=False,
                limit_price=None,
                stop_price=None,
            ),
        )
        state = await service.get_session_state(sid)
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="prime",
            command_type=C.ADVANCE_TO,
            payload=dict(virtual_time_ms=state["cursor"]["virtual_time_ms"] + 2000),
        )
    return service, run, sid


async def arguments(service, run, sid):
    tracks = tuple(await service.training.store.get_market_track_heads(run))
    snapshots = [
        (t, (await service.get_session(t["adapter_session_id"]))["snapshot"])
        for t in tracks
    ]
    target = (
        snapshots[0][1]["cursor"]["virtual_time_ms"] // INTERVAL_MS + 3
    ) * INTERVAL_MS - 1
    command = _command(
        run,
        "batch",
        C.ADVANCE_TO,
        await service.get_session(sid),
        dict(virtual_time_ms=target),
    )
    return dict(
        command=command,
        binding=await service.training.store.run_binding(run),
        tracks=tracks,
        snapshots=snapshots,
        target=target,
    )


@pytest.mark.parametrize("failure", [False, "write", "risk", "prepare"])
async def test_tape_phases_atomic_rollback_and_one_public_snapshot(
    tmp_path, monkeypatch, failure
):
    service, run, sid = await setup_tape(tmp_path, held=True)
    try:
        kwargs = await arguments(service, run, sid)
        prior = {s: await service.get_session_state(s) for s in service._sessions}
        writes = service.store._metrics["transactions"]
        original = service.store.commit_command_phases

        if failure == "prepare":
            from app.replay.training.tape_interval import PreparedIntervalRecord
            encode = PreparedIntervalRecord.prepare
            calls = 0

            def failed_encoding(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected second phase encoding failure")
                return encode(*args)

            monkeypatch.setattr(PreparedIntervalRecord, "prepare", staticmethod(failed_encoding))

        async def commit(phases):
            assert 2 <= len(phases) <= 16
            for key, state in prior.items():
                assert (
                    service._sessions[key].actor._events.after(state["sequence"]) == ()
                )
            if failure:
                rows, pre, post = phases[-1]

                def fail(connection):
                    post(connection)
                    raise (
                        tape_phases.TapeRiskBoundary()
                        if failure == "risk"
                        else RuntimeError("injected tape write failure")
                    )

                phases = [*phases[:-1], (rows, pre, fail)]
            return await original(phases)

        monkeypatch.setattr(service.store, "commit_command_phases", commit)
        if failure in {"write", "prepare"}:
            with pytest.raises(RuntimeError, match="injected"):
                await asyncio.wait_for(
                    tape_phases.try_advance(service.training, **kwargs), 15
                )
        else:
            outcome = await asyncio.wait_for(
                tape_phases.try_advance(service.training, **kwargs), 15
            )
            assert (outcome is None) == (failure == "risk")
        for key, before in prior.items():
            after = await service.get_session_state(key)
            events = service._sessions[key].actor._events.after(before["sequence"])
            if failure:
                assert after["cursor"] == before["cursor"]
                assert after["state_hash"] == before["state_hash"]
                assert events == ()
            else:
                assert len(events) == 1 and events[0].type.value == "replay.snapshot"
        assert service.store._metrics["transactions"] - writes == (0 if failure else 1)
    finally:
        await service.shutdown(step_timeout=3)


async def test_committed_tape_batch_resumes_parent_after_restart(tmp_path, monkeypatch):
    service, run, sid = await setup_tape(tmp_path, held=True)
    try:
        kwargs = await arguments(service, run, sid)
        result = await tape_phases.try_advance(service.training, **kwargs)
        assert result is not None
        committed = result[1]
        await service.shutdown(step_timeout=3)

        service = await _trade_service(
            tmp_path / "run.db",
            archive_root=tmp_path / "tape",
            symbols=("BTCUSDT", "ETHUSDT"),
            symbol_time_offset_ms=200,
        )
        service.settings = replace(
            service.settings, replay_fast_forward_optimization_enabled=True
        )
        replay = await service.training.command(run, kwargs["command"])
        assert replay["data"]["recovered"] is True
        assert replay["cursor"]["virtual_time_ms"] == kwargs["target"] > committed
        duplicate = await service.training.command(run, kwargs["command"])
        assert duplicate == replay
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)


async def test_tape_cancel_drains_commit_and_keeps_recoverable_parent(
    tmp_path, monkeypatch
):
    service, run, sid = await setup_tape(tmp_path, held=True)
    release = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    task = None
    try:
        kwargs = await arguments(service, run, sid)
        before = {s: await service.get_session_state(s) for s in service._sessions}
        original = service.store.commit_command_phases

        async def paused(phases):
            rows, pre, post = phases[0]

            def pause(connection):
                post(connection)
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(15):
                    raise TimeoutError("commit not released")

            return await original([(rows, pre, pause), *phases[1:]])

        monkeypatch.setattr(service.store, "commit_command_phases", paused)
        task = asyncio.create_task(tape_phases.try_advance(service.training, **kwargs))
        await asyncio.wait_for(entered.wait(), 15)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        for key, state in before.items():
            assert service._sessions[key].actor._events.after(state["sequence"]) == ()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 15)
        monkeypatch.setattr(service.store, "commit_command_phases", original)
        recovered = await service.training.command(run, kwargs["command"])
        assert recovered["data"]["recovered"] is True
        assert recovered["cursor"]["virtual_time_ms"] == kwargs["target"]
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await service.shutdown(step_timeout=3)


async def test_tape_pending_order_falls_back_without_consuming_events(tmp_path):
    service, run, sid = await setup_tape(tmp_path, held=True)
    try:
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="limit",
            command_type=C.PLACE_ORDER,
            payload=dict(
                client_order_id="limit",
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                reduce_only=False,
                limit_price="90",
                stop_price=None,
            ),
        )
        kwargs = await arguments(service, run, sid)
        before = [s["cursor"] for _, s in kwargs["snapshots"]]
        writes = service.store._metrics["transactions"]
        assert await tape_phases.try_advance(service.training, **kwargs) is None
        after = await arguments(service, run, sid)
        assert [s["cursor"] for _, s in after["snapshots"]] == before
        assert service.store._metrics["transactions"] == writes
    finally:
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("same_millisecond", [False, True])
async def test_real_liquidation_excursion_aborts_unpublished_tape_batch(
    tmp_path, monkeypatch, same_millisecond
):
    from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
    from tests.fixtures.replay.trade_service_fakes import TRADE_REPLAY_START_MS

    original = ParquetRawAggTradeArchive.import_verified_day

    def crash_tape(archive, trades, metadata, **kwargs):
        adjusted = []
        for trade in trades:
            row = dict(trade)
            minute = (row["trade_time_ms"] - TRADE_REPLAY_START_MS) // INTERVAL_MS
            if row["symbol"] == "BTCUSDT" and minute == 1:
                if not same_millisecond or row["trade_time_ms"] % INTERVAL_MS == 1000:
                    row["price"] = 1
                if same_millisecond:
                    row["trade_time_ms"] = TRADE_REPLAY_START_MS + INTERVAL_MS + 1000
            row["quantity"] = 1000
            row["quote_quantity"] = row["price"] * 1000
            adjusted.append(row)
        return original(archive, adjusted, metadata, **kwargs)

    monkeypatch.setattr(ParquetRawAggTradeArchive, "import_verified_day", crash_tape)
    service, run, sid = await setup_tape(tmp_path, held=True, quantity="200")
    try:
        kwargs = await arguments(service, run, sid)
        before = {s: await service.get_session_state(s) for s in service._sessions}
        assert await tape_phases.try_advance(service.training, **kwargs) is None
        for key, state in before.items():
            after = await service.get_session_state(key)
            assert after["cursor"] == state["cursor"]
            assert after["state_hash"] == state["state_hash"]
            assert service._sessions[key].actor._events.after(state["sequence"]) == ()
        # The original global coordinator must still observe the temporary crash,
        # even though the next minute recovers to the ordinary endpoint price.
        result = await service.training.command(run, kwargs["command"])
        portfolio = (await service.training.get_market_tracks(run))["portfolio"]
        assert portfolio["liquidations"]
        assert result["cursor"]["virtual_time_ms"] <= kwargs["target"]
    finally:
        await service.shutdown(step_timeout=3)


def test_durable_tape_wave_windows_require_progress_and_keep_legacy_bound():
    from types import SimpleNamespace

    store = SimpleNamespace(_multi_interval_commands={("run", "command")})
    command = SimpleNamespace(run_id="run", command_id="command")
    job = dict(current_virtual_time_ms=0, consumed=0, status="RUNNING")
    waves = tape_phases.coordinator_waves(
        store, command, {"source_kind": "AGG_TRADE"}, job, 2
    )
    assert next(waves) == 0
    assert next(waves) == 1
    job.update(current_virtual_time_ms=1, consumed=16)
    assert next(waves) == 0
    assert next(waves) == 1
    with pytest.raises(StopIteration):
        next(waves)  # No forward progress in this window.
    for binding, active_job in [
        ({"source_kind": "BAR"}, job),
        ({"source_kind": "AGG_TRADE"}, None),
    ]:
        assert list(
            tape_phases.coordinator_waves(store, command, binding, active_job, 2)
        ) == [0, 1]


async def test_tape_advance_renews_small_wave_windows(tmp_path, monkeypatch):
    service, run, sid = await setup_tape(tmp_path, held=True)
    original = tape_phases.coordinator_waves
    windows = []

    def small_windows(store, command, binding, job, budget):
        for index in original(store, command, binding, job, 1):
            windows.append(index)
            yield index

    monkeypatch.setattr(tape_phases, "coordinator_waves", small_windows)
    try:
        kwargs = await arguments(service, run, sid)
        result = await service.training.command(run, kwargs["command"])
        assert result["cursor"]["virtual_time_ms"] == kwargs["target"]
        assert len(windows) > 1
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)


async def test_tape_terminal_clock_checkpoint_resumes_before_parent_reply(
    tmp_path, monkeypatch
):
    service, run, sid = await setup_tape(tmp_path, held=True)
    try:
        kwargs = await arguments(service, run, sid)
        original = service.training.store.finish_advance_intent

        async def fail(**kwargs):
            raise RuntimeError("before parent reply")

        monkeypatch.setattr(service.training.store, "finish_advance_intent", fail)
        with pytest.raises(RuntimeError, match="before parent reply"):
            await service.training.command(run, kwargs["command"])
        monkeypatch.setattr(service.training.store, "finish_advance_intent", original)
        result = await service.training.command(run, kwargs["command"])
        assert result["data"]["recovered"] is True
        assert result["cursor"]["virtual_time_ms"] == kwargs["target"]
    finally:
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("spread", [False, True])
async def test_dense_same_time_tape_matches_scalar_financials_and_order(
    tmp_path, monkeypatch, spread
):
    from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
    from tests.fixtures.replay.trade_service_fakes import TRADE_REPLAY_START_MS

    original_import = ParquetRawAggTradeArchive.import_verified_day

    def dense(archive, trades, metadata, **kwargs):
        rows = []
        for row in trades:
            minute = (row["trade_time_ms"] - TRADE_REPLAY_START_MS) // INTERVAL_MS
            for j in range(40 if minute == 1 else 1):
                value = dict(row)
                if spread and minute == 1:
                    start = TRADE_REPLAY_START_MS + minute * INTERVAL_MS
                    value["trade_time_ms"] = (
                        start + 1000 + (row["trade_time_ms"] - start - 1000) * 100 + j
                    )
                    value["event_time_ms"] = value["trade_time_ms"]
                rows.append(value)
        for i, row in enumerate(rows):
            minute = (row["trade_time_ms"] - TRADE_REPLAY_START_MS) // INTERVAL_MS
            if minute == 1:
                row["price"] += 5 if i % 2 else -5
                row["quote_quantity"] = row["price"] * row["quantity"]
            row.update(
                agg_trade_id=metadata.first_agg_trade_id + i,
                first_trade_id=(metadata.first_agg_trade_id + i) * 10,
                last_trade_id=(metadata.first_agg_trade_id + i) * 10,
            )
        metadata = replace(
            metadata, row_count=len(rows), last_agg_trade_id=rows[-1]["agg_trade_id"]
        )
        return original_import(archive, rows, metadata, **kwargs)

    monkeypatch.setattr(ParquetRawAggTradeArchive, "import_verified_day", dense)
    results = []
    largest = []
    original_phases = tape_phases.commit_actor_phases
    for enabled, summarized in ((False, False), (True, False), (True, True)):

        async def commit_phases(service, phases, **kwargs):
            for phase in phases:
                phase["tape_summary"] = summarized
            return await original_phases(service, phases, **kwargs)

        monkeypatch.setattr(tape_phases, "commit_actor_phases", commit_phases)
        service, run, sid = await setup_tape(
            tmp_path / f"{enabled}-{summarized}", held=True
        )
        service.settings = replace(
            service.settings, replay_fast_forward_optimization_enabled=enabled
        )
        try:
            original_commit = service.store.commit_command_phases

            async def observe(phases):
                largest.extend(
                    row["result"]["data"]["consumed"]
                    for rows, _, _ in phases
                    for row in rows
                )
                return await original_commit(phases)

            monkeypatch.setattr(service.store, "commit_command_phases", observe)
            kwargs = await arguments(service, run, sid)
            await service.training.command(run, kwargs["command"])
            portfolio = (await service.training.get_market_tracks(run))["portfolio"]
            for resolution in ("1M", "15M", "1H", "EVENT"):
                await service.training.equity(run, resolution=resolution, limit=1000)
            events = await service.store.run_extension_read(
                lambda c: [
                    tuple(r)
                    for r in c.execute(
                        "SELECT actual_event_time_ms,event_phase,track_id,source_sequence FROM replay_training_global_event ORDER BY global_sequence"
                    )
                ]
            )
            results.append(
                (
                    [
                        portfolio[k]
                        for k in (
                            "cash_balance",
                            "equity",
                            "unrealized_pnl",
                            "fees_paid",
                            "history",
                            "positions",
                        )
                    ],
                    events,
                    (await service.report(sid))["report"]["max_drawdown"],
                    service._sessions[sid].actor._event_chain_hash,
                    service._sessions[sid].actor._reducer._bar_builder.snapshot(),
                    await service.store.run_extension_read(
                        lambda c: [
                            tuple(row)
                            for row in c.execute(
                                "SELECT resolution,bucket_id,source_sequence,public_time_json,equity,cash_balance,unrealized_pnl "
                                "FROM replay_equity_sample ORDER BY resolution,bucket_id"
                            )
                        ]
                    ),
                    await service.store.run_extension_read(
                        lambda c: [
                            tuple(row)
                            for row in c.execute(
                                "SELECT track_id,highest_mark,lowest_mark FROM replay_training_trade_projection ORDER BY track_id"
                            )
                        ]
                    ),
                )
            )
            if summarized:
                from tests.test_replay_tape_interval import assert_interval_history

                await assert_interval_history(service, run, tmp_path)
                assert (
                    sum(
                        h.actor._metrics.get("tape_summary_events", 0)
                        for h in service._sessions.values()
                    )
                    > 32
                )
            assert (await service.training.audit_account(run))["status"] == "PASS"
        finally:
            await service.shutdown(step_timeout=3)
    assert max(largest) > 32
    assert results[0][:5] == results[1][:5] == results[2][:5]
    # Scalar same-millisecond delivery retains packet endpoints and historically
    # misses the 96 excursion in this review projection. Check the actual tape.
    assert results[2][6][0] == ("track-1", "106", "96")
    if spread:
        assert results[0][6] == results[2][6]
    # Existing scalar and grouped coordinators retain different EVENT anchors.
    # Summary substitution preserves every anchor of the grouped path exactly.
    assert results[1] == results[2]
    assert [r for r in results[0][5] if r[0] != "EVENT"] == [
        r for r in results[2][5] if r[0] != "EVENT"
    ]
