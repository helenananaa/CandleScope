import pytest

from app.replay.training import terminal_cohort, multi_interval_advance
from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


@pytest.mark.anyio
@pytest.mark.parametrize("margin", ["CROSS", "ISOLATED"])
@pytest.mark.parametrize("range_tail", [True, False])
async def test_terminal_cohort_matches_individual_steps(
    tmp_path, monkeypatch, margin, range_tail
):
    install_shared_market(monkeypatch, tmp_path / "market")
    original = terminal_cohort.try_commit
    original_interval = multi_interval_advance.try_advance
    outcomes, commits = [], []

    async def skip(*args, **kwargs):
        return None

    for batched in (False, True):
        monkeypatch.setattr(multi_interval_advance, "try_advance", original_interval)
        monkeypatch.setattr(
            terminal_cohort, "try_commit", original if batched else skip
        )
        service, run, session, send = await make_multi(
            tmp_path / str(batched),
            horizon=12,
            tracks=8,
            margin_mode=margin,
            initial_equity="10000",
        )
        try:
            await service.training.prepare_indexed_run(run)
            plan = await service.plan_source_chunk(
                session, target_time_ms=10**13, max_events=1, indexed=True
            )
            target = plan["index"].times[-1 if range_tail else -4]
            await send(
                "prefix",
                C.ADVANCE_TO,
                dict(virtual_time_ms=target - 60000, stop_on_event=False),
            )
            before = service.store._metrics["transactions"]
            if not range_tail:
                # A prepared range may rebase past the command's final candle.
                # Exercise the exact single-cohort fallback in that case too.
                monkeypatch.setattr(multi_interval_advance, "try_advance", skip)
            reply = await send(
                "terminal",
                C.ADVANCE_TO,
                dict(virtual_time_ms=target, stop_on_event=False),
            )
            commits.append(service.store._metrics["transactions"] - before)
            heads = await service.training.store.get_market_track_heads(run)
            outcomes.append([(h["cursor"], h["position"], h["account"]) for h in heads])
            assert reply["cursor"]["virtual_time_ms"] == target
            assert (await service.training.audit_account(run))["status"] == "PASS"
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]
    assert commits[0] - commits[1] == 8


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["checkpoint", "time"])
async def test_terminal_group_rollback_restores_every_actor_and_publishes_nothing(
    tmp_path, monkeypatch, failure
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=12)
    try:
        await service.training.prepare_indexed_run(run)
        plan = await service.plan_source_chunk(
            session, target_time_ms=10**13, max_events=1, indexed=True
        )
        target = plan["index"].times[-1]
        await send(
            "prefix",
            C.ADVANCE_TO,
            dict(virtual_time_ms=target - 60000, stop_on_event=False),
        )
        heads = await service.training.store.get_market_track_heads(run)
        before = {
            h["adapter_session_id"]: (
                await service.get_session(h["adapter_session_id"])
            )["snapshot"]
            for h in heads
        }
        original = service.store.commit_command_group
        entered = []
        committed_heads = []

        async def fail(rows, *, before=None, after=None):
            entered.append(len(rows))
            # Prior mark input has its own committed phase; the terminal group
            # must roll back to that boundary, not to the preceding command.
            committed_heads.extend(
                await service.training.store.get_market_track_heads(run)
            )
            for sid, state in snapshots.items():
                assert not service._sessions[sid].actor._events.after(state["sequence"])

            def abort(connection):
                after(connection)
                raise RuntimeError("injected terminal checkpoint failure")

            return await original(rows, before=before, after=abort)

        snapshots = before
        if failure == "time":
            original_terminal = terminal_cohort.try_commit

            async def wrong_plan(owner, **kwargs):
                kwargs["target"] += 1
                kwargs["planned_times"] = {
                    tid: (kwargs["target"],) for tid in kwargs["planned_times"]
                }
                return await original_terminal(owner, **kwargs)

            monkeypatch.setattr(terminal_cohort, "try_commit", wrong_plan)
        monkeypatch.setattr(service.store, "commit_command_group", fail)
        with pytest.raises(Exception, match="injected terminal|terminal cohort missed"):
            await send(
                "terminal",
                C.ADVANCE_TO,
                dict(virtual_time_ms=target, stop_on_event=False),
            )
        assert entered == [2]
        for sid, prior in snapshots.items():
            state = (await service.get_session(sid))["snapshot"]
            assert state["cursor"] == prior["cursor"]
            assert state["state_hash"] == prior["state_hash"]
            assert not service._sessions[sid].actor._events.after(prior["sequence"])
        assert (
            await service.training.store.get_market_track_heads(run) == committed_heads
        )
    finally:
        await service.shutdown(step_timeout=5)
