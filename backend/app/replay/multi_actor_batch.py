"""Build several real command checkpoints without publishing before group commit."""

from .actor import ActorMutation
from .commands import parse_command
from .errors import ReplayDomainError, ReplayErrorCode


async def handle_batch(actor, request):
    rollback = None
    staged = []
    committed = False
    try:
        rollback = actor._capture_rollback()
        history = actor._command_history
        if len(history._records) + len(request.group.phases) > history._max_records:
            raise ReplayDomainError(ReplayErrorCode.SCAN_LIMIT_EXCEEDED, "batch exceeds command history capacity")
        for phase in request.group.phases:
            command = phase.commands[actor.session_id]
            if command.expected_revision != actor._revision:
                raise ReplayDomainError(ReplayErrorCode.REVISION_CONFLICT, "batch candidate revision changed")
            actor._command_history.ensure_capacity()
            previous = actor._component_state()
            previous_journal = list(actor._journal_entries)
            actor._begin_candidate(capture_source_events=False)
            result = await actor._execute_command(command, parse_command(command), _group=phase)
            actor._command_log_offset += 1
            components = actor._component_state()
            checkpoint = actor._checkpoint_codec.encode(
                actor._checkpoint_payload(component_state=components, state_hash=result.state_hash),
                compress_small=True,
            )
            mutation = ActorMutation(
                kind="command", session_id=actor.session_id, command=command,
                result=result, error=None, checkpoint=checkpoint,
                session_state=actor._durable_state(component_state=components, state_hash=result.state_hash),
                events=tuple(e for e, _ in actor._pending_events), source_events=(),
                component_state={**components, "journal": list(actor._journal_entries)},
                previous_component_state={**previous, "journal": previous_journal},
                history_frames=tuple(actor._pending_history_frames),
            )
            staged.append((command, result, checkpoint, tuple(actor._pending_events)))
            # A prefix barrier permits more candidate construction only. Neither
            # stream events, command history nor checkpoint rings publish here.
            await phase.stage(mutation)
            actor._pending_events = None
            actor._pending_source_events = None
            actor._pending_history_frames = []
        # The last barrier is released only after all phases have committed.
        committed = True
        for command, result, checkpoint, events in staged:
            actor._command_history.record_success(command, result)
            for event, mandatory in events:
                actor._publish_event(event, mandatory=mandatory)
        actor._metrics["commands_accepted"] += len(staged)
        if actor._checkpoint_due():
            actor._record_checkpoint(staged[-1][2], initial=False)
        if not request.future.done():
            # The queued request is the prefix command. Its ACK must equal its
            # durable idempotency record; the coordinator owns the final reply.
            request.future.set_result(staged[0][1])
    except BaseException as error:
        try:
            if not committed and rollback is not None:
                actor._restore_rollback(rollback, force_paused=False)
        finally:
            if not request.future.done():
                request.future.set_exception(error)
    finally:
        staged.clear()
        actor._command_ack_latency.add(
            max(0.0, (actor._read_wall() - request.enqueued_wall) * 1000)
        )
