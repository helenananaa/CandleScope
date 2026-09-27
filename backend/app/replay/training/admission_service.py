"""TrainingAdmissionService with explicit runtime dependencies and shared per-service state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from app.replay.models import (
    ReplaySessionConfig,
)

from . import admission_rules as admission_rules_ops
from . import control_rules as control_rules_ops
from . import service_validation as service_validation_ops
from .errors import TrainingRunError
from .models import (
    REPLAY_V2_PROTOCOL,
    StartMode,
    SubscriptionTier,
    TrainingRunCreateRequest,
    TrainingRunMarketSelectionRequest,
    TrainingRunSetupRequest,
    validate_v2_counter,
)


class TrainingAdmissionService:
    """Own admission operations outside command orchestration."""

    def __init__(
        self,
        *,
        store,
        replay_service,
        account_history,
        historical_books,
        run_id_factory,
        random_seed_factory,
        instrument_metadata_resolver,
        market_track_plans,
    ) -> None:
        self.store = store
        self.replay_service = replay_service
        self.account_history = account_history
        self.historical_books = historical_books
        self._run_id_factory = run_id_factory
        self._random_seed_factory = random_seed_factory
        self._instrument_metadata_resolver = instrument_metadata_resolver
        self._market_track_plans = market_track_plans

    async def create_empty_run(
        self,
        request: TrainingRunSetupRequest,
        *,
        preparation_id: str | None = None,
        _progressive_initial_horizon_ms: int | None = None,
    ) -> dict[str, object]:
        if not isinstance(request, TrainingRunSetupRequest):
            raise TypeError("request must be TrainingRunSetupRequest")
        run_id = service_validation_ops.identifier(
            f"prepared-{preparation_id}"
            if preparation_id is not None
            else self._run_id_factory(),
            field_name="run_id",
        )
        if preparation_id is not None:
            try:
                existing = await self.store.get_run_setup(
                    run_id, require_awaiting_market=False
                )
            except TrainingRunError as exc:
                if exc.code != "TRAINING_RUN_NOT_FOUND":
                    raise
            else:
                if existing.to_dict() != request.to_dict():
                    raise TrainingRunError(
                        "TRAINING_RUN_CONFLICT",
                        "preparation belongs to another setup",
                        status_code=409,
                    )
                return {
                    "protocol": REPLAY_V2_PROTOCOL,
                    "created": False,
                    "run": await self.store.get_run(run_id),
                }
        settings = admission_rules_ops.progressive_admission_settings(
            request, _progressive_initial_horizon_ms
        )
        catalog = await self._source_catalog_for_setup(settings)
        capability_admission = await self._setup_capability_admission(settings)
        entries = [
            entry
            for entry in cast(list[Mapping[str, object]], catalog["entries"])
            if admission_rules_ops.setup_market_compatibility(
                settings,
                entry,
                capability_admission=capability_admission,
                committed_start_ms=None,
            )["state"]
            == "READY"
        ]
        if not entries:
            raise TrainingRunError(
                "NO_SETUP_COMPATIBLE_SOURCE_MARKET",
                "no market satisfies the run's structural data requirements",
                status_code=409,
                details={
                    "source_kind": settings["source_kind"],
                    "position_mode": settings["position_mode"],
                    "book_mode": settings["book_mode"],
                    "account_data_mode": settings["account_data_mode"],
                },
            )
        if settings["start_mode"] == StartMode.MANUAL.value:
            committed_start_ms = int(settings["requested_start_ms"])
            random_seed = None
            if not any(
                admission_rules_ops.market_start_compatibility(
                    entry, committed_start_ms
                )["state"]
                == "READY"
                and admission_rules_ops.setup_market_compatibility(
                    settings,
                    entry,
                    capability_admission=capability_admission,
                    committed_start_ms=committed_start_ms,
                )["state"]
                == "READY"
                for entry in entries
            ):
                raise TrainingRunError(
                    "NO_ELIGIBLE_SOURCE_MARKET_AT_START",
                    "no market for the selected replay source can use the "
                    "requested start",
                    status_code=409,
                    details={
                        "source_kind": settings["source_kind"],
                        "requires_new_start": True,
                    },
                )
        else:
            random_seed = self._authoritative_random_seed()
            range_start = int(settings["random_range_start_ms"])
            range_end = int(settings["random_range_end_ms"])
            candidate_ranges = admission_rules_ops.eligible_source_ranges(
                entries,
                range_start_ms=range_start,
                range_end_ms=range_end,
                settings=settings,
                capability_admission=capability_admission,
            )
            if not candidate_ranges:
                raise TrainingRunError(
                    "NO_ELIGIBLE_SOURCE_MARKET_IN_RANGE",
                    "no setup-compatible market overlaps the requested range",
                    status_code=409,
                    details={
                        "source_kind": settings["source_kind"],
                        "requires_new_range": True,
                    },
                )
            committed_start_ms = admission_rules_ops._sample_unique_source_time(
                candidate_ranges,
                random_seed=random_seed,
            )
        try:
            await self.store.create_empty_run(
                run_id=run_id,
                request=request,
                committed_start_ms=committed_start_ms,
                random_seed=random_seed,
            )
        except sqlite3.IntegrityError as exc:
            raise TrainingRunError(
                "TRAINING_RUN_CONFLICT",
                "training run identity already exists",
                status_code=409,
            ) from exc
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "created": True,
            "run": await self.store.get_run(run_id),
        }

    async def market_catalog(
        self,
        run_id: str,
        *,
        _catalog_cache: dict[tuple[int, int, str, bool], dict[str, object]]
        | None = None,
        _admission_cache: dict[
            control_rules_ops._SetupAdmissionCacheKey,
            dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission],
        ]
        | None = None,
    ) -> dict[str, object]:
        normalized = service_validation_ops.identifier(run_id, field_name="run_id")
        setup = await self.store.get_run_setup(
            normalized,
            require_awaiting_market=False,
        )
        settings = setup.to_dict()
        cache_prefix = (
            int(settings["indicator_warmup_bars"]),
            int(settings["forward_cache_ms"]),
            str(settings["source_kind"]),
        )
        # A MANUAL start means the user knows the committed start; it does not
        # authorize exposing the source tail, eligible future windows, or data
        # fingerprint while the Run's disclosure policy is still active.
        blind_mode = settings["time_disclosure_policy"] != "NONE"
        cache_key = (*cache_prefix, blind_mode)
        catalog = None if _catalog_cache is None else _catalog_cache.get(cache_key)
        if catalog is None:
            catalog = await self.replay_service.catalog(
                warmup_bars=int(settings["indicator_warmup_bars"]),
                horizon_ms=int(settings["forward_cache_ms"]),
                quality_mode="exact",
                blind_mode=blind_mode,
                source_kind=str(settings["source_kind"]),
            )
            if _catalog_cache is not None:
                _catalog_cache[cache_key] = catalog
        if blind_mode:
            internal_key = (*cache_prefix, False)
            internal_catalog = (
                None if _catalog_cache is None else _catalog_cache.get(internal_key)
            )
            if internal_catalog is None:
                internal_catalog = await self._source_catalog_for_setup(settings)
                if _catalog_cache is not None:
                    _catalog_cache[internal_key] = internal_catalog
        else:
            internal_catalog = catalog
        commitment = await self.store.get_time_commitment(normalized)
        admission_key = admission_rules_ops.setup_admission_cache_key(settings)
        capability_admission = (
            None if _admission_cache is None else _admission_cache.get(admission_key)
        )
        if capability_admission is None:
            capability_admission = await self._setup_capability_admission(settings)
            if _admission_cache is not None:
                _admission_cache[admission_key] = capability_admission
        internal_by_identity = {
            admission_rules_ops.catalog_identity_key(entry): entry
            for entry in cast(list[Mapping[str, object]], internal_catalog["entries"])
        }
        for entry in cast(list[dict[str, object]], catalog["entries"]):
            internal_entry = internal_by_identity.get(
                admission_rules_ops.catalog_identity_key(entry), entry
            )
            time_compatibility = admission_rules_ops.market_start_compatibility(
                internal_entry,
                int(commitment["committed_start_ms"]),
            )
            identity_compatibility = admission_rules_ops.setup_market_compatibility(
                settings,
                internal_entry,
                capability_admission=capability_admission,
                committed_start_ms=int(commitment["committed_start_ms"]),
            )
            entry["start_compatibility"] = (
                time_compatibility
                if time_compatibility["state"] != "READY"
                else identity_compatibility
            )
        catalog["time_commitment"] = admission_rules_ops.public_time_commitment(
            commitment,
            disclose_start=settings["time_disclosure_policy"] == "NONE",
        )
        return catalog

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

        normalized_run = service_validation_ops.identifier(run_id, field_name="run_id")
        normalized_exchange = service_validation_ops.identifier(
            exchange, field_name="exchange"
        )
        normalized_market = service_validation_ops.identifier(
            market_type, field_name="market_type"
        )
        normalized_symbol = service_validation_ops.identifier(
            symbol, field_name="symbol"
        )
        try:
            tier = SubscriptionTier(subscription_tier)
        except ValueError as exc:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "subscription_tier is unsupported",
                status_code=422,
            ) from exc
        identity = self._authoritative_instrument_identity(
            exchange=normalized_exchange,
            market_type=normalized_market,
            symbol=normalized_symbol,
        )
        binding = await self.store.run_binding(normalized_run)
        admission_rules_ops.assert_same_market_scope(
            binding=binding,
            exchange=identity["exchange"],
            market_type=identity["market_type"],
            settlement_asset=identity["settlement_asset"],
        )
        adapter_config = binding.get("adapter_config")
        if not isinstance(adapter_config, Mapping):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training adapter config is invalid",
                status_code=503,
            )
        config = ReplaySessionConfig.from_dict(adapter_config)
        catalog = await self.replay_service.catalog(
            warmup_bars=config.warmup_bars,
            horizon_ms=config.horizon_ms,
            quality_mode=config.quality_mode,
            blind_mode=False,
            source_kind=str(binding["source_kind"]),
        )
        entry = next(
            (
                candidate
                for candidate in cast(list[Mapping[str, object]], catalog["entries"])
                if admission_rules_ops.catalog_identity_key(candidate)
                == (
                    identity["exchange"],
                    identity["market_type"],
                    identity["symbol"],
                )
            ),
            None,
        )
        if entry is None:
            raise TrainingRunError(
                "MARKET_TRACK_UNAVAILABLE",
                "market is not present in the Run capability catalog",
                status_code=409,
            )
        if entry.get("selected_base_interval") != config.base_interval:
            raise TrainingRunError(
                "MARKET_MODE_INCOMPATIBLE",
                "market does not support the Run's frozen base interval",
                status_code=409,
            )
        compatibility = admission_rules_ops.market_start_compatibility(
            entry,
            service_validation_ops._stored_counter(
                binding["actual_replay_start_ms"],
                field_name="actual_replay_start_ms",
            ),
        )
        if compatibility.get("state") != "READY":
            raise TrainingRunError(
                str(compatibility.get("code", "MARKET_TRACK_UNAVAILABLE")),
                str(
                    compatibility.get(
                        "message",
                        "market is not compatible with the Run's frozen start",
                    )
                ),
                status_code=409,
            )
        selected_session = await self.replay_service.get_session(
            str(binding["adapter_session_id"])
        )
        selected_snapshot = service_validation_ops.adapter_snapshot(selected_session)
        now_ms = self.replay_service.now_ms()
        plan = admission_rules_ops._MarketTrackPlan(
            plan_id=f"track-plan-{uuid.uuid4().hex}",
            run_id=normalized_run,
            exchange=identity["exchange"],
            market_type=identity["market_type"],
            symbol=identity["symbol"],
            base_asset=identity["base_asset"],
            settlement_asset=identity["settlement_asset"],
            subscription_tier=tier,
            target_virtual_time_ms=service_validation_ops.cursor_time(
                selected_snapshot
            ),
            expires_at_ms=now_ms + admission_rules_ops._MARKET_TRACK_PLAN_TTL_MS,
        )
        self._prune_market_track_plans(now_ms)
        self._market_track_plans[plan.plan_id] = plan
        self._market_track_plans.move_to_end(plan.plan_id)
        while (
            len(self._market_track_plans)
            > admission_rules_ops._MARKET_TRACK_PLAN_CACHE_SIZE
        ):
            self._market_track_plans.popitem(last=False)
        return {
            "schema_version": "replay.market-track-plan.v1",
            "plan_id": plan.plan_id,
            "run_id": plan.run_id,
            "identity": {
                "exchange": plan.exchange,
                "market_type": plan.market_type,
                "symbol": plan.symbol,
                "base_asset": plan.base_asset,
                "settlement_asset": plan.settlement_asset,
            },
            "subscription_tier": plan.subscription_tier.value,
            "compatibility": {
                "state": "READY",
                "code": "MARKET_TRACK_PLAN_READY",
                "message": "商品身份、账户范围和冻结历史已校验。",
            },
            "expires_at_ms": plan.expires_at_ms,
        }

    def _authoritative_instrument_identity(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> dict[str, str]:
        resolver = self._instrument_metadata_resolver
        if resolver is None:
            raise TrainingRunError(
                "INSTRUMENT_METADATA_UNAVAILABLE",
                "authoritative instrument metadata is unavailable",
                status_code=503,
            )
        metadata = resolver(exchange, market_type, symbol)
        if not isinstance(metadata, Mapping):
            raise TrainingRunError(
                "INSTRUMENT_METADATA_UNAVAILABLE",
                "instrument is absent from the authoritative local catalog",
                status_code=409,
            )
        try:
            resolved = {
                "exchange": service_validation_ops.identifier(
                    metadata.get("exchange"), field_name="instrument.exchange"
                ).lower(),
                "market_type": service_validation_ops.identifier(
                    metadata.get("marketType"), field_name="instrument.market_type"
                ).lower(),
                "symbol": service_validation_ops.identifier(
                    metadata.get("symbol"), field_name="instrument.symbol"
                ).upper(),
                "base_asset": service_validation_ops.identifier(
                    metadata.get("baseAsset"), field_name="instrument.base_asset"
                ).upper(),
                "settlement_asset": service_validation_ops.identifier(
                    metadata.get("quoteAsset"),
                    field_name="instrument.settlement_asset",
                ).upper(),
            }
        except (TypeError, ValueError) as exc:
            raise TrainingRunError(
                "INSTRUMENT_METADATA_INVALID",
                "authoritative instrument metadata is invalid",
                status_code=503,
            ) from exc
        requested = (exchange.lower(), market_type.lower(), symbol.upper())
        actual = (resolved["exchange"], resolved["market_type"], resolved["symbol"])
        if actual != requested:
            raise TrainingRunError(
                "INSTRUMENT_IDENTITY_MISMATCH",
                "instrument metadata does not match the requested market identity",
                status_code=409,
                details={"expected": list(requested), "actual": list(actual)},
            )
        return resolved

    def _prune_market_track_plans(self, now_ms: int) -> None:
        expired = [
            plan_id
            for plan_id, plan in self._market_track_plans.items()
            if plan.expires_at_ms < now_ms
        ]
        for plan_id in expired:
            self._market_track_plans.pop(plan_id, None)

    def _claim_market_track_plan(
        self,
        *,
        run_id: str,
        plan_id: str,
        selected_snapshot: Mapping[str, object],
    ) -> admission_rules_ops._MarketTrackPlan:
        now_ms = self.replay_service.now_ms()
        self._prune_market_track_plans(now_ms)
        plan = self._market_track_plans.get(plan_id)
        if plan is None or plan.run_id != run_id:
            raise TrainingRunError(
                "MARKET_TRACK_PLAN_EXPIRED",
                "market track plan is missing or expired; request a new plan",
                status_code=409,
            )
        self._market_track_plans.pop(plan_id, None)
        if plan.expires_at_ms < now_ms:
            raise TrainingRunError(
                "MARKET_TRACK_PLAN_EXPIRED",
                "market track plan expired; request a new plan",
                status_code=409,
            )
        if plan.target_virtual_time_ms != service_validation_ops.cursor_time(
            selected_snapshot
        ):
            raise TrainingRunError(
                "MARKET_TRACK_PLAN_STALE",
                "the Run clock changed after planning; request a new plan",
                status_code=409,
            )
        current = self._authoritative_instrument_identity(
            exchange=plan.exchange,
            market_type=plan.market_type,
            symbol=plan.symbol,
        )
        expected = (
            plan.exchange,
            plan.market_type,
            plan.symbol,
            plan.base_asset,
            plan.settlement_asset,
        )
        actual = (
            current["exchange"],
            current["market_type"],
            current["symbol"],
            current["base_asset"],
            current["settlement_asset"],
        )
        if actual != expected:
            raise TrainingRunError(
                "MARKET_TRACK_PLAN_STALE",
                "authoritative instrument metadata changed after planning",
                status_code=409,
            )
        return plan

    def _authoritative_start_request(
        self,
        request: TrainingRunCreateRequest,
    ) -> TrainingRunCreateRequest:
        if request.start_mode is StartMode.MANUAL:
            return replace(request, random_seed=None)
        return replace(request, random_seed=self._authoritative_random_seed())

    def _authoritative_random_seed(self) -> int:
        try:
            seed = validate_v2_counter(
                self._random_seed_factory(),
                field_name="server random_seed",
            )
        except (TypeError, ValueError, RuntimeError, StopIteration) as exc:
            raise TrainingRunError(
                "TRAINING_RANDOM_SEED_UNAVAILABLE",
                "server could not generate an authoritative random start seed",
                status_code=503,
            ) from exc
        return seed

    async def _require_market_at_committed_start(
        self,
        *,
        selection: TrainingRunMarketSelectionRequest,
        setup: TrainingRunSetupRequest,
        commitment: Mapping[str, object],
        progressive_initial_horizon_ms: int | None = None,
    ) -> None:
        settings = admission_rules_ops.progressive_admission_settings(
            setup, progressive_initial_horizon_ms
        )
        catalog = await self.replay_service.catalog(
            warmup_bars=int(settings["indicator_warmup_bars"]),
            horizon_ms=int(settings["forward_cache_ms"]),
            quality_mode="exact",
            blind_mode=False,
            source_kind=str(settings["source_kind"]),
        )
        if catalog["catalog_epoch"] != selection.catalog_epoch:
            raise TrainingRunError(
                "CATALOG_EPOCH_MISMATCH",
                "data capability changed after validation; refresh and try again",
                status_code=409,
            )
        identity = (selection.exchange, selection.market_type, selection.symbol)
        entry = next(
            (
                item
                for item in cast(list[Mapping[str, object]], catalog["entries"])
                if admission_rules_ops.catalog_identity_key(item) == identity
            ),
            None,
        )
        if entry is None:
            compatibility = {
                "state": "UNSUPPORTED",
                "code": "MARKET_NOT_IN_CATALOG",
                "message": "该商品不在当前回放能力目录中。",
            }
        elif entry.get("selected_base_interval") != selection.base_interval:
            compatibility = {
                "state": "UNSUPPORTED",
                "code": "MARKET_MODE_INCOMPATIBLE",
                "message": "所选基础周期与当前精确回放能力不兼容。",
            }
        else:
            compatibility = admission_rules_ops.market_start_compatibility(
                entry,
                int(commitment["committed_start_ms"]),
            )
            if compatibility["state"] == "READY":
                compatibility = admission_rules_ops.setup_market_compatibility(
                    settings,
                    entry,
                    capability_admission=await self._setup_capability_admission(
                        settings
                    ),
                    committed_start_ms=int(commitment["committed_start_ms"]),
                )
        if compatibility["state"] != "READY":
            raise TrainingRunError(
                str(compatibility["code"]),
                str(compatibility["message"]),
                status_code=409,
                details={
                    "requires_new_run": True,
                    "time_commitment_hash": commitment["commitment_hash"],
                },
            )

    async def _source_catalog_for_setup(
        self,
        settings: Mapping[str, object],
    ) -> dict[str, object]:
        return await self.replay_service.catalog(
            warmup_bars=int(settings["indicator_warmup_bars"]),
            horizon_ms=int(settings["forward_cache_ms"]),
            quality_mode="exact",
            blind_mode=False,
            source_kind=str(settings["source_kind"]),
        )

    async def _setup_capability_admission(
        self,
        settings: Mapping[str, object],
    ) -> dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission]:
        require_book = settings.get("book_mode") == "BOOK_ASSISTED_REQUIRED"
        require_account = settings.get("account_data_mode") == "HISTORICAL_EXACT"
        if not require_book and not require_account:
            return {}

        settlement_asset = str(settings.get("settlement_asset", ""))

        def read(
            connection: sqlite3.Connection,
        ) -> dict[tuple[str, str, str], admission_rules_ops._MarketSetupAdmission]:
            book_windows: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
            books_by_ref: dict[
                tuple[str, str, str],
                tuple[tuple[str, str, str], int, int],
            ] = {}
            if require_book and self.historical_books.enabled:
                for row in connection.execute(
                    """
                    SELECT archive_id, dataset_epoch, checksum_sha256,
                           exchange, market_type, symbol,
                           range_start_ms, range_end_ms, local_path
                    FROM replay_historical_book_archive
                    WHERE health = 'READY' AND coverage_state = 'EXACT'
                      AND continuity_state = 'CONTIGUOUS'
                    """
                ).fetchall():
                    key = (
                        str(row["exchange"]),
                        str(row["market_type"]),
                        str(row["symbol"]),
                    )
                    if not isinstance(row["local_path"], str) or not row["local_path"]:
                        continue
                    window = (int(row["range_start_ms"]), int(row["range_end_ms"]))
                    book_windows.setdefault(key, []).append(window)
                    books_by_ref[
                        (
                            str(row["archive_id"]),
                            str(row["dataset_epoch"]),
                            str(row["checksum_sha256"]),
                        )
                    ] = (key, *window)

            account_windows: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
            if require_account and self.account_history.enabled:
                funding_clause = (
                    " AND funding_count > 0"
                    if settings.get("funding_mode") == "HISTORICAL_EXACT"
                    else ""
                )
                for row in connection.execute(
                    f"""
                    SELECT exchange, market_type, symbol,
                           range_start_ms, range_end_ms, local_path
                    FROM replay_account_history_archive
                    WHERE health = 'READY' AND settlement_asset = ?{funding_clause}
                    """,
                    (settlement_asset,),
                ).fetchall():
                    key = (
                        str(row["exchange"]),
                        str(row["market_type"]),
                        str(row["symbol"]),
                    )
                    if not isinstance(row["local_path"], str) or not row["local_path"]:
                        continue
                    account_windows.setdefault(key, []).append(
                        (int(row["range_start_ms"]), int(row["range_end_ms"]))
                    )

            hedge_book_pairs: dict[
                tuple[str, str, str],
                list[tuple[int, int, int, int]],
            ] = {}
            require_exact_hedge = (
                settings.get("position_mode") == "HEDGE" and require_book
            )
            if require_exact_hedge:
                simulations: list[tuple[sqlite3.Row, set[str]]] = []
                for simulation in connection.execute(
                    """
                    SELECT range_start_ms, range_end_ms, required_symbols_json,
                           local_path
                    FROM replay_hedge_simulation_manifest
                    WHERE health = 'READY' AND settlement_asset = ?
                    """,
                    (settlement_asset,),
                ).fetchall():
                    if (
                        not isinstance(simulation["local_path"], str)
                        or not simulation["local_path"]
                    ):
                        continue
                    try:
                        required_symbols = json.loads(
                            str(simulation["required_symbols_json"])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(required_symbols, list):
                        simulations.append(
                            (simulation, {str(item) for item in required_symbols})
                        )
                for public in connection.execute(
                    """
                    SELECT exchange, market_type, symbol, settlement_asset,
                           range_start_ms, range_end_ms,
                           l2_archive_id, l2_dataset_epoch, l2_checksum_sha256,
                           local_path
                    FROM replay_hedge_public_archive
                    WHERE health = 'READY' AND settlement_asset = ?
                      AND archive_id NOT LIKE 'hybrid-public-%'
                    """,
                    (settlement_asset,),
                ).fetchall():
                    if (
                        not isinstance(public["local_path"], str)
                        or not public["local_path"]
                    ):
                        continue
                    symbol = str(public["symbol"])
                    key = (
                        str(public["exchange"]),
                        str(public["market_type"]),
                        symbol,
                    )
                    referenced_book = books_by_ref.get(
                        (
                            public["l2_archive_id"],
                            public["l2_dataset_epoch"],
                            public["l2_checksum_sha256"],
                        )
                    )
                    if referenced_book is None or referenced_book[0] != key:
                        continue
                    _book_key, book_start, book_end = referenced_book
                    for simulation, required_symbols in simulations:
                        if symbol not in required_symbols:
                            continue
                        start = max(
                            int(public["range_start_ms"]),
                            int(simulation["range_start_ms"]),
                        )
                        end = min(
                            int(public["range_end_ms"]),
                            int(simulation["range_end_ms"]),
                        )
                        if start <= end:
                            hedge_book_pairs.setdefault(key, []).append(
                                (book_start, book_end, start, end)
                            )

            if require_exact_hedge:
                keys = set(hedge_book_pairs)
                if require_account:
                    keys &= set(account_windows)
            elif require_book:
                keys = set(book_windows)
                if require_account:
                    keys &= set(account_windows)
            else:
                keys = set(account_windows)
            result: dict[
                tuple[str, str, str], admission_rules_ops._MarketSetupAdmission
            ] = {}
            for key in keys:
                result[key] = admission_rules_ops._MarketSetupAdmission(
                    windows=(
                        tuple(account_windows[key])
                        if require_account and not require_book
                        else ()
                    ),
                    code="REQUIRED_HISTORY_COVERAGE_UNAVAILABLE",
                    message="本局固定开始时间不在精确账户历史或连续盘口覆盖内。",
                    book_windows=(
                        tuple(book_windows[key])
                        if require_book and not require_exact_hedge
                        else ()
                    ),
                    account_windows=(
                        tuple(account_windows[key])
                        if require_account and require_book
                        else ()
                    ),
                    hedge_book_pairs=(
                        tuple(hedge_book_pairs[key]) if require_exact_hedge else ()
                    ),
                )
            return result

        return await self.store.base_store.run_extension_read(read)
