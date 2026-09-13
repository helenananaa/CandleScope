"""Acquire the existing actor leases before the prepared training UI opens."""

import uuid

from ..constants import REPLAY_PROTOCOL
from ..errors import ReplayDomainError, ReplayErrorCode
from ..models import CommandType, ReplayCommand
from ..multi_commit import commit_actor_commands


async def prepare_controllers(owner, run_id, client_id):
    service = owner.replay_service
    tracks = await owner.store.get_market_track_heads(run_id)
    snapshots = []
    for track in tracks:
        if track["subscription_tier"] != "FULL":
            continue
        sid = owner._track_session_id(track)
        snapshot = await service.get_session_state(sid)
        snapshots.append((sid, snapshot))
    # Opening another client's training remains a read-only operation.
    if any(
        s.get("controller_client_id") not in (None, client_id) for _, s in snapshots
    ):
        return False
    commands = []
    for sid, snapshot in snapshots:
        if snapshot.get("controller_client_id") == client_id:
            try:
                await service.heartbeat(sid, client_id, _renew_group=False)
            except ReplayDomainError as exc:
                if exc.code is ReplayErrorCode.CONTROLLER_CONFLICT:
                    return False
                raise
        else:
            commands.append(
                (
                    sid,
                    ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id="prepare-controller-" + uuid.uuid4().hex,
                        client_instance_id=client_id,
                        expected_revision=snapshot["revision"],
                        type=CommandType.ACQUIRE_CONTROLLER,
                        payload={"takeover": False},
                    ),
                )
            )
    if commands:
        try:
            await commit_actor_commands(
                service, commands, before=lambda _: None, after=lambda _: None
            )
        except ReplayDomainError as exc:
            if exc.code in {
                ReplayErrorCode.CONTROLLER_CONFLICT,
                ReplayErrorCode.REVISION_CONFLICT,
            }:
                return False
            raise
    groups = getattr(owner, "_prepared_controller_groups", None)
    if groups is None:
        groups = owner._prepared_controller_groups = {}
    members = tuple(sid for sid, _ in snapshots)
    for sid in members:
        groups[sid] = (client_id, members)
    while len(groups) > 256:
        groups.pop(next(iter(groups)))
    return True
