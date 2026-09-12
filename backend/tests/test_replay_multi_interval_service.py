import json
from decimal import Decimal
import pytest

from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tracks,margin,sides",
    [
        (2, "CROSS", ("LONG",)),
        (2, "CROSS", ("SHORT",)),
        (2, "CROSS", ("LONG", "SHORT")),
        (2, "ISOLATED", ("LONG",)),
        (2, "ISOLATED", ("LONG", "SHORT")),
        (8, "CROSS", ("LONG",)),
        (8, "CROSS", ("SHORT",)),
        (8, "CROSS", ("LONG", "SHORT")),
        (8, "ISOLATED", ("LONG",)),
        (8, "ISOLATED", ("SHORT",)),
        (8, "ISOLATED", ("LONG", "SHORT")),
    ],
)
async def test_multi_interval_matches_scalar_finances_and_curve(
    tmp_path, monkeypatch, tracks, margin, sides
):
    install_shared_market(monkeypatch, tmp_path / "market")
    results = []
    for enabled in (True, False):
        s, run, session, send = await make_multi(
            tmp_path / str(enabled),
            enabled=enabled,
            tracks=tracks,
            margin_mode=margin,
            sides=sides,
            initial_equity="10000" if tracks == 8 else None,
        )
        try:
            risk_equities = []
            original = s.training.store._detect_contract_liquidations

            def observe(
                connection,
                *args,
                _original=original,
                _owner=s.training.store,
                _values=risk_equities,
                **kwargs,
            ):
                value = _original(connection, *args, **kwargs)
                rid = kwargs["run_id"]
                initial = connection.execute(
                    "SELECT initial_equity FROM replay_training_run WHERE run_id=?",
                    (rid,),
                ).fetchone()[0]
                heads = [
                    _owner._market_track_from_row(r)
                    for r in connection.execute(
                        "SELECT * FROM replay_training_market_track WHERE run_id=? ORDER BY stable_ordinal,track_id",
                        (rid,),
                    )
                ]
                _values.append(
                    _owner._contract_current_equity(
                        connection, run_id=rid, initial_equity=initial, tracks=heads
                    )
                )
                return value

            monkeypatch.setattr(
                s.training.store, "_detect_contract_liquidations", observe
            )
            before = (await s.get_session_state(session))["cursor"]["virtual_time_ms"]
            await send(
                "advance",
                C.ADVANCE_TO,
                dict(virtual_time_ms=before + 90 * 60000, stop_on_event=False),
            )
            track_heads = await s.training.store.get_market_track_heads(run)
            curve = await s.training.equity(run, resolution="EVENT", limit=5000)
            audit = await s.training.audit_account(run)
            result = dict(
                tracks=[(t["position"], t["account"]) for t in track_heads],
                curve=curve,
                audit=audit,
            )
            result["portfolio_intervals"] = await s.store.run_extension_read(
                lambda c: [
                    json.loads(r[0])
                    for r in c.execute(
                        "SELECT summary_json FROM replay_multi_bar_interval WHERE run_id=? AND start_time_ms>=? ORDER BY end_time_ms",
                        (run, before),
                    )
                ]
            )
            result["risk_equities"] = risk_equities
            (tmp_path / f"{enabled}.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            results.append(result)
            if enabled:
                from app.replay.training.multi_interval_store import (
                    reconstruct_portfolio_interval,
                )

                stored_basis = await s.store.run_extension_read(
                    lambda c: c.execute(
                        "SELECT basis_json,summary_json FROM replay_multi_bar_interval WHERE run_id=? AND start_time_ms>=? ORDER BY end_time_ms LIMIT 1",
                        (run, before),
                    ).fetchone()
                )
                basis = json.loads(stored_basis[0])
                rebuilt = await s.store.run_worker(
                    "test_portfolio_history",
                    reconstruct_portfolio_interval,
                    basis,
                    input_root=s.training.hedge_inputs.root,
                    limit=20,
                )
                assert {
                    k: v for k, v in rebuilt.items() if k != "points"
                } == json.loads(stored_basis[1])
                assert len(rebuilt["points"]) <= 20
                assert all(at <= basis["end_time_ms"] for at, _ in rebuilt["points"])
                assert (
                    sum(
                        h.actor._metrics.get("indexed_skipped_events", 0)
                        for h in s._sessions.values()
                    )
                    >= 180
                )
                snapshot = (await s.get_session(session))["snapshot"]
                projection = await s.training.history_page(
                    session,
                    track_id=track_heads[-1]["track_id"],
                    before_ms=snapshot["cursor"]["virtual_time_ms"] + 1,
                    history_epoch=None,
                    revealed_boundary_ms=snapshot["cursor"]["virtual_time_ms"],
                    limit=120,
                    data_epoch=snapshot["data_epoch"],
                    display_interval="1m",
                )
                assert len(projection["bars"]) > 64
        finally:
            await s.shutdown(step_timeout=5)
    assert results[0]["tracks"] == results[1]["tracks"]
    assert results[0]["audit"]["status"] == "PASS", results[0]["audit"]
    from app.replay.training.multi_interval import combine_equity_summaries

    summary = combine_equity_summaries(results[0]["portfolio_intervals"])
    reference = [
        Decimal(summary["first"]),
        *(Decimal(v) for v in results[1]["risk_equities"]),
    ]
    assert Decimal(summary["peak"]) == max(reference)
    assert Decimal(summary["trough"]) == min(reference)
    peak, drawdown = reference[0], Decimal(0)
    for equity in reference:
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    assert Decimal(summary["max_drawdown"]) == drawdown
    assert [
        (x["source_sequence"], Decimal(x["equity"]))
        for x in results[0]["curve"]["samples"]
    ] == [
        (x["source_sequence"], Decimal(x["equity"]))
        for x in results[1]["curve"]["samples"]
    ]


@pytest.mark.anyio
async def test_group_failure_never_commits_partial_actor_state(tmp_path, monkeypatch):
    install_shared_market(monkeypatch, tmp_path / "market")
    s, run, session, send = await make_multi(tmp_path / "run")
    try:
        before = await s.training.store.get_market_track_heads(run)
        intervals_before = await s.store.run_extension_read(
            lambda c: c.execute(
                "SELECT COUNT(*) FROM replay_multi_bar_interval"
            ).fetchone()[0]
        )
        original = s.store.commit_command_group

        async def fail_after_staging(commands, *, before, after):
            def fail(connection):
                after(connection)
                raise RuntimeError("injected group write failure")

            return await original(commands, before=before, after=fail)

        monkeypatch.setattr(s.store, "commit_command_group", fail_after_staging)
        at = (await s.get_session_state(session))["cursor"]["virtual_time_ms"]
        with pytest.raises(Exception):
            await send(
                "advance",
                C.ADVANCE_TO,
                dict(virtual_time_ms=at + 90 * 60000, stop_on_event=False),
            )
        persisted = await s.training.store.get_market_track_heads(run)
        assert [(t["cursor"], t["position"], t["account"]) for t in persisted] == [
            (t["cursor"], t["position"], t["account"]) for t in before
        ]
        assert (
            await s.store.run_extension_read(
                lambda c: c.execute(
                    "SELECT COUNT(*) FROM replay_multi_bar_interval"
                ).fetchone()[0]
            )
            == intervals_before
        )
    finally:
        await s.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_group_builder_failure_rolls_back_prior_computed_candidates(
    tmp_path, monkeypatch
):
    from app.replay.broker.prepared_interval import PreparedBarInterval

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", tracks=8)
    try:
        before = {
            sid: (await service.get_session(sid))["snapshot"]
            for sid in service._sessions
        }
        original = PreparedBarInterval.apply
        calls = []

        def fail(self, *args, **kwargs):
            calls.append(self)
            if len(calls) == 2:
                raise RuntimeError("injected second candidate failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(PreparedBarInterval, "apply", fail)
        with pytest.raises(Exception):
            await send(
                "build-failure",
                C.ADVANCE_TO,
                {
                    "virtual_time_ms": before[session]["cursor"]["virtual_time_ms"]
                    + 90 * 60000,
                    "stop_on_event": False,
                },
            )
        assert len(calls) == 2
        for sid, expected in before.items():
            actual = (await service.get_session(sid))["snapshot"]
            assert actual["cursor"] == expected["cursor"]
            assert actual["components"] == expected["components"]
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_candidate_encoding_failure_restores_every_actor_cursor(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run")
    try:
        before = {
            sid: handle.actor._source.cursor().source_sequence
            for sid, handle in service._sessions.items()
        }
        victim = service._sessions[session].actor
        original = victim._checkpoint_codec.encode

        def fail(payload, **kwargs):
            if kwargs.get("compress_small"):
                raise RuntimeError("injected candidate encoding failure")
            return original(payload, **kwargs)

        monkeypatch.setattr(victim._checkpoint_codec, "encode", fail)
        at = (await service.get_session_state(session))["cursor"]["virtual_time_ms"]
        with pytest.raises(Exception):
            await send(
                "advance",
                C.ADVANCE_TO,
                {"virtual_time_ms": at + 90 * 60000, "stop_on_event": False},
            )
        assert {
            sid: handle.actor._source.cursor().source_sequence
            for sid, handle in service._sessions.items()
        } == before
        heads = await service.training.store.get_market_track_heads(run)
        assert all(
            t["cursor"]["source_sequence"] == before[t["adapter_session_id"]]
            for t in heads
        )
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["order", "funding", "tier", "liquidation"])
async def test_multi_interval_exact_boundaries_match_reference(
    tmp_path, monkeypatch, boundary
):
    install_shared_market(monkeypatch, tmp_path / "market")
    outcomes = []
    for enabled in (True, False):
        later = (
            "600"
            if boundary == "tier"
            else "10"
            if boundary == "liquidation"
            else "110"
        )
        prices = [
            "100" if i < 83 or boundary == "funding" else later for i in range(104)
        ]
        marks = [
            "100" if i < 80 or boundary in {"order", "funding"} else later
            for i in range(101)
        ]
        service, run, session, send = await make_multi(
            tmp_path / str(enabled),
            enabled=enabled,
            horizon=100,
            prices=prices,
            marks=marks,
            quantity="100" if boundary == "tier" else "0.1",
            initial_equity="10" if boundary == "liquidation" else None,
            funding_offset=50 if boundary == "funding" else 0,
        )
        try:
            if boundary == "order":
                await send(
                    "limit",
                    C.PLACE_ORDER,
                    {
                        "client_order_id": "limit",
                        "side": "SELL",
                        "position_side": "LONG",
                        "order_type": "LIMIT",
                        "quantity": "0.05",
                        "reduce_only": True,
                        "limit_price": "105",
                        "stop_price": None,
                    },
                )
            before = (await service.get_session_state(session))["cursor"][
                "virtual_time_ms"
            ]
            result = await send(
                "advance",
                C.ADVANCE_TO,
                {
                    "virtual_time_ms": before + 90 * 60000,
                    "stop_on_event": boundary != "tier",
                },
            )
            heads = await service.training.store.get_market_track_heads(run)
            outcomes.append(
                (
                    result["cursor"]["virtual_time_ms"],
                    result["data"].get("event_stop", {}).get("reason"),
                    [
                        (t["position"], t["account"], t["cursor"]["source_sequence"])
                        for t in heads
                    ],
                )
            )
            assert (await service.training.audit_account(run))["status"] == "PASS"
            if enabled:
                count = await service.store.run_extension_read(
                    lambda c: c.execute(
                        "SELECT count(*) FROM replay_multi_bar_interval WHERE end_time_ms>start_time_ms"
                    ).fetchone()[0]
                )
                assert count > 0
            if boundary != "tier":
                assert result["cursor"]["virtual_time_ms"] < before + 90 * 60000
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]


@pytest.mark.anyio
async def test_display_bar_cancel_during_preparation_keeps_committed_boundary(
    tmp_path, monkeypatch
):
    import asyncio

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.plan_source_chunk

    async def gated(*args, **kwargs):
        if kwargs.get("indexed"):
            entered.set()
            await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "plan_source_chunk", gated)
    task = None
    try:
        viewer = await service.training.get_viewer_state(run)
        task = asyncio.create_task(
            send(
                "advance",
                C.ADVANCE,
                {
                    "basis": "DISPLAY_BAR",
                    "count": 90,
                    "display_interval": "1m",
                    "viewer_revision": viewer["semantic_view_revision"],
                    "stop_on_event": False,
                },
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        before = await service.training.store.get_market_track_heads(run)
        progress = await service.training.get_advance_progress(run, "advance")
        assert progress["progress"]["cancelable"] is True
        await send("cancel", C.CANCEL_ADVANCE, {"advance_command_id": "advance"})
        release.set()
        result = await asyncio.wait_for(task, 5)
        assert result["data"]["cancelled"] is True
        after = await service.training.store.get_market_track_heads(run)
        assert [t["cursor"] for t in before] == [t["cursor"] for t in after]
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_multi_checkpoint_recovery_and_idempotent_retry(tmp_path, monkeypatch):
    from tests.test_replay_v2_training_phase6 import _risk_service
    from tests.fixtures.replay.service_fakes import START_MS
    from app.replay.training.commands import ReplayV2Command

    install_shared_market(monkeypatch, tmp_path / "market")
    root = tmp_path / "run"
    s, run, session, send = await make_multi(root)
    before = (await s.get_session_state(session))["cursor"]["virtual_time_ms"]
    result = await send(
        "advance",
        C.ADVANCE_TO,
        dict(virtual_time_ms=before + 90 * 60000, stop_on_event=False),
    )
    snapshots = {tid: (await s.get_session(tid))["snapshot"] for tid in s._sessions}
    raw = await s.store.run_extension_read(
        lambda c: c.execute(
            "SELECT command_json FROM replay_training_command WHERE command_id='advance'"
        ).fetchone()[0]
    )
    await s.shutdown(step_timeout=5)
    restored = await _risk_service(
        root / "run.db",
        symbols=("BTCUSDT", "ETHUSDT"),
        bar_prices=[str(100 + i % 7) for i in range(304)],
        now_ms=START_MS + 400 * 60000,
    )
    try:
        for tid, expected in snapshots.items():
            actual = (await restored.get_session(tid))["snapshot"]
            assert actual["cursor"] == expected["cursor"]
            assert actual["components"] == expected["components"]
        retried = await restored.training.command(
            run, ReplayV2Command.from_dict(json.loads(raw))
        )
        assert retried == result
    finally:
        await restored.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_multi_interval_does_not_jump_past_terminal(tmp_path, monkeypatch):
    from app.replay.training.errors import TrainingRunError

    install_shared_market(monkeypatch, tmp_path / "market")
    outcomes = []
    for enabled in (True, False):
        service, run, session, send = await make_multi(
            tmp_path / str(enabled), horizon=100, enabled=enabled
        )
        try:
            # This deliberately requests more source bars than exist. Preserve
            # the reference's fail-closed terminal behavior instead of letting
            # an indexed cursor silently coast beyond its unconsumed terminal.
            with pytest.raises(TrainingRunError) as caught:
                await send(
                    "end",
                    C.ADVANCE,
                    {"basis": "BASE_BAR", "count": 100, "stop_on_event": False},
                )
            heads = await service.training.store.get_market_track_heads(run)
            outcomes.append(
                (
                    caught.value.code,
                    [(t["state"], t["cursor"]["source_sequence"]) for t in heads],
                )
            )
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == "MULTI_TRACK_PAUSED"


@pytest.mark.anyio
async def test_prepared_hedge_interval_uses_public_mark_when_display_quote_is_null(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    try:
        before = (await service.get_session_state(session))["cursor"]
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_training_market_track SET public_price=NULL WHERE run_id=?",
                (run,),
            )
        )
        assert (await service.training.prepare_indexed_run(run))["status"] == "READY"
        assert (await service.get_session_state(session))["cursor"] == before
        result = await send(
            "advance",
            C.ADVANCE_TO,
            {
                "virtual_time_ms": before["virtual_time_ms"] + 90 * 60000,
                "stop_on_event": False,
            },
        )
        assert result["cursor"]["source_sequence"] == before["source_sequence"] + 90
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_rebased_market_view_is_identical_to_cold_rebuild(tmp_path, monkeypatch):
    from app.replay.broker.shared_prepared import SharedPreparedInterval

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=300)
    try:
        before = (await service.get_session_state(session))["cursor"]["virtual_time_ms"]
        await send(
            "first",
            C.ADVANCE_TO,
            {"virtual_time_ms": before + 90 * 60000, "stop_on_event": False},
        )
        for handle in service._sessions.values():
            actor = handle.actor
            previous = actor._prepared_bar_interval
            rebased = previous.rebased(
                actor._source, actor._reducer, actor._event_chain_hash
            )
            assert rebased is not None
            fresh = SharedPreparedInterval(
                actor._source.fork(), actor._reducer, actor._event_chain_hash
            )
            assert rebased.reference == fresh.reference
            assert rebased.seed == fresh.seed
            assert rebased.start == fresh.start
            assert rebased.display is previous.display
            for offset in (1, 60, 90):
                assert rebased.chains[offset] == fresh.chains[offset]
                assert (
                    rebased.builder_at(offset, tail_limit=64).snapshot()
                    == fresh.builder_at(offset, tail_limit=64).snapshot()
                )
            assert (
                previous.rebased(actor._source, actor._reducer, "sha256:" + "0" * 64)
                is None
            )
            previous.terminal = False
            assert (
                previous.rebased(actor._source, actor._reducer, actor._event_chain_hash)
                is None
            )
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_shared_group_does_not_repeat_individual_idempotency_reads(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    try:

        async def repeated_read(*args):
            pytest.fail("group issued an individual command lookup")

        monkeypatch.setattr(service.store, "get_command", repeated_read)
        before = (await service.get_session_state(session))["cursor"]
        result = await send(
            "batch-lookup",
            C.ADVANCE_TO,
            {
                "virtual_time_ms": before["virtual_time_ms"] + 90 * 60000,
                "stop_on_event": False,
            },
        )
        assert result["cursor"]["source_sequence"] == before["source_sequence"] + 90
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_multi_interval_acquires_unowned_nonselected_controllers(
    tmp_path, monkeypatch
):
    from app.replay.commands import ReplayCommand
    from app.replay.models import CommandType, REPLAY_PROTOCOL

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(
        tmp_path / "run", tracks=8, horizon=100
    )
    try:
        for track in await service.training.store.get_market_track_heads(run):
            sid = track["adapter_session_id"]
            if sid == session:
                continue
            snapshot = (await service.get_session(sid))["snapshot"]
            await service.command(
                sid,
                ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id="release-" + sid,
                    client_instance_id="phase5-browser",
                    expected_revision=snapshot["revision"],
                    type=CommandType.RELEASE_CONTROLLER,
                    payload={},
                ),
            )
        before = (await service.get_session_state(session))["cursor"]
        result = await send(
            "browser-advance",
            C.ADVANCE_TO,
            {
                "virtual_time_ms": before["virtual_time_ms"] + 90 * 60000,
                "stop_on_event": False,
            },
        )
        assert result["cursor"]["source_sequence"] == before["source_sequence"] + 90
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_long_warmup_short_multi_interval_checkpoint_recovers(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(
        tmp_path / "run", horizon=100, warmup=200
    )
    try:
        before = (await service.get_session_state(session))["cursor"]
        result = await send(
            "short",
            C.ADVANCE_TO,
            {
                "virtual_time_ms": before["virtual_time_ms"] + 3 * 60000,
                "stop_on_event": False,
            },
        )
        assert result["cursor"]["source_sequence"] == before["source_sequence"] + 3
        assert (await service.training.audit_account(run))["status"] == "PASS"
        # Mix an ordinary command with the compact candidate, then actually
        # reopen the persisted checkpoint in a fresh service.
        await send("release-after-short", C.RELEASE_CONTROLLER, {})
        assert (await service.get_session_state(session))["cursor"] == result["cursor"]
        expected = (await service.get_session(session))["snapshot"]
        from app.replay.service import ReplayService
        from app.replay.storage import ReplaySQLiteStore

        restored = ReplayService(
            settings=service.settings,
            store=ReplaySQLiteStore(service.store.path, now_ms=service.store._now_ms),
            repository=service._repository,
            now_ms=service._now_ms,
            native_intervals=service._native_intervals,
        )
        await service.shutdown(step_timeout=5)
        service = restored
        await service.start()
        actual = (await service.get_session(session))["snapshot"]
        assert actual["cursor"] == expected["cursor"]
        assert actual["components"] == expected["components"]
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["after_group", "before_ack"])
async def test_crash_after_group_commit_recovers_before_external_ack(
    tmp_path, monkeypatch, phase
):
    import subprocess
    import sys
    from pathlib import Path
    from tests.test_replay_v2_training_phase6 import _risk_service
    from tests.fixtures.replay.service_fakes import START_MS
    from app.replay.training.commands import ReplayV2Command

    script = tmp_path / "crash.py"
    backend = Path(__file__).resolve().parents[1]
    script.write_text(
        """import asyncio,os,sys
from pathlib import Path
import pytest
sys.path.insert(0,sys.argv[1])
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market
from app.replay.training.models import ReplayV2CommandType as C
async def main():
 root=Path(sys.argv[2]);patch=pytest.MonkeyPatch();install_shared_market(patch,root/'market')
 service,run,session,send=await make_multi(root/'run',horizon=100)
 async def crash(**kwargs):os._exit(93)
 if sys.argv[3]=='before_ack':service.training.store.finish_advance_intent=crash
 else:
  from app.replay.training import multi_interval_advance
  original=multi_interval_advance.commit_actor_commands
  async def crash_group(*args,**kwargs):
   await original(*args,**kwargs)
   os._exit(93)
  multi_interval_advance.commit_actor_commands=crash_group
 at=(await service.get_session_state(session))['cursor']['virtual_time_ms']
 await send('crash-advance',C.ADVANCE_TO,dict(virtual_time_ms=at+90*60000,stop_on_event=False))
asyncio.run(main())
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(backend), str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 93, completed.stderr
    install_shared_market(monkeypatch, tmp_path / "market")
    service = await _risk_service(
        tmp_path / "run/run.db",
        symbols=("BTCUSDT", "ETHUSDT"),
        bar_prices=[str(100 + i % 7) for i in range(104)],
        now_ms=START_MS + 200 * 60000,
    )
    try:
        raw = await service.store.run_extension_read(
            lambda c: c.execute(
                "SELECT command_json FROM replay_training_advance_intent WHERE command_id='crash-advance'"
            ).fetchone()[0]
        )
        command = ReplayV2Command.from_dict(json.loads(raw))
        sessions = await service.training.store.get_market_track_heads(command.run_id)
        for track in sessions:
            snapshot = (await service.get_session(track["adapter_session_id"]))[
                "snapshot"
            ]
            assert 2 < snapshot["cursor"]["source_sequence"] <= 92
            if phase == "before_ack":
                assert snapshot["cursor"]["source_sequence"] == 92
        result = await service.training.command(command.run_id, command)
        assert result["cursor"]["source_sequence"] == 92
        assert (await service.training.audit_account(command.run_id))[
            "status"
        ] == "PASS"
    finally:
        await service.shutdown(step_timeout=5)
