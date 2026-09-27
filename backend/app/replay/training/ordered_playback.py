"""Global-time playback coordination with the original atomic actor phases.

The run actor, job dictionaries and database owner are shared with the command
facade. Display adaptation, notifications and account audit are explicit ports.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.data_engine.interval_policy import (
    parse_interval_ms,
)
from app.replay.constants import (
    REPLAY_PROTOCOL,
    CommandType,
)
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.internal_commands import InternalCommandType
from app.replay.models import (
    MAX_TIMESTAMP_MS,
    ReplayCommand,
)
from app.replay.period_summary import (
    ReplayPeriodSummary,
)

from . import command_projection as command_projection_ops
from . import control_rules as control_rules_ops
from . import order_rules as order_rules_ops
from . import service_validation as service_validation_ops
from .account_history import (
    FUNDING_EVENT_PHASE,
    MARK_INDEX_EVENT_PHASE,
    RULE_EVENT_PHASE,
)
from .commands import ReplayV2Command
from .control import (
    ADVANCE_CONTRACT_VERSION,
    MAX_PLAYBACK_BATCH_UNITS,
    PLAYBACK_CONTRACT_VERSION,
    advance_basis,
    aligned_step_target_ms,
    compatible_step_interval_ms,
    control_count,
    control_rate,
    discrete_playback_units,
    fixed_interval_ms,
    supported_playback_bases,
)
from .errors import TrainingRunError
from .fast_forward import FastForwardContext, FastForwardDecision
from .hedge_inputs import (
    HedgeInputEvent,
)
from .hedge_timeline import IndexedHedgeSnapshot
from .historical_book import HISTORICAL_L2_LIQUIDATION_FIDELITY
from .models import (
    AccountDataMode,
    AdvanceBasis,
    BookMode,
    FastForwardPlan,
    ReplaySource,
    ReplayV2CommandType,
    TrainingCursor,
)
from .multitrack import (
    GLOBAL_ORDERING_VERSION,
    MARKET_EVENT_PHASE,
    StableMarketEvent,
    TrainingRunActor,
    stable_market_event_order,
)


class TrainingOrderedPlayback:
    """Coordinate full tracks at global event boundaries before publishing."""

    def __init__(
        self,
        *,
        store,
        replay_service,
        account_history,
        hedge_inputs,
        historical_books,
        run_actors,
        advance_jobs,
        fast_forward_planner,
        display,
        notify_market_tracks,
        audit_account,
    ) -> None:
        self.store = store
        self.replay_service = replay_service
        self.account_history = account_history
        self.hedge_inputs = hedge_inputs
        self.historical_books = historical_books
        self._run_actors = run_actors
        self._advance_jobs = advance_jobs
        self._fast_forward_planner = fast_forward_planner
        self.display = display
        self._notify_market_tracks = notify_market_tracks
        self.audit_account = audit_account

    async def _execute_multi_track_control(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        selected_snapshot: Mapping[str, object],
        tracks: list[Mapping[str, object]],
    ) -> dict[str, object]:
        event_stop: dict[str, object] | None = (
            {} if control_rules_ops.stop_on_event(command) else None
        )
        ordered = tuple(
            sorted(
                tracks,
                key=lambda track: (
                    service_validation_ops._stored_counter(
                        track["stable_ordinal"], field_name="stable_ordinal"
                    ),
                    str(track["track_id"]),
                ),
            )
        )
        selected_session_id = str(binding["adapter_session_id"])
        actor = self._run_actors.setdefault(
            command.run_id,
            TrainingRunActor(command.run_id),
        )
        if command.type is ReplayV2CommandType.END:
            return await self._end_multi_track_run(
                command=command,
                tracks=ordered,
                selected_session_id=selected_session_id,
            )
        direct_types = {
            ReplayV2CommandType.ACQUIRE_CONTROLLER,
            ReplayV2CommandType.TAKEOVER_CONTROLLER,
            ReplayV2CommandType.RELEASE_CONTROLLER,
            ReplayV2CommandType.PLAY,
            ReplayV2CommandType.PAUSE,
            ReplayV2CommandType.SET_SPEED,
        }
        if command.type in direct_types:
            if command.type is ReplayV2CommandType.PLAY:
                if actor.playback_is_active():
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "ordered playback is already running",
                        status_code=409,
                    )
                (
                    basis,
                    rate,
                    display_interval,
                    viewer_revision,
                    legacy_profile,
                ) = await self.display._playback_profile(
                    command=command,
                    binding=binding,
                    selected_snapshot=selected_snapshot,
                    full_track_count=len(ordered),
                    actor=actor,
                )
                for track in ordered:
                    await self._ensure_track_controller(
                        session_id=service_validation_ops.track_session_id(track),
                        client_instance_id=command.client_instance_id,
                        command_id=command.command_id,
                    )
                    session = await self.replay_service.get_session(
                        service_validation_ops.track_session_id(track)
                    )
                    snapshot = service_validation_ops.adapter_snapshot(session)
                    if snapshot["state"] != "PAUSED":
                        raise TrainingRunError(
                            "REPLAY_CONTROL_INVALID",
                            "all FULL market tracks must be paused before playback",
                            status_code=409,
                            details={"track_id": track["track_id"]},
                        )
                if order_rules_ops.requires_barrier_account_audit(binding):
                    await self.store.invalidate_account_audit(command.run_id)
                generation, stop = actor.begin_ordered_playback(
                    client_instance_id=command.client_instance_id,
                    basis=basis,
                    rate=rate,
                    display_interval=display_interval,
                    viewer_revision=viewer_revision,
                )
                task = asyncio.create_task(
                    self._run_ordered_playback(
                        run_id=command.run_id,
                        generation=generation,
                        stop=stop,
                    ),
                    name=f"replay-v2-play-{command.run_id}",
                )
                actor.attach_ordered_playback_task(
                    generation=generation,
                    task=task,
                )
                viewer = await self.store.get_viewer_state(command.run_id)
                result = command_projection_ops.result_payload(
                    command=command,
                    session_id=selected_session_id,
                    snapshot=selected_snapshot,
                    viewer=viewer.to_dict(),
                    data={
                        "full_track_count": len(ordered),
                        "ordering_version": GLOBAL_ORDERING_VERSION,
                        "playback_contract": PLAYBACK_CONTRACT_VERSION,
                        "legacy_profile": legacy_profile,
                        "global_clock": actor.playback_snapshot(),
                    },
                )
                result["state"] = "PLAYING"
                return result
            if command.type is ReplayV2CommandType.PAUSE:
                service_validation_ops.exact_payload(command.payload, set())
                if not actor.playback_is_active():
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "ordered playback is not running",
                        status_code=409,
                    )
                actor.request_ordered_pause(reason="USER_PAUSE")
                selected = await self.replay_service.get_session(selected_session_id)
                snapshot = service_validation_ops.adapter_snapshot(selected)
                viewer = await self.store.get_viewer_state(command.run_id)
                result = command_projection_ops.result_payload(
                    command=command,
                    session_id=selected_session_id,
                    snapshot=snapshot,
                    viewer=viewer.to_dict(),
                    data={
                        "full_track_count": len(ordered),
                        "ordering_version": GLOBAL_ORDERING_VERSION,
                        "global_clock": actor.playback_snapshot(),
                    },
                )
                result["state"] = "PAUSED"
                return result
            if command.type is ReplayV2CommandType.SET_SPEED:
                if not command.payload:
                    service_validation_ops.exact_payload(command.payload, {"speed"})
                (
                    basis,
                    rate,
                    display_interval,
                    viewer_revision,
                    legacy_profile,
                ) = await self.display._playback_profile(
                    command=command,
                    binding=binding,
                    selected_snapshot=selected_snapshot,
                    full_track_count=len(ordered),
                    actor=actor,
                )
                for track in ordered:
                    await self._ensure_track_controller(
                        session_id=service_validation_ops.track_session_id(track),
                        client_instance_id=command.client_instance_id,
                        command_id=command.command_id,
                    )
                selected_result: Mapping[str, object] | None = None
                if legacy_profile:
                    adapter_speed = command.payload["speed"]
                    try:
                        for track in ordered:
                            session_id = service_validation_ops.track_session_id(track)
                            session = await self.replay_service.get_session(session_id)
                            snapshot = service_validation_ops.adapter_snapshot(session)
                            adapter = ReplayCommand(
                                protocol=REPLAY_PROTOCOL,
                                command_id=control_rules_ops.multi_command_id(
                                    command.command_id,
                                    str(track["track_id"]),
                                    CommandType.SET_SPEED.value,
                                    service_validation_ops._stored_counter(
                                        snapshot["revision"],
                                        field_name="revision",
                                    ),
                                ),
                                client_instance_id=command.client_instance_id,
                                expected_revision=service_validation_ops._stored_counter(
                                    snapshot["revision"],
                                    field_name="revision",
                                ),
                                type=CommandType.SET_SPEED,
                                payload={"speed": adapter_speed},
                            )
                            acknowledged = await self.replay_service.command(
                                session_id,
                                adapter,
                            )
                            if session_id == selected_session_id:
                                selected_result = acknowledged
                    except ReplayDomainError as exc:
                        await self._fail_closed_multi_track(
                            run_id=command.run_id,
                            tracks=ordered,
                            failed_track=track,
                            client_instance_id=command.client_instance_id,
                            reason=exc.code.value,
                        )
                        raise TrainingRunError(
                            "MULTI_TRACK_PAUSED",
                            "a required FULL market track rejected the global control",
                            status_code=409,
                            details={
                                "reason": exc.code.value,
                                "track_id": track["track_id"],
                            },
                        ) from exc
                actor.update_ordered_profile(
                    basis=basis,
                    rate=rate,
                    display_interval=display_interval,
                    viewer_revision=viewer_revision,
                )
                if selected_result is None:
                    selected = await self.replay_service.get_session(
                        selected_session_id
                    )
                    selected_result = service_validation_ops.adapter_snapshot(selected)
                snapshot = (
                    selected_result
                    if "cursor" in selected_result
                    else service_validation_ops.adapter_snapshot(selected_result)
                )
                viewer = await self.store.get_viewer_state(command.run_id)
                return command_projection_ops.result_payload(
                    command=command,
                    session_id=selected_session_id,
                    snapshot=snapshot,
                    viewer=viewer.to_dict(),
                    data={
                        "full_track_count": len(ordered),
                        "ordering_version": GLOBAL_ORDERING_VERSION,
                        "playback_contract": PLAYBACK_CONTRACT_VERSION,
                        "legacy_profile": legacy_profile,
                        "profile_only": not legacy_profile,
                        "global_clock": actor.playback_snapshot(),
                    },
                )
            if command.type is ReplayV2CommandType.ACQUIRE_CONTROLLER:
                v1_type = CommandType.ACQUIRE_CONTROLLER
                payload = dict(
                    service_validation_ops.exact_payload(command.payload, {"takeover"})
                )
            elif command.type is ReplayV2CommandType.TAKEOVER_CONTROLLER:
                service_validation_ops.exact_payload(command.payload, set())
                v1_type = CommandType.ACQUIRE_CONTROLLER
                payload = {"takeover": True}
            else:
                service_validation_ops.exact_payload(command.payload, set())
                v1_type = (
                    CommandType.RELEASE_CONTROLLER
                    if command.type is ReplayV2CommandType.RELEASE_CONTROLLER
                    else CommandType.PAUSE
                )
                payload = {}
            if command.type is ReplayV2CommandType.RELEASE_CONTROLLER:
                actor.request_ordered_pause(reason="CONTROLLER_RELEASED")
            if command.type in {
                ReplayV2CommandType.RELEASE_CONTROLLER,
            }:
                for track in ordered:
                    await self._ensure_track_controller(
                        session_id=service_validation_ops.track_session_id(track),
                        client_instance_id=command.client_instance_id,
                        command_id=command.command_id,
                    )
            selected_result: Mapping[str, object] | None = None
            try:
                for track in ordered:
                    session_id = service_validation_ops.track_session_id(track)
                    session = await self.replay_service.get_session(session_id)
                    snapshot = service_validation_ops.adapter_snapshot(session)
                    adapter = ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id=control_rules_ops.multi_command_id(
                            command.command_id,
                            str(track["track_id"]),
                            v1_type.value,
                            service_validation_ops._stored_counter(
                                snapshot["revision"], field_name="revision"
                            ),
                        ),
                        client_instance_id=command.client_instance_id,
                        expected_revision=service_validation_ops._stored_counter(
                            snapshot["revision"], field_name="revision"
                        ),
                        type=v1_type,
                        payload=payload,
                    )
                    acknowledged = await self.replay_service.command(
                        session_id, adapter
                    )
                    if session_id == selected_session_id:
                        selected_result = acknowledged
            except ReplayDomainError as exc:
                await self._fail_closed_multi_track(
                    run_id=command.run_id,
                    tracks=ordered,
                    failed_track=track,
                    client_instance_id=command.client_instance_id,
                    reason=exc.code.value,
                )
                raise TrainingRunError(
                    "MULTI_TRACK_PAUSED",
                    "a required FULL market track rejected the global control",
                    status_code=409,
                    details={"reason": exc.code.value, "track_id": track["track_id"]},
                ) from exc
            if selected_result is None:
                selected = await self.replay_service.get_session(selected_session_id)
                selected_result = service_validation_ops.adapter_snapshot(selected)
            snapshot = (
                selected_result
                if "cursor" in selected_result
                else service_validation_ops.adapter_snapshot(selected_result)
            )
            viewer = await self.store.get_viewer_state(command.run_id)
            return command_projection_ops.result_payload(
                command=command,
                session_id=selected_session_id,
                snapshot=snapshot,
                viewer=viewer.to_dict(),
                data={
                    "full_track_count": len(ordered),
                    "ordering_version": GLOBAL_ORDERING_VERSION,
                    "adapter_command": v1_type.value,
                    "global_clock": actor.playback_snapshot(),
                },
            )

        current_time = service_validation_ops.cursor_time(selected_snapshot)
        fast_forward_plan: dict[str, object] | None = None
        control_plan: dict[str, object] | None = None
        advance_job: dict[str, object] | None = None
        stable_order_state = {"truncated": False}
        advance_key: tuple[str, str] | None = None
        source_goal: control_rules_ops._OrderedSourceGoal | None = None
        if command.type is ReplayV2CommandType.ADVANCE:
            requested_basis = advance_basis(command.payload.get("basis"))
            if requested_basis is AdvanceBasis.SOURCE_EVENT and len(ordered) != 1:
                normalized = service_validation_ops.exact_payload(
                    command.payload,
                    {"basis", "count"},
                )
                control_count(normalized["count"])
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNSUPPORTED",
                    "SOURCE_EVENT is unavailable with multiple FULL tracks because a same-time cohort must commit atomically",
                    status_code=409,
                    details={
                        "basis": requested_basis.value,
                        "full_track_count": len(ordered),
                        "playback_bases": [
                            item.value
                            for item in supported_playback_bases(
                                source_kind=str(binding["source_kind"]),
                                full_track_count=len(ordered),
                            )
                        ],
                    },
                )
        if command.type is ReplayV2CommandType.STEP_EVENT:
            step_event_payload = service_validation_ops.exact_payload(
                command.payload, {"count"}
            )
            count = control_count(step_event_payload["count"])
            if count > MAX_PLAYBACK_BATCH_UNITS:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    f"SOURCE_EVENT count must be between 1 and {MAX_PLAYBACK_BATCH_UNITS}",
                    status_code=422,
                    details={
                        "basis": AdvanceBasis.SOURCE_EVENT.value,
                        "requested_count": count,
                        "max_count": MAX_PLAYBACK_BATCH_UNITS,
                    },
                )
            if str(binding["source_kind"]) != "AGG_TRADE":
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNSUPPORTED",
                    "STEP_EVENT is available only for AGG_TRADE runs",
                    status_code=409,
                )
            if len(ordered) == 1:
                source_goal = await self._ordered_source_goal(
                    ordered,
                    max_events=count,
                    expected_snapshot=selected_snapshot,
                )
                if source_goal is None:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_UNAVAILABLE",
                        "all FULL market tracks reached the end of frozen history",
                        status_code=409,
                    )
                total_events = list(
                    await self._advance_full_tracks_to(
                        command=command,
                        binding=binding,
                        tracks=ordered,
                        target_virtual_time_ms=source_goal.target_virtual_time_ms,
                        audit_account_at_barrier=False,
                        source_goal=source_goal,
                        stable_order_state=stable_order_state,
                        event_stop=event_stop,
                    )
                )
            else:
                total_events = []
                for _ in range(count):
                    next_time = await self._next_global_event_time(
                        run_id=command.run_id,
                        binding=binding,
                        tracks=ordered,
                    )
                    total_events.extend(
                        await self._advance_full_tracks_to(
                            command=command,
                            binding=binding,
                            tracks=ordered,
                            target_virtual_time_ms=next_time,
                            audit_account_at_barrier=False,
                            stable_order_state=stable_order_state,
                        )
                    )
            control_plan = {
                "contract": ADVANCE_CONTRACT_VERSION,
                "basis": AdvanceBasis.SOURCE_EVENT.value,
                "count": count,
                "grain": "EVENT",
                "legacy_alias": command.type.value,
                "mode": "GLOBAL_ORDERED_INPUT_CLOCK",
            }
        else:
            _v1_type, _v1_payload, plan = await self.display._translate_control(
                command=command,
                binding=binding,
                snapshot=selected_snapshot,
            )
            target = plan.get("target_virtual_time_ms")
            if target is None and (
                command.type is ReplayV2CommandType.STEP_BASE
                or (
                    command.type is ReplayV2CommandType.ADVANCE
                    and plan.get("basis") == AdvanceBasis.BASE_BAR.value
                )
            ):
                if command.type is ReplayV2CommandType.STEP_BASE:
                    step_base_payload = service_validation_ops.exact_payload(
                        command.payload,
                        {"count"},
                    )
                    count = control_count(step_base_payload["count"])
                else:
                    count = control_count(plan.get("count"))
                target = aligned_step_target_ms(
                    current_virtual_time_ms=current_time,
                    base_interval=str(binding["base_interval"]),
                    step_interval=str(binding["base_interval"]),
                    count=count,
                )
                plan["target_virtual_time_ms"] = target
            if (
                binding.get("source_kind") == "AGG_TRADE"
                and isinstance(target, int)
                and target > control_rules_ops.training_terminal_time_ms(binding)
            ):
                # A requested jump may exceed frozen history. Stop at the same
                # immutable terminal as the scalar actor before deferred finalize.
                # The binding end can be a last-bucket open; only the source
                # knows its inclusive terminal (also mapped for blind runs).
                for track in ordered:
                    boundary = await self.replay_service.scan_source_goal(
                        service_validation_ops.track_session_id(track),
                        max_events=1,
                    )
                    target = min(
                        target,
                        service_validation_ops._stored_counter(
                            boundary["source_terminal_time_ms"],
                            field_name="source_terminal_time_ms",
                        ),
                    )
                plan["target_virtual_time_ms"] = target
            control_plan = dict(plan)
            control_plan["mode"] = "GLOBAL_ORDERED_INPUT_CLOCK"
            if binding.get("position_mode") == "HEDGE":
                control_plan["input_clock"] = "PINNED_HEDGE_PUBLIC_SIMULATION"
            if plan.get("basis") == AdvanceBasis.SOURCE_EVENT.value:
                requested_count = control_count(plan.get("count"))
                source_goal = await self._ordered_source_goal(
                    ordered,
                    max_events=requested_count,
                    expected_snapshot=selected_snapshot,
                )
                if source_goal is None:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_UNAVAILABLE",
                        "all FULL market tracks reached the end of frozen history",
                        status_code=409,
                    )
                target = source_goal.target_virtual_time_ms
                control_plan["target_virtual_time_ms"] = target
            if not isinstance(target, int):
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNSUPPORTED",
                    "multi-track control requires an exact global target",
                    status_code=409,
                )
            cancelable_scan = command.type in {
                ReplayV2CommandType.ADVANCE_BY,
                ReplayV2CommandType.ADVANCE_TO,
            } or (
                command.type is ReplayV2CommandType.ADVANCE
                and (
                    plan.get("basis") == AdvanceBasis.VIRTUAL_TIME.value
                    or plan.get("basis") == AdvanceBasis.DISPLAY_BAR.value
                )
            )
            if cancelable_scan:
                decision = self._plan_fast_forward(
                    binding=binding,
                    snapshot=selected_snapshot,
                    tracks=ordered,
                    target_virtual_time_ms=target,
                )
                fast_forward_plan = {
                    **decision.to_dict(),
                    **{
                        key: value
                        for key, value in plan.items()
                        if key
                        in {
                            "contract",
                            "basis",
                            "count",
                            "duration_ms",
                            "legacy_alias",
                            "display_interval",
                            "viewer_revision",
                            "target_virtual_time_ms",
                        }
                    },
                }
                if decision.plan is FastForwardPlan.BLOCKED:
                    raise TrainingRunError(
                        "REPLAY_FAST_FORWARD_BLOCKED",
                        decision.explanation,
                        status_code=409,
                        details={"plan": fast_forward_plan},
                    )
                advance_key = (command.run_id, command.command_id)
                if advance_key in self._advance_jobs:
                    raise TrainingRunError(
                        "ADVANCE_ALREADY_ACTIVE",
                        "advance command is already active",
                        status_code=409,
                    )
                advance_job = {
                    "cancel": asyncio.Event(),
                    "client_instance_id": command.client_instance_id,
                    "status": "RUNNING",
                    "initial_virtual_time_ms": current_time,
                    "target_virtual_time_ms": target,
                    "current_virtual_time_ms": current_time,
                    "consumed": 0,
                    "chunks": 0,
                    "cancelable": True,
                    "plan": dict(fast_forward_plan),
                    "chunk_event_limit": 1,
                    "queue_high_water": 0,
                    "stable_order_truncated": False,
                }
                self._advance_jobs[advance_key] = advance_job
            terminal_result_factory = None
            if (
                advance_job is not None
                and source_goal is None
                and self.replay_service.settings.replay_multi_bar_interval_enabled
                and not order_rules_ops.requires_barrier_account_audit(binding)
            ):
                prepared_viewer = (
                    await self.store.get_viewer_state(command.run_id)
                ).to_dict()

                def terminal_result_factory(final, events, progress):
                    return self._multi_control_result(
                        command=command,
                        selected_session_id=selected_session_id,
                        final=final,
                        viewer=prepared_viewer,
                        fast_forward_plan=fast_forward_plan,
                        control_plan=control_plan,
                        advance_job=progress,
                        source_goal=None,
                        ordered=ordered,
                        total_events=events,
                        event_stop=event_stop,
                        stable_order_state=stable_order_state,
                        executed_multi=True,
                    )

            try:
                total_events = list(
                    await self._advance_full_tracks_to(
                        command=command,
                        binding=binding,
                        tracks=ordered,
                        target_virtual_time_ms=target,
                        job=advance_job,
                        # Finalize exact account/HEDGE state at each internal
                        # wave, then run the exhaustive history proof once at
                        # the user-command acknowledgement barrier below.
                        allow_final_state_batch=True,
                        audit_account_at_barrier=False,
                        source_goal=source_goal,
                        stable_order_state=stable_order_state,
                        event_stop=event_stop,
                        terminal_result_factory=terminal_result_factory,
                    )
                )
            except BaseException:
                if advance_key is not None:
                    self._advance_jobs.pop(advance_key, None)
                raise
            if advance_key is not None:
                assert advance_job is not None
                advance_job["cancelable"] = False
                # The command response and a racing progress poll must agree
                # that a terminal job cannot still be cancelled.
                asyncio.get_running_loop().call_later(
                    control_rules_ops.ADVANCE_PROGRESS_RETENTION_SECONDS,
                    self._advance_jobs.pop,
                    advance_key,
                    None,
                )
        completed = getattr(self.store, "_multi_completed_results", {}).get(
            (command.run_id, command.command_id)
        )
        if completed is not None:
            if advance_job is not None:
                advance_job["plan"] = dict(completed["data"]["plan"])
                advance_job["status"] = completed["data"]["progress"]["status"]
            return completed
        if order_rules_ops.requires_barrier_account_audit(binding):
            await self.audit_account(command.run_id)
        selected = await self.replay_service.get_session(selected_session_id)
        final = service_validation_ops.adapter_snapshot(selected)
        viewer = await self.store.get_viewer_state(command.run_id)
        return self._multi_control_result(
            command=command,
            selected_session_id=selected_session_id,
            final=final,
            viewer=viewer.to_dict(),
            fast_forward_plan=fast_forward_plan,
            control_plan=control_plan,
            advance_job=advance_job,
            source_goal=source_goal,
            ordered=ordered,
            total_events=total_events,
            event_stop=event_stop,
            stable_order_state=stable_order_state,
            executed_multi=(command.run_id, command.command_id)
            in getattr(self.store, "_multi_interval_commands", set()),
        )

    def _multi_control_result(
        self,
        *,
        command,
        selected_session_id,
        final,
        viewer,
        fast_forward_plan,
        control_plan,
        advance_job,
        source_goal,
        ordered,
        total_events,
        event_stop,
        stable_order_state,
        executed_multi,
    ):
        if fast_forward_plan is not None:
            if executed_multi:
                fast_forward_plan = {
                    **dict(fast_forward_plan),
                    "executed_path": (
                        "MULTI_TAPE_COHORT_V1"
                        if fast_forward_plan.get("source_kind") == "AGG_TRADE"
                        else "MULTI_BAR_INTERVAL_V1"
                    ),
                    "financial_reference_equivalence": True,
                    "legacy_hash_byte_equivalence": False,
                }
            equivalence = fast_forward_plan.get("equivalence")
            if isinstance(equivalence, Mapping):
                fast_forward_plan["equivalence"] = {
                    **dict(equivalence),
                    "status": "REFERENCE_PATH",
                    "observed_state_hash": final["state_hash"],
                    "observed_cursor": dict(
                        service_validation_ops._stored_mapping(
                            final["cursor"], field_name="adapter cursor"
                        )
                    ),
                    "consumed_source_events": (
                        int(advance_job["consumed"])
                        if advance_job is not None
                        else len(total_events)
                    ),
                }
            if advance_job is not None:
                advance_job["plan"] = dict(fast_forward_plan)
        return command_projection_ops.result_payload(
            command=command,
            session_id=selected_session_id,
            snapshot=final,
            viewer=viewer,
            data={
                "consumed": (
                    final["cursor"]["source_sequence"]
                    - source_goal.start_source_sequence
                    if source_goal is not None
                    else int(advance_job["consumed"])
                    if advance_job is not None
                    else len(total_events)
                ),
                "cancelled": (
                    advance_job is not None and advance_job["status"] == "CANCELLED"
                ),
                "full_track_count": len(ordered),
                "ordering_version": GLOBAL_ORDERING_VERSION,
                "stable_order": [
                    event.to_dict() for event in stable_market_event_order(total_events)
                ],
                **(
                    {
                        "event_stop": event_stop or None,
                        "target_reached": service_validation_ops.cursor_time(final)
                        >= int(
                            (control_plan or {}).get(
                                "target_virtual_time_ms",
                                service_validation_ops.cursor_time(final),
                            )
                        ),
                    }
                    if event_stop is not None
                    else {}
                ),
                **(
                    {
                        "stable_order_truncated": bool(
                            advance_job["stable_order_truncated"]
                        ),
                        "progress": control_rules_ops.public_progress(advance_job),
                    }
                    if advance_job is not None
                    else {}
                ),
                **(
                    {"stable_order_truncated": True}
                    if advance_job is None and stable_order_state["truncated"]
                    else {}
                ),
                **(
                    {"plan": fast_forward_plan or control_plan}
                    if fast_forward_plan is not None or control_plan is not None
                    else {}
                ),
            },
        )

    async def _run_ordered_playback(
        self,
        *,
        run_id: str,
        generation: int,
        stop: asyncio.Event,
    ) -> None:
        """Drive every FULL track from one wall-clock-independent ordered lane."""

        actor = self._run_actors[run_id]
        event_loop = asyncio.get_running_loop()
        last_advance_wall = event_loop.time()
        initial_clock = actor.playback_snapshot()
        last_profile_revision = service_validation_ops._stored_counter(
            initial_clock["profile_revision"],
            field_name="global_clock.profile_revision",
        )
        terminal_state = "PAUSED"
        terminal_reason: str | None = None
        audit_at_terminal = False
        try:
            while not stop.is_set():
                try:
                    async with actor.serialized():
                        if not actor.playback_is_active(generation):
                            break
                        binding = await self.store.run_binding(run_id)
                        audit_at_terminal = (
                            order_rules_ops.requires_barrier_account_audit(binding)
                        )
                        projection_tracks = await self.store.get_market_track_heads(
                            run_id
                        )
                        tracks = TrainingRunActor.ordered_full_tracks(
                            track
                            for track in projection_tracks
                            if isinstance(track, Mapping)
                        )
                        if len(tracks) < 1:
                            terminal_reason = "ORDERED_PLAYBACK_REQUIRES_A_FULL_TRACK"
                            break
                        selected_session_id = str(binding["adapter_session_id"])
                        selected = await self.replay_service.get_session(
                            selected_session_id
                        )
                        selected_snapshot = service_validation_ops.adapter_snapshot(
                            selected
                        )
                        cursor = service_validation_ops._stored_mapping(
                            selected_snapshot.get("cursor"),
                            field_name="adapter cursor",
                        )
                        if cursor.get("at_end") is True:
                            terminal_state = "ENDED"
                            terminal_reason = "SOURCE_EXHAUSTED"
                            break
                        playback_client_id = actor.playback_client_id
                        if playback_client_id is None:
                            terminal_reason = "CONTROLLER_LEASE_LOST"
                            break
                        controller_lease_lost = False
                        for track in tracks:
                            try:
                                await self.replay_service.heartbeat(
                                    service_validation_ops.track_session_id(track),
                                    playback_client_id,
                                )
                            except ReplayDomainError:
                                controller_lease_lost = True
                                terminal_reason = "CONTROLLER_LEASE_LOST"
                                break
                        if controller_lease_lost:
                            break
                        if (
                            selected_snapshot.get("controller_client_id")
                            != playback_client_id
                        ):
                            terminal_reason = "CONTROLLER_LEASE_LOST"
                            break
                        current_time = service_validation_ops.cursor_time(
                            selected_snapshot
                        )
                        clock = actor.playback_snapshot()
                        profile_revision = service_validation_ops._stored_counter(
                            clock["profile_revision"],
                            field_name="global_clock.profile_revision",
                        )
                        now_wall = event_loop.time()
                        if profile_revision != last_profile_revision:
                            last_advance_wall = now_wall
                            last_profile_revision = profile_revision
                        raw_elapsed_seconds = now_wall - last_advance_wall
                        elapsed_seconds = max(0.0, raw_elapsed_seconds)
                        basis = advance_basis(clock.get("basis"))
                        rate = control_rate(clock.get("rate"))
                        source_kind = str(binding["source_kind"])
                        allowed = supported_playback_bases(
                            source_kind=source_kind,
                            full_track_count=len(tracks),
                        )
                        if basis not in allowed:
                            raise TrainingRunError(
                                "REPLAY_CONTROL_UNSUPPORTED",
                                "active playback basis no longer matches the FULL-track topology",
                                status_code=409,
                                details={
                                    "basis": basis.value,
                                    "playback_bases": [item.value for item in allowed],
                                },
                            )
                        consumed_wall_seconds = 0.0
                        source_goal: control_rules_ops._OrderedSourceGoal | None = None
                        if basis is AdvanceBasis.VIRTUAL_TIME:
                            try:
                                next_time = await self._next_global_event_time(
                                    run_id=run_id,
                                    binding=binding,
                                    tracks=tracks,
                                )
                            except TrainingRunError as exc:
                                if exc.code != "REPLAY_CONTROL_UNAVAILABLE":
                                    raise
                                terminal_state = "ENDED"
                                terminal_reason = "SOURCE_EXHAUSTED"
                                break
                            elapsed_ms = max(
                                0,
                                int(elapsed_seconds * 1_000 * rate),
                            )
                            if current_time + elapsed_ms < next_time:
                                timeout = min(
                                    0.25,
                                    max(
                                        0.001,
                                        (next_time - current_time) / rate / 1_000,
                                    ),
                                )
                                target = None
                            else:
                                target = max(next_time, current_time + elapsed_ms)
                                consumed_wall_seconds = elapsed_seconds
                                timeout = 0.0
                        else:
                            final_state_batch_units = 0
                            interactive_batch_limit = 0
                            if source_kind == "BAR":
                                base_interval_ms = fixed_interval_ms(
                                    str(binding["base_interval"]),
                                    field_name="base_interval",
                                )
                                if current_time <= MAX_TIMESTAMP_MS - base_interval_ms:
                                    next_base_time = current_time + base_interval_ms
                                    interactive_batch_limit = (
                                        self._ordered_playback_interactive_batch_limit(
                                            binding=binding,
                                            tracks=tracks,
                                            snapshot=selected_snapshot,
                                            target_virtual_time_ms=next_base_time,
                                        )
                                    )
                                    if (
                                        rate
                                        >= control_rules_ops.ORDERED_PLAYBACK_FINAL_STATE_MIN_RATE
                                    ):
                                        final_state_profile = (
                                            self._ordered_final_state_batch_profile(
                                                binding=binding,
                                                tracks=tracks,
                                                snapshot=selected_snapshot,
                                                target_virtual_time_ms=next_base_time,
                                                enabled=True,
                                            )
                                        )
                                        if final_state_profile is not None:
                                            final_state_batch_units = min(
                                                final_state_profile[0],
                                                (
                                                    rate
                                                    + control_rules_ops.ORDERED_PLAYBACK_FINAL_STATE_TARGET_HZ
                                                    - 1
                                                )
                                                // control_rules_ops.ORDERED_PLAYBACK_FINAL_STATE_TARGET_HZ,
                                            )
                            units = discrete_playback_units(
                                elapsed_seconds,
                                rate=rate,
                            )
                            if interactive_batch_limit > 0:
                                # The Run actor lock is also the PAUSE/SET_SPEED
                                # acknowledgement boundary.  Once orders or positions
                                # exist, yield that fair lock after every committed BAR
                                # so account growth cannot turn one playback batch into
                                # an unbounded control-command stall.
                                units = min(units, interactive_batch_limit)
                            if units < final_state_batch_units:
                                if raw_elapsed_seconds >= 0:
                                    # Keep one bounded projection batch computed
                                    # ahead of wall time. Without this lead, a fast
                                    # actor catches up and falls back to one durable
                                    # command per BAR at high public rates.
                                    units = final_state_batch_units
                                else:
                                    units = 0
                                    target = None
                                    timeout = min(
                                        0.25,
                                        max(0.001, -raw_elapsed_seconds),
                                    )
                            if units == 0:
                                if final_state_batch_units == 0:
                                    target = None
                                    timeout = min(
                                        0.25,
                                        max(
                                            0.001,
                                            (1 / rate) - elapsed_seconds,
                                        ),
                                    )
                            elif basis is AdvanceBasis.SOURCE_EVENT:
                                if len(tracks) != 1:
                                    raise TrainingRunError(
                                        "REPLAY_CONTROL_UNSUPPORTED",
                                        "SOURCE_EVENT playback requires exactly one FULL track",
                                        status_code=409,
                                    )
                                source_goal = await self._ordered_source_goal(
                                    tracks,
                                    max_events=units,
                                    require_exact_count=False,
                                    expected_snapshot=selected_snapshot,
                                )
                                if source_goal is None:
                                    terminal_state = "ENDED"
                                    terminal_reason = "SOURCE_EXHAUSTED"
                                    break
                                target = source_goal.target_virtual_time_ms
                                consumed_wall_seconds = source_goal.planned_count / rate
                                timeout = 0.0
                            else:
                                step_interval = (
                                    clock.get("display_interval")
                                    if basis is AdvanceBasis.DISPLAY_BAR
                                    else str(binding["base_interval"])
                                )
                                if not isinstance(step_interval, str):
                                    raise TrainingRunError(
                                        "TRAINING_RUN_STORAGE_DEGRADED",
                                        "display playback profile has no interval",
                                        status_code=503,
                                    )
                                if basis is AdvanceBasis.DISPLAY_BAR:
                                    target = await self.display._source_aligned_display_target(
                                        binding=binding,
                                        current_virtual_time_ms=current_time,
                                        base_interval=str(binding["base_interval"]),
                                        display_interval=step_interval,
                                        count=units,
                                    )
                                else:
                                    target = aligned_step_target_ms(
                                        current_virtual_time_ms=current_time,
                                        base_interval=str(binding["base_interval"]),
                                        step_interval=step_interval,
                                        count=units,
                                    )
                                base_interval_ms = compatible_step_interval_ms(
                                    base_interval=str(binding["base_interval"]),
                                    step_interval=str(binding["base_interval"]),
                                )
                                adapter_config = binding.get("adapter_config")
                                if not isinstance(adapter_config, Mapping):
                                    raise TrainingRunError(
                                        "TRAINING_RUN_STORAGE_DEGRADED",
                                        "training adapter config is invalid",
                                        status_code=503,
                                    )
                                actual_start_ms = (
                                    service_validation_ops._stored_counter(
                                        binding["actual_replay_start_ms"],
                                        field_name="actual_replay_start_ms",
                                    )
                                )
                                public_start_ms = (
                                    service_validation_ops._stored_counter(
                                        binding.get("synthetic_origin_ms"),
                                        field_name="synthetic_origin_ms",
                                    )
                                    if adapter_config.get("blind_mode") is True
                                    else actual_start_ms
                                )
                                final_open_ms = (
                                    public_start_ms
                                    + service_validation_ops._stored_counter(
                                        binding["actual_replay_end_ms"],
                                        field_name="actual_replay_end_ms",
                                    )
                                    - actual_start_ms
                                )
                                final_close_ms = final_open_ms + base_interval_ms - 1
                                penultimate_close_ms = final_open_ms - 1
                                if (
                                    current_time < penultimate_close_ms
                                    and target >= final_close_ms
                                ):
                                    # Leave the terminal event for one final loop.
                                    # This creates a scheduling barrier where a
                                    # pending PAUSE can win without reducing steady
                                    # state playback batch throughput.
                                    target = penultimate_close_ms
                                consumed_wall_seconds = units / rate
                                timeout = 0.0
                        if target is not None:
                            tick = actor.next_playback_tick(generation)
                            internal = ReplayV2Command(
                                protocol="replay.v3",
                                run_id=run_id,
                                command_id=f"ordered-play-{generation}-{tick}",
                                client_instance_id=str(actor.playback_client_id),
                                expected_revision=service_validation_ops._stored_counter(
                                    selected_snapshot["revision"], field_name="revision"
                                ),
                                expected_cursor=TrainingCursor(
                                    virtual_time_ms=service_validation_ops._stored_counter(
                                        cursor["virtual_time_ms"],
                                        field_name="virtual_time_ms",
                                    ),
                                    source_sequence=service_validation_ops._stored_counter(
                                        cursor["source_sequence"],
                                        field_name="source_sequence",
                                    ),
                                    revision=service_validation_ops._stored_counter(
                                        selected_snapshot["revision"],
                                        field_name="revision",
                                    ),
                                ),
                                type=ReplayV2CommandType.ADVANCE_TO,
                                payload={"virtual_time_ms": target},
                            )
                            await self._advance_full_tracks_to(
                                command=internal,
                                binding=binding,
                                tracks=tracks,
                                target_virtual_time_ms=target,
                                stop_event=stop,
                                allow_final_state_batch=True,
                                audit_account_at_barrier=False,
                                source_goal=(
                                    source_goal
                                    if basis is AdvanceBasis.SOURCE_EVENT
                                    else None
                                ),
                            )
                            actor.set_playback_data_wait(generation, waiting=False)
                            if consumed_wall_seconds > 0:
                                last_advance_wall += consumed_wall_seconds
                            else:
                                last_advance_wall = event_loop.time()
                            timeout = 0.0
                except ReplayDomainError as exc:
                    if exc.code is not ReplayErrorCode.DATASET_PENDING:
                        raise
                    async with actor.serialized():
                        actor.set_playback_data_wait(generation, waiting=True)
                    # Waiting is not virtual elapsed time. Avoid a catch-up jump
                    # when a later immutable segment becomes available.
                    last_advance_wall = event_loop.time()
                    timeout = 0.25
                if timeout > 0:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=timeout)
                    except TimeoutError:
                        pass
                else:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            terminal_reason = terminal_reason or "PLAYBACK_CANCELLED"
        except (ReplayDomainError, TrainingRunError) as exc:
            terminal_reason = (
                exc.code.value if isinstance(exc, ReplayDomainError) else exc.code
            )
            terminal_state = (
                "PAUSED" if terminal_reason.startswith("HISTORICAL_BOOK_") else "ERROR"
            )
        except Exception as exc:  # pragma: no cover - defensive task boundary
            terminal_state = "ERROR"
            terminal_reason = type(exc).__name__
        finally:
            async with actor.serialized():
                snapshot = actor.playback_snapshot()
                if (
                    service_validation_ops._stored_counter(
                        snapshot["generation"], field_name="global_clock.generation"
                    )
                    == generation
                ):
                    if snapshot["state"] != "PLAYING":
                        terminal_state = str(snapshot["state"])
                        terminal_reason = (
                            str(snapshot["reason"])
                            if snapshot["reason"] is not None
                            else terminal_reason
                        )
                    actor.finish_ordered_playback(
                        generation=generation,
                        state=terminal_state,
                        reason=terminal_reason,
                    )
                    if audit_at_terminal:
                        # Playback can contain many internal waves. Keep its
                        # proof exact while paying the O(history) audit once at
                        # the terminal PAUSE/ENDED/ERROR barrier.
                        await self.audit_account(run_id)
            self._notify_market_tracks(run_id)

    async def _ordered_source_goal(
        self,
        tracks: tuple[Mapping[str, object], ...],
        *,
        max_events: int,
        require_exact_count: bool = True,
        expected_snapshot: Mapping[str, object] | None = None,
    ) -> control_rules_ops._OrderedSourceGoal | None:
        if max_events > MAX_PLAYBACK_BATCH_UNITS:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                f"SOURCE_EVENT count must be between 1 and {MAX_PLAYBACK_BATCH_UNITS}",
                status_code=422,
                details={
                    "basis": AdvanceBasis.SOURCE_EVENT.value,
                    "requested_count": max_events,
                    "max_count": MAX_PLAYBACK_BATCH_UNITS,
                },
            )
        if len(tracks) != 1:
            raise TrainingRunError(
                "REPLAY_CONTROL_UNSUPPORTED",
                "an exact source-event boundary requires exactly one FULL track",
                status_code=409,
            )
        for track in tracks:
            session_id = service_validation_ops.track_session_id(track)
            plan = await self.replay_service.scan_source_goal(
                session_id,
                max_events=max_events,
            )
            revision = service_validation_ops._stored_counter(
                plan["revision"], field_name="revision"
            )
            cursor = service_validation_ops._stored_mapping(
                plan.get("start_cursor"), field_name="source goal start cursor"
            )
            start_sequence = service_validation_ops._stored_counter(
                cursor.get("source_sequence"), field_name="source_sequence"
            )
            if expected_snapshot is not None:
                expected_cursor = service_validation_ops._stored_mapping(
                    expected_snapshot.get("cursor"),
                    field_name="expected source goal cursor",
                )
                if start_sequence != service_validation_ops._stored_counter(
                    expected_cursor.get("source_sequence"),
                    field_name="expected source_sequence",
                ) or revision != service_validation_ops._stored_counter(
                    expected_snapshot.get("revision"),
                    field_name="expected revision",
                ):
                    raise TrainingRunError(
                        "GLOBAL_CLOCK_DIVERGED",
                        "market source cursor changed before ordered preflight",
                        status_code=409,
                    )
            event_count = service_validation_ops._stored_counter(
                plan["event_count"], field_name="event_count"
            )
            exhausted = plan.get("exhausted")
            if not isinstance(exhausted, bool):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market source goal is missing its exhaustion state",
                    status_code=503,
                )
            if event_count == 0:
                return None
            if require_exact_count and event_count != max_events:
                if not exhausted:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "market source goal stopped before its requested boundary",
                        status_code=503,
                    )
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNAVAILABLE",
                    "source history cannot satisfy the requested event count",
                    status_code=409,
                    details={
                        "requested_count": max_events,
                        "available_count": event_count,
                    },
                )
            last_event_time_ms = plan.get("last_event_time_ms")
            if not isinstance(last_event_time_ms, int):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market event plan is missing its timestamp",
                    status_code=503,
                )
            source_terminal_time_ms = plan.get("source_terminal_time_ms")
            if not isinstance(source_terminal_time_ms, int):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market event plan is missing its source terminal",
                    status_code=503,
                )
            return control_rules_ops._OrderedSourceGoal(
                start_source_sequence=start_sequence,
                start_revision=revision,
                target_source_sequence=start_sequence + event_count,
                target_virtual_time_ms=(
                    source_terminal_time_ms if exhausted else last_event_time_ms
                ),
                planned_count=event_count,
            )
        return None

    async def _end_multi_track_run(
        self,
        *,
        command: ReplayV2Command,
        tracks: tuple[Mapping[str, object], ...],
        selected_session_id: str,
    ) -> dict[str, object]:
        payload = dict(
            service_validation_ops.exact_payload(
                command.payload,
                {"open_order_disposition", "position_disposition"},
            )
        )
        actor = self._run_actors[command.run_id]
        actor.request_ordered_pause(reason="RUN_END")
        prepared = tuple(
            track
            for track in tracks
            if isinstance(track.get("adapter_session_id"), str)
        )
        snapshots: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
        for track in prepared:
            session_id = service_validation_ops.track_session_id(track)
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            if snapshot["state"] == "PLAYING":
                raise TrainingRunError(
                    "MULTI_TRACK_PAUSED",
                    "all market tracks must pause before the run can end",
                    status_code=409,
                    details={"track_id": track["track_id"]},
                )
            if snapshot["state"] != "ENDED":
                await self._ensure_track_controller(
                    session_id=session_id,
                    client_instance_id=command.client_instance_id,
                    command_id=command.command_id,
                )
                session = await self.replay_service.get_session(session_id)
                snapshot = service_validation_ops.adapter_snapshot(session)
            snapshots.append((track, snapshot))
        selected_result: Mapping[str, object] | None = None
        ended = 0
        try:
            for track, snapshot in snapshots:
                session_id = service_validation_ops.track_session_id(track)
                if snapshot["state"] == "ENDED":
                    acknowledged = snapshot
                else:
                    adapter = ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id=control_rules_ops.multi_command_id(
                            command.command_id,
                            str(track["track_id"]),
                            CommandType.END_SESSION.value,
                            service_validation_ops._stored_counter(
                                snapshot["revision"], field_name="revision"
                            ),
                        ),
                        client_instance_id=command.client_instance_id,
                        expected_revision=service_validation_ops._stored_counter(
                            snapshot["revision"], field_name="revision"
                        ),
                        type=CommandType.END_SESSION,
                        payload=payload,
                    )
                    acknowledged = await self.replay_service.command(
                        session_id,
                        adapter,
                    )
                ended += 1
                if session_id == selected_session_id:
                    selected_result = acknowledged
        except ReplayDomainError as exc:
            await self._fail_closed_multi_track(
                run_id=command.run_id,
                tracks=prepared,
                failed_track=track,
                client_instance_id=command.client_instance_id,
                reason=exc.code.value,
            )
            raise TrainingRunError(
                "MULTI_TRACK_END_FAILED",
                "a prepared market track rejected the run end command",
                status_code=409,
                details={"reason": exc.code.value, "track_id": track["track_id"]},
            ) from exc
        if selected_result is None:
            selected = await self.replay_service.get_session(selected_session_id)
            selected_result = service_validation_ops.adapter_snapshot(selected)
        selected_snapshot = (
            selected_result
            if "cursor" in selected_result
            else service_validation_ops.adapter_snapshot(selected_result)
        )
        checkpoint = await self.store.checkpoint_market_tracks(command.run_id)
        generation = service_validation_ops._stored_counter(
            actor.playback_snapshot()["generation"],
            field_name="global_clock.generation",
        )
        actor.finish_ordered_playback(
            generation=generation,
            state="ENDED",
            reason="RUN_END",
        )
        viewer = await self.store.get_viewer_state(command.run_id)
        result = command_projection_ops.result_payload(
            command=command,
            session_id=selected_session_id,
            snapshot=selected_snapshot,
            viewer=viewer.to_dict(),
            data={
                "ended_track_count": ended,
                "global_checkpoint": checkpoint,
                "ordering_version": GLOBAL_ORDERING_VERSION,
                "global_clock": actor.playback_snapshot(),
            },
        )
        result["state"] = "ENDED"
        return result

    async def _advance_full_tracks_to(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        target_virtual_time_ms: int,
        job: dict[str, object] | None = None,
        stop_event: asyncio.Event | None = None,
        allow_final_state_batch: bool = False,
        audit_account_at_barrier: bool = True,
        source_goal: control_rules_ops._OrderedSourceGoal | None = None,
        stable_order_state: dict[str, bool] | None = None,
        event_stop: dict[str, object] | None = None,
        terminal_result_factory=None,
    ) -> tuple[StableMarketEvent, ...]:
        if source_goal is not None and len(tracks) != 1:
            raise TrainingRunError(
                "REPLAY_CONTROL_UNSUPPORTED",
                "an exact source-event boundary requires exactly one FULL track",
                status_code=409,
            )
        hedge_mode = str(binding.get("position_mode")) == "HEDGE"
        if not hedge_mode:
            await self.account_history.guard_run(
                run_id=command.run_id,
                tracks=tracks,
            )
        pending_account_events = await self.store.pending_account_global_events(
            command.run_id
        )
        pending_hedge_events = await self.store.pending_hedge_input_global_events(
            command.run_id
        )
        if pending_account_events or pending_hedge_events:
            await self.store.record_global_events(
                command.run_id,
                stable_market_event_order(
                    (*pending_account_events, *pending_hedge_events)
                ),
                materialize_portfolio=False,
            )
        hedge_runtime_snapshot = (
            await self.hedge_inputs.runtime_snapshot(command.run_id)
            if hedge_mode
            else None
        )
        book_required = (
            str(binding.get("book_mode", "OFF"))
            == BookMode.BOOK_ASSISTED_REQUIRED.value
        )
        all_events: list[StableMarketEvent] = []
        pending_global_events: list[StableMarketEvent] = []
        cancel_event = stop_event
        if job is not None:
            job_cancel = job.get("cancel")
            if isinstance(job_cancel, asyncio.Event):
                cancel_event = job_cancel

        async def cancel_at_committed_barrier() -> tuple[StableMarketEvent, ...]:
            if job is not None:
                job["status"] = "CANCELLED"
            if audit_account_at_barrier:
                await self.audit_account(command.run_id)
            return stable_market_event_order(all_events)

        wave_budget = (
            10_000
            if source_goal is None
            else max(10_000, (source_goal.planned_count + 1) * 4)
        )
        source_start_verified = False
        from .tape_phases import coordinator_waves

        for _wave_index in coordinator_waves(
            self.store, command, binding, job, wave_budget
        ):
            if (
                cancel_event is not None
                and cancel_event.is_set()
                and not pending_global_events
            ):
                return await cancel_at_committed_barrier()
            snapshots: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
            times: set[int] = set()
            next_times: list[int] = []
            market_sequences: list[int] = []
            compact_multi = (
                allow_final_state_batch
                and source_goal is None
                and not pending_global_events
                and self.replay_service.settings.replay_multi_bar_interval_enabled
                and hedge_mode
                and binding.get("source_kind") == "BAR"
                and binding.get("book_mode", "OFF") == "OFF"
                and binding.get("account_data_mode")
                != AccountDataMode.HISTORICAL_EXACT.value
                and 2 <= len(tracks) <= 8
                and isinstance(hedge_runtime_snapshot, IndexedHedgeSnapshot)
            )
            compact_states = []
            if compact_multi:
                compact_states = await asyncio.gather(
                    *(
                        self.replay_service.get_session_state(
                            service_validation_ops.track_session_id(track)
                        )
                        for track in tracks
                    ),
                    return_exceptions=True,
                )
                for state in compact_states:
                    if isinstance(state, BaseException):
                        raise state
            for track_index, track in enumerate(tracks):
                session_id = service_validation_ops.track_session_id(track)
                if compact_multi:
                    snapshot = compact_states[track_index]
                else:
                    session = await self.replay_service.get_session(session_id)
                    snapshot = service_validation_ops.adapter_snapshot(session)
                if source_goal is not None and not source_start_verified:
                    snapshot_cursor = service_validation_ops._stored_mapping(
                        snapshot.get("cursor"), field_name="adapter cursor"
                    )
                    if (
                        service_validation_ops._stored_counter(
                            snapshot.get("revision"), field_name="revision"
                        )
                        != source_goal.start_revision
                        or service_validation_ops._stored_counter(
                            snapshot_cursor.get("source_sequence"),
                            field_name="source_sequence",
                        )
                        != source_goal.start_source_sequence
                    ):
                        raise TrainingRunError(
                            "GLOBAL_CLOCK_DIVERGED",
                            "market source cursor changed after ordered preflight",
                            status_code=409,
                        )
                    source_start_verified = True
                snapshots.append((track, snapshot))
                times.add(service_validation_ops.cursor_time(snapshot))
                snapshot_cursor = service_validation_ops._stored_mapping(
                    snapshot.get("cursor"), field_name="adapter cursor"
                )
                market_sequences.append(
                    service_validation_ops._stored_counter(
                        snapshot_cursor.get("source_sequence"),
                        field_name="source_sequence",
                    )
                )

            if (
                allow_final_state_batch
                and source_goal is None
                and not pending_global_events
            ):
                from .multi_interval_advance import try_advance

                completion = None
                if terminal_result_factory is not None and job is not None:
                    prior_events, prior_job = tuple(all_events), dict(job)

                    def completion(group):
                        events = [*prior_events, *group["stable"]]
                        progress = dict(prior_job)
                        if len(events) > control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS:
                            events = events[
                                -control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS :
                            ]
                            progress["stable_order_truncated"] = True
                        progress.update(
                            consumed=progress["consumed"] + len(group["stable"]),
                            chunks=progress["chunks"] + 1,
                            current_virtual_time_ms=group["target"],
                            cancelable=False,
                            status="CANCELLED"
                            if cancel_event is not None and cancel_event.is_set()
                            else "COMPLETED",
                        )
                        state = next(
                            p["state"]
                            for p in group["tracks"]
                            if p["session_id"] == group["selected_session_id"]
                        )
                        final = {**state, "sequence": state["event_sequence"]}
                        return terminal_result_factory(final, events, progress)

                recorded = await try_advance(
                    self,
                    command=command,
                    binding=binding,
                    tracks=tracks,
                    snapshots=snapshots,
                    target=target_virtual_time_ms,
                    runtime_snapshot=hedge_runtime_snapshot,
                    cancel_event=cancel_event,
                    completion=completion,
                )
                completed_multi_interval = recorded is not None
                if recorded is None:
                    from .tape_phases import try_advance as try_tape_phases

                    recorded = await try_tape_phases(
                        self,
                        command=command,
                        binding=binding,
                        tracks=tracks,
                        snapshots=snapshots,
                        target=target_virtual_time_ms,
                    )
                if recorded is None:
                    recorded = await self._try_indexed_interval(
                        command=command,
                        binding=binding,
                        tracks=tracks,
                        snapshot=snapshots[0][1],
                        target=target_virtual_time_ms,
                        runtime_snapshot=hedge_runtime_snapshot,
                    )
                if recorded is None:
                    recorded = await self._try_recorded_interval(
                        command=command,
                        binding=binding,
                        tracks=tracks,
                        snapshot=snapshots[0][1],
                        target=target_virtual_time_ms,
                        runtime_snapshot=hedge_runtime_snapshot,
                    )
                if recorded is not None:
                    recorded_events, recorded_time = recorded
                    all_events.extend(recorded_events)
                    if (job is not None or stable_order_state is not None) and len(
                        all_events
                    ) > control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS:
                        del all_events[
                            : -control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS
                        ]
                        if job is not None:
                            job["stable_order_truncated"] = True
                        if stable_order_state is not None:
                            stable_order_state["truncated"] = True
                    if job is not None:
                        job["consumed"] += len(recorded_events)
                        job["chunks"] += 1
                        job["current_virtual_time_ms"] = recorded_time
                    await asyncio.sleep(0)
                    if (
                        completed_multi_interval
                        and recorded_time >= target_virtual_time_ms
                    ):
                        # The shared planner already proved and committed all
                        # market/public-input events through this target. Do
                        # not repeat eight full snapshots and source/account
                        # preflights merely to rediscover that same boundary.
                        durable_result = getattr(
                            self.store, "_multi_completed_results", {}
                        ).get((command.run_id, command.command_id))
                        if durable_result is not None:
                            if job is not None:
                                job["status"] = durable_result["data"]["progress"][
                                    "status"
                                ]
                                job["cancelable"] = False
                            return stable_market_event_order(all_events)
                        if cancel_event is not None and cancel_event.is_set():
                            return await cancel_at_committed_barrier()
                        if job is not None:
                            job["status"] = "COMPLETED"
                            job["current_virtual_time_ms"] = recorded_time
                        if audit_account_at_barrier:
                            await self.audit_account(command.run_id)
                        return stable_market_event_order(all_events)
                    continue

            if compact_multi:
                detailed = []
                for track, authority in snapshots:
                    snapshot = service_validation_ops.adapter_snapshot(
                        await self.replay_service.get_session(
                            service_validation_ops.track_session_id(track)
                        )
                    )
                    if (
                        service_validation_ops.cursor_time(snapshot)
                        != service_validation_ops.cursor_time(authority)
                        or snapshot["cursor"]["source_sequence"]
                        != authority["cursor"]["source_sequence"]
                    ):
                        raise TrainingRunError(
                            "GLOBAL_CLOCK_DIVERGED",
                            "source changed during interval preflight",
                            status_code=409,
                        )
                    detailed.append((track, snapshot))
                snapshots = detailed

            # These input reads all precede this wave's mutations under the Run lock.
            hedge_cursor_view = (
                await self.hedge_inputs._projection_cursors(command.run_id)
                if isinstance(hedge_runtime_snapshot, IndexedHedgeSnapshot)
                and not book_required
                and binding.get("account_data_mode")
                != AccountDataMode.HISTORICAL_EXACT.value
                else None
            )
            held_prefix_end = (
                await self._held_interval_batch_end(
                    command.run_id,
                    binding=binding,
                    tracks=tracks,
                    snapshot=snapshots[0][1],
                    target_virtual_time_ms=target_virtual_time_ms,
                    runtime_snapshot=hedge_runtime_snapshot,
                    cursor_view=hedge_cursor_view,
                )
                if allow_final_state_batch and source_goal is None
                else None
            )
            constant_tape = (
                allow_final_state_batch
                and source_goal is None
                and binding.get("source_kind") == "AGG_TRADE"
                and binding.get("position_mode") == "ONE_WAY"
                and binding.get("funding_mode") == "OFF"
                and not book_required
                and binding.get("account_data_mode")
                != AccountDataMode.HISTORICAL_EXACT.value
                and any(
                    not control_rules_ops.snapshot_is_flat(snapshot)
                    for _, snapshot in snapshots
                )
            )
            final_state_profile = self._ordered_final_state_batch_profile(
                binding=binding,
                tracks=tracks,
                snapshot=snapshots[0][1],
                target_virtual_time_ms=target_virtual_time_ms,
                enabled=allow_final_state_batch and source_goal is None,
                held_certificate=held_prefix_end is not None or constant_tape,
            )
            if final_state_profile is None:
                held_prefix_end = None
                constant_tape = False
            # Read a bounded lookahead so one exact same-timestamp market
            # cohort can cross the adapter in one command.  The prefix below
            # still stops at the first different timestamp, preserving every
            # account/rule/funding/global ordering barrier.
            source_plan_limit = (
                control_rules_ops.ORDERED_SOURCE_COHORT_PLAN_EVENTS
                if final_state_profile is None
                else final_state_profile[0]
            )
            if source_goal is not None:
                remaining = source_goal.target_source_sequence - market_sequences[0]
                if remaining < 0:
                    raise TrainingRunError(
                        "GLOBAL_CLOCK_DIVERGED",
                        "market track crossed the planned source-event boundary",
                        status_code=409,
                    )
                source_plan_limit = max(
                    1,
                    min(control_rules_ops.ORDERED_SOURCE_COHORT_PLAN_EVENTS, remaining),
                )
            planned_event_times: dict[str, tuple[int, ...]] = {}
            planned_source_boundaries: dict[str, int] = {}
            for track, _snapshot in snapshots:
                session_id = service_validation_ops.track_session_id(track)
                try:
                    plan = await self.replay_service.plan_source_chunk(
                        session_id,
                        target_time_ms=(
                            target_virtual_time_ms
                            if held_prefix_end is None
                            else held_prefix_end
                        ),
                        max_events=source_plan_limit,
                        screen_interactions=final_state_profile is not None,
                        preserve_valuation=held_prefix_end is not None or constant_tape,
                    )
                except (ReplayDomainError, TrainingRunError) as exc:
                    if (
                        isinstance(exc, ReplayDomainError)
                        and exc.code is ReplayErrorCode.DATASET_PENDING
                    ):
                        raise
                    await self._fail_closed_multi_track(
                        run_id=command.run_id,
                        tracks=tracks,
                        failed_track=track,
                        client_instance_id=command.client_instance_id,
                        reason=(
                            exc.code.value
                            if isinstance(exc, ReplayDomainError)
                            else exc.code
                        ),
                    )
                    raise TrainingRunError(
                        "MULTI_TRACK_PAUSED",
                        "a required FULL market track failed global preflight",
                        status_code=409,
                        details={"track_id": track["track_id"]},
                    ) from exc
                event_count = service_validation_ops._stored_counter(
                    plan["event_count"], field_name="event_count"
                )
                raw_event_times = plan.get("event_times_ms")
                if not isinstance(raw_event_times, (list, tuple)):
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "market event plan is missing timestamps",
                        status_code=503,
                    )
                event_times = tuple(
                    service_validation_ops._stored_counter(
                        value, field_name="source_event_time_ms"
                    )
                    for value in raw_event_times
                )
                if len(event_times) != event_count:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "market event plan has an invalid timestamp count",
                        status_code=503,
                    )
                if event_count > 0:
                    preserve_final_state_batch = (
                        source_goal is None and final_state_profile is not None
                    )
                    next_time = (
                        event_times[-1]
                        if preserve_final_state_batch
                        else event_times[0]
                    )
                    cohort_count = 1
                    if preserve_final_state_batch:
                        cohort_count = len(event_times)
                    else:
                        while (
                            cohort_count < len(event_times)
                            and event_times[cohort_count] == next_time
                        ):
                            cohort_count += 1
                    track_key = str(track["track_id"])
                    planned_event_times[track_key] = event_times[:cohort_count]
                    plan_cursor = service_validation_ops._stored_mapping(
                        plan.get("cursor"), field_name="source plan cursor"
                    )
                    planned_source_boundaries[track_key] = (
                        service_validation_ops._stored_counter(
                            plan_cursor.get("source_sequence"),
                            field_name="source_sequence",
                        )
                        + cohort_count
                    )
                    next_times.append(next_time)

            def shrink_final_state_plan_to_first_event() -> None:
                nonlocal final_state_profile
                next_times.clear()
                for track_index, (track, _snapshot) in enumerate(snapshots):
                    track_key = str(track["track_id"])
                    planned_times = planned_event_times.get(track_key, ())
                    if not planned_times:
                        continue
                    first_time = planned_times[0]
                    planned_event_times[track_key] = (first_time,)
                    planned_source_boundaries[track_key] = (
                        market_sequences[track_index] + 1
                    )
                    next_times.append(first_time)
                final_state_profile = None

            if final_state_profile is not None and len(tracks) > 1:
                planned_batches = tuple(
                    planned_event_times.get(str(track["track_id"]), ())
                    for track, _snapshot in snapshots
                )
                aligned = bool(planned_batches and planned_batches[0]) and all(
                    batch == planned_batches[0] for batch in planned_batches[1:]
                )
                if not aligned:
                    # Only independent, flat accounts may coalesce unequal source
                    # grids. The coordinator still owns the global clock, events,
                    # cancellation and atomic checkpoint barrier.
                    independent_flat = (
                        not hedge_mode
                        and not book_required
                        and binding.get("funding_mode") == "OFF"
                        and binding.get("account_data_mode")
                        != AccountDataMode.HISTORICAL_EXACT.value
                        and (
                            constant_tape
                            or all(
                                control_rules_ops.snapshot_is_flat(snapshot)
                                for _, snapshot in snapshots
                            )
                        )
                    )
                    ends = [batch[-1] for batch in planned_batches if batch]
                    if independent_flat and ends:
                        boundary = min(ends)
                        next_times[:] = [boundary]
                        for track, _snapshot in snapshots:
                            key = str(track["track_id"])
                            planned_event_times[key] = tuple(
                                t
                                for t in planned_event_times.get(key, ())
                                if t <= boundary
                            )
                    else:
                        shrink_final_state_plan_to_first_event()
            if len(times) != 1:
                raise TrainingRunError(
                    "GLOBAL_CLOCK_DIVERGED",
                    "FULL market tracks do not share one VirtualTime",
                    status_code=409,
                )
            current = next(iter(times))
            current_source_sequence = market_sequences[0]
            target_actual_time_ms = control_rules_ops.actual_event_time_ms(
                binding,
                target_virtual_time_ms,
            )
            next_account_actual = await self.account_history.next_event_time(
                run_id=command.run_id,
                tracks=tracks,
                target_actual_time_ms=target_actual_time_ms,
                guarded=True,
            )
            next_hedge_actual = (
                await self.hedge_inputs.next_event_time(
                    run_id=command.run_id,
                    target_actual_time_ms=target_actual_time_ms,
                    runtime_snapshot=hedge_runtime_snapshot,
                    cursor_view=hedge_cursor_view,
                )
                if hedge_mode
                else None
            )
            next_account_virtual = (
                None
                if next_account_actual is None
                else control_rules_ops.virtual_event_time_ms(
                    binding,
                    next_account_actual,
                )
            )
            next_hedge_virtual = (
                None
                if next_hedge_actual is None
                else control_rules_ops.virtual_event_time_ms(binding, next_hedge_actual)
            )
            if next_account_virtual is not None and next_account_virtual < current:
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_CURSOR_BEHIND_MARKET",
                    "account timeline fell behind the committed market cursor",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            if next_hedge_virtual is not None and next_hedge_virtual < current:
                await self.hedge_inputs.pause_run(
                    command.run_id,
                    reason="HEDGE_INPUT_CURSOR_BEHIND_MARKET",
                )
                raise TrainingRunError(
                    "HEDGE_INPUT_CURSOR_BEHIND_MARKET",
                    "HEDGE input timeline fell behind the committed market cursor",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            batched_hedge_events: tuple[HedgeInputEvent, ...] = ()
            batched_hedge_virtual_times: tuple[int, ...] = ()
            hedge_batch_wave_time: int | None = None
            if (
                hedge_mode
                and final_state_profile is not None
                and (
                    held_prefix_end is not None
                    or all(
                        control_rules_ops.snapshot_is_flat(snapshot)
                        for _, snapshot in snapshots
                    )
                )
                and next_times
            ):
                planned_batch_time = min(next_times)
                account_after_batch = (
                    next_account_virtual is None
                    or next_account_virtual > planned_batch_time
                )
                candidate_hedge_events = await self.hedge_inputs.events_through(
                    run_id=command.run_id,
                    target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                        binding,
                        planned_batch_time,
                    ),
                    runtime_snapshot=hedge_runtime_snapshot,
                    cursor_view=hedge_cursor_view,
                )
                # A known settlement/rule boundary must split the candidate
                # block, rather than forcing every preceding safe bar through
                # the slow path. Never batch across the boundary itself.
                if len(tracks) == 1 and not book_required:
                    barriers = [
                        control_rules_ops.virtual_event_time_ms(
                            binding, event.event_time_ms
                        )
                        for event in candidate_hedge_events
                        if event.source_kind != "PUBLIC"
                        or event.event_kind != "MARK_INDEX"
                        or event.event_phase != MARK_INDEX_EVENT_PHASE
                    ]
                    if barriers:
                        boundary = min(barriers)
                        key = str(tracks[0]["track_id"])
                        safe_times = tuple(
                            t for t in planned_event_times.get(key, ()) if t < boundary
                        )
                        if safe_times:
                            planned_batch_time = safe_times[-1]
                            next_times = [planned_batch_time]
                            planned_event_times[key] = safe_times
                            candidate_hedge_events = tuple(
                                event
                                for event in candidate_hedge_events
                                if control_rules_ops.virtual_event_time_ms(
                                    binding, event.event_time_ms
                                )
                                <= planned_batch_time
                            )
                            account_after_batch = (
                                next_account_virtual is None
                                or next_account_virtual > planned_batch_time
                            )
                hedge_batch_is_safe = (
                    not book_required
                    and account_after_batch
                    and all(
                        event.source_kind == "PUBLIC"
                        and event.event_kind == "MARK_INDEX"
                        and event.event_phase == MARK_INDEX_EVENT_PHASE
                        for event in candidate_hedge_events
                    )
                )
                if hedge_batch_is_safe:
                    if candidate_hedge_events:
                        batched_hedge_events = candidate_hedge_events
                        batched_hedge_virtual_times = tuple(
                            control_rules_ops.virtual_event_time_ms(
                                binding, event.event_time_ms
                            )
                            for event in candidate_hedge_events
                        )
                        hedge_batch_wave_time = planned_batch_time
                        next_hedge_virtual = planned_batch_time
                else:
                    # A rule, fee, funding, simulation, book, or exact-account
                    # barrier must retain phase ordering against the first market
                    # event.  Shrink this preflight plan before choosing wave_time.
                    shrink_final_state_plan_to_first_event()
            source_goal_reached = (
                source_goal is None
                or current_source_sequence == source_goal.target_source_sequence
            )
            if (
                current >= target_virtual_time_ms
                and source_goal_reached
                and (not next_times or min(next_times) > current)
                and (next_account_virtual is None or next_account_virtual > current)
                and (next_hedge_virtual is None or next_hedge_virtual > current)
            ):
                if pending_global_events:
                    raise TrainingRunError(
                        "GLOBAL_CHECKPOINT_INCOMPLETE",
                        "account events reached the target without a market barrier",
                        status_code=409,
                    )
                if job is not None:
                    job["status"] = "COMPLETED"
                    job["current_virtual_time_ms"] = current
                terminal_time_ms = control_rules_ops.training_terminal_time_ms(binding)
                if (
                    str(binding.get("source_kind")) == "AGG_TRADE"
                    and current >= terminal_time_ms
                    and all(
                        service_validation_ops._stored_mapping(
                            snapshot.get("cursor"), field_name="adapter cursor"
                        ).get("at_end")
                        is True
                        for _track, snapshot in snapshots
                    )
                ):
                    await self._finalize_deferred_full_tracks(
                        command=command,
                        tracks=tracks,
                    )
                if audit_account_at_barrier:
                    await self.audit_account(command.run_id)
                return stable_market_event_order(all_events)
            candidate_times = [*next_times, target_virtual_time_ms]
            if next_account_virtual is not None:
                candidate_times.append(next_account_virtual)
            if next_hedge_virtual is not None:
                candidate_times.append(next_hedge_virtual)
            wave_time = min(candidate_times)
            market_barrier = (
                wave_time == target_virtual_time_ms or wave_time in next_times
            )
            wave_events: list[StableMarketEvent] = []
            actual_wave_time = control_rules_ops.actual_event_time_ms(
                binding, wave_time
            )
            if book_required:
                wave_book = await self.historical_books.prepare_run_projection(
                    run_id=command.run_id,
                    tracks=tracks,
                    actual_time_ms=actual_wave_time,
                    virtual_time_ms=wave_time,
                )
                await self.historical_books.commit_run_projection(
                    run_id=command.run_id,
                    prepared=wave_book,
                    event_type="READY",
                )
            account_events = await self.account_history.events_at(
                run_id=command.run_id,
                tracks=tracks,
                actual_time_ms=actual_wave_time,
                guarded=True,
            )
            if not hedge_mode:
                hedge_events = ()
            elif hedge_batch_wave_time == wave_time:
                hedge_events = batched_hedge_events
            else:
                hedge_events = await self.hedge_inputs.events_at(
                    run_id=command.run_id,
                    actual_time_ms=actual_wave_time,
                    runtime_snapshot=hedge_runtime_snapshot,
                    cursor_view=hedge_cursor_view,
                )
            pre_account_events = tuple(
                item
                for item in account_events
                if item[1].event_phase == RULE_EVENT_PHASE
            )
            post_account_events = tuple(
                item
                for item in account_events
                if item[1].event_phase in {MARK_INDEX_EVENT_PHASE, FUNDING_EVENT_PHASE}
            )
            pre_hedge_events = tuple(
                item for item in hedge_events if item.event_phase == 10
            )
            post_hedge_events = tuple(
                item for item in hedge_events if item.event_phase in {30, 40}
            )
            simulation_hedge_events = tuple(
                item for item in hedge_events if item.event_phase == 70
            )
            failed_track: Mapping[str, object] = tracks[0]
            market_cohort_incomplete = False
            atomic_market_wave = False

            async def advance_market_barrier() -> None:
                nonlocal \
                    failed_track, \
                    market_cohort_incomplete, \
                    atomic_market_wave, \
                    wave_checkpointed
                if (
                    allow_final_state_batch
                    and source_goal is None
                    and self.replay_service.settings.replay_multi_bar_interval_enabled
                    and hedge_mode
                    and binding.get("source_kind") == "BAR"
                    and not book_required
                    and 2 <= len(tracks) <= 8
                    and binding.get("account_data_mode")
                    != AccountDataMode.HISTORICAL_EXACT.value
                    and isinstance(hedge_runtime_snapshot, IndexedHedgeSnapshot)
                    and wave_time == target_virtual_time_ms
                    and not wave_events
                    and all(e.event_phase == 30 for e in pending_global_events)
                    and not account_events
                    and not hedge_events
                ):
                    from .terminal_cohort import try_commit

                    terminal = await try_commit(
                        self,
                        command=command,
                        binding=binding,
                        snapshots=snapshots,
                        planned_times=planned_event_times,
                        target=wave_time,
                        pending_events=tuple(pending_global_events),
                    )
                    if terminal is not None:
                        events, wave_checkpointed = terminal
                        wave_events.extend(events)
                        atomic_market_wave = True
                        return
                for barrier_track, before in snapshots:
                    failed_track = barrier_track
                    before_cursor = before.get("cursor")
                    if not isinstance(before_cursor, Mapping):
                        raise TrainingRunError(
                            "TRAINING_RUN_STORAGE_DEGRADED",
                            "market track cursor is invalid",
                            status_code=503,
                        )
                    before_sequence = service_validation_ops._stored_counter(
                        before_cursor["source_sequence"],
                        field_name="source_sequence",
                    )
                    track_key = str(barrier_track["track_id"])
                    planned_times = planned_event_times.get(track_key, ())
                    if final_state_profile is not None:
                        event_times = tuple(t for t in planned_times if t <= wave_time)
                    else:
                        event_times = (
                            planned_times
                            if planned_times and planned_times[0] == wave_time
                            else ()
                        )
                    adapter_source_boundary = (
                        before_sequence + len(event_times)
                        if final_state_profile is not None
                        else planned_source_boundaries[track_key]
                        if event_times
                        else before_sequence
                    )
                    after = await self._advance_adapter_to(
                        session_id=service_validation_ops.track_session_id(
                            barrier_track
                        ),
                        target_virtual_time_ms=wave_time,
                        client_instance_id=command.client_instance_id,
                        command_id=command.command_id,
                        track_id=str(barrier_track["track_id"]),
                        initial_snapshot=before,
                        final_state_max_events=(
                            None
                            if final_state_profile is None
                            else final_state_profile[0]
                        ),
                        require_empty_account=(
                            False
                            if final_state_profile is None
                            else final_state_profile[1]
                        ),
                        target_source_sequence=adapter_source_boundary,
                        defer_source_terminal=(
                            str(binding.get("source_kind")) == "AGG_TRADE"
                        ),
                    )
                    after_cursor = after.get("cursor")
                    if not isinstance(after_cursor, Mapping):
                        raise TrainingRunError(
                            "TRAINING_RUN_STORAGE_DEGRADED",
                            "market track cursor is invalid",
                            status_code=503,
                        )
                    after_sequence = service_validation_ops._stored_counter(
                        after_cursor["source_sequence"],
                        field_name="source_sequence",
                    )
                    if (
                        adapter_source_boundary is not None
                        and after_sequence != adapter_source_boundary
                    ):
                        raise TrainingRunError(
                            "GLOBAL_CHECKPOINT_INCOMPLETE",
                            "market advance did not reach its exact source boundary",
                            status_code=503,
                            details={
                                "expected_source_sequence": adapter_source_boundary,
                                "actual_source_sequence": after_sequence,
                            },
                        )
                    if event_times:
                        if after_sequence - before_sequence != len(event_times):
                            raise TrainingRunError(
                                "GLOBAL_CHECKPOINT_INCOMPLETE",
                                "batched market advance did not match its source plan",
                                status_code=503,
                                details={
                                    "planned_count": len(event_times),
                                    "consumed_count": after_sequence - before_sequence,
                                },
                            )
                        wave_events.extend(
                            StableMarketEvent(
                                actual_event_time_ms=control_rules_ops.actual_event_time_ms(
                                    binding,
                                    event_time_ms,
                                ),
                                event_phase=MARKET_EVENT_PHASE,
                                market_track_stable_id=str(barrier_track["track_id"]),
                                source_sequence=before_sequence + offset,
                            )
                            for offset, event_time_ms in enumerate(
                                event_times,
                                start=1,
                            )
                        )
                    else:
                        for sequence in range(before_sequence + 1, after_sequence + 1):
                            wave_events.append(
                                StableMarketEvent(
                                    actual_event_time_ms=control_rules_ops.actual_event_time_ms(
                                        binding,
                                        wave_time,
                                    ),
                                    event_phase=MARKET_EVENT_PHASE,
                                    market_track_stable_id=str(
                                        barrier_track["track_id"]
                                    ),
                                    source_sequence=sequence,
                                )
                            )
                    continuation = await self.replay_service.plan_source_chunk(
                        service_validation_ops.track_session_id(barrier_track),
                        target_time_ms=wave_time,
                        max_events=1,
                    )
                    market_cohort_incomplete = market_cohort_incomplete or (
                        service_validation_ops._stored_counter(
                            continuation["event_count"], field_name="event_count"
                        )
                        > 0
                    )

            before_wave_state = tuple(
                (service_validation_ops.cursor_time(snapshot), sequence)
                for (_track, snapshot), sequence in zip(
                    snapshots, market_sequences, strict=True
                )
            )

            wave_checkpointed = False
            try:
                wave_events.extend(
                    await self.store.apply_account_history_events(
                        command.run_id,
                        events=pre_account_events,
                        virtual_time_ms=wave_time,
                    )
                )
                wave_events.extend(
                    await self.store.apply_hedge_input_events(
                        command.run_id,
                        events=pre_hedge_events,
                        virtual_time_ms=wave_time,
                    )
                )
                stop_at_input = event_stop is not None and any(
                    getattr(event, "event_kind", "MARK_INDEX") != "MARK_INDEX"
                    for event in (
                        *pre_hedge_events,
                        *post_hedge_events,
                        *simulation_hedge_events,
                        *pre_account_events,
                        *post_account_events,
                    )
                )
                if market_barrier or (stop_at_input and not market_cohort_incomplete):
                    await advance_market_barrier()
                    market_barrier = True
                if not market_cohort_incomplete and not atomic_market_wave:
                    supports_combined_hedge_wave = (
                        hedge_mode
                        and str(binding.get("source_kind")) == "BAR"
                        and not book_required
                        and source_goal is None
                        and not simulation_hedge_events
                        and str(binding.get("account_data_mode"))
                        != AccountDataMode.HISTORICAL_EXACT.value
                    )
                    checkpoint_hedge_wave = (
                        supports_combined_hedge_wave and market_barrier
                    )
                    combined_mark_wave = (
                        supports_combined_hedge_wave
                        and bool(post_hedge_events)
                        and all(
                            event.source_kind == "PUBLIC"
                            and event.event_kind == "MARK_INDEX"
                            and event.event_phase == 30
                            for event in post_hedge_events
                        )
                    )
                    wave_events.extend(
                        await self.store.apply_account_history_events(
                            command.run_id,
                            events=post_account_events,
                            virtual_time_ms=wave_time,
                        )
                    )
                    if combined_mark_wave:
                        (
                            applied_marks,
                            wave_checkpointed,
                        ) = await self.store.apply_hedge_inputs_and_checkpoint(
                            command.run_id,
                            input_events=post_hedge_events,
                            events=(*pending_global_events, *wave_events),
                            risk_virtual_time_ms=wave_time,
                            checkpoint_market_wave=checkpoint_hedge_wave,
                            event_virtual_times_ms=(
                                batched_hedge_virtual_times
                                if hedge_batch_wave_time == wave_time
                                else None
                            ),
                        )
                        wave_events.extend(applied_marks)
                    else:
                        wave_events.extend(
                            await self.store.apply_hedge_input_events(
                                command.run_id,
                                events=post_hedge_events,
                                virtual_time_ms=wave_time,
                                event_virtual_times_ms=(
                                    batched_hedge_virtual_times
                                    if hedge_batch_wave_time == wave_time
                                    else None
                                ),
                            )
                        )
                    if (
                        str(binding.get("account_data_mode"))
                        == AccountDataMode.HISTORICAL_EXACT.value
                    ):
                        await self.store.finalize_account_history(
                            command.run_id,
                            write_audit=False,
                            risk_virtual_time_ms=wave_time,
                        )
                    if checkpoint_hedge_wave and not combined_mark_wave:
                        wave_checkpointed = (
                            await self.store.finalize_hedge_inputs_and_checkpoint(
                                command.run_id,
                                risk_virtual_time_ms=wave_time,
                                events=(*pending_global_events, *wave_events),
                            )
                        )
                    elif not combined_mark_wave:
                        await self.store.finalize_hedge_inputs(
                            command.run_id,
                            risk_virtual_time_ms=wave_time,
                        )
                    wave_events.extend(
                        await self.store.apply_hedge_input_events(
                            command.run_id,
                            events=simulation_hedge_events,
                            virtual_time_ms=wave_time,
                        )
                    )
                pending_liquidations = (
                    ()
                    if market_cohort_incomplete or wave_checkpointed
                    else await self.store.pending_liquidations(command.run_id)
                )
                if pending_liquidations and not market_barrier:
                    # Exact account marks can trigger liquidation between two
                    # source events. Align every adapter to that precise
                    # account time before cancel/close mutations are issued.
                    await advance_market_barrier()
                    market_barrier = True
                    # Advancing an adapter refreshes its broker projection and
                    # therefore replaces any authoritative account/HEDGE mark
                    # overlay. Reapply the pinned input after alignment so the
                    # durable risk recheck and close plan use the same mark that
                    # triggered liquidation.
                    if hedge_mode:
                        await self.store.finalize_hedge_inputs(
                            command.run_id,
                            risk_virtual_time_ms=wave_time,
                        )
                    else:
                        await self.store.finalize_account_history(
                            command.run_id,
                            write_audit=False,
                            risk_virtual_time_ms=wave_time,
                        )
                    pending_liquidations = await self.store.pending_liquidations(
                        command.run_id
                    )
            except (ReplayDomainError, TrainingRunError) as exc:
                await self._fail_closed_multi_track(
                    run_id=command.run_id,
                    tracks=tracks,
                    failed_track=failed_track,
                    client_instance_id=command.client_instance_id,
                    reason=(
                        exc.code.value
                        if isinstance(exc, ReplayDomainError)
                        else exc.code
                    ),
                )
                raise TrainingRunError(
                    "MULTI_TRACK_PAUSED",
                    "a required FULL market track failed during global advance",
                    status_code=409,
                    details={"track_id": failed_track["track_id"]},
                ) from exc
            liquidations = await self._reconcile_liquidations(
                run_id=command.run_id,
                client_instance_id=command.client_instance_id,
                command_id=command.command_id,
                pending=pending_liquidations,
            )
            if wave_events:
                ordered_wave = stable_market_event_order(wave_events)
                pending_global_events.extend(ordered_wave)
                all_events.extend(ordered_wave)
                if (job is not None or stable_order_state is not None) and len(
                    all_events
                ) > control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS:
                    del all_events[: -control_rules_ops.STABLE_ORDER_RESPONSE_EVENTS]
                    if job is not None:
                        job["stable_order_truncated"] = True
                    if stable_order_state is not None:
                        stable_order_state["truncated"] = True
            if market_barrier and (
                not market_cohort_incomplete or source_goal is not None
            ):
                if wave_checkpointed:
                    pending_global_events.clear()
                elif pending_global_events:
                    await self.store.record_global_events(
                        command.run_id,
                        stable_market_event_order(pending_global_events),
                        materialize_portfolio=False,
                    )
                    pending_global_events.clear()
                else:
                    await self.store.checkpoint_market_tracks(
                        command.run_id,
                        materialize_portfolio=False,
                    )
                self._notify_market_tracks(command.run_id)
            if market_cohort_incomplete and source_goal is not None:
                reached = await self.replay_service.get_session(
                    service_validation_ops.track_session_id(tracks[0])
                )
                reached_snapshot = service_validation_ops.adapter_snapshot(reached)
                reached_cursor = service_validation_ops._stored_mapping(
                    reached_snapshot.get("cursor"), field_name="adapter cursor"
                )
                reached_sequence = service_validation_ops._stored_counter(
                    reached_cursor.get("source_sequence"),
                    field_name="source_sequence",
                )
                if reached_sequence == source_goal.target_source_sequence:
                    if job is not None:
                        job["status"] = "COMPLETED"
                        job["current_virtual_time_ms"] = wave_time
                    # This is a durable phase-20 checkpoint inside one source
                    # timestamp.  Later input phases must wait for the rest of
                    # that timestamp's market cohort in a subsequent command.
                    return stable_market_event_order(all_events)
            stop_reason: str | None = "LIQUIDATION" if liquidations else None
            if event_stop is not None and any(
                getattr(event, "event_kind", "MARK_INDEX") != "MARK_INDEX"
                for event in (
                    *pre_hedge_events,
                    *post_hedge_events,
                    *simulation_hedge_events,
                    *pre_account_events,
                    *post_account_events,
                )
            ):
                stop_reason = stop_reason or "ACCOUNT_EVENT"
            after_wave_state: list[tuple[int, int]] = []
            for track in tracks:
                after_session = await self.replay_service.get_session(
                    service_validation_ops.track_session_id(track)
                )
                after_snapshot = service_validation_ops.adapter_snapshot(after_session)
                if event_stop is not None:
                    before_snapshot = next(
                        before
                        for original, before in snapshots
                        if original["track_id"] == track["track_id"]
                    )
                    stop_reason = stop_reason or control_rules_ops.interaction_reason(
                        before_snapshot, after_snapshot
                    )
                after_cursor = service_validation_ops._stored_mapping(
                    after_snapshot.get("cursor"), field_name="adapter cursor"
                )
                after_wave_state.append(
                    (
                        service_validation_ops.cursor_time(after_snapshot),
                        service_validation_ops._stored_counter(
                            after_cursor.get("source_sequence"),
                            field_name="source_sequence",
                        ),
                    )
                )
            if tuple(after_wave_state) == before_wave_state and not wave_events:
                raise TrainingRunError(
                    "GLOBAL_ADVANCE_STALLED",
                    "global advance made no progress toward its ordered boundary",
                    status_code=409,
                    details={
                        "current_virtual_time_ms": current,
                        "target_virtual_time_ms": target_virtual_time_ms,
                        "current_source_sequence": current_source_sequence,
                        "target_source_sequence": (
                            None
                            if source_goal is None
                            else source_goal.target_source_sequence
                        ),
                    },
                )
            if job is not None:
                job["consumed"] = int(job["consumed"]) + len(wave_events)
                job["chunks"] = int(job["chunks"]) + 1
                job["current_virtual_time_ms"] = (
                    wave_time if market_barrier else current
                )
                job["queue_high_water"] = max(
                    int(job["queue_high_water"]),
                    len(tracks),
                )
            if event_stop is not None and stop_reason is not None:
                event_stop.update(reason=stop_reason, virtual_time_ms=wave_time)
                if job is not None:
                    job["status"] = "COMPLETED"
                return stable_market_event_order(all_events)
            if (
                cancel_event is not None
                and cancel_event.is_set()
                and not pending_global_events
            ):
                return await cancel_at_committed_barrier()
            await asyncio.sleep(0)
        raise TrainingRunError(
            "REPLAY_SCAN_LIMIT_EXCEEDED",
            "global advance exceeded the bounded wave budget",
            status_code=409,
        )

    def _ordered_final_state_batch_profile(
        self,
        *,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        snapshot: Mapping[str, object],
        target_virtual_time_ms: int,
        enabled: bool,
        held_certificate: bool = False,
    ) -> tuple[int, bool] | None:
        """Choose bounded terminal delivery for ordered BAR and flat tape paths."""

        if (
            not enabled
            or str(binding.get("source_kind")) not in {"BAR", "AGG_TRADE"}
            or not tracks
            or service_validation_ops.cursor_time(snapshot) >= target_virtual_time_ms
        ):
            return None
        decision = self._plan_fast_forward(
            binding=binding,
            snapshot=snapshot,
            tracks=tracks,
            target_virtual_time_ms=target_virtual_time_ms,
        )
        dependencies = set(decision.context.path_dependencies)
        allowed_dependencies = {"OPEN_ORDER", "OPEN_POSITION"}
        if len(tracks) > 1:
            allowed_dependencies.add("MULTI_TRACK_GLOBAL_ORDER")
        if str(binding.get("position_mode")) == "HEDGE":
            # A pinned funding schedule is only a potential barrier.  The
            # coordinator inspects the exact events inside each proposed chunk
            # and shrinks to one source event whenever a settlement is present.
            allowed_dependencies.add("FUNDING_SCHEDULE")
        if decision.context.blocking_reasons or not dependencies.issubset(
            allowed_dependencies
        ):
            return None
        trading_dependencies = dependencies.intersection(
            {"OPEN_ORDER", "OPEN_POSITION"}
        )
        tape = str(binding.get("source_kind")) == "AGG_TRADE"
        screened_flat_orders = (
            trading_dependencies == {"OPEN_ORDER"}
            and (
                (tape and binding.get("position_mode") == "ONE_WAY")
                or (
                    not tape
                    and len(tracks) == 1
                    and binding.get("position_mode") == "HEDGE"
                )
            )
            and binding.get("book_mode", "OFF") == "OFF"
            and binding.get("account_data_mode")
            != AccountDataMode.HISTORICAL_EXACT.value
            and control_rules_ops.snapshot_is_flat(snapshot)
        )
        if tape and (
            (trading_dependencies and not screened_flat_orders and not held_certificate)
            or not self.replay_service.settings.replay_fast_forward_optimization_enabled
        ):
            return None
        if (
            str(binding.get("account_model")) == "TOUCH_OR_TAPE_V2"
            and trading_dependencies
            and not screened_flat_orders
            and not held_certificate
        ):
            # Contract-account marks and liquidation checks still require the
            # global event barrier while any trading path is active.
            return None
        require_empty_account = not trading_dependencies
        limit = min(
            (
                control_rules_ops.FINAL_STATE_EMPTY_ACCOUNT_INTERACTIVE_BATCH_UNITS
                if require_empty_account or screened_flat_orders or held_certificate
                else control_rules_ops.ORDERED_PLAYBACK_INTERACTIVE_BATCH_UNITS
            ),
            self.replay_service.settings.event_buffer_size,
            control_rules_ops.FINAL_STATE_EMPTY_ACCOUNT_CHUNK_EVENTS,
        )
        return max(1, limit), require_empty_account

    async def _try_indexed_interval(
        self, *, command, binding, tracks, snapshot, target, runtime_snapshot
    ):
        from bisect import bisect_left, bisect_right

        if (
            len(tracks) != 1
            or binding.get("source_kind") != "BAR"
            or binding.get("position_mode") != "HEDGE"
            or binding.get("book_mode", "OFF") != "OFF"
            or binding.get("account_data_mode")
            == AccountDataMode.HISTORICAL_EXACT.value
            or binding.get("funding_mode") not in {"OFF", "HISTORICAL_EXACT"}
            or snapshot.get("state") != "PAUSED"
            or not isinstance(runtime_snapshot, IndexedHedgeSnapshot)
            or str(tracks[0]["track_id"]) != "track-1"
        ):
            return None
        base_ms = parse_interval_ms(str(binding["base_interval"]))
        if (
            base_ms is None
            or target - service_validation_ops.cursor_time(snapshot) < 64 * base_ms
        ):
            return None
        if (
            self._ordered_final_state_batch_profile(
                binding=binding,
                tracks=tracks,
                snapshot=snapshot,
                target_virtual_time_ms=target,
                enabled=True,
                held_certificate=not control_rules_ops.snapshot_is_flat(snapshot),
            )
            is None
        ):
            return None
        public, simulation = await self.hedge_inputs._projection_cursors(command.run_id)
        actual_target = control_rules_ops.actual_event_time_ms(binding, target)
        lane = None
        for current in runtime_snapshot.lanes:
            start = bisect_right(current.sequences, current.cursor(public, simulation))
            if current.source_kind != "PUBLIC" or current.track_id != "track-1":
                barrier = start
            else:
                lane = current
                at = bisect_left(current.barrier_indices, start)
                barrier = (
                    current.barrier_indices[at]
                    if at < len(current.barrier_indices)
                    else len(current.events)
                )
            if barrier < len(current.events):
                actual_target = min(actual_target, current.times[barrier] - 1)
        if lane is None:
            return None
        target = min(
            target, control_rules_ops.virtual_event_time_ms(binding, actual_target)
        )
        if target - service_validation_ops.cursor_time(snapshot) < 64 * base_ms:
            return None
        session_id = service_validation_ops.track_session_id(tracks[0])
        source = await self.replay_service.plan_source_chunk(
            session_id, target_time_ms=target, max_events=100_000, indexed=True
        )
        if not source or source["end"] - source["start"] < 64:
            return None
        index, start, end = source["index"], source["start"], source["end"]
        end_time = index.times[end - 1]
        a = bisect_right(lane.sequences, public.get("track-1", 0))
        b = bisect_right(
            lane.times, control_rules_ops.actual_event_time_ms(binding, end_time)
        )
        first, last = (lane.events[a], lane.events[b - 1]) if b > a else (None, None)
        mark = Decimal(str(snapshot["components"]["position"]["long"]["mark_price"]))
        bounds = lane.price_index.range_bounds(start=a, end=b) if b > a else None
        if bounds is not None and not control_rules_ops.snapshot_is_flat(snapshot):
            long = (
                Decimal(str(snapshot["components"]["position"]["long"]["quantity"]))
                != 0
            )
            worst = bounds[0] if long else bounds[1]
            if await self.store.indexed_review_minimum(command.run_id, worst):
                worst_at = lane.price_index.first_touch(
                    worst, below=long, start=a, end=b
                )
                worst_end = (
                    bisect_left(
                        index.times,
                        control_rules_ops.virtual_event_time_ms(
                            binding, lane.times[worst_at]
                        ),
                    )
                    + 1
                )
                if start < worst_end < end and (
                    worst_at + 1 == len(lane.times)
                    or lane.times[worst_at + 1]
                    > control_rules_ops.actual_event_time_ms(
                        binding, index.times[worst_end - 1]
                    )
                ):
                    if worst_end - start < 64:
                        return None
                    end = worst_end
                    end_time = index.times[end - 1]
                    b = bisect_right(
                        lane.times,
                        control_rules_ops.actual_event_time_ms(binding, end_time),
                    )
                    first, last = lane.events[a], lane.events[b - 1]
                    bounds = lane.price_index.range_bounds(start=a, end=b)
        low, high = (
            (mark, mark)
            if bounds is None
            else (min(mark, bounds[0]), max(mark, bounds[1]))
        )
        fingerprint = await self.store.recorded_interval_certificate(
            command.run_id,
            low=low,
            high=high,
            target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                binding, end_time
            ),
            allow_empty=True,
        )
        if fingerprint is None and control_rules_ops.snapshot_is_flat(snapshot):
            await self.store.finalize_hedge_inputs(
                command.run_id,
                risk_virtual_time_ms=service_validation_ops.cursor_time(snapshot),
            )
            fingerprint = await self.store.recorded_interval_certificate(
                command.run_id,
                low=low,
                high=high,
                target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                    binding, end_time
                ),
                allow_empty=True,
            )
        if fingerprint is None:
            baseline = await self.store.recorded_interval_certificate(
                command.run_id, low=mark, high=mark, allow_empty=True
            )
            if baseline is None:
                return None
            left, right = start, end
            while left + 1 < right:
                middle = (left + right) // 2
                mark_end = bisect_right(
                    lane.times,
                    control_rules_ops.actual_event_time_ms(
                        binding, index.times[middle - 1]
                    ),
                )
                bounds = (
                    lane.price_index.range_bounds(start=a, end=mark_end)
                    if mark_end > a
                    else None
                )
                lower, upper = (
                    (mark, mark)
                    if bounds is None
                    else (min(mark, bounds[0]), max(mark, bounds[1]))
                )
                certificate = await self.store.recorded_interval_certificate(
                    command.run_id,
                    low=lower,
                    high=upper,
                    target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                        binding, index.times[middle - 1]
                    ),
                    allow_empty=True,
                )
                if certificate is None:
                    right = middle
                else:
                    left = middle
            end = left
            if end - start < 64:
                return None
            fingerprint = baseline
            end_time = index.times[end - 1]
            b = bisect_right(
                lane.times, control_rules_ops.actual_event_time_ms(binding, end_time)
            )
            first, last = (
                (lane.events[a], lane.events[b - 1]) if b > a else (None, None)
            )
        curve_id = await self.store.prepare_indexed_curve(command.run_id, index)
        try:
            await self.replay_service.heartbeat(session_id, command.client_instance_id)
        except ReplayDomainError as exc:
            if exc.code is ReplayErrorCode.CONTROLLER_CONFLICT:
                return None
            raise
        part_id = control_rules_ops.multi_command_id(
            command.command_id, "track-1", "indexed", int(snapshot["revision"])
        )
        plan = {
            "command_id": part_id,
            "run_id": command.run_id,
            "track_id": "track-1",
            "fingerprint": fingerprint,
            "first_mark": first,
            "last_mark": last,
            "actual_delta": control_rules_ops.actual_event_time_ms(binding, end_time)
            - end_time,
            "curve_id": curve_id,
            "start": start,
            "end": end,
            "policy": binding["time_disclosure_policy"],
        }
        if session_id in self.store._recorded_interval_plans:
            raise RuntimeError("indexed interval plan already active")
        self.store._recorded_interval_plans[session_id] = plan
        try:
            await self.replay_service.command(
                session_id,
                ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=part_id,
                    client_instance_id=command.client_instance_id,
                    expected_revision=int(snapshot["revision"]),
                    type=(
                        InternalCommandType.SHARED_INDEXED_INTERVAL
                        if getattr(index, "shared", False)
                        else InternalCommandType.INDEXED_INTERVAL
                    ),
                    payload={
                        "target_virtual_time_ms": end_time,
                        "max_events": end - start,
                        "require_empty_account": False,
                        "snapshot_only": False,
                    },
                ),
                _training_internal=True,
            )
            self.store._cache_committed_hedge_fingerprint(
                command.run_id, plan["fingerprint_after"]
            )
            return plan["stable"], end_time
        finally:
            self.store._recorded_interval_plans.pop(session_id, None)

    async def _try_recorded_interval(
        self, *, command, binding, tracks, snapshot, target, runtime_snapshot
    ):
        if (
            len(tracks) != 1
            or binding.get("source_kind") != "BAR"
            or binding.get("position_mode") != "HEDGE"
            or binding.get("book_mode", "OFF") != "OFF"
            or binding.get("account_data_mode")
            == AccountDataMode.HISTORICAL_EXACT.value
            or binding.get("funding_mode") not in {"OFF", "HISTORICAL_EXACT"}
            or snapshot.get("state") != "PAUSED"
            or control_rules_ops.snapshot_is_flat(snapshot)
            or not isinstance(runtime_snapshot, IndexedHedgeSnapshot)
        ):
            return None
        if (
            self._ordered_final_state_batch_profile(
                binding=binding,
                tracks=tracks,
                snapshot=snapshot,
                target_virtual_time_ms=target,
                enabled=True,
                held_certificate=True,
            )
            is None
        ):
            return None
        track = tracks[0]
        session_id = service_validation_ops.track_session_id(track)
        maximum = min(32, self.replay_service.settings.event_buffer_size)
        if maximum < 2:
            return None
        source = await self.replay_service.plan_source_chunk(
            session_id,
            target_time_ms=target,
            max_events=maximum + 1,
            screen_interactions=True,
        )
        # Leave the last previewed event to the ordinary path, including source
        # exhaustion. A recorded block never hides terminal broker behavior.
        times = list(source["event_times_ms"][:-1])
        if len(times) < 2:
            return None
        public, simulation = await self.hedge_inputs._projection_cursors(command.run_id)
        inputs = runtime_snapshot.events_through(
            public,
            simulation,
            control_rules_ops.actual_event_time_ms(binding, times[-1]),
        )
        barriers = [
            control_rules_ops.virtual_event_time_ms(binding, e.event_time_ms)
            for e in inputs
            if e.source_kind != "PUBLIC"
            or e.event_kind != "MARK_INDEX"
            or e.event_phase != 30
            or e.track_id != track["track_id"]
        ]
        if barriers:
            times = [time for time in times if time < min(barriers)]
        if len(times) < 2:
            return None
        target_time = times[-1]
        constant = runtime_snapshot.stable_mark_prefix(
            public,
            simulation,
            str(track["track_id"]),
            control_rules_ops.actual_event_time_ms(binding, target_time),
        )
        if constant is not None and constant[
            1
        ] >= control_rules_ops.actual_event_time_ms(binding, target_time):
            return None
        inputs = tuple(
            (e, control_rules_ops.virtual_event_time_ms(binding, e.event_time_ms))
            for e in inputs
            if control_rules_ops.virtual_event_time_ms(binding, e.event_time_ms)
            <= target_time
        )
        if len(inputs) > 256:
            return None
        position = snapshot["components"]["position"]
        prices = [Decimal(str(position["long"]["mark_price"]))]
        prices.extend(Decimal(str(event.payload["mark_price"])) for event, _ in inputs)
        fingerprint = await self.store.recorded_interval_certificate(
            command.run_id,
            low=min(prices),
            high=max(prices),
            target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                binding, target_time
            ),
        )
        if fingerprint is None:
            return None
        try:
            await self.replay_service.heartbeat(session_id, command.client_instance_id)
        except ReplayDomainError as exc:
            if exc.code is ReplayErrorCode.CONTROLLER_CONFLICT:
                return None
            raise
        part_id = control_rules_ops.multi_command_id(
            command.command_id,
            str(track["track_id"]),
            "recorded",
            int(snapshot["revision"]),
        )
        plan = {
            "command_id": part_id,
            "run_id": command.run_id,
            "track_id": track["track_id"],
            "times": tuple(times),
            "inputs": inputs,
            "fingerprint": fingerprint,
            "start_sequence": snapshot["cursor"]["source_sequence"],
            "actual_delta": control_rules_ops.actual_event_time_ms(binding, target_time)
            - target_time,
        }
        if session_id in self.store._recorded_interval_plans:
            raise RuntimeError("recorded interval plan already active")
        self.store._recorded_interval_plans[session_id] = plan
        try:
            await self.replay_service.command(
                session_id,
                ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=part_id,
                    client_instance_id=command.client_instance_id,
                    expected_revision=int(snapshot["revision"]),
                    type=InternalCommandType.RECORDED_INTERVAL,
                    payload={
                        "target_virtual_time_ms": target_time,
                        "max_events": len(times),
                        "require_empty_account": False,
                        "snapshot_only": False,
                    },
                ),
                _training_internal=True,
            )
            if "stable" not in plan:
                raise RuntimeError("recorded interval did not commit its history")
            self.store._cache_committed_hedge_fingerprint(
                command.run_id, plan["fingerprint_after"]
            )
            return plan["stable"], target_time
        finally:
            self.store._recorded_interval_plans.pop(session_id, None)

    async def _held_interval_batch_end(
        self,
        run_id: str,
        *,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        snapshot: Mapping[str, object],
        target_virtual_time_ms: int,
        runtime_snapshot,
        cursor_view=None,
    ) -> int | None:
        # Price-varying marks require the original per-event position/margin
        # ledger. Only a constant authoritative mark preserves that history.
        if (
            len(tracks) != 1
            or binding.get("source_kind") != "BAR"
            or binding.get("position_mode") != "HEDGE"
            or binding.get("book_mode", "OFF") != "OFF"
            or binding.get("account_data_mode")
            == AccountDataMode.HISTORICAL_EXACT.value
            or binding.get("funding_mode") not in {"OFF", "HISTORICAL_EXACT"}
            or runtime_snapshot is None
            or control_rules_ops.snapshot_is_flat(snapshot)
        ):
            return None
        current = service_validation_ops.cursor_time(snapshot)
        prefix = await self.hedge_inputs.stable_mark_prefix(
            run_id=run_id,
            track_id=str(tracks[0]["track_id"]),
            target_actual_time_ms=control_rules_ops.actual_event_time_ms(
                binding, target_virtual_time_ms
            ),
            runtime_snapshot=runtime_snapshot,
            cursor_view=cursor_view,
        )
        if prefix is None:
            return None
        mark, end_actual = prefix
        end_virtual = control_rules_ops.virtual_event_time_ms(binding, end_actual)
        base_interval_ms = parse_interval_ms(str(binding["base_interval"]))
        if base_interval_ms is None or end_virtual - current < 2 * base_interval_ms:
            return None
        if not await self.store.held_mark_guard(
            run_id,
            track_id=str(tracks[0]["track_id"]),
            mark=mark,
            current_virtual_time_ms=current,
            target_actual_time_ms=end_actual,
        ):
            return None
        return end_virtual

    def _ordered_playback_interactive_batch_limit(
        self,
        *,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        snapshot: Mapping[str, object],
        target_virtual_time_ms: int,
    ) -> int:
        """Bound a playing account to one durable market barrier per Run lock."""

        decision = self._plan_fast_forward(
            binding=binding,
            snapshot=snapshot,
            tracks=tracks,
            target_virtual_time_ms=target_virtual_time_ms,
        )
        dependencies = set(decision.context.path_dependencies)
        if dependencies.intersection({"OPEN_ORDER", "OPEN_POSITION"}):
            return control_rules_ops.ORDERED_PLAYBACK_INTERACTIVE_BATCH_UNITS
        return 0

    async def _next_global_event_time(
        self,
        *,
        run_id: str,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
    ) -> int:
        candidates: list[int] = []
        for track in tracks:
            plan = await self.replay_service.plan_source_chunk(
                service_validation_ops.track_session_id(track),
                target_time_ms=MAX_TIMESTAMP_MS,
                max_events=1,
            )
            if service_validation_ops._stored_counter(
                plan["event_count"], field_name="event_count"
            ) == 1 and isinstance(plan["last_event_time_ms"], int):
                candidates.append(int(plan["last_event_time_ms"]))
        next_account_actual = await self.account_history.next_event_time(
            run_id=run_id,
            tracks=tracks,
            target_actual_time_ms=service_validation_ops._stored_counter(
                binding["actual_replay_end_ms"],
                field_name="actual_replay_end_ms",
            ),
        )
        if next_account_actual is not None:
            candidates.append(
                control_rules_ops.virtual_event_time_ms(binding, next_account_actual)
            )
        if str(binding.get("position_mode")) == "HEDGE":
            next_hedge_actual = await self.hedge_inputs.next_event_time(
                run_id=run_id,
                target_actual_time_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_end_ms"],
                    field_name="actual_replay_end_ms",
                ),
            )
            if next_hedge_actual is not None:
                candidates.append(
                    control_rules_ops.virtual_event_time_ms(binding, next_hedge_actual)
                )
        if not candidates and str(binding.get("source_kind")) == "AGG_TRADE":
            terminal_time_ms = control_rules_ops.training_terminal_time_ms(binding)
            snapshots = [
                service_validation_ops.adapter_snapshot(
                    await self.replay_service.get_session(
                        service_validation_ops.track_session_id(track)
                    )
                )
                for track in tracks
            ]
            if all(
                service_validation_ops._stored_mapping(
                    snapshot.get("cursor"), field_name="adapter cursor"
                ).get("at_end")
                is True
                for snapshot in snapshots
            ):
                current_times = [
                    service_validation_ops.cursor_time(snapshot)
                    for snapshot in snapshots
                ]
                if any(current < terminal_time_ms for current in current_times):
                    candidates.append(terminal_time_ms)
        if not candidates:
            raise TrainingRunError(
                "REPLAY_CONTROL_UNAVAILABLE",
                "all FULL market tracks reached the end of frozen history",
                status_code=409,
            )
        return min(candidates)

    async def _finalize_deferred_full_tracks(
        self,
        *,
        command: ReplayV2Command,
        tracks: tuple[Mapping[str, object], ...],
    ) -> None:
        """End actors only after the committed global terminal input barrier."""

        for track in tracks:
            session_id = service_validation_ops.track_session_id(track)
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            if snapshot.get("state") == "ENDED":
                continue
            cursor = service_validation_ops._stored_mapping(
                snapshot.get("cursor"), field_name="adapter cursor"
            )
            if cursor.get("at_end") is not True:
                raise TrainingRunError(
                    "GLOBAL_CHECKPOINT_INCOMPLETE",
                    "market track source is not exhausted at terminal finalize",
                    status_code=503,
                    details={"track_id": track["track_id"]},
                )
            snapshot = await self._ensure_track_controller(
                session_id=session_id,
                client_instance_id=command.client_instance_id,
                command_id=command.command_id,
                known_snapshot=snapshot,
            )
            finalize = ReplayCommand(
                protocol=REPLAY_PROTOCOL,
                command_id=control_rules_ops.multi_command_id(
                    command.command_id,
                    str(track["track_id"]),
                    InternalCommandType.FINALIZE_DEFERRED_TERMINAL.value,
                    service_validation_ops._stored_counter(
                        snapshot["revision"], field_name="revision"
                    ),
                ),
                client_instance_id=command.client_instance_id,
                expected_revision=service_validation_ops._stored_counter(
                    snapshot["revision"], field_name="revision"
                ),
                type=InternalCommandType.FINALIZE_DEFERRED_TERMINAL,
                payload={},
            )
            try:
                await self.replay_service.command(
                    session_id,
                    finalize,
                    _training_internal=True,
                )
            except ReplayDomainError as exc:
                raise TrainingRunError(
                    exc.code.value,
                    exc.message,
                    status_code=exc.http_status,
                    details=exc.details,
                ) from exc

    async def _advance_adapter_to(
        self,
        *,
        session_id: str,
        target_virtual_time_ms: int,
        client_instance_id: str,
        command_id: str,
        track_id: str,
        initial_snapshot: Mapping[str, object] | None = None,
        final_state_max_events: int | None = None,
        require_empty_account: bool = False,
        target_source_sequence: int | None = None,
        defer_source_terminal: bool = False,
    ) -> Mapping[str, object]:
        known_snapshot = initial_snapshot
        for _chunk_index in range(100_000):
            snapshot = await self._ensure_track_controller(
                session_id=session_id,
                client_instance_id=client_instance_id,
                command_id=command_id,
                known_snapshot=known_snapshot,
            )
            known_snapshot = None
            cursor = snapshot.get("cursor")
            if not isinstance(cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market track cursor is invalid",
                    status_code=503,
                )
            current = int(cursor["virtual_time_ms"])
            current_source_sequence = service_validation_ops._stored_counter(
                cursor.get("source_sequence"), field_name="source_sequence"
            )
            if (
                target_source_sequence is not None
                and current_source_sequence > target_source_sequence
            ):
                raise TrainingRunError(
                    "GLOBAL_CLOCK_DIVERGED",
                    "market track crossed the planned source-event boundary",
                    status_code=409,
                )
            terminal_final_state = (
                final_state_max_events is not None
                and cursor.get("at_end") is True
                and not defer_source_terminal
            )
            if current > target_virtual_time_ms and not terminal_final_state:
                raise TrainingRunError(
                    "GLOBAL_CLOCK_DIVERGED",
                    "market track is ahead of the TrainingRun clock",
                    status_code=409,
                )
            if terminal_final_state:
                return snapshot
            if current == target_virtual_time_ms and (
                target_source_sequence is None
                or current_source_sequence == target_source_sequence
            ):
                return snapshot
            remaining_source_events = (
                None
                if target_source_sequence is None
                else target_source_sequence - current_source_sequence
            )
            plan = await self.replay_service.plan_source_chunk(
                session_id,
                target_time_ms=target_virtual_time_ms,
                max_events=(
                    min(
                        32
                        if final_state_max_events is None
                        else final_state_max_events,
                        remaining_source_events,
                    )
                    if remaining_source_events is not None
                    and remaining_source_events > 0
                    else 32
                    if final_state_max_events is None
                    else final_state_max_events
                ),
            )
            count = service_validation_ops._stored_counter(
                plan["event_count"], field_name="event_count"
            )
            if count > 0:
                terminal_tail = defer_source_terminal and not plan.get(
                    "has_more_before_target", True
                )
                if final_state_max_events is not None and terminal_tail and count > 1:
                    count -= 1
                if final_state_max_events is None or (terminal_tail and count == 1):
                    v1_type: CommandType | InternalCommandType = (
                        InternalCommandType.STEP_DEFER_TERMINAL
                        if defer_source_terminal
                        else CommandType.STEP
                    )
                    payload: dict[str, object] = {"count": count}
                else:
                    v1_type = InternalCommandType.FAST_FORWARD_FINAL_STATE
                    payload = {
                        "target_virtual_time_ms": target_virtual_time_ms,
                        "max_events": count,
                        "require_empty_account": require_empty_account,
                        "snapshot_only": False,
                    }
            else:
                if snapshot["state"] == "ENDED":
                    raise TrainingRunError(
                        "MARKET_TRACK_COVERAGE_UNAVAILABLE",
                        "market track ended before the TrainingRun VirtualTime",
                        status_code=409,
                    )
                v1_type = CommandType.ADVANCE_BY
                payload = {"ms": min(target_virtual_time_ms - current, 30 * 86_400_000)}
            part = ReplayCommand(
                protocol=REPLAY_PROTOCOL,
                command_id=control_rules_ops.multi_command_id(
                    command_id,
                    track_id,
                    v1_type.value,
                    service_validation_ops._stored_counter(
                        snapshot["revision"], field_name="revision"
                    ),
                ),
                client_instance_id=client_instance_id,
                expected_revision=service_validation_ops._stored_counter(
                    snapshot["revision"], field_name="revision"
                ),
                type=v1_type,
                payload=payload,
            )
            try:
                acknowledged = await self.replay_service.command(
                    session_id,
                    part,
                    _training_internal=isinstance(v1_type, InternalCommandType),
                )
            except ReplayDomainError as exc:
                raise TrainingRunError(
                    exc.code.value,
                    exc.message,
                    status_code=exc.http_status,
                    details=exc.details,
                ) from exc
            acknowledged_cursor = acknowledged.get("cursor")
            if isinstance(acknowledged_cursor, Mapping):
                acknowledged_time = int(acknowledged_cursor["virtual_time_ms"])
                acknowledged_sequence = service_validation_ops._stored_counter(
                    acknowledged_cursor.get("source_sequence"),
                    field_name="source_sequence",
                )
                if acknowledged_sequence < current_source_sequence or (
                    acknowledged_sequence == current_source_sequence
                    and acknowledged_time == current
                ):
                    raise TrainingRunError(
                        "GLOBAL_ADVANCE_STALLED",
                        "market adapter made no progress toward the ordered boundary",
                        status_code=409,
                        details={
                            "current_virtual_time_ms": current,
                            "target_virtual_time_ms": target_virtual_time_ms,
                            "current_source_sequence": current_source_sequence,
                            "target_source_sequence": target_source_sequence,
                        },
                    )
                if (
                    target_source_sequence is not None
                    and acknowledged_sequence > target_source_sequence
                ):
                    raise TrainingRunError(
                        "GLOBAL_CLOCK_DIVERGED",
                        "market adapter crossed the planned source-event boundary",
                        status_code=409,
                    )
                acknowledged_at_end = acknowledged_cursor.get("at_end") is True
                if final_state_max_events is not None and acknowledged_at_end:
                    return acknowledged
                if acknowledged_time == target_virtual_time_ms and (
                    target_source_sequence is None
                    or acknowledged_sequence == target_source_sequence
                ):
                    return acknowledged
            known_snapshot = acknowledged
            await asyncio.sleep(0)
        raise TrainingRunError(
            "REPLAY_SCAN_LIMIT_EXCEEDED",
            "market track catch-up exceeded the bounded chunk budget",
            status_code=409,
        )

    async def _ensure_track_controller(
        self,
        *,
        session_id: str,
        client_instance_id: str,
        command_id: str,
        known_snapshot: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        if known_snapshot is None:
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
        else:
            snapshot = known_snapshot
        owner = snapshot.get("controller_client_id")
        if owner == client_instance_id:
            try:
                await self.replay_service.heartbeat(
                    session_id,
                    client_instance_id,
                    _renew_group=False,
                )
                return snapshot
            except ReplayDomainError as exc:
                if exc.code is not ReplayErrorCode.CONTROLLER_CONFLICT:
                    raise TrainingRunError(
                        exc.code.value,
                        exc.message,
                        status_code=exc.http_status,
                        details=exc.details,
                    ) from exc
                session = await self.replay_service.get_session(session_id)
                snapshot = service_validation_ops.adapter_snapshot(session)
                owner = snapshot.get("controller_client_id")
        if owner is not None:
            raise TrainingRunError(
                "CONTROLLER_CONFLICT",
                "market track is controlled by another client",
                status_code=409,
            )
        acquire = ReplayCommand(
            protocol=REPLAY_PROTOCOL,
            command_id=control_rules_ops.multi_command_id(
                command_id,
                session_id,
                "acquire",
                service_validation_ops._stored_counter(
                    snapshot["revision"], field_name="revision"
                ),
            ),
            client_instance_id=client_instance_id,
            expected_revision=service_validation_ops._stored_counter(
                snapshot["revision"], field_name="revision"
            ),
            type=CommandType.ACQUIRE_CONTROLLER,
            payload={"takeover": False},
        )
        try:
            return await self.replay_service.command(session_id, acquire)
        except ReplayDomainError as exc:
            raise TrainingRunError(
                exc.code.value,
                exc.message,
                status_code=exc.http_status,
                details=exc.details,
            ) from exc

    async def _pause_ready_full_tracks(
        self,
        run_id: str,
        client_instance_id: str,
    ) -> None:
        projection = await self.store.get_market_tracks(run_id)
        tracks = projection["tracks"]
        if not isinstance(tracks, list):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market tracks projection is invalid",
                status_code=503,
            )
        for track in sorted(tracks, key=lambda item: int(item["stable_ordinal"])):
            if track["subscription_tier"] != "FULL" or not track["adapter_session_id"]:
                continue
            session_id = str(track["adapter_session_id"])
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            if snapshot["state"] != "PLAYING":
                continue
            pause = ReplayCommand(
                protocol=REPLAY_PROTOCOL,
                command_id=control_rules_ops.multi_command_id(
                    "select-pause",
                    str(track["track_id"]),
                    "pause",
                    service_validation_ops._stored_counter(
                        snapshot["revision"], field_name="revision"
                    ),
                ),
                client_instance_id=client_instance_id,
                expected_revision=service_validation_ops._stored_counter(
                    snapshot["revision"], field_name="revision"
                ),
                type=CommandType.PAUSE,
                payload={},
            )
            try:
                await self.replay_service.command(session_id, pause)
            except ReplayDomainError as exc:
                raise TrainingRunError(
                    "MULTI_TRACK_PAUSED",
                    "global clock could not pause before selecting a track",
                    status_code=409,
                    details={"reason": exc.code.value},
                ) from exc

    async def _fail_closed_multi_track(
        self,
        *,
        run_id: str,
        tracks: tuple[Mapping[str, object], ...],
        failed_track: Mapping[str, object],
        client_instance_id: str,
        reason: str,
    ) -> None:
        await self.store.mark_market_track_error(
            run_id=run_id,
            track_id=str(failed_track["track_id"]),
            reason=reason,
            degraded=True,
        )
        for track in tracks:
            try:
                session_id = service_validation_ops.track_session_id(track)
                session = await self.replay_service.get_session(session_id)
                snapshot = service_validation_ops.adapter_snapshot(session)
                if snapshot["state"] != "PLAYING":
                    continue
                pause = ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=control_rules_ops.multi_command_id(
                        "fail-closed",
                        str(track["track_id"]),
                        "pause",
                        service_validation_ops._stored_counter(
                            snapshot["revision"], field_name="revision"
                        ),
                    ),
                    client_instance_id=client_instance_id,
                    expected_revision=service_validation_ops._stored_counter(
                        snapshot["revision"], field_name="revision"
                    ),
                    type=CommandType.PAUSE,
                    payload={},
                )
                await self.replay_service.command(session_id, pause)
            except (ReplayDomainError, TrainingRunError):
                continue

    async def _market_track_result(
        self,
        *,
        command: ReplayV2Command,
        session_id: str,
        snapshot: Mapping[str, object],
        data: Mapping[str, object],
    ) -> dict[str, object]:
        viewer = await self.store.get_viewer_state(command.run_id)
        return command_projection_ops.result_payload(
            command=command,
            session_id=session_id,
            snapshot=snapshot,
            viewer=viewer.to_dict(),
            data=data,
        )

    async def _reconcile_liquidations(
        self,
        *,
        run_id: str,
        client_instance_id: str,
        command_id: str,
        pending: Sequence[Mapping[str, object]] | None = None,
    ) -> int:
        pending_events = tuple(pending) if pending is not None else ()
        completed_case_ids: set[str] = set()
        for iteration in range(256):
            events = (
                pending_events
                if iteration == 0 and pending_events
                else await self.store.pending_liquidations(run_id)
            )
            if not events:
                return len(completed_case_ids)
            progressed = False
            for event in events:
                liquidation_id = str(event["liquidation_id"])
                pending_step = event.get("pending_step")
                if not isinstance(pending_step, Mapping):
                    raise TrainingRunError(
                        "LIQUIDATION_EXECUTION_FAILED",
                        "liquidation case lost its durable pending step",
                        status_code=409,
                    )
                step_sequence = service_validation_ops._stored_counter(
                    pending_step.get("step_sequence"),
                    field_name="liquidation step sequence",
                )
                step_type = str(pending_step.get("step_type"))
                plan = pending_step.get("plan")
                if not isinstance(plan, Mapping):
                    raise TrainingRunError(
                        "LIQUIDATION_EXECUTION_FAILED",
                        "liquidation step lost its immutable action plan",
                        status_code=409,
                    )
                try:
                    if step_type == "CANCEL_ORDERS":
                        canceled: list[dict[str, object]] = []
                        planned_orders = plan.get("orders")
                        if not isinstance(planned_orders, list):
                            raise TrainingRunError(
                                "LIQUIDATION_EXECUTION_FAILED",
                                "liquidation cancellation plan is invalid",
                                status_code=409,
                            )
                        track_by_id = {
                            str(track["track_id"]): track
                            for track in event.get("tracks", [])
                            if isinstance(track, Mapping)
                        }
                        for raw in planned_orders:
                            if not isinstance(raw, Mapping):
                                raise TrainingRunError(
                                    "LIQUIDATION_EXECUTION_FAILED",
                                    "liquidation cancellation target is invalid",
                                    status_code=409,
                                )
                            track_id = str(raw["track_id"])
                            order_id = str(raw["order_id"])
                            track = track_by_id.get(track_id)
                            session_id = (
                                track.get("adapter_session_id")
                                if track is not None
                                else None
                            )
                            if not isinstance(session_id, str):
                                raise TrainingRunError(
                                    "LIQUIDATION_EXECUTION_FAILED",
                                    "liquidation cancellation lost its market adapter",
                                    status_code=409,
                                )
                            await self._ensure_track_controller(
                                session_id=session_id,
                                client_instance_id=client_instance_id,
                                command_id=command_id,
                            )
                            session = await self.replay_service.get_session(session_id)
                            snapshot = service_validation_ops.adapter_snapshot(session)
                            cancel = ReplayCommand(
                                protocol=REPLAY_PROTOCOL,
                                command_id=control_rules_ops.multi_command_id(
                                    liquidation_id,
                                    track_id,
                                    f"step-{step_sequence}-cancel-{order_id}",
                                    0,
                                ),
                                client_instance_id=client_instance_id,
                                expected_revision=service_validation_ops._stored_counter(
                                    snapshot["revision"], field_name="revision"
                                ),
                                type=CommandType.CANCEL_ORDER,
                                payload={"order_id": order_id},
                            )
                            cancel = await self._resume_durable_liquidation_command(
                                session_id=session_id,
                                proposed=cancel,
                            )
                            await self.replay_service.command(session_id, cancel)
                            canceled.append(
                                {"track_id": track_id, "order_id": order_id}
                            )
                        await self.store.commit_liquidation_cancellation(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                            canceled_orders=canceled,
                        )
                    elif step_type == "RISK_RECHECK":
                        await self.store.commit_liquidation_recheck(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                        )
                    elif step_type in {"PARTIAL_LIQUIDATION", "FULL_LIQUIDATION"}:
                        session_id = plan.get("adapter_session_id")
                        if not isinstance(session_id, str):
                            raise TrainingRunError(
                                "LIQUIDATION_EXECUTION_FAILED",
                                "liquidation execution lost its market adapter",
                                status_code=409,
                            )
                        await self._ensure_track_controller(
                            session_id=session_id,
                            client_instance_id=client_instance_id,
                            command_id=command_id,
                        )
                        session = await self.replay_service.get_session(session_id)
                        snapshot = service_validation_ops.adapter_snapshot(session)
                        hedge_execution = plan.get("position_mode") == "HEDGE"
                        book_execution = plan.get("book_execution")
                        historical_book_execution = isinstance(book_execution, Mapping)
                        revealed_reference_execution = (
                            hedge_execution and not historical_book_execution
                        )
                        if (
                            plan.get("execution_model")
                            == HISTORICAL_L2_LIQUIDATION_FIDELITY
                            and not historical_book_execution
                        ):
                            raise TrainingRunError(
                                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                                "historical L2 liquidation lost its frozen execution plan",
                                status_code=409,
                            )
                        close = ReplayCommand(
                            protocol=REPLAY_PROTOCOL,
                            command_id=control_rules_ops.multi_command_id(
                                liquidation_id,
                                str(plan["track_id"]),
                                f"step-{step_sequence}-close-{plan['position_side']}",
                                0,
                            ),
                            client_instance_id=client_instance_id,
                            expected_revision=service_validation_ops._stored_counter(
                                snapshot["revision"], field_name="revision"
                            ),
                            type=(
                                InternalCommandType.EXECUTE_HISTORICAL_BOOK_CLOSE
                                if historical_book_execution
                                else (
                                    InternalCommandType.EXECUTE_REVEALED_REFERENCE_CLOSE
                                    if revealed_reference_execution
                                    else CommandType.CLOSE_POSITION
                                )
                            ),
                            payload=(
                                {
                                    "position_side": str(plan["position_side"]),
                                    "side": str(plan["side"]),
                                    "quantity": str(plan["quantity"]),
                                    "levels": list(book_execution["levels"]),
                                    "book_hash": str(book_execution["book_hash"]),
                                    "last_update_id": service_validation_ops._stored_counter(
                                        book_execution["last_update_id"],
                                        field_name="historical book last_update_id",
                                    ),
                                    "execution_fidelity": str(
                                        book_execution["execution_fidelity"]
                                    ),
                                    "queue_exact": False,
                                }
                                if historical_book_execution
                                else (
                                    {
                                        "position_side": str(plan["position_side"]),
                                        "quantity": str(plan["quantity"]),
                                        "reference_mark": str(plan["reference_mark"]),
                                        "market_slippage_bps": str(
                                            plan["market_slippage_bps"]
                                        ),
                                        "price_tick": str(plan["price_tick"]),
                                        "execution_price": str(plan["execution_price"]),
                                        "execution_fidelity": str(
                                            plan["execution_model"]
                                        ),
                                    }
                                    if revealed_reference_execution
                                    else {
                                        "quantity": str(plan["quantity"]),
                                    }
                                )
                            ),
                        )
                        close = await self._resume_durable_liquidation_command(
                            session_id=session_id,
                            proposed=close,
                        )
                        closed = await self.replay_service.command(
                            session_id,
                            close,
                            _training_internal=(
                                historical_book_execution
                                or revealed_reference_execution
                            ),
                        )
                        data = service_validation_ops._stored_mapping(
                            closed.get("data"), field_name="liquidation close data"
                        )
                        orders = data.get("orders")
                        if (
                            not isinstance(orders, list)
                            or not orders
                            or not isinstance(orders[0], Mapping)
                            or not isinstance(orders[0].get("order_id"), str)
                        ):
                            raise TrainingRunError(
                                "LIQUIDATION_EXECUTION_FAILED",
                                "liquidation close order projection is missing",
                                status_code=409,
                            )
                        await self.store.commit_liquidation_execution(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                            order_id=str(orders[0]["order_id"]),
                        )
                    elif step_type == "BANKRUPTCY_TRANSFER":
                        await self.store.commit_liquidation_bankruptcy(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                        )
                    elif step_type == "INSURANCE_FUND_SETTLEMENT":
                        await self.store.commit_liquidation_insurance(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                        )
                    elif step_type == "ADL":
                        await self.store.commit_liquidation_adl(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                        )
                    elif step_type == "COMPLETE":
                        await self.store.commit_liquidation_complete(
                            run_id=run_id,
                            liquidation_id=liquidation_id,
                            step_sequence=step_sequence,
                        )
                        completed_case_ids.add(liquidation_id)
                    elif step_type == "FAILED_CLOSED":
                        raise TrainingRunError(
                            str(
                                plan.get("failure_code", "LIQUIDATION_EXECUTION_FAILED")
                            ),
                            "liquidation continuation failed closed before a fallback execution",
                            status_code=409,
                        )
                    else:
                        raise TrainingRunError(
                            "LIQUIDATION_EXECUTION_FAILED",
                            "liquidation durable step type is unsupported",
                            status_code=409,
                            details={"step_type": step_type},
                        )
                    progressed = True
                except (
                    ReplayDomainError,
                    TrainingRunError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    failure_code = (
                        exc.code.value
                        if isinstance(exc, ReplayDomainError)
                        else exc.code
                        if isinstance(exc, TrainingRunError)
                        else type(exc).__name__
                    )
                    await self.store.fail_liquidation_case(
                        run_id=run_id,
                        liquidation_id=liquidation_id,
                        failure_code=str(failure_code),
                    )
                    raise TrainingRunError(
                        "LIQUIDATION_EXECUTION_FAILED",
                        "simulated account liquidation failed closed",
                        status_code=409,
                        details={
                            "liquidation_id": liquidation_id,
                            "reason": failure_code,
                        },
                    ) from exc
            if not progressed:
                break
        raise TrainingRunError(
            "LIQUIDATION_EXECUTION_FAILED",
            "liquidation state machine exceeded its deterministic step budget",
            status_code=409,
        )

    async def _resume_durable_liquidation_command(
        self,
        *,
        session_id: str,
        proposed: ReplayCommand,
    ) -> ReplayCommand:
        """Reuse the exact durable broker envelope after response/process loss."""

        stored = await self.replay_service.store.get_command(
            session_id,
            proposed.command_id,
        )
        if stored is None:
            return proposed
        try:
            durable = ReplayCommand.from_persisted_dict(stored.command)
        except (KeyError, TypeError, ValueError) as exc:
            raise TrainingRunError(
                "LIQUIDATION_COMMAND_EVIDENCE_INVALID",
                "durable liquidation command envelope is invalid",
                status_code=503,
            ) from exc
        proposed_payload = proposed.to_dict()
        durable_payload = durable.to_dict()
        for field in ("protocol", "command_id", "type", "payload"):
            if durable_payload[field] != proposed_payload[field]:
                raise TrainingRunError(
                    "LIQUIDATION_COMMAND_CONFLICT",
                    "durable liquidation command no longer matches its immutable plan",
                    status_code=409,
                    details={"field": field, "command_id": proposed.command_id},
                )
        return durable

    async def _activate_existing_track(
        self,
        *,
        command: ReplayV2Command,
        track: Mapping[str, object],
        target_virtual_time_ms: int,
    ) -> None:
        session_id = track.get("adapter_session_id")
        if not isinstance(session_id, str):
            raise TrainingRunError(
                "MARKET_TRACK_NOT_PREPARED",
                "market track has no frozen adapter session",
                status_code=409,
            )
        snapshot = await self._ensure_track_controller(
            session_id=session_id,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
        )
        await self._advance_adapter_to(
            session_id=session_id,
            target_virtual_time_ms=target_virtual_time_ms,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
            track_id=str(track["track_id"]),
            initial_snapshot=snapshot,
        )

    def _plan_fast_forward(
        self,
        *,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        target_virtual_time_ms: int,
        summary: ReplayPeriodSummary | None = None,
    ) -> FastForwardDecision:
        if (
            isinstance(target_virtual_time_ms, bool)
            or not isinstance(target_virtual_time_ms, int)
            or target_virtual_time_ms < 0
        ):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "fast-forward target must be a non-negative integer",
                status_code=422,
            )
        cursor = service_validation_ops._stored_mapping(
            snapshot.get("cursor"), field_name="adapter cursor"
        )
        current = service_validation_ops._stored_counter(
            cursor.get("virtual_time_ms"), field_name="virtual_time_ms"
        )
        full_tracks = tuple(
            track for track in tracks if track.get("subscription_tier") == "FULL"
        )
        dependencies: set[str] = set()
        blocking: set[str] = set()
        if len(full_tracks) > 1:
            dependencies.add("MULTI_TRACK_GLOBAL_ORDER")
        if str(binding.get("funding_mode")) != "OFF":
            dependencies.add("FUNDING_SCHEDULE")
        if (
            str(binding.get("account_data_mode"))
            == AccountDataMode.HISTORICAL_EXACT.value
        ):
            dependencies.add("ACCOUNT_HISTORY_TIMELINE")
        if str(binding.get("account_status")) != "ACTIVE":
            dependencies.add("ACCOUNT_RISK_STATE")
        if str(binding.get("book_mode", "OFF")) != "OFF":
            dependencies.add("BOOK_ASSISTED_PATH")
        if (
            snapshot.get("state") == "ERROR"
            or snapshot.get("degraded_reason") is not None
        ):
            blocking.add("SESSION_DEGRADED")
        terminal_order_states = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
        for track in full_tracks or tracks:
            if (
                track.get("state") in {"DEGRADED", "ERROR"}
                or track.get("degraded_reason") is not None
            ):
                blocking.add("TRACK_DEGRADED")
            position = track.get("position")
            if order_rules_ops._position_is_open(position):
                dependencies.add("OPEN_POSITION")
            count = track.get("open_order_count")
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                dependencies.add("OPEN_ORDER")
        components = snapshot.get("components")
        if isinstance(components, Mapping):
            orders = components.get("orders")
            if isinstance(orders, (list, tuple)) and any(
                isinstance(order, Mapping)
                and order.get("status") not in terminal_order_states
                for order in orders
            ):
                dependencies.add("OPEN_ORDER")
            position = components.get("position")
            if order_rules_ops._position_is_open(position):
                dependencies.add("OPEN_POSITION")
        optimization_enabled = bool(
            self.replay_service.settings.replay_fast_forward_optimization_enabled
        )
        optimized_candidate = optimization_enabled and not dependencies and not blocking
        chunk_event_limit = (
            min(
                4_096,
                self.replay_service.settings.event_buffer_size,
                self.replay_service.settings.trade_page_rows,
            )
            if optimized_candidate
            else min(32, self.replay_service.settings.event_buffer_size)
        )
        context = FastForwardContext(
            source_kind=ReplaySource(str(binding["source_kind"])),
            current_virtual_time_ms=current,
            target_virtual_time_ms=target_virtual_time_ms,
            dataset_epoch=str(binding["dataset_epoch"]),
            optimization_enabled=optimization_enabled,
            path_dependencies=tuple(dependencies),
            blocking_reasons=tuple(blocking),
            checkpoint_identity_match=summary is not None,
            checkpoint_state_hash=(
                summary.summary_hash if summary is not None else None
            ),
            estimated_events=(summary.event_count if summary is not None else None),
            chunk_event_limit=max(1, chunk_event_limit),
            tail_event_count=(min(32, chunk_event_limit) if optimized_candidate else 0),
            track_count=max(1, len(full_tracks)),
        )
        return self._fast_forward_planner.plan(context)
