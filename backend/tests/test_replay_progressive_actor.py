import asyncio

import pytest

from app.replay.actor import ReplaySessionActor
from app.replay.constants import CommandType, SessionState
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from tests.fixtures.replay.actor_fakes import FixtureSource, CountingReducer, event_fixture, session_config
from tests.test_replay_actor import _async_test, _command


@_async_test
@pytest.mark.parametrize("restart", [False, True, "explicit-pause"])
async def test_playback_wait_is_durable_nonterminal_and_resumes_without_reapplying_events(restart):
    available = [2]
    events = event_fixture(count=4, step_ms=1)
    mutations = []

    class Source(FixtureSource):
        def fork(self):
            clone = Source(events)
            clone._index = self._index
            return clone

        def peek(self):
            if available[0] <= self._index < len(events):
                raise ReplayDomainError(ReplayErrorCode.DATASET_PENDING, "Waiting for history")
            return super().peek()

        def ready(self):
            return self._index < available[0] or self.exhausted()

    async def persist(mutation):
        mutations.append(mutation)

    def create(checkpoint=None):
        return ReplaySessionActor(session_id="progressive-actor", config=session_config(),
            source_factory=lambda: Source(events), initial_virtual_time_ms=1000,
            command_queue_size=8, event_buffer_size=64, max_emit_fps=30,
            controller_ttl_seconds=60, checkpoint_event_interval=2, checkpoint_virtual_ms=1000,
            reducer=CountingReducer(), mutation_hook=persist, restore_checkpoint=checkpoint)

    async def wait_paused(actor):
        async def wait():
            while True:
                snapshot = await actor.public_snapshot()
                if snapshot["status_reason"] == "data_pending":
                    return snapshot
                await asyncio.sleep(0.001)
        return await asyncio.wait_for(wait(), 2)

    actor = create()
    await actor.start()
    try:
        await actor.submit(_command("acquire", CommandType.ACQUIRE_CONTROLLER, revision=0))
        await actor.submit(_command("speed", CommandType.SET_SPEED, revision=1, payload={"speed": "MAX"}))
        await actor.submit(_command("play", CommandType.PLAY, revision=2))
        paused = await wait_paused(actor)
        assert paused["state"] == "PAUSED"
        assert paused["cursor"]["source_sequence"] == 2
        assert paused["cursor"]["at_end"] is False
        assert paused["components"] == {"count": 2, "total": events[0].value + events[1].value}
        waiting = next(item for item in mutations if item.kind == "data_pending")
        assert waiting.checkpoint is not None
        assert not waiting.source_events
        with pytest.raises(ReplayDomainError) as pending:
            await actor.submit(_command("too-soon", CommandType.PLAY, revision=paused["revision"]))
        assert pending.value.code is ReplayErrorCode.DATASET_PENDING
        with pytest.raises(ReplayDomainError) as pending_step:
            await actor.submit(_command("step-too-soon", CommandType.STEP, revision=paused["revision"], payload={"count": 1}))
        assert pending_step.value.code is ReplayErrorCode.DATASET_PENDING
        unchanged = await actor.public_snapshot()
        assert unchanged["cursor"] == paused["cursor"]
        assert unchanged["components"] == paused["components"]
        assert unchanged["revision"] == paused["revision"]
        checkpoint = await actor.checkpoint()
        if restart == "explicit-pause":
            await actor.submit(_command("stop-waiting", CommandType.PAUSE, revision=paused["revision"]))
            available[0] = 4
            await asyncio.sleep(0.3)
            stopped = await actor.public_snapshot()
            assert stopped["state"] == "PAUSED"
            assert stopped["status_reason"] == "pause"
            assert stopped["cursor"]["source_sequence"] == 2
            return
        if not restart:
            available[0] = 4
            async def wait_resumed():
                while (current := await actor.snapshot()).state is not SessionState.ENDED:
                    await asyncio.sleep(0.001)
                return current
            ended = await asyncio.wait_for(wait_resumed(), 2)
            assert ended.cursor.source_sequence == 4
            assert any(item.kind == "data_ready" and not item.source_events for item in mutations)
            final = await actor.public_snapshot()
            assert final["components"] == {"count": 4, "total": sum(event.value for event in events)}
            return
    finally:
        await actor.shutdown()

    restored = create(checkpoint)
    await restored.start()
    try:
        before = await restored.snapshot()
        assert before.cursor.source_sequence == 2
        available[0] = 4
        acquired = await restored.submit(_command("new-owner", CommandType.ACQUIRE_CONTROLLER, revision=before.revision))
        await restored.submit(_command("resume", CommandType.PLAY, revision=acquired.revision))
        async def wait_end():
            while (current := await restored.snapshot()).state is not SessionState.ENDED:
                await asyncio.sleep(0.001)
            return current
        ended = await asyncio.wait_for(wait_end(), 2)
        assert ended.cursor.source_sequence == 4
        final = await restored.public_snapshot()
        assert final["components"] == {"count": 4, "total": sum(event.value for event in events)}
    finally:
        await restored.shutdown()
