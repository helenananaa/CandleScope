"""Atomically persist the exact final BAR cohort requested by an advance."""

import json

from ..canonical import canonical_json
from ..constants import CommandType, REPLAY_PROTOCOL
from ..models import ReplayCommand
from ..multi_commit import commit_actor_commands
from .multitrack import StableMarketEvent, stable_market_event_order


async def try_commit(
    owner, *, command, binding, snapshots, planned_times, target, pending_events
):
    """Caller excludes new account/input phases; prior settled marks join the checkpoint.

    Execute ordinary STEP reducers, including their real terminal behavior.
    Only their persistence/publication barrier is shared.
    """
    service, store = owner.replay_service, owner.store
    commands, expected, events = [], {}, []
    for track, snapshot in snapshots:
        tid, sid = track["track_id"], owner._track_session_id(track)
        if snapshot["state"] != "PAUSED" or planned_times.get(tid) != (target,):
            return None
        # The coordinator already planned this exact one-event BAR cohort.
        # Do not rebase/prepare eight indexes merely to rediscover that plan.
        # Recheck the source revision before writing and the actual time after.
        controlled = await owner._ensure_track_controller(
            session_id=sid,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
            known_snapshot=snapshot,
        )
        expected[sid] = (
            controlled["revision"],
            controlled["cursor"]["source_sequence"],
        )
        commands.append(
            (
                sid,
                ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=owner._multi_command_id(
                        command.command_id,
                        tid,
                        CommandType.STEP.value,
                        controlled["revision"],
                    ),
                    client_instance_id=command.client_instance_id,
                    expected_revision=controlled["revision"],
                    type=CommandType.STEP,
                    payload={"count": 1},
                ),
            )
        )
        events.append(
            StableMarketEvent(
                actual_event_time_ms=owner._actual_event_time_ms(binding, target),
                event_phase=20,
                market_track_stable_id=tid,
                source_sequence=expected[sid][1] + 1,
            )
        )
    ordered = stable_market_event_order(events)
    cached = store._hedge_risk_fingerprints.get(command.run_id)
    outcome = {}

    def before(connection):
        for sid, (revision, sequence) in expected.items():
            row = connection.execute(
                "SELECT revision,source_sequence FROM replay_session WHERE session_id=?",
                (sid,),
            ).fetchone()
            if row is None or tuple(row) != (revision, sequence):
                raise ValueError("terminal cohort changed during preparation")

    def after(connection):
        latest = []
        selected_cursor = None
        for sid, (_, sequence) in expected.items():
            row = connection.execute(
                "SELECT s.source_sequence,t.virtual_time_ms,s.state_hash,s.revision FROM replay_session s "
                "JOIN replay_training_market_track t ON t.adapter_session_id=s.session_id "
                "WHERE s.session_id=?",
                (sid,),
            ).fetchone()
            if row is None or tuple(row)[:2] != (sequence + 1, target):
                raise ValueError("terminal cohort missed its exact source boundary")
            latest.append(
                dict(
                    session_id=sid,
                    source_sequence=row[0],
                    virtual_time_ms=row[1],
                    state_hash=row[2],
                )
            )
            if sid == binding["adapter_session_id"]:
                selected_cursor = dict(
                    source_sequence=row[0], virtual_time_ms=row[1], revision=row[3]
                )
        fingerprint, checkpointed = store._checkpoint_hedge_wave_in_transaction(
            connection,
            run_id=command.run_id,
            risk_virtual_time_ms=target,
            ordered=stable_market_event_order((*pending_events, *ordered)),
            cached_fingerprint=cached,
        )
        outcome.update(fingerprint=fingerprint, checkpointed=checkpointed)
        # A crash after this commit but before the external result must resume
        # from these actors, not reject the earlier interval's stale bookmark.
        intent = connection.execute(
            "SELECT plan_json FROM replay_training_advance_intent "
            "WHERE run_id=? AND command_id=? AND status='RUNNING'",
            (command.run_id, command.command_id),
        ).fetchone()
        if checkpointed and intent is not None:
            plan = json.loads(intent[0])
            if plan.get("schema") == "multi-bar-advance-intent.v1":
                plan.update(risk_fingerprint=fingerprint, latest_tracks=latest)
                connection.execute(
                    "UPDATE replay_training_advance_intent SET plan_json=?,latest_cursor_json=? "
                    "WHERE run_id=? AND command_id=? AND status='RUNNING'",
                    (
                        canonical_json(plan),
                        canonical_json(selected_cursor),
                        command.run_id,
                        command.command_id,
                    ),
                )

    await commit_actor_commands(service, commands, before=before, after=after)
    store._cache_committed_hedge_fingerprint(command.run_id, outcome["fingerprint"])
    return ordered, outcome["checkpointed"]
