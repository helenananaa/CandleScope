"""Fast-forward preparation and durable target-scan lifecycle.

The run facade serializes commands. This owner reuses its actor/job maps and the
existing store; it neither creates actors outside that map nor owns a writer.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Mapping
from typing import Protocol, cast

from app.replay.canonical import canonical_sha256
from app.replay.constants import REPLAY_PROTOCOL, CommandType
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.internal_commands import InternalCommandType
from app.replay.models import MAX_TIMESTAMP_MS, ReplayCommand
from app.replay.period_summary import EncodedPeriodSummaryCandidate, ReplayPeriodSummary

from . import control_rules as control_rules_ops
from . import service_validation as service_validation_ops
from .commands import ReplayV2Command
from .errors import TrainingRunError
from .fast_forward import FastForwardDecision
from .historical_book import HistoricalBookArchiveManager, HistoricalBookProjection
from .models import AccountDataMode, BookMode, FastForwardPlan, REPLAY_V2_PROTOCOL
from .multitrack import TrainingRunActor
from .storage import TrainingRunStore


class FastForwardPlanning(Protocol):
    def __call__(
        self,
        *,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        target_virtual_time_ms: int,
        summary: ReplayPeriodSummary | None = None,
    ) -> FastForwardDecision: ...


class LiquidationReconciliation(Protocol):
    def __call__(
        self, *, run_id: str, client_instance_id: str, command_id: str,
    ) -> Awaitable[int]: ...


class TrainingAdvanceService:
    """Own summary builds, scan progress, cancellation and durable completion."""

    def __init__(
        self,
        *,
        store: TrainingRunStore,
        replay_service,
        historical_books: HistoricalBookArchiveManager,
        run_actors: dict[str, TrainingRunActor],
        advance_jobs: dict[tuple[str, str], dict[str, object]],
        plan_fast_forward: FastForwardPlanning,
        reconcile_liquidations: LiquidationReconciliation,
    ) -> None:
        self.store = store
        self.replay_service = replay_service
        self.historical_books = historical_books
        self._run_actors = run_actors
        self._advance_jobs = advance_jobs
        self._plan_fast_forward = plan_fast_forward
        self._reconcile_liquidations = reconcile_liquidations
        self._period_summary_builds: set[str] = set()

    async def get_fast_forward_plan(
        self,
        run_id: str,
        *,
        target_virtual_time_ms: int,
    ) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        binding = await self.store.run_binding(normalized)
        session = await self.replay_service.get_session(
            str(binding["adapter_session_id"])
        )
        snapshot = service_validation_ops.adapter_snapshot(session)
        projection = await self.store.get_market_tracks(normalized)
        tracks = projection.get("tracks")
        if not isinstance(tracks, list):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market tracks projection is invalid",
                status_code=503,
            )
        decision = self._plan_fast_forward(
            binding=binding,
            snapshot=snapshot,
            tracks=tuple(
                cast(Mapping[str, object], track)
                for track in tracks
                if isinstance(track, Mapping)
            ),
            target_virtual_time_ms=target_virtual_time_ms,
        )
        summary_lookup: Mapping[str, object] = {
            "status": "SKIPPED",
            "reason_code": (
                "REFERENCE_OR_BLOCKED_PLAN"
                if decision.plan is not FastForwardPlan.AGGREGATE_SCAN
                else "SUMMARY_LOOKUP_NOT_RUN"
            ),
            "summary": None,
        }
        if decision.plan is FastForwardPlan.AGGREGATE_SCAN:
            summary_lookup = await self.eligible_period_summary(
                run_id=normalized,
                binding=binding,
                snapshot=snapshot,
                target_virtual_time_ms=target_virtual_time_ms,
            )
            candidate = summary_lookup.get("summary")
            if isinstance(candidate, ReplayPeriodSummary):
                decision = self._plan_fast_forward(
                    binding=binding,
                    snapshot=snapshot,
                    tracks=tuple(
                        cast(Mapping[str, object], track)
                        for track in tracks
                        if isinstance(track, Mapping)
                    ),
                    target_virtual_time_ms=target_virtual_time_ms,
                    summary=candidate,
                )
        return {
            "protocol": "replay.v3",
            "run_id": normalized,
            "plan": control_rules_ops.fast_forward_plan_payload(
                decision,
                summary_lookup=summary_lookup,
            ),
        }

    async def get_period_summary_status(self, run_id: str) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        await self.store.run_binding(normalized)
        enabled = bool(
            self.replay_service.settings.replay_fast_forward_optimization_enabled
        )
        if not enabled:
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": normalized,
                "enabled": False,
                "status": {
                    "schema_version": "replay.period-summary-set.v1",
                    "latest_build": None,
                    "active_set": None,
                    "reason_code": "OPTIMIZATION_DISABLED",
                },
            }
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "run_id": normalized,
            "enabled": True,
            "status": await self.store.period_summary_status(normalized),
        }

    async def prepare_period_summaries(
        self,
        run_id: str,
    ) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        if normalized in self._period_summary_builds:
            raise TrainingRunError(
                "PERIOD_SUMMARY_BUILD_ACTIVE",
                "a period-summary build is already active for this run",
                status_code=409,
            )
        self._period_summary_builds.add(normalized)
        try:
            return await self._prepare_period_summaries_once(normalized)
        finally:
            self._period_summary_builds.discard(normalized)

    async def _prepare_period_summaries_once(
        self,
        normalized: str,
    ) -> dict[str, object]:
        if not bool(
            self.replay_service.settings.replay_fast_forward_optimization_enabled
        ):
            raise TrainingRunError(
                "PERIOD_SUMMARY_DISABLED",
                "period-summary preparation requires the fast-forward optimization flag",
                status_code=409,
            )
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        async with actor.serialized():
            binding = await self.store.run_binding(normalized)
            session_id = str(binding["adapter_session_id"])
            session = await self.replay_service.get_session(session_id)
            snapshot = service_validation_ops.adapter_snapshot(session)
            if snapshot.get("state") != "PAUSED":
                raise TrainingRunError(
                    "PERIOD_SUMMARY_REQUIRES_PAUSE",
                    "pause the training run before preparing period summaries",
                    status_code=409,
                )
            projection = await self.store.get_market_tracks(normalized)
            raw_tracks = projection.get("tracks")
            if not isinstance(raw_tracks, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market tracks projection is invalid",
                    status_code=503,
                )
            tracks = tuple(
                cast(Mapping[str, object], track)
                for track in raw_tracks
                if isinstance(track, Mapping)
            )
            current_time = service_validation_ops.cursor_time(snapshot)
            if bool(
                service_validation_ops._stored_mapping(
                    snapshot.get("cursor"),
                    field_name="adapter cursor",
                ).get("at_end")
            ):
                raise TrainingRunError(
                    "PERIOD_SUMMARY_RANGE_UNAVAILABLE",
                    "the replay source has no future range to summarize",
                    status_code=409,
                )
            eligibility_target = min(MAX_TIMESTAMP_MS, current_time + 1)
            eligibility = self._plan_fast_forward(
                binding=binding,
                snapshot=snapshot,
                tracks=tracks,
                target_virtual_time_ms=eligibility_target,
            )
            if eligibility.plan is not FastForwardPlan.AGGREGATE_SCAN:
                raise TrainingRunError(
                    "PERIOD_SUMMARY_PATH_DEPENDENCY",
                    "the current run state is not eligible for summary preparation",
                    status_code=409,
                    details={"plan": eligibility.to_dict()},
                )
            integrity = await self.store.integrity(normalized)
            set_id = f"summary-{uuid.uuid4().hex}"
            await self.store.begin_period_summary_build(
                run_id=normalized,
                set_id=set_id,
            )
            try:
                prepared = await self.replay_service.prepare_period_summaries(
                    session_id,
                    run_id=normalized,
                    set_id=set_id,
                    rule_revision=int(integrity["active_rule_revision"]),
                    rule_hash=str(integrity["active_rule_hash"]),
                )
                candidates = prepared.get("candidates")
                metadata = prepared.get("metadata")
                if not isinstance(candidates, tuple) or not isinstance(
                    metadata, Mapping
                ):
                    raise TypeError("period-summary builder returned an invalid result")
                build = await self.store.finish_period_summary_build(
                    run_id=normalized,
                    set_id=set_id,
                    metadata=metadata,
                    build_proof_hash=str(prepared["build_proof_hash"]),
                    candidates=cast(
                        tuple[EncodedPeriodSummaryCandidate, ...],
                        candidates,
                    ),
                    source_event_count=int(prepared["source_event_count"]),
                    build_wall_ms=int(prepared["build_wall_ms"]),
                    build_cpu_ms=int(prepared["build_cpu_ms"]),
                )
            except asyncio.CancelledError:
                await asyncio.shield(
                    self.store.fail_period_summary_build(
                        run_id=normalized,
                        set_id=set_id,
                        cancelled=True,
                        error_code="PREPARATION_CANCELLED",
                        error_message="period-summary preparation was cancelled",
                    )
                )
                raise
            except BaseException as exc:
                await asyncio.shield(
                    self.store.fail_period_summary_build(
                        run_id=normalized,
                        set_id=set_id,
                        cancelled=False,
                        error_code=(
                            exc.code.value
                            if isinstance(exc, ReplayDomainError)
                            else type(exc).__name__
                        ),
                        error_message=(
                            exc.message
                            if isinstance(exc, ReplayDomainError)
                            else str(exc)
                        ),
                    )
                )
                if isinstance(exc, TrainingRunError):
                    raise
                if isinstance(exc, ReplayDomainError):
                    raise TrainingRunError(
                        exc.code.value,
                        exc.message,
                        status_code=exc.http_status,
                        details=exc.details,
                    ) from exc
                raise
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": normalized,
                "enabled": True,
                "build": build,
                "status": await self.store.period_summary_status(normalized),
            }

    async def eligible_period_summary(
        self,
        *,
        run_id: str,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        target_virtual_time_ms: int,
    ) -> Mapping[str, object]:
        if (
            str(binding.get("account_data_mode"))
            == AccountDataMode.HISTORICAL_EXACT.value
        ):
            return {
                "status": "BLOCKED",
                "reason_code": "ACCOUNT_HISTORY_TIMELINE_REFERENCE_PATH_REQUIRED",
                "summary": None,
            }
        if not bool(
            self.replay_service.settings.replay_fast_forward_optimization_enabled
        ):
            return {
                "status": "DISABLED",
                "reason_code": "OPTIMIZATION_DISABLED",
                "summary": None,
            }
        cursor = service_validation_ops._stored_mapping(snapshot.get("cursor"), field_name="adapter cursor")
        session_id = str(binding["adapter_session_id"])
        authority = await self.replay_service.summary_authority(session_id)
        if authority.get("has_active_trading_path") is True:
            return {
                "status": "INCOMPATIBLE",
                "reason_code": "ACTIVE_TRADING_PATH",
                "summary": None,
            }
        integrity = await self.store.integrity(run_id)
        lookup = await self.store.period_summary_candidate(
            run_id=run_id,
            current_source_sequence=service_validation_ops._stored_counter(
                cursor.get("source_sequence"),
                field_name="source_sequence",
            ),
            target_virtual_time_ms=target_virtual_time_ms,
            identity={
                "session_id": session_id,
                "source_kind": str(binding["source_kind"]),
                "data_epoch": str(authority["data_epoch"]),
                "snapshot_ref_hash": str(authority["snapshot_ref_hash"]),
                "session_config_hash": str(authority["session_config_hash"]),
                "execution_version": str(authority["execution_version"]),
                "rule_revision": int(integrity["active_rule_revision"]),
                "rule_hash": str(integrity["active_rule_hash"]),
            },
        )
        candidate = lookup.get("summary")
        if not isinstance(candidate, ReplayPeriodSummary):
            return lookup
        if candidate.base_domain_command_position != int(
            authority["domain_command_position"]
        ):
            return {
                "status": "INCOMPATIBLE",
                "reason_code": "SUMMARY_DOMAIN_LINEAGE_MISMATCH",
                "summary": None,
            }
        current_sequence = service_validation_ops._stored_counter(
            cursor.get("source_sequence"),
            field_name="source_sequence",
        )
        if current_sequence == candidate.base_source_sequence and (
            candidate.base_event_chain_hash != authority["event_chain_hash"]
            or candidate.base_component_state_hash != authority["component_state_hash"]
        ):
            return {
                "status": "INCOMPATIBLE",
                "reason_code": "SUMMARY_BASE_STATE_MISMATCH",
                "summary": None,
            }
        return lookup

    async def get_advance_progress(
        self,
        run_id: str,
        command_id: str,
    ) -> dict[str, object]:
        normalized_run = service_validation_ops.identifier(run_id, field_name="run_id")
        normalized_command = service_validation_ops.identifier(command_id, field_name="command_id")
        job = self._advance_jobs.get((normalized_run, normalized_command))
        if job is None:
            raise TrainingRunError(
                "ADVANCE_NOT_ACTIVE",
                "advance command is not active",
                status_code=404,
            )
        return {
            "protocol": "replay.v3",
            "run_id": normalized_run,
            "command_id": normalized_command,
            "progress": control_rules_ops.public_progress(job),
        }

    async def execute_target_scan(
        self,
        *,
        command: ReplayV2Command,
        session_id: str,
        target_virtual_time_ms: int,
        plan: Mapping[str, object],
        summary: ReplayPeriodSummary | None,
        resuming: bool = False,
    ) -> dict[str, object]:
        key = (command.run_id, command.command_id)
        if key in self._advance_jobs:
            raise TrainingRunError(
                "ADVANCE_ALREADY_ACTIVE",
                "advance command is already active",
                status_code=409,
            )
        initial_cursor = command.expected_cursor.to_dict()
        intent = await self.store.begin_advance_intent(
            run_id=command.run_id,
            command_id=command.command_id,
            command=command.to_dict(),
            session_id=session_id,
            initial_cursor=initial_cursor,
            target_virtual_time_ms=target_virtual_time_ms,
            plan=plan,
            summary=summary,
        )
        if str(intent["status"]) in {"COMPLETED", "CANCELLED"}:
            result = intent.get("result")
            if not isinstance(result, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "completed advance intent is missing its result",
                    status_code=503,
                )
            return dict(result)
        if (
            str(intent["session_id"]) != session_id
            or int(intent["target_virtual_time_ms"]) != target_virtual_time_ms
        ):
            raise TrainingRunError(
                "COMMAND_ID_REUSED",
                "durable advance identity changed",
                status_code=409,
            )
        stored_initial_cursor = service_validation_ops._stored_mapping(
            intent["initial_cursor"],
            field_name="durable initial cursor",
        )
        initial = service_validation_ops._stored_counter(
            stored_initial_cursor.get("virtual_time_ms"),
            field_name="initial_virtual_time_ms",
        )
        if target_virtual_time_ms <= initial:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "advance target must be ahead of the current cursor",
                status_code=422,
            )
        binding = await self.store.run_binding(command.run_id)
        prepared_book: tuple[tuple[str, HistoricalBookProjection], ...] = ()
        full_tracks: list[Mapping[str, object]] = []
        if (
            str(binding.get("book_mode", "OFF"))
            == BookMode.BOOK_ASSISTED_REQUIRED.value
        ):
            raw_tracks = await self.store.get_market_track_heads(command.run_id)
            full_tracks = [
                cast(Mapping[str, object], track)
                for track in raw_tracks
                if isinstance(track, Mapping)
                and track.get("subscription_tier") == "FULL"
            ]
            prepared_book = await self.historical_books.prepare_run_projection(
                run_id=command.run_id,
                tracks=full_tracks,
                actual_time_ms=control_rules_ops.actual_event_time_ms(
                    binding,
                    target_virtual_time_ms,
                ),
                virtual_time_ms=target_virtual_time_ms,
            )
        cancel = asyncio.Event()
        job: dict[str, object] = {
            "cancel": cancel,
            "client_instance_id": command.client_instance_id,
            "status": "RUNNING",
            "initial_virtual_time_ms": initial,
            "target_virtual_time_ms": target_virtual_time_ms,
            "current_virtual_time_ms": initial,
            "consumed": 0,
            "summary_skipped_events": 0,
            "tail_reducer_events": 0,
            "coalesced_projection_events": 0,
            "published_projection_events": 0,
            "batch_reducer_events": 0,
            "chunks": 0,
            "simulated_account_liquidations": 0,
            "cancelable": bool(plan.get("cancelable", False)),
            "plan": dict(plan),
            "chunk_event_limit": service_validation_ops._stored_counter(
                plan.get("chunk_event_limit", 32), field_name="chunk_event_limit"
            ),
            "queue_high_water": 0,
            "resumed_from_intent": resuming,
        }
        self._advance_jobs[key] = job
        try:
            summary_applied: ReplayPeriodSummary | None = None
            if (
                summary is not None
                and plan.get("mode") == FastForwardPlan.CHECKPOINT_JUMP.value
            ):
                current = service_validation_ops._stored_mapping(
                    await self.replay_service.get_session_state(session_id),
                    field_name="adapter snapshot",
                )
                current_cursor = service_validation_ops._stored_mapping(
                    current.get("cursor"),
                    field_name="adapter cursor",
                )
                current_sequence = service_validation_ops._stored_counter(
                    current_cursor.get("source_sequence"),
                    field_name="source_sequence",
                )
                if (
                    current_sequence < summary.end_source_sequence
                    and service_validation_ops._stored_counter(
                        current_cursor.get("virtual_time_ms"),
                        field_name="virtual_time_ms",
                    )
                    < summary.end_virtual_time_ms
                ):
                    try:
                        jumped = await self.replay_service.apply_period_summary(
                            session_id,
                            summary,
                            client_instance_id=command.client_instance_id,
                            expected_revision=service_validation_ops._stored_counter(
                                current.get("revision"),
                                field_name="revision",
                            ),
                        )
                    except ReplayDomainError as exc:
                        fallback_plan = dict(plan)
                        fallback_plan["mode"] = FastForwardPlan.AGGREGATE_SCAN.value
                        fallback_plan["plan"] = FastForwardPlan.AGGREGATE_SCAN.value
                        fallback_plan["period_summary"] = {
                            "status": "RUNTIME_REJECTED",
                            "reason_code": exc.code.value,
                            "fallback": FastForwardPlan.AGGREGATE_SCAN.value,
                        }
                        plan = fallback_plan
                        job["plan"] = fallback_plan
                    else:
                        skipped = service_validation_ops._stored_counter(
                            jumped.get("skipped_source_events"),
                            field_name="summary skipped_source_events",
                        )
                        summary_applied = summary
                        job["summary_skipped_events"] = skipped
                        job["consumed"] = skipped
                        jumped_snapshot = service_validation_ops._stored_mapping(
                            jumped.get("snapshot"),
                            field_name="summary jump snapshot",
                        )
                        jumped_cursor = service_validation_ops._stored_mapping(
                            jumped_snapshot.get("cursor"),
                            field_name="summary jump cursor",
                        )
                        job["current_virtual_time_ms"] = service_validation_ops._stored_counter(
                            jumped_cursor.get("virtual_time_ms"),
                            field_name="virtual_time_ms",
                        )
                        await self.store.update_advance_intent_cursor(
                            run_id=command.run_id,
                            command_id=command.command_id,
                            cursor=jumped_cursor,
                        )
            while True:
                if cancel.is_set():
                    job["status"] = "CANCELLED"
                    break
                current = service_validation_ops._stored_mapping(
                    await self.replay_service.get_session_state(session_id),
                    field_name="adapter snapshot",
                )
                cursor = service_validation_ops._stored_mapping(
                    current.get("cursor"), field_name="adapter cursor"
                )
                current_time = service_validation_ops._stored_counter(
                    cursor.get("virtual_time_ms"), field_name="virtual_time_ms"
                )
                job["current_virtual_time_ms"] = current_time
                if (
                    current_time >= target_virtual_time_ms
                    or current["state"] == "ENDED"
                ):
                    job["status"] = "COMPLETED"
                    break
                v1_type: CommandType | InternalCommandType
                payload: dict[str, object]
                interaction_before = (
                    service_validation_ops.adapter_snapshot(await self.replay_service.get_session(session_id))
                    if control_rules_ops.stop_on_event(command) else None
                )
                if plan.get("projection_delivery") == control_rules_ops.FINAL_STATE_PROJECTION_DELIVERY:
                    v1_type = InternalCommandType.FAST_FORWARD_FINAL_STATE
                    payload = {
                        "target_virtual_time_ms": target_virtual_time_ms,
                        "max_events": service_validation_ops._stored_counter(
                            job.get("chunk_event_limit"),
                            field_name="chunk_event_limit",
                        ),
                        "require_empty_account": (
                            plan.get("path_execution") == "EMPTY_ACCOUNT"
                        ),
                        "snapshot_only": False,
                    }
                    if interaction_before is not None and not control_rules_ops.snapshot_is_flat(interaction_before):
                        payload["max_events"] = 1
                else:
                    chunk = await self.replay_service.plan_source_chunk(
                        session_id,
                        target_time_ms=target_virtual_time_ms,
                        max_events=1 if interaction_before is not None and not control_rules_ops.snapshot_is_flat(interaction_before) else service_validation_ops._stored_counter(
                            job.get("chunk_event_limit"),
                            field_name="chunk_event_limit",
                        ),
                        screen_interactions=interaction_before is not None,
                    )
                    if cancel.is_set():
                        job["status"] = "CANCELLED"
                        break
                    count = service_validation_ops._stored_counter(
                        chunk.get("event_count"), field_name="event_count"
                    )
                    if count > 0:
                        if plan.get("mode") in {
                            FastForwardPlan.AGGREGATE_SCAN.value,
                            FastForwardPlan.CHECKPOINT_JUMP.value,
                        }:
                            v1_type = InternalCommandType.FAST_FORWARD_EMPTY_ACCOUNT
                            payload = {
                                "count": count,
                                "tail_events": min(
                                    count,
                                    service_validation_ops._stored_counter(
                                        plan.get("tail_event_count", 0),
                                        field_name="tail_event_count",
                                    ),
                                ),
                            }
                        else:
                            v1_type = CommandType.STEP
                            payload = {"count": count}
                    else:
                        # The v1 adapter bounds one duration command to 30 days.
                        duration = min(
                            target_virtual_time_ms - current_time,
                            30 * 86_400_000,
                        )
                        v1_type = CommandType.ADVANCE_BY
                        payload = {"ms": duration}
                part = ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=control_rules_ops.advance_part_id(
                        command,
                        source_sequence=service_validation_ops._stored_counter(
                            cursor.get("source_sequence"),
                            field_name="source_sequence",
                        ),
                        virtual_time_ms=current_time,
                        target_virtual_time_ms=target_virtual_time_ms,
                    ),
                    client_instance_id=command.client_instance_id,
                    expected_revision=service_validation_ops._stored_counter(
                        current.get("revision"), field_name="revision"
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
                acknowledged_data = service_validation_ops._stored_mapping(
                    acknowledged.get("data"), field_name="adapter command data"
                )
                acknowledged_cursor = service_validation_ops._stored_mapping(
                    acknowledged.get("cursor"), field_name="adapter cursor"
                )
                acknowledged_consumed = service_validation_ops._stored_counter(
                    acknowledged_data.get("consumed", 0),
                    field_name="acknowledged consumed",
                )
                acknowledged_time = service_validation_ops._stored_counter(
                    acknowledged_cursor.get("virtual_time_ms"),
                    field_name="virtual_time_ms",
                )
                if (
                    acknowledged_consumed == 0
                    and acknowledged_time <= current_time
                    and acknowledged.get("state") != "ENDED"
                ):
                    raise TrainingRunError(
                        ReplayErrorCode.DATASET_MISMATCH.value,
                        "fast-forward chunk made no cursor progress",
                        status_code=409,
                    )
                job["chunks"] = (
                    service_validation_ops._stored_counter(job.get("chunks"), field_name="chunks") + 1
                )
                job["queue_high_water"] = max(
                    service_validation_ops._stored_counter(
                        job.get("queue_high_water"), field_name="queue_high_water"
                    ),
                    1,
                )
                job["consumed"] = (
                    service_validation_ops._stored_counter(job.get("consumed"), field_name="consumed")
                    + acknowledged_consumed
                )
                job["tail_reducer_events"] = (
                    service_validation_ops._stored_counter(
                        job.get("tail_reducer_events"),
                        field_name="tail_reducer_events",
                    )
                    + acknowledged_consumed
                )
                job["coalesced_projection_events"] = service_validation_ops._stored_counter(
                    job.get("coalesced_projection_events"),
                    field_name="coalesced_projection_events",
                ) + service_validation_ops._stored_counter(
                    acknowledged_data.get("coalesced_projection_events", 0),
                    field_name="acknowledged coalesced_projection_events",
                )
                job["published_projection_events"] = service_validation_ops._stored_counter(
                    job.get("published_projection_events"),
                    field_name="published_projection_events",
                ) + service_validation_ops._stored_counter(
                    acknowledged_data.get("published_projection_events", 0),
                    field_name="acknowledged published_projection_events",
                )
                job["batch_reducer_events"] = service_validation_ops._stored_counter(
                    job.get("batch_reducer_events"),
                    field_name="batch_reducer_events",
                ) + service_validation_ops._stored_counter(
                    acknowledged_data.get("batch_reducer_events", 0),
                    field_name="acknowledged batch_reducer_events",
                )
                job["current_virtual_time_ms"] = acknowledged_time
                await self.store.update_advance_intent_cursor(
                    run_id=command.run_id,
                    command_id=command.command_id,
                    cursor=acknowledged_cursor,
                )
                job["simulated_account_liquidations"] = service_validation_ops._stored_counter(
                    job.get("simulated_account_liquidations"),
                    field_name="simulated_account_liquidations",
                ) + await self._reconcile_liquidations(
                    run_id=command.run_id,
                    client_instance_id=command.client_instance_id,
                    command_id=command.command_id,
                )
                if control_rules_ops.stop_on_event(command):
                    reached = service_validation_ops.adapter_snapshot(await self.replay_service.get_session(session_id))
                    reason = control_rules_ops.interaction_reason(interaction_before or {}, reached)
                    if reason is not None:
                        job["event_stop"] = {"reason": reason, "virtual_time_ms": acknowledged_time}
                        job["status"] = "COMPLETED"
                        break
                await asyncio.sleep(0)

            if (
                job.get("status") == "CANCELLED"
                and plan.get("projection_delivery") == control_rules_ops.FINAL_STATE_PROJECTION_DELIVERY
                and service_validation_ops._stored_counter(job.get("consumed"), field_name="consumed") > 0
            ):
                cancelled_state = service_validation_ops._stored_mapping(
                    await self.replay_service.get_session_state(session_id),
                    field_name="adapter snapshot",
                )
                cancelled_cursor = service_validation_ops._stored_mapping(
                    cancelled_state.get("cursor"),
                    field_name="adapter cursor",
                )
                cancelled_time = service_validation_ops._stored_counter(
                    cancelled_cursor.get("virtual_time_ms"),
                    field_name="virtual_time_ms",
                )
                sync = ReplayCommand(
                    protocol=REPLAY_PROTOCOL,
                    command_id=control_rules_ops.advance_part_id(
                        command,
                        source_sequence=service_validation_ops._stored_counter(
                            cancelled_cursor.get("source_sequence"),
                            field_name="source_sequence",
                        ),
                        virtual_time_ms=cancelled_time,
                        target_virtual_time_ms=cancelled_time,
                    ),
                    client_instance_id=command.client_instance_id,
                    expected_revision=service_validation_ops._stored_counter(
                        cancelled_state.get("revision"),
                        field_name="revision",
                    ),
                    type=InternalCommandType.FAST_FORWARD_FINAL_STATE,
                    payload={
                        "target_virtual_time_ms": cancelled_time,
                        "max_events": 1,
                        "require_empty_account": False,
                        "snapshot_only": True,
                    },
                )
                try:
                    synchronized = await self.replay_service.command(
                        session_id,
                        sync,
                        _training_internal=True,
                    )
                except ReplayDomainError as exc:
                    raise TrainingRunError(
                        exc.code.value,
                        exc.message,
                        status_code=exc.http_status,
                        details=exc.details,
                    ) from exc
                synchronized_cursor = service_validation_ops._stored_mapping(
                    synchronized.get("cursor"),
                    field_name="adapter cursor",
                )
                await self.store.update_advance_intent_cursor(
                    run_id=command.run_id,
                    command_id=command.command_id,
                    cursor=synchronized_cursor,
                )
                job["cancel_snapshot_published"] = True

            final_response = await self.replay_service.get_session(session_id)
            final = service_validation_ops._stored_mapping(
                final_response.get("snapshot"), field_name="adapter snapshot"
            )
            final_cursor = service_validation_ops._stored_mapping(
                final.get("cursor"), field_name="adapter cursor"
            )
            if prepared_book:
                final_virtual_time = service_validation_ops._stored_counter(
                    final_cursor.get("virtual_time_ms"), field_name="virtual_time_ms"
                )
                if final_virtual_time != target_virtual_time_ms:
                    prepared_book = await self.historical_books.prepare_run_projection(
                        run_id=command.run_id,
                        tracks=full_tracks,
                        actual_time_ms=control_rules_ops.actual_event_time_ms(
                            binding,
                            final_virtual_time,
                        ),
                        virtual_time_ms=final_virtual_time,
                    )
                await self.historical_books.commit_run_projection(
                    run_id=command.run_id,
                    prepared=prepared_book,
                )
            viewer = await self.store.get_viewer_state(command.run_id)
            resolved_plan = dict(plan)
            equivalence = resolved_plan.get("equivalence")
            if isinstance(equivalence, Mapping):
                components = final.get("components")
                component_hash = (
                    canonical_sha256(components)
                    if isinstance(components, Mapping)
                    else None
                )
                report_response = await self.replay_service.report(session_id)
                report_payload = report_response.get("report")
                report_hash = (
                    canonical_sha256(report_payload)
                    if isinstance(report_payload, Mapping)
                    else None
                )
                resolved_plan["equivalence"] = {
                    **dict(equivalence),
                    "status": (
                        "VERIFIED_BY_CHECKPOINT_SUMMARY_TAIL"
                        if summary_applied is not None
                        else (
                            "VERIFIED_BY_EXACT_REDUCER_PATH"
                            if resolved_plan.get("optimized") is True
                            else "REFERENCE_PATH"
                        )
                    ),
                    "observed_state_hash": final["state_hash"],
                    "observed_component_state_hash": component_hash,
                    "observed_report_hash": report_hash,
                    "observed_cursor": dict(final_cursor),
                    "consumed_source_events": service_validation_ops._stored_counter(
                        job.get("consumed"), field_name="consumed"
                    ),
                    "summary_skipped_events": service_validation_ops._stored_counter(
                        job.get("summary_skipped_events"),
                        field_name="summary_skipped_events",
                    ),
                    "tail_reducer_events": service_validation_ops._stored_counter(
                        job.get("tail_reducer_events"),
                        field_name="tail_reducer_events",
                    ),
                    **(
                        {
                            "summary_id": summary_applied.summary_id,
                            "summary_hash": summary_applied.summary_hash,
                            "summary_component_state_hash": (
                                summary_applied.end_component_state_hash
                            ),
                        }
                        if summary_applied is not None
                        else {}
                    ),
                }
            job["plan"] = resolved_plan
            if job.get("status") in {"COMPLETED", "CANCELLED"}:
                job["cancelable"] = False
            progress = control_rules_ops.public_progress(job)
            result = {
                "protocol": "replay.v3",
                "run_id": command.run_id,
                "session_id": session_id,
                "command_id": command.command_id,
                "revision": final["revision"],
                "sequence": final["sequence"],
                "state": final["state"],
                "state_hash": final["state_hash"],
                "cursor": final["cursor"],
                "viewer_state": viewer.to_dict(),
                "data": {
                    "consumed": service_validation_ops._stored_counter(
                        job.get("consumed"), field_name="consumed"
                    ),
                    **({"event_stop": job.get("event_stop"),
                        "target_reached": service_validation_ops.cursor_time(final) >= target_virtual_time_ms}
                       if control_rules_ops.stop_on_event(command) else {}),
                    "summary_skipped_events": service_validation_ops._stored_counter(
                        job.get("summary_skipped_events"),
                        field_name="summary_skipped_events",
                    ),
                    "tail_reducer_events": service_validation_ops._stored_counter(
                        job.get("tail_reducer_events"),
                        field_name="tail_reducer_events",
                    ),
                    "coalesced_projection_events": service_validation_ops._stored_counter(
                        job.get("coalesced_projection_events"),
                        field_name="coalesced_projection_events",
                    ),
                    "published_projection_events": service_validation_ops._stored_counter(
                        job.get("published_projection_events"),
                        field_name="published_projection_events",
                    ),
                    "batch_reducer_events": service_validation_ops._stored_counter(
                        job.get("batch_reducer_events"),
                        field_name="batch_reducer_events",
                    ),
                    "cancelled": job["status"] == "CANCELLED",
                    "target_virtual_time_ms": target_virtual_time_ms,
                    "plan": resolved_plan,
                    "progress": progress,
                    "simulated_account_liquidations": service_validation_ops._stored_counter(
                        job.get("simulated_account_liquidations"),
                        field_name="simulated_account_liquidations",
                    ),
                },
            }
            await self.store.finish_advance_intent(
                run_id=command.run_id,
                command_id=command.command_id,
                result=result,
                cancelled=job["status"] == "CANCELLED",
            )
            return result
        finally:
            if job.get("status") in {"COMPLETED", "CANCELLED"}:
                # The browser starts polling while the command response is still
                # in flight. Retain only terminal progress briefly so that race
                # returns 200 without leaving a completed job cancelable.
                job["cancelable"] = False
                asyncio.get_running_loop().call_later(
                    control_rules_ops.ADVANCE_PROGRESS_RETENTION_SECONDS,
                    self._advance_jobs.pop,
                    key,
                    None,
                )
            else:
                self._advance_jobs.pop(key, None)

    async def cancel_advance(
        self,
        command: ReplayV2Command,
        *,
        session_id: str,
    ) -> dict[str, object]:
        payload = service_validation_ops.exact_payload(command.payload, {"advance_command_id"})
        advance_command_id = payload["advance_command_id"]
        if not isinstance(advance_command_id, str):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "advance_command_id must be a string",
                status_code=422,
            )
        advance_command_id = service_validation_ops.identifier(
            advance_command_id,
            field_name="advance_command_id",
        )
        job = self._advance_jobs.get((command.run_id, advance_command_id))
        if job is None or not bool(job["cancelable"]):
            raise TrainingRunError(
                "ADVANCE_NOT_ACTIVE",
                "cancelable advance command is not active",
                status_code=404,
            )
        if job["client_instance_id"] != command.client_instance_id:
            raise TrainingRunError(
                "CONTROLLER_CONFLICT",
                "only the client that started an advance can cancel it",
                status_code=409,
            )
        cancel = job["cancel"]
        if not isinstance(cancel, asyncio.Event):
            raise RuntimeError("advance cancellation state is invalid")
        job["status"] = "CANCEL_REQUESTED"
        cancel.set()
        current_response = await self.replay_service.get_session(session_id)
        current = current_response["snapshot"]
        viewer = await self.store.get_viewer_state(command.run_id)
        return {
            "protocol": "replay.v3",
            "run_id": command.run_id,
            "session_id": session_id,
            "command_id": command.command_id,
            "revision": current["revision"],
            "sequence": current["sequence"],
            "state": current["state"],
            "state_hash": current["state_hash"],
            "cursor": current["cursor"],
            "viewer_state": viewer.to_dict(),
            "data": {
                "cancel_requested": True,
                "advance_command_id": advance_command_id,
                "progress": control_rules_ops.public_progress(job),
            },
        }
