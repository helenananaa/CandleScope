"""TrainingRun lifecycle, ViewerState, and replay.v3 control adaptation."""

from __future__ import annotations


from .ordered_playback import TrainingOrderedPlayback
from .advance_service import TrainingAdvanceService
from .review_service import TrainingReviewService

from .order_service import TrainingOrderService
from .admission_service import TrainingAdmissionService
from .display_service import TrainingDisplayService

from . import admission_rules as admission_rules_ops
from . import command_projection as command_projection_ops
from . import control_rules as control_rules_ops
from . import display_state as display_state_ops
from . import order_rules as order_rules_ops
from . import service_validation as service_validation_ops

from app.replay.training.persistence import account_marks as account_marks_ops

import asyncio
import sqlite3
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import TYPE_CHECKING, cast

from app.replay.constants import (
    REPLAY_PROTOCOL,
    CommandType,
    StartPolicy,
)
from app.replay.broker.models import TOUCH_OR_TAPE_EXECUTION_MODE
from app.replay.canonical import canonical_sha256
from app.replay.timing import collect_timings
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.internal_commands import InternalCommandType
from app.replay.models import (
    ReplayCommand,
    ReplaySessionConfig,
    normalize_decimal_string,
)
from app.replay.period_summary import (
    ReplayPeriodSummary,
)

from .errors import TrainingRunError
from .commands import ReplayV2Command
from .control import (
    MAX_CONTROL_COUNT,
    PLAYBACK_CONTRACT_VERSION,
    advance_basis,
    compatible_step_interval_ms,
    default_playback_basis,
    fixed_interval_ms,
    supported_advance_bases,
    supported_playback_bases,
)
from .account_history import (
    AccountHistoryArchiveManager,
)
from .historical_book import HistoricalBookArchiveManager
from .hedge_timeline import IndexedHedgeSnapshot
from .hedge_inputs import (
    HYBRID_PUBLIC_INPUT_FIDELITY,
    HedgeInputArchiveManager,
    PreparedHedgeInputBinding,
)
from .account import isolated_margin_key, round_to_step
from .fast_forward import FastForwardDecision, FastForwardPlanner
from .models import (
    AccountDataMode,
    AdvanceBasis,
    BookMode,
    FastForwardPlan,
    FundingMode,
    HedgePublicHistoryRef,
    HedgeSimulationManifestRef,
    IntegrityMode,
    REPLAY_V2_PROTOCOL,
    ReplaySource,
    ReplayV2CommandType,
    RunState,
    StartMode,
    SubscriptionTier,
    TrainingCursor,
    TrainingRunCreateRequest,
    TrainingRunMarketSelectionRequest,
    TrainingRunSetupRequest,
    validate_v2_counter,
)

from .multitrack import (
    GLOBAL_ORDERING_VERSION,
    StableMarketEvent,
    TrainingRunActor,
)
from .storage import TrainingRunStore
from .storage_governance import ReplayStorageGovernance
from .segments import (
    ReplaySegmentManager,
    resolve_history_policy,
)
from .trade_flow import ReplayTradeFlowAdapter

if TYPE_CHECKING:
    from app.replay.service import ReplayService


