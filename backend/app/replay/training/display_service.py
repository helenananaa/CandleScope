"""TrainingDisplayService with explicit runtime dependencies and shared per-service state."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace

from app.data_engine.interval_policy import (
    VALID_INTERVALS,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.canonical import canonical_sha256
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.constants import (
    CommandType,
)
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.models import (
    MAX_TIMESTAMP_MS,
)

from . import control_rules as control_rules_ops
from . import display_state as display_state_ops
from . import service_validation as service_validation_ops
from .commands import ReplayV2Command
from .control import (
    ADVANCE_CONTRACT_VERSION,
    advance_basis,
    aligned_step_target_ms,
    compatible_step_interval_ms,
    control_count,
    control_rate,
    default_playback_basis,
    source_aligned_step_target_ms,
    supported_advance_bases,
    supported_playback_bases,
    validate_bar_duration_ms,
    virtual_duration_ms,
)
from .errors import TrainingRunError
from .history import (
    build_display_projection,
    build_history_page,
    _progressive_repository,
    is_progressive_dataset,
    is_requested_horizon_dataset,
)
from .models import (
    AdvanceBasis,
    ReplayV2CommandType,
    SubscriptionTier,
)
from .multitrack import (
    TrainingRunActor,
)


class TrainingDisplayService:
    """Own display operations outside command orchestration."""

    def __init__(
        self,
        *,
        store,
        replay_service,
        display_source_grid_anchors,
        native_display_pin_proofs,
    ) -> None:
        self.store = store
        self.replay_service = replay_service
        self._display_source_grid_anchors = display_source_grid_anchors
        self._native_display_pin_proofs = native_display_pin_proofs

    def _remember_native_display_pin_proof(
        self,
        key: display_state_ops._NativeDisplayPinProofKey,
        proof: display_state_ops._NativeDisplayPinProof,
    ) -> None:
        self._native_display_pin_proofs[key] = proof
        self._native_display_pin_proofs.move_to_end(key)
        if (
            len(self._native_display_pin_proofs)
            > display_state_ops._NATIVE_DISPLAY_PIN_PROOF_CACHE_SIZE
        ):
            self._native_display_pin_proofs.popitem(last=False)

    async def _attach_native_display_archive_pin(
        self,
        binding: Mapping[str, object],
        *,
        display_interval: str | None,
        require_projection_grid: bool = False,
        persisted: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Bind optional chart context without changing the execution snapshot."""

        # Automatic preparation seals a finite base window, without downloading
        # separate native intervals. Aggregate that same revision for charts and
        # interval commands; unrelated native archives must not become required.
        if persisted is not None and is_requested_horizon_dataset(persisted):
            return dict(binding)

        requested_interval = (
            str(binding["display_interval"])
            if display_interval is None
            else display_interval
        )
        base_interval = str(binding["base_interval"])
        policy = binding.get("history_policy")
        lookback = (
            policy.get("visible_history_lookback")
            if isinstance(policy, Mapping)
            else None
        )
        if requested_interval == base_interval or (
            not require_projection_grid
            and (
                not isinstance(lookback, Mapping)
                or lookback.get("mode") != "ALL_AVAILABLE"
            )
        ):
            return dict(binding)

        run_id = str(binding["run_id"])
        track_id = str(binding["track_id"])
        interval_ms = parse_interval_ms(requested_interval)
        if interval_ms is None or interval_ms < 1:
            return dict(binding)
        actual_replay_start_ms = int(policy["actual_replay_start_ms"])
        strict_native_source = (
            str(binding.get("exchange", "")).lower() == "binance"
            and str(binding.get("market_type", "")).lower() == "spot"
            and str(binding.get("source_kind", "")).upper() == "BAR"
        )
        if getattr(self.replay_service, "_native_intervals_explicit", False):
            try:
                advertised_native_intervals = set(
                    self.replay_service._native_intervals(  # noqa: SLF001
                        ReplaySeriesIdentity(
                            str(binding["exchange"]),
                            str(binding["market_type"]),
                            str(binding["symbol"]),
                        )
                    )
                )
            except Exception as exc:
                raise TrainingRunError(
                    "HISTORY_SOURCE_UNAVAILABLE",
                    "native display interval capabilities are unavailable",
                    status_code=503,
                ) from exc
        else:
            advertised_native_intervals = set(VALID_INTERVALS)
        native_display_required = (
            strict_native_source and requested_interval in advertised_native_intervals
        )
        # BTC can legitimately have exchange-maintenance holes on intraday
        # series. Daily and wider native bars must remain continuous; otherwise
        # a missing archive object turns into exactly the giant chart gaps this
        # path is responsible for preventing.
        zero_gap_native_required = strict_native_source and interval_ms >= 86_400_000

        def resolve_source_grid(
            bounds: Mapping[str, object],
        ) -> tuple[int, str, int]:
            raw_anchor = bounds.get("source_bucket_anchor_ms")
            if raw_anchor is None:
                anchor_ms = compute_bucket_start_ms(
                    0,
                    interval_ms,
                    interval=requested_interval,
                )
            elif isinstance(raw_anchor, bool) or not isinstance(raw_anchor, int):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display source grid is invalid",
                    status_code=503,
                )
            else:
                anchor_ms = raw_anchor
            raw_alignment = bounds.get("alignment_policy")
            if raw_alignment is None:
                alignment_policy = "LEGACY_CANONICAL_INTERVAL_V1"
            elif isinstance(raw_alignment, str) and raw_alignment:
                alignment_policy = raw_alignment
            else:
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display source grid is invalid",
                    status_code=503,
                )
            raw_start_ms = bounds.get("earliest_open_time")
            raw_end_ms = bounds.get("latest_open_time")
            if (
                isinstance(raw_start_ms, bool)
                or not isinstance(raw_start_ms, int)
                or isinstance(raw_end_ms, bool)
                or not isinstance(raw_end_ms, int)
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display source grid is invalid",
                    status_code=503,
                )
            try:
                mapper = SourceBucketTimeMapper.create(
                    interval=requested_interval,
                    actual_replay_start_ms=actual_replay_start_ms,
                    public_replay_start_ms=actual_replay_start_ms,
                    source_bucket_anchor_ms=anchor_ms,
                )
                mapper.actual_bucket_ordinal(raw_start_ms)
                mapper.actual_bucket_ordinal(raw_end_ms)
                previous_open_ms = mapper.actual_bucket_open(-1)
            except ValueError as exc:
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display source grid is invalid",
                    status_code=503,
                ) from exc
            if previous_open_ms < 0:
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display source grid does not have a closed prefix",
                    status_code=503,
                )
            return anchor_ms, alignment_policy, previous_open_ms

        def assert_pin_identity(
            pin: Mapping[str, object],
            *,
            interval: str,
        ) -> None:
            if (
                str(pin.get("exchange")) != str(binding["exchange"])
                or str(pin.get("market_type")) != str(binding["market_type"])
                or str(pin.get("symbol")) != str(binding["symbol"])
                or str(pin.get("base_interval")) != interval
                or str(pin.get("dataset_epoch")) != str(binding["track_dataset_epoch"])
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_IDENTITY_DRIFT",
                    "training history archive pin identity changed",
                    status_code=503,
                )

        async def assert_native_continuity(
            *,
            source_revision: str,
            range_start_ms: int,
            last_complete_open_ms: int,
        ) -> None:
            if not strict_native_source:
                return
            scan_gaps = getattr(
                self.replay_service.history_repository,
                "scan_gaps_at_revision",
                None,
            )
            if not callable(scan_gaps):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "pinned native display history has no continuity proof",
                    status_code=503,
                )
            try:
                gap_evidence = await self.replay_service.store.run_worker(
                    "display_pin",
                    scan_gaps,
                    source_revision,
                    str(binding["symbol"]),
                    requested_interval,
                    start_ms=range_start_ms,
                    end_ms=last_complete_open_ms,
                    exchange=str(binding["exchange"]),
                    market_type=str(binding["market_type"]),
                    limit=100_000,
                )
            except Exception as exc:
                raise TrainingRunError(
                    "HISTORY_SOURCE_UNAVAILABLE",
                    "pinned native display continuity proof is unavailable",
                    status_code=503,
                ) from exc
            gap_count = (
                gap_evidence.get("gap_count")
                if isinstance(gap_evidence, Mapping)
                else None
            )
            if (
                not isinstance(gap_evidence, Mapping)
                or gap_evidence.get("truncated") is not False
                or gap_evidence.get("source_revision") not in {None, source_revision}
                or isinstance(gap_count, bool)
                or not isinstance(gap_count, int)
                or gap_count < 0
                or (zero_gap_native_required and gap_count != 0)
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "pinned native display history is not continuous",
                    status_code=503,
                )

        base_pin = await self.store.history_archive_pin(
            run_id=run_id,
            track_id=track_id,
            interval=base_interval,
        )
        if base_pin is None:
            if native_display_required:
                raise TrainingRunError(
                    "HISTORY_NATIVE_DISPLAY_REQUIRED",
                    "native replay display history requires an immutable base archive pin",
                    status_code=503,
                )
            # A same-interval projection does not require a separate native pin.
            return dict(binding)
        assert_pin_identity(base_pin, interval=base_interval)
        display_pin = await self.store.history_archive_pin(
            run_id=run_id,
            track_id=track_id,
            interval=requested_interval,
        )
        candidate_proof: (
            tuple[
                str,
                int,
                int,
                int,
                str,
                int,
            ]
            | None
        ) = None
        if display_pin is None:
            repository = self.replay_service.history_repository
            get_bounds = getattr(repository, "get_bounds", None)
            if not callable(get_bounds):
                if native_display_required:
                    raise TrainingRunError(
                        "HISTORY_NATIVE_DISPLAY_REQUIRED",
                        "native replay display history is unavailable",
                        status_code=503,
                    )
                return dict(binding)
            try:
                bounds = await self.replay_service.store.run_worker(
                    "display_pin",
                    get_bounds,
                    str(binding["symbol"]),
                    requested_interval,
                    exchange=str(binding["exchange"]),
                    market_type=str(binding["market_type"]),
                )
                source_revision = str(bounds["source_revision"])
                range_start_ms = int(bounds["earliest_open_time"])
                range_end_ms = int(bounds["latest_open_time"])
                (
                    candidate_source_bucket_anchor_ms,
                    candidate_alignment_policy,
                    candidate_last_complete_open_ms,
                ) = resolve_source_grid(bounds)
                get_bounds_at_revision = getattr(
                    repository,
                    "get_bounds_at_revision",
                    None,
                )
                if strict_native_source and not callable(get_bounds_at_revision):
                    raise TrainingRunError(
                        "HISTORY_SOURCE_INCOMPLETE",
                        "native display history has no immutable bounds proof",
                        status_code=503,
                    )
                if not callable(get_bounds_at_revision):
                    return dict(binding)
                if callable(get_bounds_at_revision):
                    exact_bounds = await self.replay_service.store.run_worker(
                        "display_pin",
                        get_bounds_at_revision,
                        source_revision,
                        str(binding["symbol"]),
                        requested_interval,
                        exchange=str(binding["exchange"]),
                        market_type=str(binding["market_type"]),
                    )
                    exact_revision = str(exact_bounds["source_revision"])
                    exact_start_ms = int(exact_bounds["earliest_open_time"])
                    exact_end_ms = int(exact_bounds["latest_open_time"])
                    (
                        exact_source_bucket_anchor_ms,
                        exact_alignment_policy,
                        exact_last_complete_open_ms,
                    ) = resolve_source_grid(exact_bounds)
                    if (
                        exact_revision != source_revision
                        or exact_start_ms != range_start_ms
                        or exact_end_ms != range_end_ms
                        or exact_source_bucket_anchor_ms
                        != candidate_source_bucket_anchor_ms
                        or exact_alignment_policy != candidate_alignment_policy
                        or exact_last_complete_open_ms
                        != candidate_last_complete_open_ms
                    ):
                        raise TrainingRunError(
                            "HISTORY_SOURCE_IDENTITY_DRIFT",
                            "native display archive bounds changed before pinning",
                            status_code=503,
                        )
                if (
                    len(source_revision) != 71
                    or not source_revision.startswith("sha256:")
                    or range_start_ms < 0
                    or range_end_ms < candidate_last_complete_open_ms
                    or range_start_ms > candidate_last_complete_open_ms
                ):
                    raise TrainingRunError(
                        "HISTORY_SOURCE_INCOMPLETE",
                        "native display archive does not cover the replay seam",
                        status_code=503,
                    )
            except (KeyError, TypeError, ValueError):
                if native_display_required:
                    raise TrainingRunError(
                        "HISTORY_NATIVE_DISPLAY_REQUIRED",
                        "native replay display history is unavailable",
                        status_code=503,
                    ) from None
                return dict(binding)
            except TrainingRunError:
                raise
            except Exception:
                if native_display_required:
                    raise TrainingRunError(
                        "HISTORY_NATIVE_DISPLAY_REQUIRED",
                        "native replay display history is unavailable",
                        status_code=503,
                    ) from None
                # An optional native chart catalog may be absent. The pinned
                # base archive remains the deterministic, gap-aware fallback.
                return dict(binding)
            # Validate the candidate before making it an immutable Run pin. A
            # rejected or gappy catalog must never become sticky for the Run.
            await assert_native_continuity(
                source_revision=source_revision,
                range_start_ms=range_start_ms,
                last_complete_open_ms=candidate_last_complete_open_ms,
            )
            candidate_proof = (
                source_revision,
                range_start_ms,
                range_end_ms,
                candidate_source_bucket_anchor_ms,
                candidate_alignment_policy,
                candidate_last_complete_open_ms,
            )
            display_pin = await self.store.pin_history_archive_interval(
                run_id=run_id,
                track_id=track_id,
                source_revision=source_revision,
                exchange=str(binding["exchange"]),
                market_type=str(binding["market_type"]),
                symbol=str(binding["symbol"]),
                interval=requested_interval,
                range_start_ms=range_start_ms,
                range_end_ms=range_end_ms,
            )
        assert_pin_identity(display_pin, interval=requested_interval)
        repository = self.replay_service.history_repository
        try:
            pinned_start_ms = int(display_pin["range_start_ms"])
            pinned_end_ms = int(display_pin["range_end_ms"])
            pinned_source_revision = str(display_pin["source_revision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TrainingRunError(
                "HISTORY_SOURCE_INCOMPLETE",
                "native display archive pin range is invalid",
                status_code=503,
            ) from exc
        proof_key = (
            pinned_source_revision,
            str(binding["exchange"]),
            str(binding["market_type"]),
            str(binding["symbol"]),
            requested_interval,
            pinned_start_ms,
            pinned_end_ms,
            actual_replay_start_ms,
            str(binding["track_dataset_epoch"]),
        )
        if candidate_proof is not None and candidate_proof[:3] == (
            pinned_source_revision,
            pinned_start_ms,
            pinned_end_ms,
        ):
            self._remember_native_display_pin_proof(proof_key, candidate_proof[3:])
        cached_proof = self._native_display_pin_proofs.get(proof_key)
        if cached_proof is not None:
            self._native_display_pin_proofs.move_to_end(proof_key)
        if cached_proof is None:
            get_bounds_at_revision = getattr(
                repository,
                "get_bounds_at_revision",
                None,
            )
            if not callable(get_bounds_at_revision):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "pinned native display history has no immutable bounds proof",
                    status_code=503,
                )
            try:
                pinned_bounds = await self.replay_service.store.run_worker(
                    "display_pin",
                    get_bounds_at_revision,
                    pinned_source_revision,
                    str(binding["symbol"]),
                    requested_interval,
                    exchange=str(binding["exchange"]),
                    market_type=str(binding["market_type"]),
                )
                exact_source_revision = str(pinned_bounds["source_revision"])
                exact_start_ms = int(pinned_bounds["earliest_open_time"])
                exact_end_ms = int(pinned_bounds["latest_open_time"])
                cached_proof = resolve_source_grid(pinned_bounds)
            except TrainingRunError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "native display archive pin range is invalid",
                    status_code=503,
                ) from exc
            except Exception as exc:
                raise TrainingRunError(
                    "HISTORY_SOURCE_UNAVAILABLE",
                    "pinned native display history is unavailable",
                    status_code=503,
                ) from exc
            if (
                exact_source_revision != pinned_source_revision
                or exact_start_ms != pinned_start_ms
                or exact_end_ms != pinned_end_ms
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_IDENTITY_DRIFT",
                    "pinned native display archive bounds changed",
                    status_code=503,
                )
            (
                display_source_bucket_anchor_ms,
                display_alignment_policy,
                last_complete_open_ms,
            ) = cached_proof
            if (
                pinned_start_ms < 0
                or pinned_start_ms > last_complete_open_ms
                or pinned_end_ms < last_complete_open_ms
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "pinned native display archive does not cover the replay seam",
                    status_code=503,
                )
            await assert_native_continuity(
                source_revision=pinned_source_revision,
                range_start_ms=pinned_start_ms,
                last_complete_open_ms=last_complete_open_ms,
            )
            self._remember_native_display_pin_proof(proof_key, cached_proof)
        else:
            (
                display_source_bucket_anchor_ms,
                display_alignment_policy,
                last_complete_open_ms,
            ) = cached_proof
        display_grid_commitment = canonical_sha256(
            {
                "schema_version": "replay.display-source-grid.v1",
                "source_revision": pinned_source_revision,
                "display_interval": requested_interval,
                "source_bucket_anchor_ms": display_source_bucket_anchor_ms,
                "alignment_policy": display_alignment_policy,
            }
        )
        self._display_source_grid_anchors[
            (
                run_id,
                track_id,
                requested_interval,
                str(binding["track_dataset_epoch"]),
            )
        ] = display_source_bucket_anchor_ms
        return {
            **binding,
            "display_source_revision": pinned_source_revision,
            # The display catalog is immutable at ``pinned_source_revision``,
            # but it can legitimately lag the newer pinned base catalog near
            # the live tail.  Carry its exact bounds so projection can use
            # native authority only where that revision actually has rows and
            # aggregate the remaining closed tail from the pinned base source.
            "display_source_range_start_ms": pinned_start_ms,
            "display_source_range_end_ms": pinned_end_ms,
            "display_source_bucket_anchor_ms": display_source_bucket_anchor_ms,
            "display_alignment_policy": display_alignment_policy,
            "display_grid_commitment": display_grid_commitment,
        }

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

        normalized_session = service_validation_ops.identifier(
            session_id, field_name="session_id"
        )
        normalized_track = service_validation_ops.identifier(
            track_id, field_name="track_id"
        )
        binding = await self.store.history_binding(
            session_id=normalized_session,
            track_id=normalized_track,
        )
        if binding.get("subscription_tier") == SubscriptionTier.NONE.value:
            raise TrainingRunError(
                "HISTORY_SUBSCRIPTION_REQUIRED",
                "history is unavailable while the market track is unsubscribed",
                status_code=409,
                details={"required_tier": "WARM_OR_FULL"},
            )
        persisted = await self.replay_service.store.load_dataset(normalized_session)
        if persisted is None:
            raise TrainingRunError(
                "HISTORY_SNAPSHOT_UNAVAILABLE",
                "training history snapshot is unavailable",
                status_code=503,
            )
        if not is_progressive_dataset(persisted):
            binding = await self._attach_native_display_archive_pin(
                binding,
                display_interval=display_interval,
                persisted=persisted,
            )
        context = getattr(self.replay_service, "history_context", None)
        lookback = binding.get("history_policy", {}).get("visible_history_lookback", {})
        extend_context = (context is not None and context.preparation.enabled
                          and str(binding.get("base_interval")) == "1m"
                          and lookback.get("mode") == "ALL_AVAILABLE"
                          and (is_requested_horizon_dataset(persisted) or is_progressive_dataset(persisted)))
        repository = self.replay_service.prepared_history_repository(normalized_session, data_epoch)
        page = await asyncio.to_thread(
            build_history_page,
            binding=binding,
            persisted=persisted,
            before_ms=before_ms,
            revealed_boundary_ms=revealed_boundary_ms,
            limit=limit,
            data_epoch=data_epoch,
            expected_history_epoch=None if extend_context else history_epoch,
            display_interval=display_interval,
            repository=repository,
            progressive_history_factory=lambda: self.replay_service.progressive_history,
        )
        if extend_context:
            context_repository, _ = _progressive_repository(
                persisted, repository, lambda: self.replay_service.progressive_history)
            return await context.extend(page=page, binding=binding, persisted=persisted,
                                        repository=context_repository, before_ms=before_ms, limit=limit,
                                        expected_history_epoch=history_epoch)
        return page


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

        normalized_session = service_validation_ops.identifier(
            session_id, field_name="session_id"
        )
        normalized_track = service_validation_ops.identifier(
            track_id, field_name="track_id"
        )
        binding = await self.store.history_binding(
            session_id=normalized_session,
            track_id=normalized_track,
        )
        if binding.get("subscription_tier") == SubscriptionTier.NONE.value:
            raise TrainingRunError(
                "HISTORY_SUBSCRIPTION_REQUIRED",
                "display projection is unavailable while the market track is unsubscribed",
                status_code=409,
                details={"required_tier": "WARM_OR_FULL"},
            )
        persisted = await self.replay_service.store.load_dataset(normalized_session)
        if persisted is None:
            raise TrainingRunError(
                "HISTORY_SNAPSHOT_UNAVAILABLE",
                "training display projection snapshot is unavailable",
                status_code=503,
            )
        if not is_progressive_dataset(persisted):
            binding = await self._attach_native_display_archive_pin(
                binding,
                display_interval=display_interval,
                require_projection_grid=True,
                persisted=persisted,
            )
        return await self.replay_service.store.run_worker(
            "display_build",
            build_display_projection,
            binding=binding,
            persisted=persisted,
            revealed_boundary_ms=revealed_boundary_ms,
            limit=limit,
            data_epoch=data_epoch,
            display_interval=display_interval,
            repository=self.replay_service.prepared_history_repository(
                normalized_session, data_epoch
            ),
            progressive_history_factory=lambda: self.replay_service.progressive_history,
        )

    async def _set_display_interval(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> dict[str, object]:
        payload = service_validation_ops.exact_payload(
            command.payload,
            {"display_interval", "expected_viewer_revision"},
        )
        interval = payload["display_interval"]
        if not isinstance(interval, str):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "display_interval must be a string",
                status_code=422,
            )
        base_interval = str(binding["base_interval"])
        compatible_step_interval_ms(
            base_interval=base_interval,
            step_interval=interval,
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
        viewer = await self.store.set_display_interval(
            run_id=command.run_id,
            display_interval=interval,
            expected_revision=expected_viewer_revision,
            command_id=command.command_id,
            command=command.to_dict(),
        )
        cursor = dict(snapshot["cursor"])  # type: ignore[arg-type]
        return {
            "protocol": "replay.v3",
            "run_id": command.run_id,
            "session_id": snapshot["session_id"],
            "command_id": command.command_id,
            "revision": snapshot["revision"],
            "sequence": snapshot["sequence"],
            "state": snapshot["state"],
            "state_hash": snapshot["state_hash"],
            "cursor": cursor,
            "viewer_state": viewer.to_dict(),
            "data": {
                "source_events_consumed": 0,
                "domain_hash_unchanged": True,
                "display_interval": interval,
            },
        }

    async def _validate_display_binding(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        base_interval: str,
        display_interval: object,
        viewer_revision: object,
    ) -> tuple[str, int]:
        if (
            not isinstance(display_interval, str)
            or isinstance(viewer_revision, bool)
            or not isinstance(viewer_revision, int)
            or viewer_revision < 0
        ):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "display control binding is invalid",
                status_code=422,
            )
        compatible_step_interval_ms(
            base_interval=base_interval,
            step_interval=display_interval,
        )
        submitted_view = await self.store.viewer_state_at_revision(
            command.run_id,
            viewer_revision,
        )
        if (
            submitted_view.display_interval != display_interval
            or submitted_view.selected_track_id != str(binding["selected_track_id"])
        ):
            raise TrainingRunError(
                "VIEWER_REVISION_CONFLICT",
                "display control does not match the bound viewer revision",
                status_code=409,
            )
        return display_interval, viewer_revision

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
        interval, revision = await self._validate_display_binding(
            command=command,
            binding=binding,
            base_interval=base_interval,
            display_interval=display_interval,
            viewer_revision=viewer_revision,
        )
        return (
            await self._source_aligned_display_target(
                binding=binding,
                current_virtual_time_ms=current_time,
                base_interval=base_interval,
                display_interval=interval,
                count=count,
            ),
            interval,
            revision,
        )

    async def _display_source_bucket_anchor_ms(
        self,
        *,
        binding: Mapping[str, object],
        display_interval: str,
    ) -> int | None:
        if display_interval == str(binding["base_interval"]):
            return None
        history_binding = await self.store.history_binding(
            session_id=str(binding["adapter_session_id"]),
            track_id=str(binding["selected_track_id"]),
        )
        cache_key = (
            str(history_binding["run_id"]),
            str(history_binding["track_id"]),
            display_interval,
            str(history_binding["track_dataset_epoch"]),
        )
        cached = self._display_source_grid_anchors.get(cache_key)
        if cached is not None:
            return cached
        grid_binding = await self._attach_native_display_archive_pin(
            history_binding,
            display_interval=display_interval,
            require_projection_grid=True,
            persisted=await self.replay_service.store.load_dataset(
                str(binding["adapter_session_id"])
            ),
        )
        raw_anchor = grid_binding.get("display_source_bucket_anchor_ms")
        if raw_anchor is None:
            return None
        if isinstance(raw_anchor, bool) or not isinstance(raw_anchor, int):
            raise TrainingRunError(
                "HISTORY_SOURCE_INCOMPLETE",
                "pinned native display grid anchor is invalid",
                status_code=503,
            )
        self._display_source_grid_anchors[cache_key] = raw_anchor
        return raw_anchor

    async def _source_aligned_display_target(
        self,
        *,
        binding: Mapping[str, object],
        current_virtual_time_ms: int,
        base_interval: str,
        display_interval: str,
        count: int,
    ) -> int:
        actual_start_ms = service_validation_ops._stored_counter(
            binding["actual_replay_start_ms"],
            field_name="actual_replay_start_ms",
        )
        synthetic_origin_ms = binding.get("synthetic_origin_ms")
        public_start_ms = (
            actual_start_ms
            if synthetic_origin_ms is None
            else service_validation_ops._stored_counter(
                synthetic_origin_ms,
                field_name="synthetic_origin_ms",
            )
        )
        source_bucket_anchor_ms = await self._display_source_bucket_anchor_ms(
            binding=binding,
            display_interval=display_interval,
        )
        return source_aligned_step_target_ms(
            current_virtual_time_ms=current_virtual_time_ms,
            actual_replay_start_ms=actual_start_ms,
            public_replay_start_ms=public_start_ms,
            source_bucket_anchor_ms=source_bucket_anchor_ms,
            base_interval=base_interval,
            step_interval=display_interval,
            count=count,
        )

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

        source_kind = str(binding["source_kind"])
        base_interval = str(binding["base_interval"])
        allowed = supported_playback_bases(
            source_kind=source_kind,
            full_track_count=full_track_count,
        )
        payload = command.payload
        legacy = not payload or set(payload) == {"speed"}
        if legacy:
            actor_profile = actor.playback_snapshot()
            profile_revision = actor_profile.get("profile_revision")
            candidate_basis: AdvanceBasis
            if (
                isinstance(profile_revision, int)
                and not isinstance(profile_revision, bool)
                and profile_revision > 0
                and actor_profile.get("basis") is not None
            ):
                candidate_basis = advance_basis(actor_profile["basis"])
            else:
                candidate_basis = default_playback_basis(source_kind)
            basis = (
                candidate_basis
                if candidate_basis in allowed
                else default_playback_basis(source_kind)
            )
            if set(payload) == {"speed"}:
                rate = control_rules_ops.legacy_playback_rate(payload["speed"])
            elif (
                isinstance(profile_revision, int)
                and not isinstance(profile_revision, bool)
                and profile_revision > 0
            ):
                rate = control_rate(actor_profile.get("rate"))
            else:
                rate = control_rules_ops.legacy_playback_rate(
                    selected_snapshot.get("speed", 1)
                )
            display_interval = (
                actor_profile.get("display_interval")
                if basis is AdvanceBasis.DISPLAY_BAR
                else None
            )
            viewer_revision = (
                actor_profile.get("viewer_revision")
                if basis is AdvanceBasis.DISPLAY_BAR
                else None
            )
            if basis is AdvanceBasis.DISPLAY_BAR:
                (
                    display_interval,
                    viewer_revision,
                ) = await self._validate_display_binding(
                    command=command,
                    binding=binding,
                    base_interval=base_interval,
                    display_interval=display_interval,
                    viewer_revision=viewer_revision,
                )
            return basis, rate, display_interval, viewer_revision, True

        basis = advance_basis(payload.get("basis"))
        if basis not in allowed:
            raise TrainingRunError(
                "REPLAY_CONTROL_UNSUPPORTED",
                "playback basis is unavailable for the current source and FULL-track topology",
                status_code=409,
                details={
                    "basis": basis.value,
                    "playback_bases": [item.value for item in allowed],
                    "full_track_count": full_track_count,
                },
            )
        expected = {"basis", "rate"}
        if basis is AdvanceBasis.DISPLAY_BAR:
            expected.update({"display_interval", "viewer_revision"})
        normalized = service_validation_ops.exact_payload(payload, expected)
        rate = control_rate(normalized["rate"])
        if basis is AdvanceBasis.DISPLAY_BAR:
            display_interval, viewer_revision = await self._validate_display_binding(
                command=command,
                binding=binding,
                base_interval=base_interval,
                display_interval=normalized["display_interval"],
                viewer_revision=normalized["viewer_revision"],
            )
        else:
            display_interval = None
            viewer_revision = None
        return basis, rate, display_interval, viewer_revision, False

    async def _translate_control(
        self,
        *,
        command: ReplayV2Command,
        binding: Mapping[str, object],
        snapshot: Mapping[str, object],
    ) -> tuple[CommandType, dict[str, object], dict[str, object]]:
        if "stop_on_event" in command.payload and command.type in {
            ReplayV2CommandType.ADVANCE,
            ReplayV2CommandType.ADVANCE_BY,
            ReplayV2CommandType.ADVANCE_TO,
            ReplayV2CommandType.STEP_DISPLAY,
        }:
            control_rules_ops.stop_on_event(command)
            command = replace(
                command,
                payload={
                    k: v for k, v in command.payload.items() if k != "stop_on_event"
                },
            )
        source_kind = str(binding["source_kind"])
        base_interval = str(binding["base_interval"])
        cursor = snapshot["cursor"]
        if not isinstance(cursor, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "adapter cursor is invalid",
                status_code=503,
            )
        current_time = int(cursor["virtual_time_ms"])
        command_type = command.type
        plan: dict[str, object] = {
            "contract": ADVANCE_CONTRACT_VERSION,
            "mode": "DIRECT_ADAPTER",
            "cancelable": False,
            "source_kind": source_kind,
        }

        if command_type is ReplayV2CommandType.ACQUIRE_CONTROLLER:
            payload = service_validation_ops.exact_payload(
                command.payload, {"takeover"}
            )
            if not isinstance(payload["takeover"], bool):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "takeover must be a boolean",
                    status_code=422,
                )
            return CommandType.ACQUIRE_CONTROLLER, dict(payload), plan
        if command_type is ReplayV2CommandType.TAKEOVER_CONTROLLER:
            service_validation_ops.exact_payload(command.payload, set())
            return CommandType.ACQUIRE_CONTROLLER, {"takeover": True}, plan
        direct_empty = {
            ReplayV2CommandType.RELEASE_CONTROLLER: CommandType.RELEASE_CONTROLLER,
            ReplayV2CommandType.PLAY: CommandType.PLAY,
            ReplayV2CommandType.PAUSE: CommandType.PAUSE,
        }
        if command_type in direct_empty:
            service_validation_ops.exact_payload(command.payload, set())
            return direct_empty[command_type], {}, plan
        if command_type is ReplayV2CommandType.SET_SPEED:
            payload = service_validation_ops.exact_payload(command.payload, {"speed"})
            return CommandType.SET_SPEED, dict(payload), plan
        if command_type is ReplayV2CommandType.END:
            payload = service_validation_ops.exact_payload(
                command.payload,
                {"open_order_disposition", "position_disposition"},
            )
            return CommandType.END_SESSION, dict(payload), plan
        if command_type is ReplayV2CommandType.ADVANCE:
            payload = command.payload
            basis = advance_basis(payload.get("basis"))
            allowed = supported_advance_bases(
                source_kind=source_kind,
                full_track_count=1,
            )
            if basis not in allowed:
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNSUPPORTED",
                    "advance basis is unavailable for the current source",
                    status_code=409,
                    details={
                        "basis": basis.value,
                        "supported_bases": [item.value for item in allowed],
                    },
                )
            if basis is AdvanceBasis.DISPLAY_BAR:
                normalized = service_validation_ops.exact_payload(
                    payload,
                    {"basis", "count", "display_interval", "viewer_revision"},
                )
                count = control_count(normalized["count"])
                target, interval, viewer_revision = await self._display_advance_target(
                    command=command,
                    binding=binding,
                    base_interval=base_interval,
                    current_time=current_time,
                    count=count,
                    display_interval=normalized["display_interval"],
                    viewer_revision=normalized["viewer_revision"],
                )
                return (
                    CommandType.ADVANCE_BY,
                    {"ms": target - current_time},
                    {
                        **plan,
                        "basis": basis.value,
                        "count": count,
                        "display_interval": interval,
                        "viewer_revision": viewer_revision,
                        "target_virtual_time_ms": target,
                    },
                )
            if basis is AdvanceBasis.BASE_BAR:
                normalized = service_validation_ops.exact_payload(
                    payload, {"basis", "count"}
                )
                count = control_count(normalized["count"])
                if source_kind == "BAR":
                    return (
                        CommandType.STEP,
                        {"count": count},
                        {**plan, "basis": basis.value, "count": count},
                    )
                target = aligned_step_target_ms(
                    current_virtual_time_ms=current_time,
                    base_interval=base_interval,
                    step_interval=base_interval,
                    count=count,
                )
                return (
                    CommandType.ADVANCE_BY,
                    {"ms": target - current_time},
                    {
                        **plan,
                        "basis": basis.value,
                        "count": count,
                        "target_virtual_time_ms": target,
                    },
                )
            if basis is AdvanceBasis.SOURCE_EVENT:
                normalized = service_validation_ops.exact_payload(
                    payload, {"basis", "count"}
                )
                count = control_count(normalized["count"])
                return (
                    CommandType.STEP,
                    {"count": count},
                    {**plan, "basis": basis.value, "count": count},
                )
            normalized = service_validation_ops.exact_payload(
                payload, {"basis", "duration_ms"}
            )
            duration = virtual_duration_ms(
                normalized["duration_ms"],
                source_kind=source_kind,
                base_interval=base_interval,
            )
            if current_time > MAX_TIMESTAMP_MS - duration:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "advance target exceeds the timestamp range",
                    status_code=422,
                )
            target = current_time + duration
            return (
                CommandType.ADVANCE_BY,
                {"ms": duration},
                {
                    **plan,
                    "basis": basis.value,
                    "duration_ms": duration,
                    "mode": "FULL_EVENT_SCAN",
                    "cancelable": True,
                    "target_virtual_time_ms": target,
                },
            )
        if command_type is ReplayV2CommandType.STEP_EVENT:
            if source_kind != "AGG_TRADE":
                raise TrainingRunError(
                    "REPLAY_CONTROL_UNSUPPORTED",
                    "STEP_EVENT is available only for AGG_TRADE runs",
                    status_code=409,
                )
            payload = service_validation_ops.exact_payload(command.payload, {"count"})
            count = control_count(payload["count"])
            return (
                CommandType.STEP,
                {"count": count},
                {
                    **plan,
                    "basis": AdvanceBasis.SOURCE_EVENT.value,
                    "count": count,
                    "grain": "EVENT",
                    "legacy_alias": command_type.value,
                },
            )
        if command_type is ReplayV2CommandType.STEP_BASE:
            payload = service_validation_ops.exact_payload(command.payload, {"count"})
            count = control_count(payload["count"])
            if source_kind == "BAR":
                return (
                    CommandType.STEP,
                    {"count": count},
                    {
                        **plan,
                        "basis": AdvanceBasis.BASE_BAR.value,
                        "count": count,
                        "grain": "BASE",
                        "legacy_alias": command_type.value,
                    },
                )
            target = aligned_step_target_ms(
                current_virtual_time_ms=current_time,
                base_interval=base_interval,
                step_interval=base_interval,
                count=count,
            )
            return (
                CommandType.ADVANCE_BY,
                {"ms": target - current_time},
                {
                    **plan,
                    "basis": AdvanceBasis.BASE_BAR.value,
                    "count": count,
                    "grain": "BASE",
                    "legacy_alias": command_type.value,
                    "target_virtual_time_ms": target,
                },
            )
        if command_type is ReplayV2CommandType.STEP_DISPLAY:
            payload = service_validation_ops.exact_payload(
                command.payload,
                {"count", "display_interval", "viewer_revision"},
            )
            count = control_count(payload["count"])
            target, interval, viewer_revision = await self._display_advance_target(
                command=command,
                binding=binding,
                base_interval=base_interval,
                current_time=current_time,
                count=count,
                display_interval=payload["display_interval"],
                viewer_revision=payload["viewer_revision"],
            )
            return (
                CommandType.ADVANCE_BY,
                {"ms": target - current_time},
                {
                    **plan,
                    "basis": AdvanceBasis.DISPLAY_BAR.value,
                    "count": count,
                    "grain": "DISPLAY",
                    "legacy_alias": command_type.value,
                    "display_interval": interval,
                    "viewer_revision": viewer_revision,
                    "target_virtual_time_ms": target,
                },
            )
        if command_type is ReplayV2CommandType.ADVANCE_BY:
            payload = service_validation_ops.exact_payload(command.payload, {"ms"})
            duration = payload["ms"]
            if source_kind == "BAR":
                duration = validate_bar_duration_ms(
                    duration_ms=duration,
                    base_interval=base_interval,
                )
            elif (
                isinstance(duration, bool)
                or not isinstance(duration, int)
                or duration <= 0
            ):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "advance duration must be a positive integer",
                    status_code=422,
                )
            if current_time > MAX_TIMESTAMP_MS - duration:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "advance target exceeds the timestamp range",
                    status_code=422,
                )
            target = current_time + duration
            return (
                CommandType.ADVANCE_BY,
                {"ms": duration},
                {
                    **plan,
                    "basis": AdvanceBasis.VIRTUAL_TIME.value,
                    "duration_ms": duration,
                    "legacy_alias": command_type.value,
                    "mode": "FULL_EVENT_SCAN",
                    "cancelable": True,
                    "target_virtual_time_ms": target,
                },
            )
        if command_type is ReplayV2CommandType.ADVANCE_TO:
            payload = service_validation_ops.exact_payload(
                command.payload, {"virtual_time_ms"}
            )
            target = payload["virtual_time_ms"]
            if (
                isinstance(target, bool)
                or not isinstance(target, int)
                or target <= current_time
                or target > MAX_TIMESTAMP_MS
            ):
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "advance target must be ahead of the current cursor",
                    status_code=422,
                )
            duration = target - current_time
            if source_kind == "BAR":
                validate_bar_duration_ms(
                    duration_ms=duration,
                    base_interval=base_interval,
                )
            return (
                CommandType.ADVANCE_BY,
                {"ms": duration},
                {
                    **plan,
                    "basis": AdvanceBasis.VIRTUAL_TIME.value,
                    "duration_ms": duration,
                    "legacy_alias": command_type.value,
                    "mode": "FULL_EVENT_SCAN",
                    "cancelable": True,
                    "target_virtual_time_ms": target,
                },
            )
        raise TrainingRunError(
            "REPLAY_CONTROL_UNSUPPORTED",
            f"command {command_type.value} is not implemented in Phase 3",
            status_code=409,
        )