class TrainingRunService:
    """Own Hub metadata and delegate active single-track execution to replay.v1."""

    def __init__(
        self,
        *,
        replay_service: "ReplayService",
        run_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        random_seed_factory: Callable[[], int] = (lambda: uuid.uuid4().int % (1 << 53)),
        instrument_metadata_resolver: (
            Callable[[str, str, str], Mapping[str, object] | None] | None
        ) = None,
    ) -> None:
        self.replay_service = replay_service
        self.store = TrainingRunStore(replay_service.store)
        self.segments = ReplaySegmentManager(
            replay_service.store,
            download_worker_enabled=(
                replay_service.settings.replay_segment_download_worker_enabled
            ),
            auto_gc_enabled=replay_service.settings.replay_segment_auto_gc_enabled,
            max_archive_bytes=(
                replay_service.settings.replay_segment_max_archive_bytes
            ),
        )
        self.historical_books = HistoricalBookArchiveManager(
            replay_service.store,
            enabled=replay_service.settings.replay_historical_book_enabled,
            max_archive_bytes=(
                replay_service.settings.replay_historical_book_max_archive_bytes
            ),
        )
        self.account_history = AccountHistoryArchiveManager(
            replay_service.store,
            enabled=replay_service.settings.replay_account_history_enabled,
            max_archive_bytes=(
                replay_service.settings.replay_account_history_max_archive_bytes
            ),
        )
        self.hedge_inputs = HedgeInputArchiveManager(
            replay_service.store,
            indexed_event_limit=(800_000 if replay_service.settings.replay_multi_bar_interval_enabled else 200_000),
        )
        self.storage_governance = ReplayStorageGovernance(
            replay_service.store,
            settings=replay_service.settings,
            segments=self.segments,
            historical_books=self.historical_books,
            account_history=self.account_history,
            bar_repository=replay_service.history_repository,
            raw_trade_archive=replay_service.raw_trade_archive,
        )
        self._run_id_factory = run_id_factory
        self._random_seed_factory = random_seed_factory
        self._instrument_metadata_resolver = instrument_metadata_resolver
        self._fast_forward_planner = FastForwardPlanner()
        self._trade_flow_adapter = ReplayTradeFlowAdapter()
        self._advance_jobs: dict[tuple[str, str], dict[str, object]] = {}
        self._run_actors: dict[str, TrainingRunActor] = {}
        self._foreground_controls = 0
        self._last_foreground_control: float | None = None
        self._display_source_grid_anchors: dict[tuple[str, str, str, str], int] = {}
        self._native_display_pin_proofs: OrderedDict[
            display_state_ops._NativeDisplayPinProofKey,
            display_state_ops._NativeDisplayPinProof,
        ] = OrderedDict()
        self._market_track_plans: OrderedDict[str, admission_rules_ops._MarketTrackPlan] = OrderedDict()
        self._market_track_subscribers: dict[
            str,
            set[asyncio.Queue[Mapping[str, object] | None]],
        ] = {}

        self._order_service = TrainingOrderService(
            store=self.store,
            replay_service=self.replay_service,
            historical_books=self.historical_books,
            run_actors=self._run_actors,
        )
        self._admission_service = TrainingAdmissionService(
            store=self.store,
            replay_service=self.replay_service,
            account_history=self.account_history,
            historical_books=self.historical_books,
            run_id_factory=self._run_id_factory,
            random_seed_factory=self._random_seed_factory,
            instrument_metadata_resolver=self._instrument_metadata_resolver,
            market_track_plans=self._market_track_plans,
        )
        self._display_service = TrainingDisplayService(
            store=self.store,
            replay_service=self.replay_service,
            display_source_grid_anchors=self._display_source_grid_anchors,
            native_display_pin_proofs=self._native_display_pin_proofs,
        )

        self._ordered_playback = TrainingOrderedPlayback(
            store=self.store,
            replay_service=self.replay_service,
            account_history=self.account_history,
            hedge_inputs=self.hedge_inputs,
            historical_books=self.historical_books,
            run_actors=self._run_actors,
            advance_jobs=self._advance_jobs,
            fast_forward_planner=self._fast_forward_planner,
            display=self._display_service,
            notify_market_tracks=self._notify_market_tracks,
            audit_account=self.audit_account,
        )

        self._advance_service = TrainingAdvanceService(
            store=self.store,
            replay_service=self.replay_service,
            historical_books=self.historical_books,
            run_actors=self._run_actors,
            advance_jobs=self._advance_jobs,
            plan_fast_forward=self._plan_fast_forward,
            reconcile_liquidations=self._reconcile_liquidations,
        )
        self._review_service = TrainingReviewService(
            store=self.store,
            replay_service=self.replay_service,
            audit_account=self.audit_account,
            get_market_tracks=self.get_market_tracks,
        )

    def _remember_native_display_pin_proof(
        self,
        key: display_state_ops._NativeDisplayPinProofKey,
        proof: display_state_ops._NativeDisplayPinProof,
    ) -> None:
        return self._display_service._remember_native_display_pin_proof(key, proof)

    async def start(self) -> None:
        await self.store.start()
        await self.segments.start()
        await self.historical_books.start()
        await self.account_history.start()
        await self.hedge_inputs.start()

    async def shutdown(self) -> frozenset[str]:
        """Stop server-owned ordered playback before replay.v1 actors close."""

        tasks: list[asyncio.Task[None]] = []
        active_run_ids: list[str] = []
        for run_id, actor in tuple(self._run_actors.items()):
            async with actor.serialized():
                if actor.playback_snapshot()["state"] == "PLAYING":
                    active_run_ids.append(run_id)
                task = actor.request_ordered_pause(reason="SERVICE_SHUTDOWN")
                if task is not None:
                    tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        shutdown_pause_sessions: set[str] = set()
        for run_id in active_run_ids:
            projection = await self.store.get_market_tracks(run_id)
            tracks = projection.get("tracks")
            if not isinstance(tracks, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market tracks projection is invalid during shutdown",
                    status_code=503,
                )
            for track in tracks:
                if not isinstance(track, Mapping):
                    continue
                session_id = track.get("adapter_session_id")
                if track.get("subscription_tier") == "FULL" and isinstance(
                    session_id, str
                ):
                    shutdown_pause_sessions.add(session_id)
        await self.segments.shutdown()
        return frozenset(shutdown_pause_sessions)

    async def get_selection_preparation(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        normalized = self._identifier(
            preparation_id,
            field_name="preparation_id",
        )
        return {
            "protocol": "replay.v3",
            "preparation": await self.store.selection_preparation(normalized),
        }

    async def retry_selection_preparation(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        return await self._retry_selection_preparation(preparation_id)

    async def _retry_selection_preparation(
        self,
        preparation_id: str,
        *,
        existing_shell_run_id: str | None = None,
    ) -> dict[str, object]:
        normalized = self._identifier(
            preparation_id,
            field_name="preparation_id",
        )
        retry = await self.store.claim_selection_preparation_retry(normalized)
        try:
            request = TrainingRunCreateRequest.from_dict(retry["request"])
        except (TypeError, ValueError) as exc:
            await self.store.fail_selection_preparation(
                normalized,
                error_code="TRAINING_RUN_STORAGE_DEGRADED",
                error_message="training preparation retry request is invalid",
            )
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training preparation retry request is invalid",
                status_code=503,
                details={"preparation_id": normalized},
            ) from exc
        try:
            return await self.create_run(
                request,
                _retry_preparation=retry,
                _existing_shell_run_id=existing_shell_run_id,
            )
        except BaseException:
            await self.store.fail_selection_preparation(
                normalized,
                error_code="TRAINING_RUN_CREATE_FAILED",
                error_message="training preparation retry failed",
            )
            raise

    async def list_runs(
        self,
        *,
        limit: int,
        cursor: str | None,
        state: str | None,
        source_kind: str | None,
        compatibility: str | None,
    ) -> dict[str, object]:
        if compatibility is not None and compatibility not in {
            "READY",
            "UNAVAILABLE",
        }:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "compatibility filter is invalid",
                status_code=422,
            )
        if compatibility is None:
            result = await self.store.list_runs(
                limit=limit,
                cursor=cursor,
                state=state,
                source_kind=source_kind,
                compatibility=None,
            )
            catalog_cache: dict[tuple[int, int, str, bool], dict[str, object]] = {}
            admission_cache: dict[
                control_rules_ops._SetupAdmissionCacheKey,
                dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
            ] = {}
            result["items"] = [
                await self._project_awaiting_market_compatibility(
                    item,
                    catalog_cache=catalog_cache,
                    admission_cache=admission_cache,
                )
                for item in cast(list[dict[str, object]], result["items"])
            ]
            return result

        # Source-aware compatibility is a live projection for legacy empty Runs,
        # so it cannot be filtered by the persisted SQL column. Walk one opaque
        # storage row at a time and look ahead to the next projected match. The
        # returned cursor resumes immediately before that match, avoiding both
        # skipped archives and a false final cursor whose next page is empty.
        scan_cursor = cursor
        matches: list[dict[str, object]] = []
        next_cursor: str | None = None
        catalog_cache: dict[tuple[int, int, str, bool], dict[str, object]] = {}
        admission_cache: dict[
            control_rules_ops._SetupAdmissionCacheKey,
            dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
        ] = {}
        while True:
            cursor_before_row = scan_cursor
            page = await self.store.list_runs(
                limit=1,
                cursor=scan_cursor,
                state=state,
                source_kind=source_kind,
                compatibility=None,
            )
            rows = cast(list[dict[str, object]], page["items"])
            if not rows:
                break
            projected = await self._project_awaiting_market_compatibility(
                rows[0],
                catalog_cache=catalog_cache,
                admission_cache=admission_cache,
            )
            scan_cursor = cast(str | None, page["next_cursor"])
            if projected.get("compatibility") == compatibility:
                if len(matches) == limit:
                    next_cursor = cursor_before_row
                    break
                matches.append(projected)
            if scan_cursor is None:
                break
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "schema_version": "replay.training.v2",
            "items": matches,
            "next_cursor": next_cursor,
        }

    async def get_run(self, run_id: str) -> dict[str, object]:
        card = await self.store.get_run(
            self._identifier(run_id, field_name="run_id")
        )
        return await self._project_awaiting_market_compatibility(card)

    async def _project_awaiting_market_compatibility(
        self,
        card: dict[str, object],
        *,
        catalog_cache: dict[tuple[int, int, str, bool], dict[str, object]] | None = None,
        admission_cache: dict[
            control_rules_ops._SetupAdmissionCacheKey,
            dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
        ] | None = None,
    ) -> dict[str, object]:
        if card.get("state") != RunState.AWAITING_MARKET.value:
            return card
        try:
            catalog = await self.market_catalog(
                str(card["run_id"]),
                _catalog_cache=catalog_cache,
                _admission_cache=admission_cache,
            )
        except (ReplayDomainError, TrainingRunError):
            return {
                **card,
                "compatibility": "UNAVAILABLE",
                "resume_action": "UNAVAILABLE",
                "status": {
                    "code": "SOURCE_CATALOG_UNAVAILABLE",
                    "message": "该存档的历史源目录当前不可用，不能继续选择商品。",
                },
            }
        compatible = any(
            isinstance(entry.get("start_compatibility"), Mapping)
            and entry["start_compatibility"].get("state")  # type: ignore[union-attr]
            == "READY"
            for entry in cast(list[Mapping[str, object]], catalog["entries"])
        )
        if compatible:
            return card
        return {
            **card,
            "compatibility": "UNAVAILABLE",
            "resume_action": "UNAVAILABLE",
            "status": {
                "code": "NO_COMPATIBLE_SOURCE_MARKET",
                "message": "该存档的固定开始时间没有兼容历史源商品；请用合法覆盖时间新建 Run。",
            },
        }

    async def create_empty_run(
        self,
        request: TrainingRunSetupRequest,
        *,
        preparation_id: str | None = None,
        _market_identity: tuple[str, str, str] | None = None,
        _progressive_initial_horizon_ms: int | None = None,
    ) -> dict[str, object]:
        return await self._admission_service.create_empty_run(request, preparation_id=preparation_id, _market_identity=_market_identity, _progressive_initial_horizon_ms=_progressive_initial_horizon_ms)

    async def select_initial_market(
        self,
        run_id: str,
        selection: TrainingRunMarketSelectionRequest,
        *,
        _progressive_feed_id: str | None = None,
        _progressive_initial_horizon_ms: int | None = None,
    ) -> dict[str, object]:
        if not isinstance(selection, TrainingRunMarketSelectionRequest):
            raise TypeError("selection must be TrainingRunMarketSelectionRequest")
        normalized = self._identifier(run_id, field_name="run_id")
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        async with actor.serialized():
            setup = await self.store.get_run_setup(normalized)
            commitment = await self.store.get_time_commitment(normalized)
            request = setup.for_market(selection)
            if request.start_mode is StartMode.RANDOM:
                request = replace(request, random_seed=int(commitment["random_seed"]))
            else:
                request = replace(request, random_seed=None)
            await self._require_market_at_committed_start(
                selection=selection,
                setup=setup,
                commitment=commitment,
                progressive_initial_horizon_ms=_progressive_initial_horizon_ms,
            )
            preparation_id = canonical_sha256(
                {
                    "contract": "replay.initial-market-preparation.v1",
                    "run_id": normalized,
                    "selection": selection.to_dict(),
                    "time_commitment_hash": commitment["commitment_hash"],
                }
            )[7:39]
            try:
                preparation = await self.store.selection_preparation(preparation_id)
            except TrainingRunError as exc:
                if exc.code != "TRAINING_PREPARATION_NOT_FOUND":
                    raise
                result = await self.create_run(
                    request,
                    _existing_shell_run_id=normalized,
                    _preparation_id=preparation_id,
                    _committed_start_ms=int(commitment["committed_start_ms"]),
                    _progressive_feed_id=_progressive_feed_id,
                    _progressive_initial_horizon_ms=_progressive_initial_horizon_ms,
                )
            else:
                status = str(preparation.get("status"))
                if status == "FAILED":
                    result = await self._retry_selection_preparation(
                        preparation_id,
                        existing_shell_run_id=normalized,
                    )
                elif status == "PREPARING_DATA":
                    raise TrainingRunError(
                        "TRAINING_RUN_BUSY",
                        "the initial market is already being prepared",
                        status_code=409,
                        details={"preparation_id": preparation_id},
                    )
                else:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "an empty run has an already-completed market preparation",
                        status_code=503,
                        details={"preparation_id": preparation_id},
                    )
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "initialized": True,
            "run": result["run"],
        }

    async def market_catalog(
        self,
        run_id: str,
        *,
        _catalog_cache: dict[tuple[int, int, str, bool], dict[str, object]] | None = None,
        _admission_cache: dict[
            control_rules_ops._SetupAdmissionCacheKey,
            dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
        ] | None = None,
    ) -> dict[str, object]:
        return await self._admission_service.market_catalog(run_id, _catalog_cache=_catalog_cache, _admission_cache=_admission_cache)

    async def market_track_plan(
        self,
        run_id: str,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        subscription_tier: str,
    ) -> dict[str, object]:
        """Plan one authoritative MarketTrack without mutating the Run.

        The plan binds exchange metadata, account scope, the selected Run clock,
        and the requested tier.  The command path consumes only ``plan_id`` so a
        browser cannot declare a quote/settlement asset on the account's behalf.
        """
        return await self._admission_service.market_track_plan(run_id, exchange=exchange, market_type=market_type, symbol=symbol, subscription_tier=subscription_tier)

    async def initial_market_plan(
        self,
        run_id: str,
        selection: TrainingRunMarketSelectionRequest,
    ) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        setup = await self.store.get_run_setup(normalized)
        commitment = await self.store.get_time_commitment(normalized)
        await self._require_market_at_committed_start(
            selection=selection,
            setup=setup,
            commitment=commitment,
        )
        request = setup.for_market(selection)
        return await self.segment_plan(
            replace(
                request,
                start_mode=StartMode.MANUAL,
                requested_start_ms=int(commitment["committed_start_ms"]),
                random_seed=None,
            )
        )

    async def account_record_page(
        self,
        run_id: str,
        *,
        record_type: str,
        order_scope: str,
        track_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        normalized_track = (
            None
            if track_id is None
            else self._identifier(track_id, field_name="track_id")
        )
        return await self.store.account_record_page(
            normalized,
            record_type=record_type,
            order_scope=order_scope,
            track_id=normalized_track,
            cursor=cursor,
            limit=limit,
        )

    async def delete_run(self, run_id: str) -> dict[str, object]:
        """Pause, detach, and atomically remove one Hub archive."""

        normalized = self._identifier(run_id, field_name="run_id")
        # Reject missing or protected archives before publishing a run actor.
        await self.store.deletion_target(normalized)
        pause_task: asyncio.Task[None] | None = None
        actor = self._run_actors.setdefault(
            normalized,
            TrainingRunActor(normalized),
        )
        try:
            async with actor.serialized():
                kind, session_ids = await self.store.deletion_target(normalized)
                if kind == "V2":
                    pause_task = actor.request_ordered_pause(reason="DELETE_RUN")
                try:
                    if session_ids:
                        deleted_session_ids = (
                            await self.replay_service.delete_sessions_atomically(
                                session_ids,
                                lambda: self.store.delete_run(
                                    normalized,
                                    expected_session_ids=session_ids,
                                ),
                            )
                        )
                    else:
                        deleted_session_ids = await self.store.delete_run(
                            normalized,
                            expected_session_ids=(),
                        )
                except ReplayDomainError as exc:
                    if exc.http_status == 409:
                        raise TrainingRunError(
                            "TRAINING_RUN_BUSY",
                            "training run cannot be deleted while an adapter session is busy",
                            status_code=409,
                            details={
                                "reason": exc.code.value,
                                "session_id": exc.details.get("session_id"),
                            },
                        ) from exc
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "training adapter sessions could not be detached for deletion",
                        status_code=503,
                        details={"reason": exc.code.value},
                    ) from exc
                if self._run_actors.get(normalized) is actor:
                    self._run_actors.pop(normalized, None)
                for cache_key in tuple(self._display_source_grid_anchors):
                    if cache_key[0] == normalized:
                        self._display_source_grid_anchors.pop(cache_key, None)
        finally:
            if pause_task is not None:
                await asyncio.gather(pause_task, return_exceptions=True)
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "deleted": True,
            "run_id": normalized,
            "session_ids": list(deleted_session_ids),
        }

    async def segment_plan(
        self, request: TrainingRunCreateRequest
    ) -> dict[str, object]:
        if not isinstance(request, TrainingRunCreateRequest):
            raise TypeError("request must be TrainingRunCreateRequest")
        plan = await self.segments.plan_for_request(
            request,
            max_dataset_rows=self.replay_service.settings.max_bar_dataset_rows,
        )
        hedge_plan = await self._hedge_plan_with_playable_fallback(request)
        return {
            **plan,
            "historical_book": await self.historical_books.plan_for_request(request),
            "account_history": await self.account_history.plan_for_request(request),
            "hedge_inputs": hedge_plan,
        }

    async def _hedge_plan_with_playable_fallback(
        self,
        request: TrainingRunCreateRequest,
        *,
        selection: Mapping[str, object] | None = None,
        warmup_bars: int | None = None,
    ) -> dict[str, object]:
        plan = await self.hedge_inputs.plan_for_request(request)
        if (
            request.position_mode.value != "HEDGE"
            or request.book_mode is not BookMode.OFF
            or plan.get("capability_state") in {"AVAILABLE_EXACT", "AVAILABLE_APPROX"}
            or plan.get("reason") != "NO_COMPLETE_CROSS_VERIFIED_INPUT_SET"
            or request.start_mode is not StartMode.MANUAL
            or request.requested_start_ms is None
        ):
            return plan
        effective_warmup = (
            self._selection_warmup_bars(request) if warmup_bars is None else warmup_bars
        )
        config = self._adapter_config(request, warmup_bars=effective_warmup)
        bound_selection = selection
        if bound_selection is None:
            bound_selection = await self.replay_service.select_training_window(
                config,
                expected_catalog_epoch=request.catalog_epoch,
                minimum_history_bars=effective_warmup,
            )
        seed = await self.replay_service.materialize_training_hybrid_input_seed(
            config,
            bound_selection,
        )
        await self.hedge_inputs.ensure_hybrid_inputs(request, seed)
        return await self.hedge_inputs.plan_for_request(request)

    async def list_account_history_archives(self) -> dict[str, object]:
        return await self.account_history.list_archives()

    async def storage_inventory(self) -> dict[str, object]:
        return await self.storage_governance.inventory()

    async def account_history_gc_plan(
        self, *, target_reclaim_bytes: int, max_archives: int
    ) -> dict[str, object]:
        return await self.account_history.gc_plan(
            target_reclaim_bytes=target_reclaim_bytes,
            max_archives=max_archives,
        )

    async def account_history_gc_run(
        self,
        *,
        plan_hash: str,
        target_reclaim_bytes: int,
        max_archives: int,
    ) -> dict[str, object]:
        return await self.account_history.gc_run(
            plan_hash=plan_hash,
            target_reclaim_bytes=target_reclaim_bytes,
            max_archives=max_archives,
        )

    async def rehydrate_account_history_archive(
        self, archive_id: str
    ) -> dict[str, object]:
        return await self.account_history.rehydrate_archive(
            self._identifier(archive_id, field_name="archive_id")
        )

    async def audit_account(self, run_id: str) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        hedge_input_audit = await self.hedge_inputs.audit_run(normalized)
        projection = await self.store.get_market_tracks(normalized)
        portfolio = projection.get("portfolio")
        authoritative: Mapping[str, Mapping[str, object]] | None = None
        if (
            isinstance(portfolio, Mapping)
            and isinstance(portfolio.get("account_history"), Mapping)
            and portfolio["account_history"].get("mode") == "HISTORICAL_EXACT"  # type: ignore[union-attr]
        ):
            raw_tracks = projection.get("tracks")
            if not isinstance(raw_tracks, list):
                raise TypeError("exact account tracks projection is invalid")
            authoritative = await self.account_history.authoritative_projections(
                run_id=normalized,
                tracks=tuple(
                    track for track in raw_tracks if isinstance(track, Mapping)
                ),
            )
        account_audit = await self.store.audit_account(
            normalized,
            authoritative_projections=authoritative,
        )
        account_status = str(account_audit.get("status"))
        hedge_input_status = str(hedge_input_audit.get("status"))
        combined_status = (
            "PASS"
            if account_status == "PASS"
            and hedge_input_status in {"PASS", "NOT_APPLICABLE"}
            else "FAIL"
        )
        return {
            **account_audit,
            "status": combined_status,
            "account_audit_status": account_status,
            "hedge_input_audit": self._public_hedge_input_audit(hedge_input_audit),
        }

    @staticmethod
    def _requires_barrier_account_audit(binding: Mapping[str, object]) -> bool:
        return order_rules_ops.requires_barrier_account_audit(binding)

    @staticmethod
    def _public_hedge_input_audit(
        audit: Mapping[str, object],
    ) -> dict[str, object]:
        return order_rules_ops.public_hedge_input_audit(audit)

    async def list_data_segments(
        self, *, run_id: str | None = None
    ) -> dict[str, object]:
        normalized = (
            None if run_id is None else self._identifier(run_id, field_name="run_id")
        )
        redact = normalized is None
        if normalized is not None:
            integrity = await self.store.integrity(normalized)
            redact = not bool(integrity.get("revealed"))
        return await self.segments.list_segments(
            run_id=normalized,
            redact_ranges=redact,
        )

    async def list_historical_book_archives(self) -> dict[str, object]:
        return await self.historical_books.list_archives()

    async def historical_book_gc_plan(
        self, *, target_reclaim_bytes: int, max_archives: int
    ) -> dict[str, object]:
        return await self.historical_books.gc_plan(
            target_reclaim_bytes=target_reclaim_bytes,
            max_archives=max_archives,
        )

    async def historical_book_gc_run(
        self,
        *,
        plan_hash: str,
        target_reclaim_bytes: int,
        max_archives: int,
    ) -> dict[str, object]:
        return await self.historical_books.gc_run(
            plan_hash=plan_hash,
            target_reclaim_bytes=target_reclaim_bytes,
            max_archives=max_archives,
        )

    async def rehydrate_historical_book_archive(
        self, archive_id: str
    ) -> dict[str, object]:
        normalized = self._identifier(archive_id, field_name="archive_id")
        return await self.historical_books.rehydrate_archive(normalized)

    async def resync_historical_book(self, run_id: str) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        binding = await self.store.run_binding(normalized)
        if str(binding.get("book_mode")) != BookMode.BOOK_ASSISTED_REQUIRED.value:
            raise TrainingRunError(
                "HISTORICAL_BOOK_NOT_REQUIRED",
                "the TrainingRun does not use BOOK_ASSISTED_REQUIRED",
                status_code=409,
            )
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        if actor.playback_is_active():
            raise TrainingRunError(
                "HISTORICAL_BOOK_RESYNC_REQUIRES_PAUSE",
                "pause ordered playback before historical book resync",
                status_code=409,
            )
        session = await self.replay_service.get_session(
            str(binding["adapter_session_id"])
        )
        snapshot = self._snapshot(session)
        if snapshot.get("state") != "PAUSED":
            raise TrainingRunError(
                "HISTORICAL_BOOK_RESYNC_REQUIRES_PAUSE",
                "all FULL tracks must be paused before historical book resync",
                status_code=409,
            )
        cursor = service_validation_ops._stored_mapping(snapshot.get("cursor"), field_name="adapter cursor")
        virtual_time_ms = service_validation_ops._stored_counter(
            cursor.get("virtual_time_ms"), field_name="virtual_time_ms"
        )
        projection = await self.store.get_market_tracks(normalized)
        raw_tracks = projection.get("tracks")
        if not isinstance(raw_tracks, list):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market tracks projection is invalid",
                status_code=503,
            )
        tracks = [
            cast(Mapping[str, object], track)
            for track in raw_tracks
            if isinstance(track, Mapping)
        ]
        prepared = await self.historical_books.resync_run(
            run_id=normalized,
            tracks=tracks,
            actual_time_ms=self._actual_event_time_ms(binding, virtual_time_ms),
            virtual_time_ms=virtual_time_ms,
        )
        return {
            "protocol": "replay.historical-book.resync.v1",
            "run_id": normalized,
            "resynced_track_count": len(prepared),
            "fallback_applied": False,
            "tracks": (await self.store.get_market_tracks(normalized))["tracks"],
        }

    async def data_segment_gc_plan(
        self, *, target_reclaim_bytes: int, max_segments: int
    ) -> dict[str, object]:
        return await self.segments.gc_plan(
            target_reclaim_bytes=target_reclaim_bytes,
            max_segments=max_segments,
        )

    async def data_segment_gc_run(
        self,
        *,
        plan_hash: str,
        target_reclaim_bytes: int,
        max_segments: int,
    ) -> dict[str, object]:
        return await self.segments.gc_run(
            plan_hash=plan_hash,
            target_reclaim_bytes=target_reclaim_bytes,
            max_segments=max_segments,
        )

    async def get_viewer_state(self, run_id: str) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        return (await self.store.get_viewer_state(normalized)).to_dict()

    async def get_viewer_state_by_session(self, session_id: str) -> dict[str, object]:
        run_id = await self.store.run_id_for_session(
            self._identifier(session_id, field_name="session_id")
        )
        return (await self.store.get_viewer_state(run_id)).to_dict()

    async def get_market_tracks(self, run_id: str) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        projection = await self.store.get_market_tracks(normalized)
        return await self._with_global_clock(normalized, projection)

    async def get_live_market_tracks(self, run_id: str) -> dict[str, object]:
        """Return the bounded UI projection; audit history remains REST-only."""

        normalized = self._identifier(run_id, field_name="run_id")
        projection = await self.store.get_market_tracks(
            normalized,
            live_portfolio=True,
        )
        return await self._with_global_clock(normalized, projection)

    async def subscribe_market_tracks(
        self,
        run_id: str,
        *,
        live: bool = False,
    ) -> tuple[dict[str, object], asyncio.Queue[Mapping[str, object] | None]]:
        """Atomically attach a coalescing Run projection subscriber.

        Registration happens before the requested initial read. A concurrent
        commit can therefore only cause one harmless follow-up snapshot; it
        cannot create a gap between the initial projection and the live tail.
        """

        normalized = self._identifier(run_id, field_name="run_id")
        queue: asyncio.Queue[Mapping[str, object] | None] = asyncio.Queue(maxsize=1)
        subscribers = self._market_track_subscribers.setdefault(normalized, set())
        subscribers.add(queue)
        try:
            projection = await (
                self.get_live_market_tracks(normalized)
                if live
                else self.get_market_tracks(normalized)
            )
        except BaseException:
            self.unsubscribe_market_tracks(normalized, queue)
            raise
        return projection, queue

    def unsubscribe_market_tracks(
        self,
        run_id: str,
        queue: asyncio.Queue[Mapping[str, object] | None],
    ) -> None:
        subscribers = self._market_track_subscribers.get(run_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._market_track_subscribers.pop(run_id, None)

    def _notify_market_tracks(self, run_id: str, projection: Mapping[str, object] | None = None) -> None:
        # A command may already have built this committed live projection for
        # its acknowledgement. Detach it once for stream consumers; callers
        # remain free to mutate their returned response.
        from copy import deepcopy
        queued_projection = deepcopy(projection) if projection is not None else None
        for queue in tuple(self._market_track_subscribers.get(run_id, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(queued_projection)

    async def preview_order(
        self,
        run_id: str,
        *,
        expected_revision: int,
        expected_cursor: TrainingCursor,
        position_intent: str,
        order: Mapping[str, object],
        trade_plan: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Return a non-mutating order preview bound to one authoritative cursor."""
        return await self._order_service.preview_order(run_id, expected_revision=expected_revision, expected_cursor=expected_cursor, position_intent=position_intent, order=order, trade_plan=trade_plan)

    async def order_capacity(
        self,
        run_id: str,
        *,
        expected_revision: int,
        expected_cursor: TrainingCursor,
        position_intent: str,
        context: Mapping[str, object],
    ) -> dict[str, object]:
        """Return a cursor-bound maximum without validating a draft quantity."""
        return await self._order_service.order_capacity(run_id, expected_revision=expected_revision, expected_cursor=expected_cursor, position_intent=position_intent, context=context)

    async def get_fast_forward_plan(
        self,
        run_id: str,
        *,
        target_virtual_time_ms: int,
    ) -> dict[str, object]:
        return await self._advance_service.get_fast_forward_plan(
            run_id,
            target_virtual_time_ms=target_virtual_time_ms,
        )

    async def get_period_summary_status(self, run_id: str) -> dict[str, object]:
        return await self._advance_service.get_period_summary_status(run_id)

    async def prepare_period_summaries(
        self,
        run_id: str,
    ) -> dict[str, object]:
        return await self._advance_service.prepare_period_summaries(run_id)

    async def trade_flow_page(
        self,
        run_id: str,
        *,
        track_id: str | None,
        after_sequence: int | None,
        limit: int,
    ) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1_000
        ):
            raise TrainingRunError(
                "REPLAY_TRADE_FLOW_INVALID",
                "trade-flow limit must be between 1 and 1000",
                status_code=422,
            )
        binding = await self.store.run_binding(normalized)
        if str(binding["source_kind"]) != "AGG_TRADE":
            raise TrainingRunError(
                "REPLAY_TRADE_FLOW_UNSUPPORTED_SOURCE",
                "BAR runs cannot expose aggregate-trade tape or exact order flow",
                status_code=409,
                details={
                    "tape": "UNSUPPORTED_SOURCE_MODE",
                    "order_flow": "UNSUPPORTED_SOURCE_MODE",
                },
            )
        selected_track_id = (
            str(binding["selected_track_id"])
            if track_id is None
            else self._identifier(track_id, field_name="track_id")
        )
        track = await self.store.get_market_track(normalized, selected_track_id)
        if (
            track.get("state") in {"DEGRADED", "ERROR"}
            or track.get("degraded_reason") is not None
        ):
            raise TrainingRunError(
                "REPLAY_TRADE_FLOW_DEGRADED",
                "market track continuity is degraded; clear tape and resync",
                status_code=409,
                details={"clear_projection": True, "track_id": selected_track_id},
            )
        session_id = self._track_session_id(track)
        session = await self.replay_service.get_session(session_id)
        snapshot = self._snapshot(session)
        cursor = service_validation_ops._stored_mapping(snapshot.get("cursor"), field_name="adapter cursor")
        revealed_sequence = service_validation_ops._stored_counter(
            cursor.get("source_sequence"), field_name="source_sequence"
        )
        bounded_limit = min(limit, self.replay_service.settings.trade_page_rows)
        if after_sequence is None:
            after = max(0, revealed_sequence - bounded_limit)
        else:
            after = service_validation_ops._stored_counter(after_sequence, field_name="after_sequence")
        if after > revealed_sequence:
            raise TrainingRunError(
                "REPLAY_TRADE_FLOW_RESYNC_REQUIRED",
                "trade-flow cursor is ahead of the revealed replay prefix",
                status_code=409,
                details={
                    "clear_projection": True,
                    "revealed_sequence": revealed_sequence,
                },
            )
        try:
            page = await self.replay_service.source_events_page(
                session_id,
                after_sequence=after,
                limit=bounded_limit,
            )
        except ReplayDomainError as exc:
            raise TrainingRunError(
                "REPLAY_TRADE_FLOW_DEGRADED",
                "aggregate-trade page failed continuity validation",
                status_code=409,
                details={
                    "clear_projection": True,
                    "reason": exc.code.value,
                    "track_id": selected_track_id,
                },
            ) from exc
        return self._trade_flow_adapter.project(
            run_id=normalized,
            track_id=selected_track_id,
            source_page=page,
        )

    async def get_market_tracks_by_session(
        self,
        session_id: str,
    ) -> dict[str, object]:
        normalized = self._identifier(session_id, field_name="session_id")
        run_id = await self.store.run_id_for_session(normalized)
        projection = await self.store.get_market_tracks(run_id)
        return await self._with_global_clock(run_id, projection)

    async def _with_global_clock(
        self,
        run_id: str,
        projection: Mapping[str, object],
    ) -> dict[str, object]:
        tracks = projection.get("tracks")
        viewer = projection.get("viewer_state")
        if not isinstance(tracks, list) or not isinstance(viewer, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market tracks projection is invalid",
                status_code=503,
            )
        selected_track_id = viewer.get("selected_track_id")
        if selected_track_id is None and not tracks:
            return {
                **dict(projection),
                "global_clock": None,
            }
        selected = next(
            (
                track
                for track in tracks
                if isinstance(track, Mapping)
                and track.get("track_id") == selected_track_id
            ),
            None,
        )
        if not isinstance(selected, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "selected market track is unavailable",
                status_code=503,
            )
        selected_session_id = selected.get("adapter_session_id")
        if not isinstance(selected_session_id, str):
            raise TrainingRunError(
                "MARKET_TRACK_NOT_PREPARED",
                "selected market track has no frozen adapter session",
                status_code=409,
            )
        selected_snapshot = await self.replay_service.get_session_state(
            selected_session_id, include_config=True
        )
        selected_config = service_validation_ops._stored_mapping(
            selected_snapshot.get("config"),
            field_name="selected adapter config",
        )
        source_kind = str(selected.get("source_kind"))
        base_interval = str(selected_config.get("base_interval"))
        full_count = sum(
            1
            for track in tracks
            if isinstance(track, Mapping) and track.get("subscription_tier") == "FULL"
        )
        portfolio = projection.get("portfolio")
        contract_clock = (
            isinstance(portfolio, Mapping)
            and portfolio.get("account_model") == "TOUCH_OR_TAPE_V2"
        )
        actor = self._run_actors.get(run_id)
        actor_clock: dict[str, object] | None = None
        if actor is not None:
            actor_clock = actor.playback_snapshot()
            if (
                actor_clock["state"] == "PLAYING"
                and service_validation_ops._stored_mapping(
                    selected_snapshot.get("cursor"),
                    field_name="selected adapter cursor",
                ).get("at_end")
                is not True
                and selected_snapshot.get("controller_client_id")
                != actor.playback_client_id
            ):
                actor.request_ordered_pause(reason="CONTROLLER_LEASE_LOST")
                actor_clock = actor.playback_snapshot()
        actor_generation = (
            service_validation_ops._stored_counter(
                actor_clock.get("generation", 0), field_name="global_clock.generation"
            )
            if actor_clock is not None
            else 0
        )
        actor_tick = (
            service_validation_ops._stored_counter(actor_clock.get("tick", 0), field_name="global_clock.tick")
            if actor_clock is not None
            else 0
        )
        actor_profile_revision = (
            service_validation_ops._stored_counter(
                actor_clock.get("profile_revision", 0),
                field_name="global_clock.profile_revision",
            )
            if actor_clock is not None
            else 0
        )
        preserve_actor_terminal = (
            actor_clock is not None
            and (actor_generation > 0 or actor_profile_revision > 0)
            and (
                actor_clock.get("state") in {"PLAYING", "PAUSED", "ENDED", "ERROR"}
                or actor_clock.get("reason") == "CONTROLLER_LEASE_LOST"
            )
        )
        if (
            (contract_clock or full_count > 1)
            and preserve_actor_terminal
            and actor_clock is not None
        ):
            global_clock = dict(actor_clock)
        else:
            adapter_speed = selected_snapshot["speed"]
            rate = (
                int(adapter_speed)
                if isinstance(adapter_speed, int)
                and not isinstance(adapter_speed, bool)
                else 1
            )
            global_clock = {
                "contract": PLAYBACK_CONTRACT_VERSION,
                "mode": "ORDERED" if contract_clock or full_count > 1 else "ADAPTER",
                "state": selected_snapshot["state"],
                "basis": default_playback_basis(source_kind).value,
                "rate": rate,
                "speed": rate,
                "display_interval": None,
                "viewer_revision": None,
                "profile_revision": actor_profile_revision,
                "reason": None,
                "generation": actor_generation,
                "tick": actor_tick,
            }
        supported = supported_advance_bases(
            source_kind=source_kind,
            full_track_count=full_count,
        )
        playback_supported = supported_playback_bases(
            source_kind=source_kind,
            full_track_count=full_count,
        )
        effective_basis = advance_basis(global_clock.get("basis"))
        if effective_basis not in playback_supported:
            effective_basis = default_playback_basis(source_kind)
            global_clock["basis"] = effective_basis.value
            global_clock["display_interval"] = None
            global_clock["viewer_revision"] = None
        global_clock.update(
            {
                "contract": PLAYBACK_CONTRACT_VERSION,
                "supported_bases": [basis.value for basis in supported],
                "playback_bases": [basis.value for basis in playback_supported],
                "max_count": MAX_CONTROL_COUNT,
                "virtual_time_quantum_ms": (
                    fixed_interval_ms(
                        base_interval,
                        field_name="base_interval",
                    )
                    if source_kind == "BAR"
                    else 1
                ),
            }
        )
        return {**dict(projection), "global_clock": global_clock}

    async def integrity(self, run_id: str) -> dict[str, object]:
        return await self._review_service.integrity(run_id)

    async def rules(self, run_id: str) -> dict[str, object]:
        return await self._review_service.rules(run_id)

    async def current_drawing_document(self, run_id: str) -> dict[str, object]:
        return await self._review_service.current_drawing_document(run_id)

    async def record_drawing_document(
        self,
        run_id: str,
        *,
        command_id: str,
        document_hash: str,
        document: Mapping[str, object],
        entity_count: int,
    ) -> dict[str, object]:
        return await self._review_service.record_drawing_document(
            run_id,
            command_id=command_id,
            document_hash=document_hash,
            document=document,
            entity_count=entity_count,
        )

    async def record_review_marker(
        self,
        run_id: str,
        *,
        command_id: str,
        text: str,
    ) -> dict[str, object]:
        return await self._review_service.record_review_marker(
            run_id,
            command_id=command_id,
            text=text,
        )

    async def public_times(
        self,
        run_id: str,
        *,
        timeline_ms: tuple[int, ...],
    ) -> dict[str, object]:
        return await self._review_service.public_times(run_id, timeline_ms=timeline_ms)

    async def equity(
        self,
        run_id: str,
        *,
        resolution: str = "AUTO",
        limit: int = 1_000,
    ) -> dict[str, object]:
        return await self._review_service.equity(
            run_id,
            resolution=resolution,
            limit=limit,
        )

    async def journal(self, run_id: str) -> dict[str, object]:
        return await self._review_service.journal(run_id)

    async def report(self, run_id: str) -> dict[str, object]:
        return await self._review_service.report(run_id)

    async def training_results(self, run_id: str, *, limit: int) -> dict[str, object]:
        return await self._review_service.training_results(run_id, limit=limit)

    async def start_review(
        self,
        run_id: str,
        *,
        event_id: str | None,
    ) -> dict[str, object]:
        return await self._review_service.start_review(run_id, event_id=event_id)

    async def control_review(
        self,
        run_id: str,
        review_id: str,
        *,
        action: str,
        event_id: str | None,
        expected_cursor_revision: int,
        playback_rate: str | None,
    ) -> dict[str, object]:
        return await self._review_service.control_review(
            run_id,
            review_id,
            action=action,
            event_id=event_id,
            expected_cursor_revision=expected_cursor_revision,
            playback_rate=playback_rate,
        )

    async def fork_run(
        self,
        run_id: str,
        *,
        event_id: str,
    ) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        normalized_event = self._identifier(event_id, field_name="event_id")
        market_tracks = await self.store.get_market_tracks(normalized)
        event = await self.store.checkpoint_for_event(normalized, normalized_event)
        anchors = event.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise TrainingRunError(
                "REVIEW_ANCHOR_UNAVAILABLE",
                "review event has no immutable actor anchors",
                status_code=503,
            )
        tracks = market_tracks.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "parent market tracks are unavailable",
                status_code=503,
            )
        parent_track_by_id = {
            str(track["track_id"]): track
            for track in tracks
            if isinstance(track, Mapping)
        }
        primary_anchor = next(
            (
                anchor
                for anchor in anchors
                if isinstance(anchor, Mapping) and anchor.get("track_id") == "track-1"
            ),
            anchors[0],
        )
        if not isinstance(primary_anchor, Mapping):
            raise TypeError("primary review anchor is invalid")
        checkpoint_id = validate_v2_counter(
            primary_anchor["checkpoint_id"],
            field_name="review checkpoint_id",
        )
        child_run_id = self._identifier(self._run_id_factory(), field_name="run_id")
        extension_factory = self.store.fork_run_writer(
            child_run_id=child_run_id,
            parent_run_id=normalized,
            parent_event_id=normalized_event,
            parent_checkpoint_id=checkpoint_id,
            parent_timeline_sequence=validate_v2_counter(
                event["timeline_sequence"],
                field_name="review timeline_sequence",
            ),
            parent_anchor_set_hash=str(event["anchor_set_hash"]),
        )
        child_sessions: list[str] = []
        try:
            forked = await self.replay_service.fork_session_from_checkpoint_blob(
                str(primary_anchor["adapter_session_id"]),
                checkpoint=bytes(primary_anchor["payload"]),
                extension_factory=extension_factory,
            )
        except ReplayDomainError as exc:
            raise TrainingRunError(
                "REVIEW_FORK_FAILED",
                "review event could not be forked exactly",
                status_code=409,
                details={"reason": exc.code.value},
            ) from exc
        snapshot = forked["snapshot"]
        child_sessions.append(str(forked["session_id"]))
        if (
            not isinstance(snapshot, Mapping)
            or snapshot.get("state_hash") != primary_anchor["state_hash"]
        ):
            await self.replay_service.discard_session(child_sessions[0])
            raise TrainingRunError(
                "REVIEW_FORK_MISMATCH",
                "forked run state does not match the selected review event",
                status_code=409,
            )
        try:
            secondary_anchors = sorted(
                (
                    anchor
                    for anchor in anchors
                    if isinstance(anchor, Mapping)
                    and anchor.get("track_id") != primary_anchor["track_id"]
                ),
                key=lambda item: str(item["track_id"]),
            )
            for anchor in secondary_anchors:
                parent_track_id = str(anchor["track_id"])
                parent_track = parent_track_by_id.get(parent_track_id)
                if parent_track is None:
                    raise TrainingRunError(
                        "REVIEW_FORK_MISMATCH",
                        "review anchor references an unknown market track",
                        status_code=409,
                    )
                reserved = await self.store.reserve_market_track(
                    run_id=child_run_id,
                    exchange=str(parent_track["exchange"]),
                    market_type=str(parent_track["market_type"]),
                    symbol=str(parent_track["symbol"]),
                    settlement_asset=str(parent_track["settlement_asset"]),
                    source_kind=str(parent_track["source_kind"]),
                    subscription_tier="FULL",
                )
                child_track_id = str(reserved["track_id"])
                attach = self.store.attach_market_track_writer(
                    run_id=child_run_id,
                    track_id=child_track_id,
                    requested_tier="FULL",
                    review_parent_run_id=normalized,
                    review_parent_track_id=parent_track_id,
                    review_parent_event_id=normalized_event,
                )
                attached = await self.replay_service.fork_session_from_checkpoint_blob(
                    str(anchor["adapter_session_id"]),
                    checkpoint=bytes(anchor["payload"]),
                    extension_factory=attach,
                )
                child_sessions.append(str(attached["session_id"]))
                attached_snapshot = attached.get("snapshot")
                if (
                    not isinstance(attached_snapshot, Mapping)
                    or attached_snapshot.get("state_hash") != anchor["state_hash"]
                ):
                    raise TrainingRunError(
                        "REVIEW_FORK_MISMATCH",
                        "secondary forked actor does not match its review anchor",
                        status_code=409,
                    )
            await self.store.checkpoint_market_tracks(child_run_id)
            portfolio = market_tracks.get("portfolio")
            history = (
                portfolio.get("account_history")
                if isinstance(portfolio, Mapping)
                else None
            )
            account_audit = None
            if (
                isinstance(history, Mapping)
                and history.get("mode") == "HISTORICAL_EXACT"
                or (
                    isinstance(portfolio, Mapping)
                    and portfolio.get("position_mode") == "HEDGE"
                )
            ):
                account_audit = await self.audit_account(child_run_id)
                if account_audit.get("status") != "PASS":
                    raise TrainingRunError(
                        "REVIEW_FORK_ACCOUNT_AUDIT_FAILED",
                        "exact-account child failed its independent audit",
                        status_code=409,
                        details={
                            "fallback_applied": False,
                            "differences": account_audit.get("differences", []),
                        },
                    )
                hedge_audit = account_audit.get("hedge_input_audit")
                if (
                    isinstance(portfolio, Mapping)
                    and portfolio.get("position_mode") == "HEDGE"
                    and (
                        not isinstance(hedge_audit, Mapping)
                        or hedge_audit.get("status") != "PASS"
                    )
                ):
                    raise TrainingRunError(
                        "REVIEW_FORK_HEDGE_INPUT_AUDIT_FAILED",
                        "HEDGE child failed its pinned input audit",
                        status_code=409,
                        details={
                            "fallback_applied": False,
                            "differences": (
                                hedge_audit.get("difference_hashes", [])
                                if isinstance(hedge_audit, Mapping)
                                else []
                            ),
                        },
                    )
        except BaseException:
            for session_id in reversed(child_sessions):
                try:
                    await self.replay_service.discard_session(session_id)
                except BaseException:
                    pass
            raise
        card = await self.store.get_run(child_run_id)
        child_tracks = await self.store.get_market_tracks(child_run_id)
        return {
            "protocol": "replay.v3",
            "parent_run_id": normalized,
            "parent_event_id": normalized_event,
            "parent_timeline_sequence": event["timeline_sequence"],
            "anchor_set_hash": event["anchor_set_hash"],
            "run": {
                **card,
                "dataset_epoch": event["dataset_epoch"],
                "state_hash": snapshot["state_hash"],
            },
            "tracks": child_tracks["tracks"],
            "account_audit": account_audit,
        }

    async def create_run(
        self,
        request: TrainingRunCreateRequest,
        *,
        _retry_preparation: Mapping[str, object] | None = None,
        _existing_shell_run_id: str | None = None,
        _preparation_id: str | None = None,
        _committed_start_ms: int | None = None,
        _progressive_feed_id: str | None = None,
        _progressive_initial_horizon_ms: int | None = None,
    ) -> dict[str, object]:
        if not isinstance(request, TrainingRunCreateRequest):
            raise TypeError("request must be TrainingRunCreateRequest")
        if _retry_preparation is None:
            if _committed_start_ms is None:
                request = self._authoritative_start_request(request)
                selection_request = request
            else:
                selection_request = replace(
                    request,
                    start_mode=StartMode.MANUAL,
                    requested_start_ms=_committed_start_ms,
                    random_seed=None,
                )
            selection_config = self._adapter_config(selection_request)
            if _progressive_feed_id is not None:
                if (request.source_kind is not ReplaySource.BAR
                        or type(_progressive_initial_horizon_ms) is not int
                        or _progressive_initial_horizon_ms < 60_000
                        or _progressive_initial_horizon_ms % 60_000
                        or _progressive_initial_horizon_ms > request.forward_cache_ms):
                    raise TrainingRunError("PROGRESSIVE_PREPARATION_INVALID",
                        "progressive BAR preparation needs an aligned prefix within the requested horizon",
                        status_code=422)
                selection_config = replace(selection_config, horizon_ms=_progressive_initial_horizon_ms)
            elif _progressive_initial_horizon_ms is not None:
                raise TrainingRunError("PROGRESSIVE_PREPARATION_INVALID",
                    "progressive prefix requires its durable data feed", status_code=422)
            try:
                selection = await self.replay_service.select_training_window(
                    selection_config,
                    expected_catalog_epoch=request.catalog_epoch,
                    minimum_history_bars=self._selection_warmup_bars(request),
                )
            except ReplayDomainError as exc:
                if exc.details.get("reason") == "CATALOG_EPOCH_MISMATCH":
                    raise TrainingRunError(
                        "CATALOG_EPOCH_MISMATCH",
                        "data capability changed after validation; refresh and try again",
                        status_code=409,
                    ) from exc
                raise TrainingRunError(
                    "MARKET_UNSUPPORTED_AT_COMMITTED_START",
                    "this market cannot replay from the run's immutable start time",
                    status_code=409,
                    details={
                        "reason": exc.code.value,
                        "requires_new_run": True,
                    },
                ) from exc
        else:
            raw_selection = _retry_preparation.get("selection")
            if not isinstance(raw_selection, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training preparation retry selection is invalid",
                    status_code=503,
                )
            selection = dict(raw_selection)
        if _retry_preparation is None and _progressive_feed_id is not None:
            selection = {**selection, "progressive_preparation": {
                "feed_id": _progressive_feed_id,
                "initial_horizon_ms": _progressive_initial_horizon_ms,
            }}
        progressive_preparation = selection.get("progressive_preparation")
        if progressive_preparation is not None and (
            not isinstance(progressive_preparation, Mapping)
            or set(progressive_preparation) != {"feed_id", "initial_horizon_ms"}
            or not isinstance(progressive_preparation.get("feed_id"), str)
            or type(progressive_preparation.get("initial_horizon_ms")) is not int
        ):
            raise TrainingRunError("PROGRESSIVE_PREPARATION_INVALID",
                "saved progressive preparation is invalid", status_code=409)
        history_policy = resolve_history_policy(
            request,
            selection,
            max_dataset_rows=self.replay_service.settings.max_bar_dataset_rows,
        )
        if request.position_mode.value == "HEDGE":
            if (
                request.hedge_public_history_ref is None
                and request.simulation_manifest_ref is None
            ):
                hedge_plan = await self._hedge_plan_with_playable_fallback(
                    request,
                    selection=selection,
                    warmup_bars=history_policy.effective_warmup_bars,
                )
                public_ref = hedge_plan.get("hedge_public_history_ref")
                simulation_ref = hedge_plan.get("simulation_manifest_ref")
                if isinstance(public_ref, Mapping) and isinstance(
                    simulation_ref, Mapping
                ):
                    request = replace(
                        request,
                        hedge_public_history_ref=HedgePublicHistoryRef.from_dict(
                            public_ref
                        ),
                        simulation_manifest_ref=(
                            HedgeSimulationManifestRef.from_dict(simulation_ref)
                        ),
                    )
            if request.hedge_public_history_ref is not None:
                public_fidelity = await self.hedge_inputs.fidelity_for_public_ref(
                    request.hedge_public_history_ref
                )
                if (
                    public_fidelity == HYBRID_PUBLIC_INPUT_FIDELITY
                    and request.funding_mode is FundingMode.HISTORICAL_EXACT
                ):
                    request = replace(
                        request,
                        funding_mode=FundingMode.OFF,
                        fixed_funding_rate=None,
                        funding_interval_ms=None,
                    )
        # Empty Run creation commits T0 before a market is selected.  RANDOM
        # remains the durable/user-facing start mode, while input binding needs
        # the exact committed instant just like a manual request.  Keep this
        # projection local so seed ownership and blind-training eligibility are
        # not rewritten as MANUAL in persisted Run evidence.
        input_binding_request = (
            replace(
                request,
                start_mode=StartMode.MANUAL,
                requested_start_ms=history_policy.actual_replay_start_ms,
                random_seed=None,
            )
            if _existing_shell_run_id is not None
            else request
        )
        base_interval_ms = compatible_step_interval_ms(
            base_interval=request.base_interval,
            step_interval=request.display_interval,
        )
        if (
            request.funding_mode is FundingMode.HISTORICAL_EXACT
            and request.account_data_mode
            not in {
                AccountDataMode.HISTORICAL_EXACT,
                AccountDataMode.DETERMINISTIC_SIMULATION,
            }
        ):
            raise TrainingRunError(
                "HISTORICAL_FUNDING_UNAVAILABLE",
                "historical exact funding requires exact account-history inputs",
                status_code=409,
                details={
                    "funding_rate": "UNSUPPORTED_NO_HISTORY",
                    "historical_mark": "UNSUPPORTED_NO_HISTORY",
                    "fallback_applied": False,
                },
            )
        account_history_binding = None
        if request.account_data_mode is AccountDataMode.HISTORICAL_EXACT:
            if input_binding_request.start_mode is not StartMode.MANUAL:
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_MANUAL_START_REQUIRED",
                    "historical exact account data requires a manual start",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            account_history_binding = await self.account_history.prepare_binding(
                request=input_binding_request,
                bound_range_start_ms=history_policy.actual_replay_start_ms,
                bound_range_end_ms=(
                    history_policy.actual_replay_start_ms + request.forward_cache_ms
                ),
                actual_time_ms=history_policy.actual_replay_start_ms,
                virtual_time_ms=history_policy.actual_replay_start_ms,
            )
        historical_book_binding = None
        if request.book_mode is BookMode.BOOK_ASSISTED_REQUIRED:
            if (
                input_binding_request.start_mode is not StartMode.MANUAL
                or input_binding_request.requested_start_ms is None
            ):
                raise TrainingRunError(
                    "HISTORICAL_BOOK_MANUAL_START_REQUIRED",
                    "BOOK_ASSISTED_REQUIRED currently requires an exact manual start",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            historical_book_binding = await self.historical_books.prepare_binding(
                exchange=request.exchange,
                market_type=request.market_type,
                symbol=request.symbol,
                range_start_ms=input_binding_request.requested_start_ms,
                range_end_ms=(
                    input_binding_request.requested_start_ms
                    + request.forward_cache_ms
                    + base_interval_ms
                ),
                actual_time_ms=input_binding_request.requested_start_ms,
                virtual_time_ms=input_binding_request.requested_start_ms,
            )
        hedge_input_binding: PreparedHedgeInputBinding | None = None
        if request.position_mode.value == "HEDGE":
            if input_binding_request.start_mode is not StartMode.MANUAL:
                raise TrainingRunError(
                    "HEDGE_INPUT_MANUAL_START_REQUIRED",
                    "pinned HEDGE inputs require an exact manual start",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            hedge_input_binding = await self.hedge_inputs.prepare_binding(
                request=input_binding_request,
                bound_range_start_ms=history_policy.actual_replay_start_ms,
                bound_range_end_ms=(
                    history_policy.actual_replay_start_ms
                    + history_policy.forward_cache_ms
                ),
                virtual_time_ms=history_policy.actual_replay_start_ms,
                historical_book_binding=historical_book_binding,
            )
        run_id = self._identifier(
            (
                _existing_shell_run_id
                if _existing_shell_run_id is not None
                else (
                    self._run_id_factory()
                    if _retry_preparation is None
                    else _retry_preparation.get("preparation_id")
                )
            ),
            field_name="run_id",
        )
        preparation_id = self._identifier(
            (
                _retry_preparation.get("preparation_id")
                if _retry_preparation is not None
                else (
                    _preparation_id
                    if _preparation_id is not None
                    else (
                        uuid.uuid4().hex
                        if _existing_shell_run_id is not None
                        else run_id
                    )
                )
            ),
            field_name="preparation_id",
        )
        config = self._adapter_config(
            request,
            warmup_bars=history_policy.effective_warmup_bars,
        )
        required_start_ms = (
            history_policy.actual_replay_start_ms
            - history_policy.effective_warmup_bars * history_policy.interval_ms
        )
        required_end_ms = (
            history_policy.actual_replay_start_ms
            + history_policy.forward_cache_ms
            - history_policy.interval_ms
        )
        if _retry_preparation is None:
            try:
                await self.store.create_selection_preparation(
                    preparation_id=preparation_id,
                    start_mode=request.start_mode.value,
                    random_seed=request.random_seed,
                    catalog_epoch=request.catalog_epoch,
                    source_fingerprint=str(selection["source_fingerprint"]),
                    selected_start_ms=history_policy.actual_replay_start_ms,
                    required_start_ms=required_start_ms,
                    required_end_ms=required_end_ms,
                    interval_ms=history_policy.interval_ms,
                    request=request,
                    selection=selection,
                )
            except sqlite3.IntegrityError as exc:
                raise TrainingRunError(
                    "TRAINING_RUN_CONFLICT",
                    "training preparation identity already exists",
                    status_code=409,
                ) from exc

        def extension_factory(
            *,
            session_id: str,
            session_state: Mapping[str, object],
            component_state: Mapping[str, object],
            broker_config: Mapping[str, object],
            dataset_ref: Mapping[str, object],
            dataset_blob: Mapping[str, object],
            actual_replay_start_ms: int,
            actual_replay_end_ms: int,
        ):
            bound_book = historical_book_binding
            bound_account = account_history_binding
            bound_hedge = hedge_input_binding
            if bound_book is not None:
                cursor = session_state.get("cursor")
                if not isinstance(cursor, Mapping):
                    raise TypeError("training adapter cursor must be an object")
                bound_book = replace(
                    bound_book,
                    projection=replace(
                        bound_book.projection,
                        actual_time_ms=actual_replay_start_ms,
                        virtual_time_ms=int(cursor["virtual_time_ms"]),
                    ),
                )
            if bound_account is not None:
                cursor = session_state.get("cursor")
                if not isinstance(cursor, Mapping):
                    raise TypeError("training adapter cursor must be an object")
                bound_account = replace(
                    bound_account,
                    projection=replace(
                        bound_account.projection,
                        as_of_actual_time_ms=actual_replay_start_ms,
                        as_of_virtual_time_ms=int(cursor["virtual_time_ms"]),
                    ),
                )
            if bound_hedge is not None:
                cursor = session_state.get("cursor")
                if not isinstance(cursor, Mapping):
                    raise TypeError("training adapter cursor must be an object")
                bound_hedge = replace(
                    bound_hedge,
                    public_projection=replace(
                        bound_hedge.public_projection,
                        as_of_virtual_time_ms=int(cursor["virtual_time_ms"]),
                    ),
                    simulation_projection=replace(
                        bound_hedge.simulation_projection,
                        as_of_virtual_time_ms=int(cursor["virtual_time_ms"]),
                    ),
                )
            return self.store.initial_run_writer(
                run_id=run_id,
                request=request,
                adapter_session_id=session_id,
                session_state=session_state,
                component_state=component_state,
                broker_config=broker_config,
                dataset_ref=dataset_ref,
                dataset_blob=dataset_blob,
                actual_replay_start_ms=actual_replay_start_ms,
                actual_replay_end_ms=actual_replay_end_ms,
                history_policy=history_policy,
                source_fingerprint=str(selection["source_fingerprint"]),
                historical_book_binding=bound_book,
                account_history_binding=bound_account,
                hedge_input_binding=bound_hedge,
                existing_shell=_existing_shell_run_id is not None,
                preparation_id=preparation_id,
            )

        try:
            if progressive_preparation is not None:
                await self.replay_service.create_progressive_session(
                    config,
                    feed_id=str(progressive_preparation["feed_id"]),
                    training_selection=selection,
                    initial_horizon_ms=int(progressive_preparation["initial_horizon_ms"]),
                    extension_factory=extension_factory,
                    execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE,
                )
            else:
                await self.replay_service.create_session(
                    config,
                    _expected_catalog_epoch=request.catalog_epoch,
                    _internal_forced_start_ms=history_policy.actual_replay_start_ms,
                    _internal_expected_source_fingerprint=str(
                        selection["source_fingerprint"]
                    ),
                    _internal_training_history=True,
                    _internal_training_selection=selection,
                    _extension_factory=extension_factory,
                    _internal_execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE,
                )
        except ReplayDomainError as exc:
            await self.store.fail_selection_preparation(
                preparation_id,
                error_code=exc.code.value,
                error_message="selected replay data could not be materialized",
            )
            catalog_drift = False
            failure: BaseException | None = exc
            while isinstance(failure, ReplayDomainError):
                if failure.details.get("reason") == "CATALOG_EPOCH_MISMATCH":
                    catalog_drift = True
                    break
                failure = failure.__cause__
            if exc.code is ReplayErrorCode.DATASET_MISMATCH and catalog_drift:
                raise TrainingRunError(
                    "CATALOG_EPOCH_MISMATCH",
                    "data capability changed after validation; refresh and try again",
                    status_code=409,
                    details={"preparation_id": preparation_id},
                ) from exc
            raise TrainingRunError(
                "TRAINING_RUN_CREATE_FAILED",
                "training run could not be created",
                status_code=409,
                details={
                    "reason": exc.code.value,
                    "preparation_id": preparation_id,
                },
            ) from exc
        except sqlite3.IntegrityError as exc:
            await self.store.fail_selection_preparation(
                preparation_id,
                error_code="TRAINING_RUN_CONFLICT",
                error_message="training run persistence conflicted",
            )
            raise TrainingRunError(
                "TRAINING_RUN_CONFLICT",
                "training run identity already exists",
                status_code=409,
                details={"preparation_id": preparation_id},
            ) from exc
        except BaseException as exc:
            await self.store.fail_selection_preparation(
                preparation_id,
                error_code=type(exc).__name__,
                error_message="training data preparation failed",
            )
            raise
        run = await self.store.get_run(run_id)
        return {
            "protocol": "replay.v3",
            "created": True,
            "run": run,
        }

    async def return_to_hub(self, run_id: str) -> dict[str, object]:
        run_id = self._identifier(run_id, field_name="run_id")
        actor = self._run_actors.setdefault(run_id, TrainingRunActor(run_id))
        async with actor.serialized():
            actor.request_ordered_pause(reason="RETURN_TO_HUB")
            projection = await self.store.get_market_tracks(run_id)
            tracks = projection.get("tracks")
            if not isinstance(tracks, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market tracks projection is invalid",
                    status_code=503,
                )
            released = 0
            durable_states: list[str] = []
            for track in sorted(
                tracks,
                key=lambda item: (int(item["stable_ordinal"]), str(item["track_id"])),
            ):
                adapter_session_id = track.get("adapter_session_id")
                if not isinstance(adapter_session_id, str):
                    continue
                try:
                    await self.replay_service.release_session_to_hub(adapter_session_id)
                except ReplayDomainError as exc:
                    raise TrainingRunError(
                        "TRAINING_RUN_BUSY",
                        "training run cannot return to the Hub while another mutation is active",
                        status_code=409,
                        details={
                            "reason": exc.code.value,
                            "track_id": track["track_id"],
                        },
                    ) from exc
                record = await self.replay_service.store.get_session(adapter_session_id)
                durable_state = None if record is None else str(record["state"])
                if durable_state not in {
                    RunState.PAUSED.value,
                    RunState.ENDED.value,
                    RunState.ERROR.value,
                }:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "training run did not reach a durable Hub-safe state",
                        status_code=503,
                        details={
                            "track_id": track["track_id"],
                            "state": durable_state,
                        },
                    )
                durable_states.append(durable_state)
                released += 1
            checkpoint = await self.store.checkpoint_market_tracks(run_id)
            await self.store.set_actor_segment_refs(run_id, active=False)
            card = await self.store.get_run(run_id)
            run_state = str(card["state"])
            if run_state not in {
                RunState.PAUSED.value,
                RunState.ENDED.value,
                RunState.ERROR.value,
            } or run_state not in set(durable_states):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training run Hub state is inconsistent with its durable tracks",
                    status_code=503,
                    details={
                        "run_state": run_state,
                        "track_states": durable_states,
                    },
                )
        result: dict[str, object] = {
            "protocol": "replay.v3",
            "run_id": run_id,
            "state": run_state,
            "checkpointed": True,
            "released": True,
        }
        if len(tracks) > 1:
            result.update(
                {
                    "released_track_count": released,
                    "global_checkpoint": checkpoint,
                }
            )
        return result

    async def _attach_native_display_archive_pin(
        self,
        binding: Mapping[str, object],
        *,
        display_interval: str | None,
        require_projection_grid: bool = False,
    ) -> dict[str, object]:
        """Bind optional chart context without changing the execution snapshot."""
        return await self._display_service._attach_native_display_archive_pin(binding, display_interval=display_interval, require_projection_grid=require_projection_grid)

    async def history_page(
        self,
        session_id: str,
        *,
        track_id: str,
        before_ms: int,
        revealed_boundary_ms: int,
        limit: int,
        data_epoch: str,
        history_epoch: str | None,
        display_interval: str | None = None,
    ) -> dict[str, object]:
        """Return one revealed-only page through the replay-owned data boundary."""
        return await self._display_service.history_page(session_id, track_id=track_id, before_ms=before_ms, revealed_boundary_ms=revealed_boundary_ms, limit=limit, data_epoch=data_epoch, history_epoch=history_epoch, display_interval=display_interval)

    async def display_projection(
        self,
        session_id: str,
        *,
        track_id: str,
        revealed_boundary_ms: int,
        limit: int,
        data_epoch: str,
        display_interval: str,
    ) -> dict[str, object]:
        """Return a source-bucket-aligned, public-time-only viewer tail."""
        return await self._display_service.display_projection(session_id, track_id=track_id, revealed_boundary_ms=revealed_boundary_ms, limit=limit, data_epoch=data_epoch, display_interval=display_interval)

    def _uses_tape_interval_clock(
        self,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        command: ReplayV2Command,
    ) -> bool:
        """Route eligible advances to the interval coordinator, retaining legacy adapters."""
        return (
            self.replay_service.settings.replay_fast_forward_optimization_enabled
            and binding.get("source_kind") == "AGG_TRADE"
            and binding.get("position_mode") == "ONE_WAY"
            and binding.get("book_mode", "OFF") == "OFF"
            and binding.get("funding_mode") == "OFF"
            and binding.get("account_data_mode") != AccountDataMode.HISTORICAL_EXACT.value
            and (command.type in {ReplayV2CommandType.ADVANCE_TO, ReplayV2CommandType.ADVANCE_BY}
                 or (command.type is ReplayV2CommandType.ADVANCE
                     and command.payload.get("basis") in {"DISPLAY_BAR", "VIRTUAL_TIME"}))
            and not any(o["status"] in {"OPEN", "PARTIALLY_FILLED"}
                        for o in snapshot["components"]["orders"])
        )

    async def command(
        self,
        run_id: str,
        command: ReplayV2Command,
        *,
        include_display_tail: bool = False,
        timings: dict[str, float] | None = None,
    ) -> dict[str, object]:
        self._foreground_controls += 1
        try:
            return await self._command_with_timings(
                run_id, command, include_display_tail=include_display_tail, timings=timings
            )
        finally:
            self._foreground_controls -= 1
            self._last_foreground_control = perf_counter()

    def has_foreground_work(self) -> bool:
        return self._foreground_controls > 0

    def foreground_idle_seconds(self) -> float:
        if self.has_foreground_work():
            return 0.0
        if self._last_foreground_control is None:
            return float("inf")
        return max(0.0, perf_counter() - self._last_foreground_control)

    async def _command_with_timings(
        self,
        run_id: str,
        command: ReplayV2Command,
        *,
        include_display_tail: bool = False,
        timings: dict[str, float] | None = None,
    ) -> dict[str, object]:
        normalized = self._identifier(run_id, field_name="run_id")
        if command.type in {
            ReplayV2CommandType.CANCEL_ADVANCE,
            ReplayV2CommandType.SET_DISPLAY_INTERVAL,
            ReplayV2CommandType.RECORD_VIEW_ACTION,
        }:
            started = perf_counter()
            result = await self._command_serialized(normalized, command)
            if timings is not None:
                timings["advance"] = (perf_counter() - started) * 1000
            self._notify_market_tracks(normalized)
            return result
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        ordered_pause_barrier = (
            command.type is ReplayV2CommandType.PAUSE and actor.playback_is_active()
        )
        if command.type is ReplayV2CommandType.PAUSE:
            # A pause is a barrier, not ordinary queued work. Signal the
            # server-owned loop before waiting for its serialization lock so a
            # high playback rate cannot consume the remaining dataset first.
            actor.signal_ordered_stop()
        queued = perf_counter()
        with collect_timings(timings):
            async with actor.serialized():
                started = perf_counter()
                if timings is not None:
                    timings["queue"] = (started - queued) * 1000
                result = await self._command_serialized(
                    normalized,
                    command,
                    ordered_pause_barrier=ordered_pause_barrier,
                )
                if timings is not None:
                    timings["advance"] = (perf_counter() - started) * 1000
                if include_display_tail:
                    started = perf_counter()
                    result = await self._with_command_display_tail(command, result)
                    if timings is not None:
                        timings["display"] = (perf_counter() - started) * 1000
        response_data = result.get("data")
        live_projection = response_data.get("market_tracks") if isinstance(response_data, Mapping) else None
        self._notify_market_tracks(normalized, live_projection if isinstance(live_projection, Mapping) else None)
        return result

    async def _with_command_display_tail(
        self, command: ReplayV2Command, result: dict[str, object]
    ) -> dict[str, object]:
        """Attach a bounded, cursor-bound UI tail without changing durable results.

        This runs under the Run barrier. Failure to project an optional view
        must not turn an already committed command into a reported failure;
        clients retain the ordinary authoritative projection recovery path.
        """
        if not (
            command.type is ReplayV2CommandType.ADVANCE
            and command.payload.get("basis") == AdvanceBasis.DISPLAY_BAR.value
            and command.payload.get("count") == 1
        ):
            return result
        viewer = result.get("viewer_state")
        cursor = result.get("cursor")
        if not isinstance(viewer, Mapping) or not isinstance(cursor, Mapping):
            return result
        try:
            session_id = str(result["session_id"])
            snapshot = await self.replay_service.get_session_state(session_id)
            if snapshot["revision"] != result["revision"]:
                return result
            projection = await self.display_projection(
                session_id,
                track_id=str(viewer["selected_track_id"]),
                revealed_boundary_ms=int(cursor["virtual_time_ms"]),
                limit=2,
                data_epoch=str(snapshot["data_epoch"]),
                display_interval=str(viewer["display_interval"]),
            )
        except (TrainingRunError, ReplayDomainError, KeyError, TypeError, ValueError, OSError):
            return result
        data = {**dict(result["data"]), "display_tail": projection}
        if (getattr(getattr(self.replay_service, "settings", None), "replay_multi_bar_interval_enabled", False)
                and data.get("full_track_count", 0) > 1):
            try:
                tracks = await self.get_live_market_tracks(str(result["run_id"]))
                selected = next(track for track in tracks["tracks"] if track["adapter_session_id"] == session_id)
                if selected["cursor"]["revision"] == result["revision"]:
                    data["market_tracks"] = tracks
            except (TrainingRunError, ReplayDomainError, KeyError, TypeError, ValueError, OSError, StopIteration):
                pass
        return {**result, "data": data}

    async def _command_serialized(
        self,
        run_id: str,
        command: ReplayV2Command,
        *,
        ordered_pause_barrier: bool = False,
    ) -> dict[str, object]:
        normalized_run = self._identifier(run_id, field_name="run_id")
        if not isinstance(command, ReplayV2Command):
            raise TypeError("command must be ReplayV2Command")
        if command.run_id != normalized_run:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "command run_id does not match the route",
                status_code=422,
            )
        command_payload = command.to_dict()
        replayed = await self.store.get_command_result(
            normalized_run,
            command.command_id,
            command_payload,
        )
        if replayed is not None:
            return replayed

        binding = await self.store.run_binding(normalized_run)
        if str(
            binding.get("account_data_mode")
        ) == AccountDataMode.HISTORICAL_EXACT.value and (
            not self.account_history.enabled
            or str(binding.get("account_history_status")) != "ACTIVE"
        ):
            raise TrainingRunError(
                (
                    "ACCOUNT_HISTORY_DISABLED"
                    if not self.account_history.enabled
                    else "ACCOUNT_HISTORY_ARCHIVE_DEGRADED"
                ),
                "exact account inputs are unavailable; the Run remains paused",
                status_code=409,
                details={
                    "compatibility": binding["compatibility"],
                    "fallback_applied": False,
                },
            )
        if binding["compatibility"] != "READY":
            if (
                str(binding.get("book_mode", "OFF"))
                == BookMode.BOOK_ASSISTED_REQUIRED.value
            ):
                raise TrainingRunError(
                    (
                        "HISTORICAL_BOOK_CAPABILITY_UNAVAILABLE"
                        if self.historical_books.enabled
                        else "HISTORICAL_BOOK_DISABLED"
                    ),
                    "book-assisted execution capability is unavailable; the Run remains paused",
                    status_code=409,
                    details={
                        "compatibility": binding["compatibility"],
                        "fallback_applied": False,
                    },
                )
            raise TrainingRunError(
                "REPLAY_CONTROL_UNAVAILABLE",
                "Phase 3 controls require a base-interval v2 adapter",
                status_code=409,
                details={"compatibility": binding["compatibility"]},
            )
        await self.store.set_actor_segment_refs(normalized_run, active=True)
        session_id = str(binding["adapter_session_id"])
        if command.type is ReplayV2CommandType.CANCEL_ADVANCE:
            result = await self._advance_service.cancel_advance(command, session_id=session_id)
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result
        session = await self.replay_service.get_session(session_id)
        durable_intent = await self.store.get_advance_intent(
            run_id=normalized_run,
            command_id=command.command_id,
            command=command_payload,
        )
        if durable_intent is not None:
            intent_status = str(durable_intent["status"])
            stored_result = durable_intent.get("result")
            if intent_status in {"COMPLETED", "CANCELLED"}:
                if not isinstance(stored_result, Mapping):
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "completed advance intent is missing its result",
                        status_code=503,
                    )
                result = dict(stored_result)
                await self.store.save_command_result(
                    run_id=normalized_run,
                    command_id=command.command_id,
                    command=command_payload,
                    result=result,
                )
                return result
            if intent_status == "RUNNING":
                stored_plan = service_validation_ops._stored_mapping(
                    durable_intent.get("plan"),
                    field_name="durable advance plan",
                )
                if stored_plan.get('schema') in {'multi-bar-advance-intent.v1', 'tape-cohort-advance.v1'}:
                    if stored_plan.get('schema') == 'tape-cohort-advance.v1':
                        if not hasattr(self.store, '_tape_intent_runs'):
                            self.store._tape_intent_runs = set()
                        self.store._tape_intent_runs.add(normalized_run)
                    from .multi_interval_advance import resume_advance
                    return await resume_advance(self,command=command,binding=binding,intent=durable_intent)
                stored_mode = str(
                    stored_plan.get(
                        "mode",
                        FastForwardPlan.FULL_EVENT_SCAN.value,
                    )
                )
                recovery_mode = (
                    FastForwardPlan.AGGREGATE_SCAN.value
                    if stored_mode
                    in {
                        FastForwardPlan.CHECKPOINT_JUMP.value,
                        FastForwardPlan.AGGREGATE_SCAN.value,
                    }
                    else FastForwardPlan.FULL_EVENT_SCAN.value
                )
                recovery_plan = {
                    **dict(stored_plan),
                    "mode": recovery_mode,
                    "plan": recovery_mode,
                    "optimized": (
                        recovery_mode == FastForwardPlan.AGGREGATE_SCAN.value
                    ),
                    "period_summary": {
                        "status": "RECOVERY_REFERENCE",
                        "reason_code": "DURABLE_INTENT_RESUME",
                    },
                }
                try:
                    await self.replay_service.ensure_advance_recovery_controller(
                        session_id,
                        client_instance_id=command.client_instance_id,
                    )
                except ReplayDomainError as exc:
                    raise TrainingRunError(
                        exc.code.value,
                        exc.message,
                        status_code=exc.http_status,
                        details=exc.details,
                    ) from exc
                result = await self._advance_service.execute_target_scan(
                    command=command,
                    session_id=session_id,
                    target_virtual_time_ms=service_validation_ops._stored_counter(
                        durable_intent["target_virtual_time_ms"],
                        field_name="target_virtual_time_ms",
                    ),
                    plan=recovery_plan,
                    summary=None,
                    resuming=True,
                )
                return result
            raise TrainingRunError(
                "ADVANCE_INTENT_FAILED",
                "the durable advance intent cannot be resumed automatically",
                status_code=409,
                details={"status": intent_status},
            )
        if command.type in {
            ReplayV2CommandType.ADD_TRACK,
            ReplayV2CommandType.SELECT_TRACK,
            ReplayV2CommandType.SET_SUBSCRIPTION_TIER,
            ReplayV2CommandType.REMOVE_UNOWNED_TRACK,
        }:
            snapshot = self._assert_expected_cursor(command, session)
            result = await self._execute_market_track_command(
                command=command,
                binding=binding,
                selected_snapshot=snapshot,
            )
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result
        if command.type in {
            ReplayV2CommandType.PLACE_ORDER,
            ReplayV2CommandType.REPLACE_ORDER,
            ReplayV2CommandType.CANCEL_ORDER,
            ReplayV2CommandType.CANCEL_ORDERS,
            ReplayV2CommandType.CLOSE_POSITION,
            ReplayV2CommandType.EXECUTE_POSITION_INTENT,
            ReplayV2CommandType.SET_POSITION_PROTECTION,
            ReplayV2CommandType.SET_POSITION_LEVERAGE,
        }:
            snapshot = self._assert_expected_cursor(command, session)
            await self._guard_historical_book_current(
                run_id=normalized_run,
                binding=binding,
                snapshot=snapshot,
            )
            result = await self._execute_market_trade_command(
                command=command,
                binding=binding,
                snapshot=snapshot,
            )
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result
        if command.type is ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN:
            snapshot = self._assert_expected_cursor(command, session)
            payload = self._exact_payload(
                command.payload,
                {"track_id", "position_side", "amount"},
            )
            track_id = self._identifier(payload["track_id"], field_name="track_id")
            position_side = payload["position_side"]
            if binding.get("position_mode") == "HEDGE":
                if position_side not in {"LONG", "SHORT"}:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "HEDGE isolated margin requires position_side",
                        status_code=422,
                    )
            elif position_side is not None:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "ONE_WAY isolated margin does not accept position_side",
                    status_code=422,
                )
            amount = payload["amount"]
            if not isinstance(amount, str):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "isolated margin amount must be a canonical Decimal string",
                    status_code=422,
                )
            try:
                normalized_amount = normalize_decimal_string(
                    amount,
                    field_name="isolated margin amount",
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "isolated margin amount is invalid",
                    status_code=422,
                ) from exc
            if normalized_amount != amount or Decimal(amount) < 0:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "isolated margin amount must be a non-negative canonical Decimal string",
                    status_code=422,
                )
            cursor = service_validation_ops._stored_mapping(snapshot["cursor"], field_name="adapter cursor")
            portfolio = await self.store.allocate_isolated_margin(
                run_id=normalized_run,
                track_id=track_id,
                position_side=(None if position_side is None else str(position_side)),
                amount=amount,
                command_id=command.command_id,
                virtual_time_ms=service_validation_ops._stored_counter(
                    cursor["virtual_time_ms"],
                    field_name="virtual_time_ms",
                ),
                source_sequence=service_validation_ops._stored_counter(
                    cursor["source_sequence"],
                    field_name="source_sequence",
                ),
            )
            checkpoint = await self.store.checkpoint_market_tracks(normalized_run)
            refreshed = await self.store.get_market_tracks(normalized_run)
            portfolio = cast(dict[str, object], refreshed["portfolio"])
            viewer = await self.store.get_viewer_state(normalized_run)
            result = self._result_payload(
                command=command,
                session_id=session_id,
                snapshot=snapshot,
                viewer=viewer.to_dict(),
                data={
                    "account_contract": "TOUCH_OR_TAPE_V2_CONTRACT_ACCOUNT",
                    "portfolio": portfolio,
                    "global_checkpoint": checkpoint,
                    "allocated_track_id": track_id,
                    "allocated_position_side": position_side,
                    "allocated_margin": amount,
                },
            )
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result
        if command.type is ReplayV2CommandType.RECORD_VIEW_ACTION:
            snapshot = self._assert_expected_cursor(command, session)
            payload = self._exact_payload(
                command.payload,
                {"event_type", "semantic_key", "value"},
            )
            event_type = self._identifier(
                payload["event_type"],
                field_name="view event_type",
            )
            semantic_key = self._identifier(
                payload["semantic_key"],
                field_name="view semantic_key",
            )
            value = payload["value"]
            if not isinstance(value, Mapping):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "view action value must be an object",
                    status_code=422,
                )
            cursor = snapshot["cursor"]
            if not isinstance(cursor, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "adapter cursor is invalid",
                    status_code=503,
                )
            view_action = await self.store.record_view_action(
                run_id=normalized_run,
                command_id=command.command_id,
                event_type=event_type,
                semantic_key=semantic_key,
                value=value,
                public_time_ms=int(cursor["virtual_time_ms"]),
                source_sequence=int(cursor["source_sequence"]),
            )
            viewer = await self.store.get_viewer_state(normalized_run)
            return {
                "protocol": "replay.v3",
                "run_id": normalized_run,
                "session_id": session_id,
                "command_id": command.command_id,
                "revision": snapshot["revision"],
                "sequence": snapshot["sequence"],
                "state": snapshot["state"],
                "state_hash": snapshot["state_hash"],
                "cursor": cursor,
                "viewer_state": viewer.to_dict(),
                "data": {
                    "view_action": view_action,
                    "domain_hash_unchanged": True,
                },
            }
        if command.type in {
            ReplayV2CommandType.DEPOSIT,
            ReplayV2CommandType.WITHDRAW,
            ReplayV2CommandType.CHANGE_FEE_POLICY,
            ReplayV2CommandType.CHANGE_LEVERAGE_CAP,
            ReplayV2CommandType.CHANGE_FUNDING_POLICY,
            ReplayV2CommandType.REVEAL_TIME,
        }:
            snapshot = self._assert_expected_cursor(command, session)
            result = await self._execute_policy_command(
                command=command,
                binding=binding,
                snapshot=snapshot,
                session_id=session_id,
            )
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result
        if command.type is ReplayV2CommandType.SET_DISPLAY_INTERVAL:
            # ViewerState is outside the domain hash and cursor. A display
            # switch submitted while an advance is running must not be rejected
            # merely because its captured domain cursor is already stale.
            snapshot = self._snapshot(session)
            result = await self._set_display_interval(
                command=command,
                binding=binding,
                snapshot=snapshot,
            )
            await self.store.save_command_result(
                run_id=normalized_run,
                command_id=command.command_id,
                command=command_payload,
                result=result,
            )
            return result

        run_actor = self._run_actors.setdefault(
            normalized_run,
            TrainingRunActor(normalized_run),
        )
        if run_actor.playback_is_active() and command.type not in {
            ReplayV2CommandType.PAUSE,
            ReplayV2CommandType.SET_SPEED,
            ReplayV2CommandType.RELEASE_CONTROLLER,
            ReplayV2CommandType.END,
        }:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "pause ordered playback before submitting another clock control",
                status_code=409,
            )
        snapshot = (
            self._snapshot(session)
            if (run_actor.playback_is_active() or ordered_pause_barrier)
            and command.type
            in {
                ReplayV2CommandType.PAUSE,
                ReplayV2CommandType.SET_SPEED,
                ReplayV2CommandType.RELEASE_CONTROLLER,
                ReplayV2CommandType.END,
            }
            else self._assert_expected_cursor(command, session)
        )
        all_tracks = cast(
            list[Mapping[str, object]],
            await self.store.get_market_track_heads(normalized_run),
        )
        full_tracks = [
            track for track in all_tracks if track.get("subscription_tier") == "FULL"
        ]
        if command.type in {
            ReplayV2CommandType.PLAY,
            ReplayV2CommandType.STEP_EVENT,
            ReplayV2CommandType.STEP_BASE,
            ReplayV2CommandType.STEP_DISPLAY,
            ReplayV2CommandType.ADVANCE,
            ReplayV2CommandType.ADVANCE_BY,
            ReplayV2CommandType.ADVANCE_TO,
        }:
            await self._guard_historical_book_current(
                run_id=normalized_run,
                binding=binding,
                snapshot=snapshot,
                tracks=full_tracks,
            )
        contract_clock = binding.get("account_model") == "TOUCH_OR_TAPE_V2"
        contract_ordered_types = {
            ReplayV2CommandType.PLAY,
            ReplayV2CommandType.PAUSE,
            ReplayV2CommandType.SET_SPEED,
            ReplayV2CommandType.RELEASE_CONTROLLER,
        }
        exact_account_ordered_types = contract_ordered_types | {
            ReplayV2CommandType.STEP_EVENT,
            ReplayV2CommandType.STEP_BASE,
            ReplayV2CommandType.STEP_DISPLAY,
            ReplayV2CommandType.ADVANCE,
            ReplayV2CommandType.ADVANCE_BY,
            ReplayV2CommandType.ADVANCE_TO,
        }
        exact_account_clock = (
            binding.get("account_data_mode") == AccountDataMode.HISTORICAL_EXACT.value
        )
        hedge_input_clock = binding.get("position_mode") == "HEDGE"
        tape_interval_clock = self._uses_tape_interval_clock(binding, snapshot, command)
        multi_track_command = (
            len(full_tracks) > 1
            or tape_interval_clock
            or (contract_clock and command.type in contract_ordered_types)
            or (exact_account_clock and command.type in exact_account_ordered_types)
            or (hedge_input_clock and command.type in exact_account_ordered_types)
            or (command.type is ReplayV2CommandType.END and len(all_tracks) > 1)
        )
        if multi_track_command and command.type in {
            ReplayV2CommandType.ACQUIRE_CONTROLLER,
            ReplayV2CommandType.TAKEOVER_CONTROLLER,
            ReplayV2CommandType.RELEASE_CONTROLLER,
            ReplayV2CommandType.PLAY,
            ReplayV2CommandType.PAUSE,
            ReplayV2CommandType.SET_SPEED,
            ReplayV2CommandType.STEP_EVENT,
            ReplayV2CommandType.STEP_BASE,
            ReplayV2CommandType.STEP_DISPLAY,
            ReplayV2CommandType.ADVANCE,
            ReplayV2CommandType.ADVANCE_BY,
            ReplayV2CommandType.ADVANCE_TO,
            ReplayV2CommandType.END,
        }:
            used_intervals = getattr(self.store, '_multi_interval_commands', set())
            key = (normalized_run, command.command_id)
            try:
                result = await self._execute_multi_track_control(
                    command=command, binding=binding, selected_snapshot=snapshot,
                    tracks=(all_tracks if command.type is ReplayV2CommandType.END else full_tracks),
                )
                # The first group created its durable parent intent in the
                # same transaction; finish it with the external response.
                used_intervals = getattr(self.store, '_multi_interval_commands', set())
                if key in getattr(self.store, "_multi_completed_results", {}):
                    pass  # Result and terminal intent were committed with the actors.
                elif key in used_intervals:
                    await self.store.finish_advance_intent(run_id=normalized_run,
                        command_id=command.command_id, result=result,
                        cancelled=bool(result.get('data',{}).get('cancelled',False)))
                else:
                    await self.store.save_command_result(run_id=normalized_run,
                        command_id=command.command_id, command=command_payload, result=result)
            finally:
                getattr(self.store, '_multi_interval_commands', set()).discard(key)
                getattr(self.store, "_multi_completed_results", {}).pop(key, None)
            return result
        v1_type, v1_payload, plan = await self._translate_control(
            command=command,
            binding=binding,
            snapshot=snapshot,
        )
        target = plan.get("target_virtual_time_ms")
        if v1_type is CommandType.ADVANCE_BY and isinstance(target, int):
            decision = self._plan_fast_forward(
                binding=binding,
                snapshot=snapshot,
                tracks=tuple(all_tracks),
                target_virtual_time_ms=target,
            )
            summary_lookup: Mapping[str, object] = {
                "status": "SKIPPED",
                "reason_code": "REFERENCE_OR_BLOCKED_PLAN",
                "summary": None,
            }
            if decision.plan is FastForwardPlan.AGGREGATE_SCAN:
                summary_lookup = await self._advance_service.eligible_period_summary(
                    run_id=normalized_run,
                    binding=binding,
                    snapshot=snapshot,
                    target_virtual_time_ms=target,
                )
                candidate = summary_lookup.get("summary")
                if isinstance(candidate, ReplayPeriodSummary):
                    decision = self._plan_fast_forward(
                        binding=binding,
                        snapshot=snapshot,
                        tracks=tuple(all_tracks),
                        target_virtual_time_ms=target,
                        summary=candidate,
                    )
            translated_plan = plan
            final_state_delivery = translated_plan.get(
                "basis"
            ) == AdvanceBasis.DISPLAY_BAR.value and command.type in {
                ReplayV2CommandType.ADVANCE,
                ReplayV2CommandType.STEP_DISPLAY,
            }
            plan = {
                **self._fast_forward_plan_payload(
                    decision,
                    summary_lookup=summary_lookup,
                ),
                **{
                    key: value
                    for key, value in translated_plan.items()
                    if key
                    in {
                        "contract",
                        "basis",
                        "count",
                        "duration_ms",
                        "legacy_alias",
                        "grain",
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
                    details={"plan": plan},
                )
            if final_state_delivery:
                empty_account_path = not decision.context.path_dependencies
                sparse_interaction_path = set(decision.context.path_dependencies) == {
                    "OPEN_ORDER"
                }
                if empty_account_path or sparse_interaction_path:
                    plan["chunk_event_limit"] = max(
                        1,
                        min(
                            control_rules_ops.FINAL_STATE_EMPTY_ACCOUNT_CHUNK_EVENTS,
                            self.replay_service.settings.event_buffer_size,
                            self.replay_service.settings.trade_page_rows,
                        ),
                    )
                plan.update(
                    {
                        "projection_delivery": control_rules_ops.FINAL_STATE_PROJECTION_DELIVERY,
                        "path_execution": (
                            "EMPTY_ACCOUNT"
                            if empty_account_path
                            else (
                                "SPARSE_INTERACTION"
                                if sparse_interaction_path
                                else "EXACT_INTERACTION"
                            )
                        ),
                        "final_state_optimized": True,
                        "single_pass_source_chunks": True,
                        "interaction_boundary_stop": sparse_interaction_path,
                        "intermediate_projection_policy": "ORDERS_FILLS_WARNINGS",
                    }
                )
            result = await self._advance_service.execute_target_scan(
                command=command,
                session_id=session_id,
                target_virtual_time_ms=target,
                plan=plan,
                summary=(
                    candidate
                    if isinstance(
                        (candidate := summary_lookup.get("summary")),
                        ReplayPeriodSummary,
                    )
                    else None
                ),
            )
            return result
        v1_command = ReplayCommand(
            protocol=REPLAY_PROTOCOL,
            command_id=command.command_id,
            client_instance_id=command.client_instance_id,
            expected_revision=command.expected_revision,
            type=v1_type,
            payload=v1_payload,
        )
        try:
            adapter_result = await self.replay_service.command(session_id, v1_command)
        except ReplayDomainError as exc:
            raise TrainingRunError(
                exc.code.value,
                exc.message,
                status_code=exc.http_status,
                details=exc.details,
            ) from exc
        adapter_data = dict(
            service_validation_ops._stored_mapping(
                adapter_result.get("data"),
                field_name="adapter_result.data",
            )
        )
        liquidation_count = await self._reconcile_liquidations(
            run_id=normalized_run,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
        )
        authoritative = (
            self._snapshot(await self.replay_service.get_session(session_id))
            if liquidation_count
            else adapter_result
        )
        if command.type in {
            ReplayV2CommandType.STEP_EVENT,
            ReplayV2CommandType.STEP_BASE,
            ReplayV2CommandType.STEP_DISPLAY,
            ReplayV2CommandType.ADVANCE,
        }:
            await self._guard_historical_book_current(
                run_id=normalized_run,
                binding=binding,
                snapshot=authoritative,
            )
        viewer = await self.store.get_viewer_state(normalized_run)
        result = {
            "protocol": "replay.v3",
            "run_id": normalized_run,
            "session_id": session_id,
            "command_id": command.command_id,
            "revision": authoritative["revision"],
            "sequence": authoritative["sequence"],
            "state": authoritative["state"],
            "state_hash": authoritative["state_hash"],
            "cursor": authoritative["cursor"],
            "viewer_state": viewer.to_dict(),
            "data": {
                **adapter_data,
                "plan": plan,
                "adapter_command": v1_type.value,
                "simulated_account_liquidations": liquidation_count,
            },
        }
        await self.store.save_command_result(
            run_id=normalized_run,
            command_id=command.command_id,
            command=command_payload,
            result=result,
        )
        return result

    async def _execute_market_track_command(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        selected_snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        actor = self._run_actors.setdefault(
            command.run_id,
            TrainingRunActor(command.run_id),
        )
        actor.request_ordered_pause(reason="TRACK_MUTATION")
        if command.type is ReplayV2CommandType.ADD_TRACK:
            if self._instrument_metadata_resolver is not None:
                if set(command.payload) != {"plan_id"}:
                    raise TrainingRunError(
                        "MARKET_TRACK_PLAN_REQUIRED",
                        "production MarketTrack creation requires an authoritative plan_id",
                        status_code=409,
                    )
                payload = self._exact_payload(command.payload, {"plan_id"})
                plan_id = self._identifier(payload["plan_id"], field_name="plan_id")
                plan = self._claim_market_track_plan(
                    run_id=command.run_id,
                    plan_id=plan_id,
                    selected_snapshot=selected_snapshot,
                )
                exchange = plan.exchange
                market_type = plan.market_type
                symbol = plan.symbol
                settlement_asset = plan.settlement_asset
                tier = plan.subscription_tier
            else:
                if set(command.payload) == {"plan_id"}:
                    raise TrainingRunError(
                        "INSTRUMENT_METADATA_UNAVAILABLE",
                        "authoritative instrument metadata is unavailable",
                        status_code=503,
                    )
                # Direct service fixtures may opt out of the application-owned
                # instrument resolver. The production runtime always wires it
                # and therefore never accepts this legacy payload.
                payload = self._exact_payload(
                    command.payload,
                    {
                        "exchange",
                        "market_type",
                        "symbol",
                        "settlement_asset",
                        "subscription_tier",
                    },
                )
                exchange = self._identifier(payload["exchange"], field_name="exchange")
                market_type = self._identifier(
                    payload["market_type"], field_name="market_type"
                )
                symbol = self._identifier(payload["symbol"], field_name="symbol")
                settlement_asset = self._identifier(
                    payload["settlement_asset"],
                    field_name="settlement_asset",
                )
                try:
                    tier = SubscriptionTier(str(payload["subscription_tier"]))
                except ValueError as exc:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "subscription_tier is unsupported",
                        status_code=422,
                    ) from exc
            self._assert_same_market_scope(
                binding=binding,
                exchange=exchange,
                market_type=market_type,
                settlement_asset=settlement_asset,
            )
            target_virtual_time_ms = self._cursor_time(selected_snapshot)
            if (
                str(binding.get("book_mode", "OFF"))
                == BookMode.BOOK_ASSISTED_REQUIRED.value
                and tier is SubscriptionTier.FULL
            ):
                # Prove exact L2 coverage before reserving the track. A failed
                # capability check must not leave a phantom FULL track behind.
                await self.historical_books.prepare_binding(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    range_start_ms=service_validation_ops._stored_counter(
                        binding["actual_replay_start_ms"],
                        field_name="actual_replay_start_ms",
                    ),
                    range_end_ms=service_validation_ops._stored_counter(
                        binding["actual_replay_end_ms"],
                        field_name="actual_replay_end_ms",
                    ),
                    actual_time_ms=self._actual_event_time_ms(
                        binding,
                        target_virtual_time_ms,
                    ),
                    virtual_time_ms=target_virtual_time_ms,
                )
            track = await self.store.reserve_market_track(
                run_id=command.run_id,
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                settlement_asset=settlement_asset,
                source_kind=str(binding["source_kind"]),
                subscription_tier=tier.value,
            )
            if tier is not SubscriptionTier.NONE:
                try:
                    track = await self._prepare_market_track(
                        command=command,
                        binding=binding,
                        track=track,
                        requested_tier=tier,
                        target_virtual_time_ms=target_virtual_time_ms,
                    )
                except TrainingRunError:
                    if track.get("adapter_session_id") is None:
                        await self.store.remove_market_track(
                            command.run_id,
                            str(track["track_id"]),
                        )
                    raise
                except Exception as exc:
                    await self.store.mark_market_track_error(
                        run_id=command.run_id,
                        track_id=str(track["track_id"]),
                        reason=type(exc).__name__,
                    )
                    raise TrainingRunError(
                        "MARKET_TRACK_PREPARE_FAILED",
                        "market track could not be prepared from frozen history",
                        status_code=409,
                    ) from exc
            return await self._market_track_result(
                command=command,
                session_id=str(binding["adapter_session_id"]),
                snapshot=selected_snapshot,
                data={
                    "track": track,
                    "history_reads": 0 if tier is SubscriptionTier.NONE else "BOUNDED",
                    "ordering_version": GLOBAL_ORDERING_VERSION,
                },
            )

        payload = self._exact_payload(
            command.payload,
            (
                {"track_id", "expected_viewer_revision"}
                if command.type is ReplayV2CommandType.SELECT_TRACK
                else (
                    {"track_id", "subscription_tier"}
                    if command.type is ReplayV2CommandType.SET_SUBSCRIPTION_TIER
                    else {"track_id"}
                )
            ),
        )
        track_id = self._identifier(payload["track_id"], field_name="track_id")
        track = await self.store.get_market_track(command.run_id, track_id)

        if command.type is ReplayV2CommandType.REMOVE_UNOWNED_TRACK:
            session_id = await self.store.remove_market_track(command.run_id, track_id)
            if session_id is not None:
                await self.replay_service.discard_session(session_id)
            return await self._market_track_result(
                command=command,
                session_id=str(binding["adapter_session_id"]),
                snapshot=selected_snapshot,
                data={"removed_track_id": track_id},
            )

        if command.type is ReplayV2CommandType.SET_SUBSCRIPTION_TIER:
            recovered = False
            tier_book_binding = None
            try:
                tier = SubscriptionTier(str(payload["subscription_tier"]))
            except ValueError as exc:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "subscription_tier is unsupported",
                    status_code=422,
                ) from exc
            if tier is not SubscriptionTier.NONE:
                if track["adapter_session_id"] is None:
                    track = await self._prepare_market_track(
                        command=command,
                        binding=binding,
                        track=track,
                        requested_tier=tier,
                        target_virtual_time_ms=self._cursor_time(selected_snapshot),
                    )
                elif tier is SubscriptionTier.FULL:
                    if (
                        str(binding.get("book_mode", "OFF"))
                        == BookMode.BOOK_ASSISTED_REQUIRED.value
                        and track.get("subscription_tier")
                        != SubscriptionTier.FULL.value
                    ):
                        target_virtual_time_ms = self._cursor_time(selected_snapshot)
                        tier_book_binding = await self.historical_books.prepare_binding(
                            exchange=str(track["exchange"]),
                            market_type=str(track["market_type"]),
                            symbol=str(track["symbol"]),
                            range_start_ms=service_validation_ops._stored_counter(
                                binding["actual_replay_start_ms"],
                                field_name="actual_replay_start_ms",
                            ),
                            range_end_ms=service_validation_ops._stored_counter(
                                binding["actual_replay_end_ms"],
                                field_name="actual_replay_end_ms",
                            ),
                            actual_time_ms=self._actual_event_time_ms(
                                binding,
                                target_virtual_time_ms,
                            ),
                            virtual_time_ms=target_virtual_time_ms,
                        )
                    await self._activate_existing_track(
                        command=command,
                        track=track,
                        target_virtual_time_ms=self._cursor_time(selected_snapshot),
                    )
                    forced_reasons = track.get("forced_full_reasons")
                    needs_recovery = (
                        track["state"] == "DEGRADED"
                        or track.get("degraded_reason") is not None
                        or (
                            isinstance(forced_reasons, list)
                            and "REVIEW_REQUIRED" in forced_reasons
                        )
                    )
                    if needs_recovery:
                        track = await self.store.clear_market_track_degradation(
                            run_id=command.run_id,
                            track_id=track_id,
                        )
                        recovered = True
            if tier is not SubscriptionTier.FULL:
                # The tier writer performs the forced-reason check in the same
                # transaction. Only a clean track reaches this checkpoint.
                await self.store.checkpoint_market_tracks(command.run_id)
            track = await self.store.set_market_track_tier(
                run_id=command.run_id,
                track_id=track_id,
                subscription_tier=tier.value,
                historical_book_binding=tier_book_binding,
            )
            if tier is not SubscriptionTier.FULL and track["adapter_session_id"]:
                await self.replay_service.release_session_to_hub(
                    str(track["adapter_session_id"])
                )
            recovery_checkpoint = (
                await self.store.checkpoint_market_tracks(command.run_id)
                if recovered
                else None
            )
            return await self._market_track_result(
                command=command,
                session_id=str(binding["adapter_session_id"]),
                snapshot=selected_snapshot,
                data={
                    "track": track,
                    "checkpointed_before_downgrade": tier.value != "FULL",
                    "recovered_from_degradation": recovered,
                    "recovery_checkpoint": recovery_checkpoint,
                },
            )

        expected_viewer_revision = payload["expected_viewer_revision"]
        if (
            isinstance(expected_viewer_revision, bool)
            or not isinstance(expected_viewer_revision, int)
            or expected_viewer_revision < 0
        ):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "expected_viewer_revision must be a non-negative integer",
                status_code=422,
            )
        if track["adapter_session_id"] is None:
            track = await self._prepare_market_track(
                command=command,
                binding=binding,
                track=track,
                requested_tier=SubscriptionTier.FULL,
                target_virtual_time_ms=self._cursor_time(selected_snapshot),
            )
        else:
            await self._activate_existing_track(
                command=command,
                track=track,
                target_virtual_time_ms=self._cursor_time(selected_snapshot),
            )
        await self.store.set_market_track_tier(
            run_id=command.run_id,
            track_id=track_id,
            subscription_tier="FULL",
        )
        await self._pause_ready_full_tracks(command.run_id, command.client_instance_id)
        viewer = await self.store.select_market_track(
            run_id=command.run_id,
            track_id=track_id,
            expected_viewer_revision=expected_viewer_revision,
            command_id=command.command_id,
            command=command.to_dict(),
        )
        target_session_id = str(track["adapter_session_id"])
        target_session = await self.replay_service.get_session(target_session_id)
        target_snapshot = self._snapshot(target_session)
        await self.store.checkpoint_market_tracks(command.run_id)
        return self._result_payload(
            command=command,
            session_id=target_session_id,
            snapshot=target_snapshot,
            viewer=viewer.to_dict(),
            data={
                "selected_track_id": track_id,
                "atomic_switch": True,
                "global_clock_paused": True,
                "ordering_version": GLOBAL_ORDERING_VERSION,
            },
        )

    async def _prepare_market_track(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        track: Mapping[str, object],
        requested_tier: SubscriptionTier,
        target_virtual_time_ms: int,
    ) -> dict[str, object]:
        config_payload = binding.get("adapter_config")
        if not isinstance(config_payload, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training adapter config is invalid",
                status_code=503,
            )
        base_config = ReplaySessionConfig.from_dict(config_payload)
        config = replace(
            base_config,
            symbol=str(track["symbol"]),
            start_policy=StartPolicy.MANUAL,
            requested_start_ms=service_validation_ops._stored_counter(
                binding["actual_replay_start_ms"],
                field_name="actual_replay_start_ms",
            ),
            display_interval=base_config.base_interval,
        )
        historical_book_binding = None
        account_history_binding = None
        hedge_track_public_binding = None
        if str(
            binding.get("account_data_mode")
        ) == AccountDataMode.HISTORICAL_EXACT.value and requested_tier in {
            SubscriptionTier.WARM,
            SubscriptionTier.FULL,
        }:
            actual_time_ms = self._actual_event_time_ms(
                binding,
                target_virtual_time_ms,
            )
            account_history_binding = await self.account_history.prepare_track_binding(
                exchange=str(track["exchange"]),
                market_type=str(track["market_type"]),
                symbol=str(track["symbol"]),
                settlement_asset=str(track["settlement_asset"]),
                source_kind=str(track["source_kind"]),
                bound_range_start_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_start_ms"],
                    field_name="actual_replay_start_ms",
                ),
                bound_range_end_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_end_ms"],
                    field_name="actual_replay_end_ms",
                ),
                actual_time_ms=actual_time_ms,
                virtual_time_ms=target_virtual_time_ms,
                require_funding=(
                    str(binding.get("funding_mode"))
                    == FundingMode.HISTORICAL_EXACT.value
                ),
            )
        if (
            str(binding.get("book_mode")) == BookMode.BOOK_ASSISTED_REQUIRED.value
            and requested_tier is SubscriptionTier.FULL
        ):
            actual_time_ms = self._actual_event_time_ms(
                binding,
                target_virtual_time_ms,
            )
            historical_book_binding = await self.historical_books.prepare_binding(
                exchange=str(track["exchange"]),
                market_type=str(track["market_type"]),
                symbol=str(track["symbol"]),
                range_start_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_start_ms"],
                    field_name="actual_replay_start_ms",
                ),
                range_end_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_end_ms"],
                    field_name="actual_replay_end_ms",
                ),
                actual_time_ms=actual_time_ms,
                virtual_time_ms=target_virtual_time_ms,
            )
        if (
            str(binding.get("position_mode")) == "HEDGE"
            and requested_tier is SubscriptionTier.FULL
        ):
            actual_time_ms = self._actual_event_time_ms(
                binding,
                target_virtual_time_ms,
            )
            hedge_track_public_binding = (
                await self.hedge_inputs.prepare_track_public_binding(
                    run_id=command.run_id,
                    track_id=str(track["track_id"]),
                    exchange=str(track["exchange"]),
                    market_type=str(track["market_type"]),
                    symbol=str(track["symbol"]),
                    settlement_asset=str(track["settlement_asset"]),
                    bound_range_start_ms=service_validation_ops._stored_counter(
                        binding["actual_replay_start_ms"],
                        field_name="actual_replay_start_ms",
                    ),
                    bound_range_end_ms=service_validation_ops._stored_counter(
                        binding["actual_replay_end_ms"],
                        field_name="actual_replay_end_ms",
                    ),
                    actual_time_ms=actual_time_ms,
                    virtual_time_ms=target_virtual_time_ms,
                    historical_book_binding=historical_book_binding,
                )
            )
        extension_factory = self.store.attach_market_track_writer(
            run_id=command.run_id,
            track_id=str(track["track_id"]),
            requested_tier=requested_tier.value,
            historical_book_binding=historical_book_binding,
            account_history_binding=account_history_binding,
            hedge_track_public_binding=hedge_track_public_binding,
        )
        try:
            track_catalog = await self.replay_service.catalog(
                warmup_bars=config.warmup_bars,
                horizon_ms=config.horizon_ms,
                quality_mode=config.quality_mode,
                blind_mode=config.blind_mode,
                source_kind=config.source_kind,
            )
            track_catalog_epoch = str(track_catalog["catalog_epoch"])
            selection = await self.replay_service.select_training_window(
                config,
                expected_catalog_epoch=track_catalog_epoch,
            )
            created = await self.replay_service.create_session(
                config,
                _expected_catalog_epoch=track_catalog_epoch,
                _internal_forced_start_ms=service_validation_ops._stored_counter(
                    binding["actual_replay_start_ms"],
                    field_name="actual_replay_start_ms",
                ),
                _internal_expected_source_fingerprint=str(
                    selection["source_fingerprint"]
                ),
                _internal_training_history=True,
                _internal_training_selection=selection,
                _extension_factory=extension_factory,
                _internal_execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE,
            )
        except ReplayDomainError as exc:
            await self.store.mark_market_track_error(
                run_id=command.run_id,
                track_id=str(track["track_id"]),
                reason=exc.code.value,
            )
            raise TrainingRunError(
                "MARKET_TRACK_COVERAGE_UNAVAILABLE",
                "market track lacks qualifying frozen coverage for this TrainingRun",
                status_code=409,
                details={"reason": exc.code.value},
            ) from exc
        session_id = str(created["session_id"])
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
        if requested_tier is SubscriptionTier.WARM:
            await self.replay_service.release_session_to_hub(session_id)
        return await self.store.get_market_track(command.run_id, str(track["track_id"]))

    async def _execute_market_trade_command(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        expected_fields = {
            ReplayV2CommandType.PLACE_ORDER: {
                "client_order_id",
                "side",
                "order_type",
                "quantity",
                "reduce_only",
                "limit_price",
                "stop_price",
            },
            ReplayV2CommandType.REPLACE_ORDER: {
                "order_id",
                "client_order_id",
                "quantity",
                "limit_price",
                "stop_price",
            },
            ReplayV2CommandType.CANCEL_ORDER: {"order_id"},
            ReplayV2CommandType.CANCEL_ORDERS: {"scope", "order_ids"},
            ReplayV2CommandType.CLOSE_POSITION: {"quantity"},
            ReplayV2CommandType.EXECUTE_POSITION_INTENT: {
                "intent",
                "side",
                "quantity",
            },
            ReplayV2CommandType.SET_POSITION_PROTECTION: {
                "quantity",
                "stop_loss_price",
                "take_profit_price",
            },
            ReplayV2CommandType.SET_POSITION_LEVERAGE: {
                "position_side",
                "leverage",
            },
        }
        v1_types = {
            ReplayV2CommandType.PLACE_ORDER: CommandType.PLACE_ORDER,
            ReplayV2CommandType.REPLACE_ORDER: CommandType.REPLACE_ORDER,
            ReplayV2CommandType.CANCEL_ORDER: CommandType.CANCEL_ORDER,
            ReplayV2CommandType.CANCEL_ORDERS: CommandType.CANCEL_ORDERS,
            ReplayV2CommandType.CLOSE_POSITION: CommandType.CLOSE_POSITION,
            ReplayV2CommandType.EXECUTE_POSITION_INTENT: (
                CommandType.EXECUTE_POSITION_INTENT
            ),
            ReplayV2CommandType.SET_POSITION_PROTECTION: (
                CommandType.SET_POSITION_PROTECTION
            ),
            ReplayV2CommandType.SET_POSITION_LEVERAGE: (
                CommandType.SET_POSITION_LEVERAGE
            ),
        }
        trade_plan_draft: Mapping[str, object] | None = None
        if (
            command.type is ReplayV2CommandType.PLACE_ORDER
            and "trade_plan" in command.payload
        ):
            payload_with_plan = self._order_payload_with_optional_leverage(
                command.payload,
                expected_fields[command.type] | {"trade_plan"},
            )
            raw_trade_plan = payload_with_plan["trade_plan"]
            if not isinstance(raw_trade_plan, Mapping):
                raise TrainingRunError(
                    "TRADE_PLAN_INVALID",
                    "trade_plan must be an object",
                    status_code=422,
                )
            trade_plan_draft = raw_trade_plan
            payload = {
                key: value
                for key, value in payload_with_plan.items()
                if key != "trade_plan"
            }
        elif command.type in {
            ReplayV2CommandType.PLACE_ORDER,
            ReplayV2CommandType.EXECUTE_POSITION_INTENT,
            ReplayV2CommandType.CLOSE_POSITION,
            ReplayV2CommandType.SET_POSITION_PROTECTION,
        }:
            payload = dict(
                self._order_payload_with_optional_leverage(
                    command.payload,
                    expected_fields[command.type],
                )
            )
        elif command.type is ReplayV2CommandType.SET_POSITION_LEVERAGE:
            payload = dict(
                self._exact_payload(command.payload, expected_fields[command.type])
            )
            if payload.get("position_side") not in {"LONG", "SHORT"}:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "position_side must be LONG or SHORT",
                    status_code=422,
                )
            raw_leverage = payload.get("leverage")
            if not isinstance(raw_leverage, str):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "position leverage must be a canonical Decimal string",
                    status_code=422,
                )
            try:
                normalized_leverage = normalize_decimal_string(
                    raw_leverage,
                    field_name="position leverage",
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "position leverage is invalid",
                    status_code=422,
                ) from exc
            if normalized_leverage != raw_leverage or Decimal(raw_leverage) < 1:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "position leverage must be canonical and at least 1",
                    status_code=422,
                )
        else:
            payload = dict(
                self._exact_payload(command.payload, expected_fields[command.type])
            )
        projection = await self.store.get_market_tracks(command.run_id)
        tracks = projection.get("tracks")
        if not isinstance(tracks, list):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market tracks projection is invalid",
                status_code=503,
            )
        selected_track_id = str(binding["selected_track_id"])
        selected = next(
            (
                track
                for track in tracks
                if isinstance(track, Mapping)
                and track.get("track_id") == selected_track_id
            ),
            None,
        )
        if (
            selected is None
            or selected.get("subscription_tier") != "FULL"
            or selected.get("state") != "READY"
        ):
            raise TrainingRunError(
                "MARKET_TRACK_NOT_READY",
                "orders require the selected market track to be READY and FULL",
                status_code=409,
            )
        if command.type is ReplayV2CommandType.SET_POSITION_LEVERAGE:
            if binding.get("position_mode") != "HEDGE":
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "set_position_leverage requires HEDGE mode",
                    status_code=422,
                )
            portfolio = projection.get("portfolio")
            if not isinstance(portfolio, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "run portfolio projection is invalid",
                    status_code=503,
                )
            rule = self._active_instrument_rule(
                portfolio,
                track_id=selected_track_id,
            )
            leverage = Decimal(str(payload["leverage"]))
            if leverage > Decimal(str(rule["max_leverage"])):
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "position leverage exceeds the active instrument rule",
                    status_code=409,
                )
            if portfolio.get("margin_mode") == "ISOLATED":
                positions = portfolio.get("positions")
                allocations = portfolio.get("isolated_allocations")
                orders = portfolio.get("orders")
                if (
                    not isinstance(positions, list)
                    or not isinstance(allocations, Mapping)
                    or not isinstance(orders, list)
                ):
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "HEDGE isolated risk projection is invalid",
                        status_code=503,
                    )
                side = str(payload["position_side"])
                risk_position = next(
                    (
                        item
                        for item in positions
                        if isinstance(item, Mapping)
                        and item.get("track_id") == selected_track_id
                        and item.get("position_side") == side
                    ),
                    None,
                )
                notional = Decimal(
                    str(
                        0
                        if not isinstance(risk_position, Mapping)
                        else risk_position.get("account_notional", "0")
                    )
                )
                required = round_to_step(
                    notional / leverage,
                    Decimal(str(rule["quote_step"])),
                    upward=True,
                )
                reserved = sum(
                    (
                        Decimal(str(order.get("reserved_margin", "0")))
                        for order in orders
                        if isinstance(order, Mapping)
                        and order.get("track_id") == selected_track_id
                        and order.get("position_side") == side
                        and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                    ),
                    Decimal(0),
                )
                allocation = Decimal(
                    str(
                        allocations.get(
                            isolated_margin_key(selected_track_id, side),
                            "0",
                        )
                    )
                )
                if required + reserved > allocation:
                    raise TrainingRunError(
                        "RUN_ACCOUNT_MARGIN_EXCEEDED",
                        "position leverage change exceeds isolated leg wallet",
                        status_code=409,
                    )
        session_id = str(binding["adapter_session_id"])
        if command.type is ReplayV2CommandType.PLACE_ORDER:
            if trade_plan_draft is not None:
                provisional_plan = self._build_trade_plan_snapshot(
                    draft=trade_plan_draft,
                    payload=payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    entry_price=self._planned_entry_reference(
                        payload=payload,
                        selected_track=selected,
                    ),
                )
                try:
                    raw_plan_preview = await self.replay_service.preview_order(
                        session_id,
                        {**payload, "quantity": provisional_plan["quantity"]},
                    )
                except ReplayDomainError as exc:
                    raise TrainingRunError(
                        exc.code.value,
                        exc.message,
                        status_code=exc.http_status,
                        details=exc.details,
                    ) from exc
                plan_preview = service_validation_ops._stored_mapping(
                    raw_plan_preview.get("preview"),
                    field_name="adapter trade-plan preview",
                )
                normalized_plan = self._build_trade_plan_snapshot(
                    draft=trade_plan_draft,
                    payload=payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    entry_price=plan_preview.get("estimated_fill_price"),
                )
                if payload.get("quantity") != normalized_plan["quantity"]:
                    raise TrainingRunError(
                        "TRADE_PLAN_QUANTITY_CHANGED",
                        "planned quantity no longer matches the authoritative cursor",
                        status_code=409,
                        details={
                            "submitted_quantity": payload.get("quantity"),
                            "calculated_quantity": normalized_plan["quantity"],
                        },
                    )
                payload["trade_plan"] = normalized_plan
            self._assert_exact_account_order_filters(
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
            )
            self._assert_shared_settlement_reservation(
                payload=payload,
                selected_track=selected,
                portfolio=projection.get("portfolio"),
                binding=binding,
            )
        elif command.type is ReplayV2CommandType.REPLACE_ORDER:
            portfolio = projection.get("portfolio")
            if not isinstance(portfolio, Mapping):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "run portfolio projection is invalid",
                    status_code=503,
                )
            raw_orders = portfolio.get("orders")
            if not isinstance(raw_orders, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "active order projection is invalid",
                    status_code=503,
                )
            existing = next(
                (
                    order
                    for order in raw_orders
                    if isinstance(order, Mapping)
                    and order.get("order_id") == payload.get("order_id")
                    and order.get("track_id") == selected_track_id
                    and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                ),
                None,
            )
            if not isinstance(existing, Mapping):
                raise TrainingRunError(
                    "ORDER_REJECTED",
                    "replacement requires an open order on the selected track",
                    status_code=409,
                    details={"order_id": payload.get("order_id")},
                )
            replacement_payload = {
                "quantity": payload.get("quantity"),
                "reduce_only": existing.get("reduce_only"),
                "limit_price": payload.get("limit_price"),
                "stop_price": payload.get("stop_price"),
            }
            self._assert_exact_account_order_filters(
                payload=replacement_payload,
                selected_track=selected,
                portfolio=portfolio,
            )
            self._assert_shared_settlement_reservation(
                payload=replacement_payload,
                selected_track=selected,
                portfolio=portfolio,
                binding=binding,
                release_order_reservation=Decimal(
                    str(existing.get("reserved_margin", "0"))
                ),
            )
        elif command.type is ReplayV2CommandType.EXECUTE_POSITION_INTENT:
            intent = payload.get("intent")
            if intent in {"OPEN", "REVERSE"}:
                opening_payload = {
                    "quantity": payload.get("quantity"),
                    "reduce_only": False,
                    "limit_price": None,
                    "stop_price": None,
                    "leverage": payload.get("leverage"),
                    "position_side": payload.get("position_side"),
                }
                self._assert_exact_account_order_filters(
                    payload=opening_payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    replace_position=intent == "REVERSE",
                )
                self._assert_shared_settlement_reservation(
                    payload=opening_payload,
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                    binding=binding,
                    release_selected_margin=intent == "REVERSE",
                )
        elif command.type is ReplayV2CommandType.SET_POSITION_PROTECTION:
            position = selected.get("position")
            if (
                isinstance(position, Mapping)
                and position.get("position_mode") == "HEDGE"
            ):
                leg_name = str(payload.get("position_side", "")).lower()
                position = position.get(leg_name)
            raw_quantity = payload.get("quantity")
            if raw_quantity is None and isinstance(position, Mapping):
                try:
                    raw_quantity = normalize_decimal_string(
                        format(abs(Decimal(str(position.get("quantity")))), "f"),
                        field_name="protection quantity",
                    )
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "position protection quantity is invalid",
                        status_code=422,
                    ) from exc
            for field_name in ("stop_loss_price", "take_profit_price"):
                price = payload.get(field_name)
                if price is None:
                    continue
                self._assert_exact_account_order_filters(
                    payload={
                        "quantity": raw_quantity,
                        "reduce_only": True,
                        "limit_price": None,
                        "stop_price": price,
                    },
                    selected_track=selected,
                    portfolio=projection.get("portfolio"),
                )
        controller_snapshot = await self._ensure_track_controller(
            session_id=session_id,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
            known_snapshot=snapshot,
        )
        adapter = ReplayCommand(
            protocol=REPLAY_PROTOCOL,
            command_id=command.command_id,
            client_instance_id=command.client_instance_id,
            expected_revision=service_validation_ops._stored_counter(
                controller_snapshot["revision"], field_name="revision"
            ),
            type=v1_types[command.type],
            payload=payload,
        )
        try:
            acknowledged = await self.replay_service.command(session_id, adapter)
        except ReplayDomainError as exc:
            raise TrainingRunError(
                exc.code.value,
                exc.message,
                status_code=exc.http_status,
                details=exc.details,
            ) from exc
        await self.store.finalize_account_history(command.run_id)
        adapter_data = dict(
            service_validation_ops._stored_mapping(
                acknowledged.get("data"),
                field_name="adapter_result.data",
            )
        )
        liquidation_count = await self._reconcile_liquidations(
            run_id=command.run_id,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
        )
        if liquidation_count:
            acknowledged = self._snapshot(
                await self.replay_service.get_session(session_id)
            )
        checkpoint = await self.store.checkpoint_market_tracks(command.run_id)
        refreshed = await self.store.get_market_tracks(command.run_id)
        viewer = await self.store.get_viewer_state(command.run_id)
        return self._result_payload(
            command=command,
            session_id=session_id,
            snapshot=acknowledged,
            viewer=viewer.to_dict(),
            data={
                **adapter_data,
                "selected_track_id": selected_track_id,
                "portfolio": refreshed["portfolio"],
                "global_checkpoint": checkpoint,
                "account_contract": "TOUCH_OR_TAPE_V2_CONTRACT_ACCOUNT",
                "simulated_account_liquidations": liquidation_count,
            },
        )

    @staticmethod
    def _planned_entry_reference(
        *,
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
    ) -> object:
        return order_rules_ops.planned_entry_reference(payload=payload, selected_track=selected_track)

    @staticmethod
    def _active_instrument_rule(
        portfolio: Mapping[str, object],
        *,
        track_id: str,
    ) -> Mapping[str, object]:
        return order_rules_ops.active_instrument_rule(portfolio, track_id=track_id)

    @classmethod
    def _build_trade_plan_snapshot(
        cls,
        *,
        draft: Mapping[str, object],
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
        portfolio: object,
        entry_price: object,
    ) -> dict[str, object]:
        return order_rules_ops.build_trade_plan_snapshot(draft=draft, payload=payload, selected_track=selected_track, portfolio=portfolio, entry_price=entry_price)

    @staticmethod
    def _assert_exact_account_order_filters(
        *,
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
        portfolio: object,
        replace_position: bool = False,
    ) -> None:
        return order_rules_ops.assert_exact_account_order_filters(payload=payload, selected_track=selected_track, portfolio=portfolio, replace_position=replace_position)

    @staticmethod
    def _assert_exact_account_capacity_context(
        *,
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
        portfolio: object,
    ) -> None:
        return order_rules_ops.assert_exact_account_capacity_context(payload=payload, selected_track=selected_track, portfolio=portfolio)

    @staticmethod
    def _shared_order_capacity_quantity(
        *,
        adapter_max_quantity: object,
        reference_price: object,
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
        portfolio: object,
        binding: Mapping[str, object],
    ) -> str:
        return order_rules_ops.shared_order_capacity_quantity(adapter_max_quantity=adapter_max_quantity, reference_price=reference_price, payload=payload, selected_track=selected_track, portfolio=portfolio, binding=binding)

    async def _reconcile_liquidations(
        self,
        *,
        run_id: str,
        client_instance_id: str,
        command_id: str,
        pending: Sequence[Mapping[str, object]] | None = None,
    ) -> int:
        return await self._ordered_playback._reconcile_liquidations(run_id=run_id, client_instance_id=client_instance_id, command_id=command_id, pending=pending)

    async def _resume_durable_liquidation_command(
        self,
        *,
        session_id: str,
        proposed: ReplayCommand,
    ) -> ReplayCommand:
        """Reuse the exact durable broker envelope after response/process loss."""
        return await self._ordered_playback._resume_durable_liquidation_command(session_id=session_id, proposed=proposed)

    @staticmethod
    def _assert_shared_settlement_reservation(
        *,
        payload: Mapping[str, object],
        selected_track: Mapping[str, object],
        portfolio: object,
        binding: Mapping[str, object],
        release_selected_margin: bool = False,
        release_order_reservation: Decimal = Decimal(0),
    ) -> None:
        return order_rules_ops.assert_shared_settlement_reservation(payload=payload, selected_track=selected_track, portfolio=portfolio, binding=binding, release_selected_margin=release_selected_margin, release_order_reservation=release_order_reservation)

    async def _activate_existing_track(
        self,
        *,
        command: ReplayV2Command,
        track: Mapping[str, object],
        target_virtual_time_ms: int,
    ) -> None:
        return await self._ordered_playback._activate_existing_track(command=command, track=track, target_virtual_time_ms=target_virtual_time_ms)

    async def _execute_multi_track_control(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        selected_snapshot: Mapping[str, object],
        tracks: list[Mapping[str, object]],
    ) -> dict[str, object]:
        return await self._ordered_playback._execute_multi_track_control(command=command, binding=binding, selected_snapshot=selected_snapshot, tracks=tracks)

    def _multi_control_result(self, *, command, selected_session_id, final, viewer,
                              fast_forward_plan, control_plan, advance_job, source_goal,
                              ordered, total_events, event_stop, stable_order_state, executed_multi):
        return self._ordered_playback._multi_control_result(command=command, selected_session_id=selected_session_id, final=final, viewer=viewer, fast_forward_plan=fast_forward_plan, control_plan=control_plan, advance_job=advance_job, source_goal=source_goal, ordered=ordered, total_events=total_events, event_stop=event_stop, stable_order_state=stable_order_state, executed_multi=executed_multi)

    async def _run_ordered_playback(
        self,
        *,
        run_id: str,
        generation: int,
        stop: asyncio.Event,
    ) -> None:
        """Drive every FULL track from one wall-clock-independent ordered lane."""
        return await self._ordered_playback._run_ordered_playback(run_id=run_id, generation=generation, stop=stop)

    async def _ordered_source_goal(
        self,
        tracks: tuple[Mapping[str, object], ...],
        *,
        max_events: int,
        require_exact_count: bool = True,
        expected_snapshot: Mapping[str, object] | None = None,
    ) -> control_rules_ops._OrderedSourceGoal | None:
        return await self._ordered_playback._ordered_source_goal(tracks, max_events=max_events, require_exact_count=require_exact_count, expected_snapshot=expected_snapshot)

    async def _end_multi_track_run(
        self,
        *,
        command: ReplayV2Command,
        tracks: tuple[Mapping[str, object], ...],
        selected_session_id: str,
    ) -> dict[str, object]:
        return await self._ordered_playback._end_multi_track_run(command=command, tracks=tracks, selected_session_id=selected_session_id)

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
        return await self._ordered_playback._advance_full_tracks_to(command=command, binding=binding, tracks=tracks, target_virtual_time_ms=target_virtual_time_ms, job=job, stop_event=stop_event, allow_final_state_batch=allow_final_state_batch, audit_account_at_barrier=audit_account_at_barrier, source_goal=source_goal, stable_order_state=stable_order_state, event_stop=event_stop, terminal_result_factory=terminal_result_factory)

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
        return self._ordered_playback._ordered_final_state_batch_profile(binding=binding, tracks=tracks, snapshot=snapshot, target_virtual_time_ms=target_virtual_time_ms, enabled=enabled, held_certificate=held_certificate)

    async def prepare_indexed_run(self, run_id, *, client_instance_id=None):
        normalized = self._identifier(run_id, field_name="run_id")
        client = None if client_instance_id is None else self._identifier(client_instance_id, field_name="client_instance_id")
        actor = self._run_actors.setdefault(normalized, TrainingRunActor(normalized))
        async with actor.serialized():
            result = await self._prepare_indexed_run_serialized(normalized)
            if (client is not None and result["status"] == "READY"
                    and self.replay_service.settings.replay_multi_bar_interval_enabled):
                from .controller_preparation import prepare_controllers
                result["controller_ready"] = await prepare_controllers(self, normalized, client)
            return result

    async def _prepare_indexed_run_serialized(self, run_id):
        run_id = self._identifier(run_id, field_name="run_id")
        binding = await self.store.run_binding(run_id)
        tracks = tuple(await self.store.get_market_track_heads(run_id))
        result = {
            "protocol": REPLAY_V2_PROTOCOL,
            "run_id": run_id,
            "status": "SKIPPED",
            "prepared_events": 0,
        }
        if (
            binding.get("source_kind") != "BAR"
            or binding.get("position_mode") != "HEDGE"
            or (len(tracks) != 1 and not (
                self.replay_service.settings.replay_multi_bar_interval_enabled
                and 2 <= len(tracks) <= 8
            ))
            or binding.get("book_mode", "OFF") != "OFF"
            or binding.get("account_data_mode")
            == AccountDataMode.HISTORICAL_EXACT.value
        ):
            return result
        if len(tracks) > 1:
            count = 0
            for track in tracks:
                sid = self._track_session_id(track)
                snapshot = self._snapshot(await self.replay_service.get_session(sid))
                if snapshot.get("state") != "PAUSED":
                    return result
                prepared = await self.replay_service.plan_source_chunk(
                    sid, target_time_ms=self._cursor_time(snapshot), max_events=100_000, indexed=True
                )
                if not prepared or not getattr(prepared["index"], "shared", False):
                    return result
                await asyncio.to_thread(prepared["index"].prepare_transport_tail, 16)
                count += prepared["prepared_events"]
            inputs = await self.hedge_inputs.runtime_snapshot(run_id)
            if isinstance(inputs, IndexedHedgeSnapshot):
                for lane in inputs.lanes:
                    _ = lane.price_index, lane.barrier_indices
                await asyncio.to_thread(lambda: inputs.portfolio_prices)
                from .public_price_blocks import prepare_price_blocks
                public_rows = await self.store.base_store.run_extension_read(
                    lambda connection: connection.execute(
                        "SELECT b.track_id,b.public_checksum_sha256,a.local_path FROM replay_hedge_track_public_binding b JOIN replay_hedge_public_archive a ON a.archive_id=b.public_archive_id WHERE b.run_id=?", (run_id,)
                    ).fetchall())
                public_lanes = {lane.track_id: lane for lane in inputs.lanes if lane.source_kind == "PUBLIC"}
                def prepare_blocks():
                    for row in public_rows:
                        if row["track_id"] in public_lanes:
                            path = (self.hedge_inputs.root / row["local_path"]).resolve()
                            if not path.is_relative_to(self.hedge_inputs.root):
                                raise ValueError("public price input escaped its owner")
                            prepare_price_blocks(path, row["public_checksum_sha256"], public_lanes[row["track_id"]].events)
                await asyncio.to_thread(prepare_blocks)
            fingerprint = await self.replay_service.store.run_extension_read(
                lambda connection:account_marks_ops.hedge_risk_fingerprint(connection,run_id=run_id))
            if self.store._hedge_risk_fingerprints.get(run_id) != fingerprint:
                audit = await self.audit_account(run_id)
                if audit['status'] != 'PASS':
                    raise TrainingRunError('TRAINING_ACCOUNT_AUDIT_FAILED',
                        'account validation failed during interval preparation',status_code=409)
                self.store._cache_committed_hedge_fingerprint(run_id,fingerprint)
            return {**result, "status": "READY", "prepared_events": count}
        session_id = self._track_session_id(tracks[0])
        snapshot = self._snapshot(await self.replay_service.get_session(session_id))
        if snapshot.get("state") != "PAUSED":
            return result
        prepared = await self.replay_service.plan_source_chunk(
            session_id,
            target_time_ms=self._cursor_time(snapshot),
            max_events=100_000,
            indexed=True,
        )
        if not prepared:
            return result
        await self.store.prepare_indexed_curve(run_id, prepared["index"])
        inputs = await self.hedge_inputs.runtime_snapshot(run_id)
        if isinstance(inputs, IndexedHedgeSnapshot):
            for lane in inputs.lanes:
                _ = lane.price_index, lane.barrier_indices
        return {**result, "status": "READY", "prepared_events": prepared["prepared_events"]}

    async def _try_indexed_interval(
        self, *, command, binding, tracks, snapshot, target, runtime_snapshot
    ):
        return await self._ordered_playback._try_indexed_interval(command=command, binding=binding, tracks=tracks, snapshot=snapshot, target=target, runtime_snapshot=runtime_snapshot)

    async def _try_recorded_interval(
        self, *, command, binding, tracks, snapshot, target, runtime_snapshot
    ):
        return await self._ordered_playback._try_recorded_interval(command=command, binding=binding, tracks=tracks, snapshot=snapshot, target=target, runtime_snapshot=runtime_snapshot)

    async def _held_interval_batch_end(
        self, run_id: str, *, binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...], snapshot: Mapping[str, object],
        target_virtual_time_ms: int, runtime_snapshot, cursor_view=None,
    ) -> int | None:
        # Price-varying marks require the original per-event position/margin
        # ledger. Only a constant authoritative mark preserves that history.
        return await self._ordered_playback._held_interval_batch_end(run_id, binding=binding, tracks=tracks, snapshot=snapshot, target_virtual_time_ms=target_virtual_time_ms, runtime_snapshot=runtime_snapshot, cursor_view=cursor_view)

    @staticmethod
    def _stop_on_event(command: ReplayV2Command) -> bool:
        return control_rules_ops.stop_on_event(command)

    @staticmethod
    def _interaction_reason(before: Mapping[str, object], after: Mapping[str, object]) -> str | None:
        return control_rules_ops.interaction_reason(before, after)

    @staticmethod
    def _snapshot_is_flat(snapshot: Mapping[str, object]) -> bool:
        return control_rules_ops.snapshot_is_flat(snapshot)

    def _ordered_playback_interactive_batch_limit(
        self,
        *,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        snapshot: Mapping[str, object],
        target_virtual_time_ms: int,
    ) -> int:
        """Bound a playing account to one durable market barrier per Run lock."""
        return self._ordered_playback._ordered_playback_interactive_batch_limit(binding=binding, tracks=tracks, snapshot=snapshot, target_virtual_time_ms=target_virtual_time_ms)

    @staticmethod
    def _actual_event_time_ms(
        binding: Mapping[str, object],
        virtual_time_ms: int,
    ) -> int:
        return control_rules_ops.actual_event_time_ms(binding, virtual_time_ms)

    @staticmethod
    def _virtual_event_time_ms(
        binding: Mapping[str, object],
        actual_time_ms: int,
    ) -> int:
        return control_rules_ops.virtual_event_time_ms(binding, actual_time_ms)

    async def _guard_historical_book_current(
        self,
        *,
        run_id: str,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        tracks: list[Mapping[str, object]] | None = None,
    ) -> None:
        return await self._order_service._guard_historical_book_current(run_id=run_id, binding=binding, snapshot=snapshot, tracks=tracks)

    async def _next_global_event_time(
        self,
        *,
        run_id: str,
        binding: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
    ) -> int:
        return await self._ordered_playback._next_global_event_time(run_id=run_id, binding=binding, tracks=tracks)

    @staticmethod
    def _training_terminal_time_ms(binding: Mapping[str, object]) -> int:
        return control_rules_ops.training_terminal_time_ms(binding)

    async def _finalize_deferred_full_tracks(
        self,
        *,
        command: ReplayV2Command,
        tracks: tuple[Mapping[str, object], ...],
    ) -> None:
        """End actors only after the committed global terminal input barrier."""
        return await self._ordered_playback._finalize_deferred_full_tracks(command=command, tracks=tracks)

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
        return await self._ordered_playback._advance_adapter_to(session_id=session_id, target_virtual_time_ms=target_virtual_time_ms, client_instance_id=client_instance_id, command_id=command_id, track_id=track_id, initial_snapshot=initial_snapshot, final_state_max_events=final_state_max_events, require_empty_account=require_empty_account, target_source_sequence=target_source_sequence, defer_source_terminal=defer_source_terminal)

    async def _ensure_track_controller(
        self,
        *,
        session_id: str,
        client_instance_id: str,
        command_id: str,
        known_snapshot: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        return await self._ordered_playback._ensure_track_controller(session_id=session_id, client_instance_id=client_instance_id, command_id=command_id, known_snapshot=known_snapshot)

    async def _pause_ready_full_tracks(
        self,
        run_id: str,
        client_instance_id: str,
    ) -> None:
        return await self._ordered_playback._pause_ready_full_tracks(run_id, client_instance_id)

    async def _fail_closed_multi_track(
        self,
        *,
        run_id: str,
        tracks: tuple[Mapping[str, object], ...],
        failed_track: Mapping[str, object],
        client_instance_id: str,
        reason: str,
    ) -> None:
        return await self._ordered_playback._fail_closed_multi_track(run_id=run_id, tracks=tracks, failed_track=failed_track, client_instance_id=client_instance_id, reason=reason)

    async def _market_track_result(
        self,
        *,
        command: ReplayV2Command,
        session_id: str,
        snapshot: Mapping[str, object],
        data: Mapping[str, object],
    ) -> dict[str, object]:
        return await self._ordered_playback._market_track_result(command=command, session_id=session_id, snapshot=snapshot, data=data)

    @staticmethod
    def _result_payload(
        *,
        command: ReplayV2Command,
        session_id: str,
        snapshot: Mapping[str, object],
        viewer: Mapping[str, object],
        data: Mapping[str, object],
    ) -> dict[str, object]:
        return command_projection_ops.result_payload(command=command, session_id=session_id, snapshot=snapshot, viewer=viewer, data=data)

    @classmethod
    def project_public_command_result(
        cls,
        result: Mapping[str, object],
    ) -> dict[str, object]:
        return command_projection_ops.project_public_command_result(result)

    @classmethod
    def _project_public_command_value(cls, value: object) -> object:
        return command_projection_ops.project_public_command_value(value)

    @staticmethod
    def _cursor_time(snapshot: Mapping[str, object]) -> int:
        return service_validation_ops.cursor_time(snapshot)

    @staticmethod
    def _track_session_id(track: Mapping[str, object]) -> str:
        return service_validation_ops.track_session_id(track)

    @staticmethod
    def _multi_command_id(
        command_id: str,
        track_id: str,
        operation: str,
        revision: int,
    ) -> str:
        return control_rules_ops.multi_command_id(command_id, track_id, operation, revision)

    @staticmethod
    def _assert_same_market_scope(
        *,
        binding: Mapping[str, object],
        exchange: str,
        market_type: str,
        settlement_asset: str,
    ) -> None:
        return admission_rules_ops.assert_same_market_scope(binding=binding, exchange=exchange, market_type=market_type, settlement_asset=settlement_asset)

    def _authoritative_instrument_identity(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> dict[str, str]:
        return self._admission_service._authoritative_instrument_identity(exchange=exchange, market_type=market_type, symbol=symbol)

    def _prune_market_track_plans(self, now_ms: int) -> None:
        return self._admission_service._prune_market_track_plans(now_ms)

    def _claim_market_track_plan(
        self,
        *,
        run_id: str,
        plan_id: str,
        selected_snapshot: Mapping[str, object],
    ) -> admission_rules_ops._MarketTrackPlan:
        return self._admission_service._claim_market_track_plan(run_id=run_id, plan_id=plan_id, selected_snapshot=selected_snapshot)

    async def _execute_policy_command(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        session_id: str,
    ) -> dict[str, object]:
        command_value = command.type.value
        integrity_mode = IntegrityMode(str(binding["integrity_mode"]))
        allowed_payload = binding["allowed_mutations"]
        if not isinstance(allowed_payload, (list, tuple)) or any(
            not isinstance(item, str) for item in allowed_payload
        ):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training mutation allowlist is invalid",
                status_code=503,
            )
        allowed = {str(item) for item in allowed_payload}
        if integrity_mode is IntegrityMode.CHALLENGE:
            if command.type is not ReplayV2CommandType.REVEAL_TIME:
                raise TrainingRunError(
                    "INTEGRITY_POLICY_REJECTED",
                    "CHALLENGE integrity mode rejects policy mutations",
                    status_code=409,
                    details={"command": command_value},
                )
            if snapshot["state"] != "ENDED":
                raise TrainingRunError(
                    "INTEGRITY_POLICY_REJECTED",
                    "CHALLENGE time reveal is available only after the run ended",
                    status_code=409,
                )
        elif integrity_mode is IntegrityMode.PRACTICE and command_value not in allowed:
            raise TrainingRunError(
                "INTEGRITY_POLICY_REJECTED",
                "PRACTICE mutation is not in the creation-time allowlist",
                status_code=409,
                details={"command": command_value},
            )
        if command.type in {
            ReplayV2CommandType.CHANGE_FEE_POLICY,
            ReplayV2CommandType.CHANGE_LEVERAGE_CAP,
            ReplayV2CommandType.CHANGE_FUNDING_POLICY,
        }:
            if command.type is ReplayV2CommandType.CHANGE_FEE_POLICY:
                policy_payload = dict(
                    self._exact_payload(
                        command.payload,
                        {"maker_fee_bps", "taker_fee_bps", "reason"},
                    )
                )
                decimal_fields = ("maker_fee_bps", "taker_fee_bps")
            elif command.type is ReplayV2CommandType.CHANGE_LEVERAGE_CAP:
                policy_payload = dict(
                    self._exact_payload(
                        command.payload,
                        {"max_leverage", "reason"},
                    )
                )
                decimal_fields = ("max_leverage",)
            else:
                policy_payload = dict(
                    self._exact_payload(
                        command.payload,
                        {
                            "funding_mode",
                            "fixed_funding_rate",
                            "funding_interval_ms",
                            "reason",
                        },
                    )
                )
                decimal_fields = ()
            reason = policy_payload.get("reason")
            if (
                not isinstance(reason, str)
                or not reason.strip()
                or len(reason.strip()) > 500
            ):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "policy revision reason must contain 1-500 characters",
                    status_code=422,
                )
            policy_payload["reason"] = reason.strip()
            for field_name in decimal_fields:
                value = policy_payload.get(field_name)
                if not isinstance(value, str):
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        f"{field_name} must be a canonical Decimal string",
                        status_code=422,
                    )
                try:
                    normalized = normalize_decimal_string(
                        value,
                        field_name=field_name,
                    )
                except (TypeError, ValueError) as exc:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        f"{field_name} is invalid",
                        status_code=422,
                    ) from exc
                positive = field_name == "max_leverage"
                decimal_value = Decimal(value)
                if (
                    normalized != value
                    or (positive and decimal_value <= 0)
                    or (not positive and decimal_value < 0)
                ):
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        f"{field_name} is outside the supported range",
                        status_code=422,
                    )
            if command.type is ReplayV2CommandType.CHANGE_FUNDING_POLICY:
                if integrity_mode is not IntegrityMode.SANDBOX:
                    raise TrainingRunError(
                        "INTEGRITY_POLICY_REJECTED",
                        "custom funding policy is available only in SANDBOX",
                        status_code=409,
                    )
                mode = policy_payload.get("funding_mode")
                rate = policy_payload.get("fixed_funding_rate")
                interval = policy_payload.get("funding_interval_ms")
                if mode == "OFF":
                    if rate is not None or interval is not None:
                        raise TrainingRunError(
                            "REPLAY_CONTROL_INVALID",
                            "OFF funding cannot include fixed funding fields",
                            status_code=422,
                        )
                elif mode == "SANDBOX_FIXED":
                    if not isinstance(rate, str) or not isinstance(interval, int):
                        raise TrainingRunError(
                            "REPLAY_CONTROL_INVALID",
                            "SANDBOX_FIXED funding requires Decimal rate and interval",
                            status_code=422,
                        )
                    try:
                        normalized_rate = normalize_decimal_string(
                            rate,
                            field_name="fixed_funding_rate",
                        )
                    except (TypeError, ValueError) as exc:
                        raise TrainingRunError(
                            "REPLAY_CONTROL_INVALID",
                            "fixed funding rate is invalid",
                            status_code=422,
                        ) from exc
                    if (
                        normalized_rate != rate
                        or isinstance(interval, bool)
                        or not 60_000 <= interval <= 30 * 86_400_000
                    ):
                        raise TrainingRunError(
                            "REPLAY_CONTROL_INVALID",
                            "fixed funding policy is outside supported bounds",
                            status_code=422,
                        )
                else:
                    raise TrainingRunError(
                        "HISTORICAL_FUNDING_UNAVAILABLE",
                        "historical exact funding cannot be enabled without aligned history",
                        status_code=409,
                        details={"fallback_applied": False},
                    )
            cursor = service_validation_ops._stored_mapping(snapshot["cursor"], field_name="adapter cursor")
            policy = await self.store.revise_contract_policy(
                run_id=command.run_id,
                command_id=command.command_id,
                command_type=command_value,
                payload=policy_payload,
                virtual_time_ms=service_validation_ops._stored_counter(
                    cursor["virtual_time_ms"],
                    field_name="virtual_time_ms",
                ),
                source_sequence=service_validation_ops._stored_counter(
                    cursor["source_sequence"],
                    field_name="source_sequence",
                ),
            )
            viewer = await self.store.get_viewer_state(command.run_id)
            return self._result_payload(
                command=command,
                session_id=session_id,
                snapshot=snapshot,
                viewer=viewer.to_dict(),
                data={
                    "policy_command": command_value,
                    "atomic": True,
                    "applied": True,
                    **policy,
                },
            )
        if command.type is ReplayV2CommandType.REVEAL_TIME:
            if bool(binding["revealed"]):
                raise TrainingRunError(
                    "TIME_ALREADY_REVEALED",
                    "training time disclosure is already irreversible",
                    status_code=409,
                )
            if set(command.payload) not in (set(), {"reason"}):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "reveal_time accepts only an optional reason",
                    status_code=422,
                )
            reason = command.payload.get("reason", "user reveal")
            if (
                not isinstance(reason, str)
                or not reason.strip()
                or len(reason.strip()) > 500
            ):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "reveal reason must contain 1-500 characters",
                    status_code=422,
                )
            v1_type = InternalCommandType.REVEAL_HISTORY_AUTHORIZED
            v1_payload: dict[str, object] = {"reason": reason.strip()}
        else:
            payload = self._exact_payload(command.payload, {"amount", "reason"})
            amount = payload["amount"]
            reason = payload["reason"]
            if not isinstance(amount, str) or not isinstance(reason, str):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "capital mutation requires Decimal amount and reason strings",
                    status_code=422,
                )
            try:
                normalized_amount = normalize_decimal_string(
                    amount,
                    field_name="capital amount",
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "capital amount is invalid",
                    status_code=422,
                ) from exc
            if normalized_amount != amount or Decimal(amount) <= 0:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "capital amount must be a positive canonical Decimal string",
                    status_code=422,
                )
            normalized_reason = reason.strip()
            if not normalized_reason or len(normalized_reason) > 500:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "capital mutation reason must contain 1-500 characters",
                    status_code=422,
                )
            v1_type = InternalCommandType.ADJUST_CAPITAL
            v1_payload = {
                "kind": command_value,
                "amount": normalized_amount,
                "reason": normalized_reason,
            }
        v1_command = ReplayCommand(
            protocol=REPLAY_PROTOCOL,
            command_id=command.command_id,
            client_instance_id=command.client_instance_id,
            expected_revision=command.expected_revision,
            type=v1_type,
            payload=v1_payload,
        )
        try:
            adapter_result = await self.replay_service.command(
                session_id,
                v1_command,
                _training_internal=True,
            )
        except ReplayDomainError as exc:
            raise TrainingRunError(
                exc.code.value,
                exc.message,
                status_code=exc.http_status,
                details=exc.details,
            ) from exc
        viewer = await self.store.get_viewer_state(command.run_id)
        adapter_data = adapter_result["data"]
        if not isinstance(adapter_data, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "adapter command data is invalid",
                status_code=503,
            )
        return {
            "protocol": "replay.v3",
            "run_id": command.run_id,
            "session_id": session_id,
            "command_id": command.command_id,
            "revision": adapter_result["revision"],
            "sequence": adapter_result["sequence"],
            "state": adapter_result["state"],
            "state_hash": adapter_result["state_hash"],
            "cursor": adapter_result["cursor"],
            "viewer_state": viewer.to_dict(),
            "data": {
                **dict(adapter_data),
                "integrity_mode": integrity_mode.value,
                "policy_command": command_value,
                "adapter_command": v1_type.value,
            },
        }

    def _plan_fast_forward(
        self,
        *,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
        tracks: tuple[Mapping[str, object], ...],
        target_virtual_time_ms: int,
        summary: ReplayPeriodSummary | None = None,
    ) -> FastForwardDecision:
        return self._ordered_playback._plan_fast_forward(binding=binding, snapshot=snapshot, tracks=tracks, target_virtual_time_ms=target_virtual_time_ms, summary=summary)

    @staticmethod
    def _fast_forward_plan_payload(
        decision: FastForwardDecision,
        *,
        summary_lookup: Mapping[str, object],
    ) -> dict[str, object]:
        return control_rules_ops.fast_forward_plan_payload(decision, summary_lookup=summary_lookup)

    async def get_advance_progress(
        self,
        run_id: str,
        command_id: str,
    ) -> dict[str, object]:
        return await self._advance_service.get_advance_progress(run_id, command_id)

    async def _set_display_interval(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        return await self._display_service._set_display_interval(command=command, binding=binding, snapshot=snapshot)

    async def _validate_display_binding(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        base_interval: str,
        display_interval: object,
        viewer_revision: object,
    ) -> tuple[str, int]:
        return await self._display_service._validate_display_binding(command=command, binding=binding, base_interval=base_interval, display_interval=display_interval, viewer_revision=viewer_revision)

    async def _display_advance_target(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        base_interval: str,
        current_time: int,
        count: int,
        display_interval: object,
        viewer_revision: object,
    ) -> tuple[int, str, int]:
        return await self._display_service._display_advance_target(command=command, binding=binding, base_interval=base_interval, current_time=current_time, count=count, display_interval=display_interval, viewer_revision=viewer_revision)

    async def _display_source_bucket_anchor_ms(
        self,
        *,
        binding: Mapping[str, object],
        display_interval: str,
    ) -> int | None:
        return await self._display_service._display_source_bucket_anchor_ms(binding=binding, display_interval=display_interval)

    async def _source_aligned_display_target(
        self,
        *,
        binding: Mapping[str, object],
        current_virtual_time_ms: int,
        base_interval: str,
        display_interval: str,
        count: int,
    ) -> int:
        return await self._display_service._source_aligned_display_target(binding=binding, current_virtual_time_ms=current_virtual_time_ms, base_interval=base_interval, display_interval=display_interval, count=count)

    @staticmethod
    def _legacy_playback_rate(value: object) -> int:
        return control_rules_ops.legacy_playback_rate(value)

    async def _playback_profile(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        selected_snapshot: Mapping[str, object],
        full_track_count: int,
        actor: TrainingRunActor,
    ) -> tuple[AdvanceBasis, int, str | None, int | None, bool]:
        """Validate one canonical profile or resolve a legacy default.

        The returned boolean marks the old empty-PLAY / speed-only contract.
        It is used only to preserve adapter compatibility; the public clock is
        always normalized to replay.playback.v1.
        """
        return await self._display_service._playback_profile(command=command, binding=binding, selected_snapshot=selected_snapshot, full_track_count=full_track_count, actor=actor)

    async def _translate_control(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> tuple[CommandType, dict[str, object], dict[str, object]]:
        return await self._display_service._translate_control(command=command, binding=binding, snapshot=snapshot)

    @staticmethod
    def _snapshot(session: Mapping[str, object]) -> Mapping[str, object]:
        return service_validation_ops.adapter_snapshot(session)

    @staticmethod
    def _assert_expected_cursor(
        command: ReplayV2Command,
        session: Mapping[str, object],
    ) -> Mapping[str, object]:
        return service_validation_ops.assert_expected_cursor(command, session)

    @staticmethod
    def _exact_payload(
        payload: Mapping[str, object],
        expected: set[str],
    ) -> Mapping[str, object]:
        return service_validation_ops.exact_payload(payload, expected)

    @classmethod
    def _order_payload_with_optional_leverage(
        cls,
        payload: Mapping[str, object],
        expected: set[str],
    ) -> Mapping[str, object]:
        return order_rules_ops.order_payload_with_optional_leverage(payload, expected)

    @staticmethod
    def _selection_warmup_bars(request: TrainingRunCreateRequest) -> int:
        return admission_rules_ops.selection_warmup_bars(request)

    @staticmethod
    def _adapter_config(
        request: TrainingRunCreateRequest,
        *,
        warmup_bars: int | None = None,
    ) -> ReplaySessionConfig:
        return admission_rules_ops.adapter_config(request, warmup_bars=warmup_bars)

    @staticmethod
    def _identifier(value: object, *, field_name: str) -> str:
        return service_validation_ops.identifier(value, field_name=field_name)

    def _authoritative_start_request(
        self,
        request: TrainingRunCreateRequest,
    ) -> TrainingRunCreateRequest:
        return self._admission_service._authoritative_start_request(request)

    def _authoritative_random_seed(self) -> int:
        return self._admission_service._authoritative_random_seed()

    @staticmethod
    def _catalog_identity_key(entry: Mapping[str, object]) -> tuple[str, str, str]:
        return admission_rules_ops.catalog_identity_key(entry)

    @staticmethod
    def _market_start_compatibility(
        entry: Mapping[str, object],
        committed_start_ms: int,
    ) -> dict[str, object]:
        return admission_rules_ops.market_start_compatibility(entry, committed_start_ms)

    @staticmethod
    def _progressive_admission_settings(setup, initial_horizon_ms):
        return admission_rules_ops.progressive_admission_settings(setup, initial_horizon_ms)

    async def _require_market_at_committed_start(
        self,
        *,
        selection: TrainingRunMarketSelectionRequest,
        setup: TrainingRunSetupRequest,
        commitment: Mapping[str, object],
        progressive_initial_horizon_ms: int | None = None,
    ) -> None:
        return await self._admission_service._require_market_at_committed_start(selection=selection, setup=setup, commitment=commitment, progressive_initial_horizon_ms=progressive_initial_horizon_ms)

    async def _source_catalog_for_setup(
        self,
        settings: Mapping[str, object],
    ) -> dict[str, object]:
        return await self._admission_service._source_catalog_for_setup(settings)

    @staticmethod
    def _setup_market_compatibility(
        settings: Mapping[str, object],
        entry: Mapping[str, object],
        *,
        capability_admission: Mapping[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
        committed_start_ms: int | None,
    ) -> dict[str, object]:
        return admission_rules_ops.setup_market_compatibility(settings, entry, capability_admission=capability_admission, committed_start_ms=committed_start_ms)

    async def _setup_capability_admission(
        self,
        settings: Mapping[str, object],
    ) -> dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission]:
        return await self._admission_service._setup_capability_admission(settings)

    @staticmethod
    def _setup_admission_cache_key(
        settings: Mapping[str, object],
    ) -> control_rules_ops._SetupAdmissionCacheKey:
        return admission_rules_ops.setup_admission_cache_key(settings)

    @staticmethod
    def _eligible_source_ranges(
        entries: Sequence[Mapping[str, object]],
        *,
        range_start_ms: int,
        range_end_ms: int,
        settings: Mapping[str, object],
        capability_admission: Mapping[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
    ) -> list[tuple[int, int, int]]:
        return admission_rules_ops.eligible_source_ranges(entries, range_start_ms=range_start_ms, range_end_ms=range_end_ms, settings=settings, capability_admission=capability_admission)

    @staticmethod
    def _public_time_commitment(
        commitment: Mapping[str, object],
        *,
        disclose_start: bool,
    ) -> dict[str, object]:
        return admission_rules_ops.public_time_commitment(commitment, disclose_start=disclose_start)


__all__ = ["TrainingRunService"]
