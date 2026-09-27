"""TrainingRun metadata storage layered on the internal replay adapter database."""

from __future__ import annotations


from .repositories.runs import TrainingRunRepository
from .repositories.review import TrainingReviewRepository
from .repositories.markets import TrainingMarketRepository
from .repositories.liquidations import TrainingLiquidationRepository
from .repositories.advances import TrainingAdvanceRepository
from .repositories.curves import TrainingCurveRepository

from .persistence import account_audit as account_audit_ops
from .persistence import account_marks as account_marks_ops
from .persistence import curve_records as curve_records_ops
from .persistence import fork_records as fork_records_ops
from .persistence import liquidation as liquidation_ops
from .persistence import portfolio as portfolio_ops
from .persistence import public_time as public_time_ops
from .persistence import result_records as result_records_ops
from .persistence import run_records as run_records_ops


import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation, getcontext
from typing import cast

from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.checkpoints import CheckpointCodec
from app.replay.broker.models import decimal_to_string
from app.replay.internal_commands import (
    InternalCommandType,
)
from app.replay.period_summary import (
    EncodedPeriodSummaryCandidate,
    ReplayPeriodSummary,
)
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from .errors import TrainingRunError
from .phase_projection import PhaseSummary
from .account_history import (
    AccountHistoryEvent,
    PreparedAccountHistoryBinding,
    account_rule_component_hash,
    bind_account_history_archive,
    runtime_instrument_rule,
)
from .historical_book import (
    PreparedHistoricalBookBinding,
    bind_historical_book_archive,
)
from .hedge_inputs import (
    HedgeInputEvent,
    PreparedHedgeInputBinding,
    PreparedHedgeTrackPublicBinding,
    bind_hedge_inputs,
    bind_hedge_track_public_input,
    runtime_hedge_rule,
)
from .account import (
    CONTRACT_ACCOUNT_MODEL,
    InstrumentRule,
    isolated_margin_key,
)
from .models import (
    TrainingRunCreateRequest,
    TrainingRunSetupRequest,
    ViewerState,
    validate_v2_counter,
)
from .multitrack import (
    GLOBAL_ORDERING_VERSION,
    StableMarketEvent,
    global_ordering_hash,
    stable_market_event_order,
)
from .schema import (
    migrate_training_schema,
)
from .review import (
    ReviewRecorder,
)
from .segments import (
    ResolvedHistoryPolicy,
    backfill_archive_segments,
    register_archive_segment,
)


class TrainingRunStore:
    """Own v2 metadata while reusing the internal adapter transaction owner."""


    def __init__(self, base_store: ReplaySQLiteStore) -> None:
        self.base_store = base_store
        self._review = ReviewRecorder(self)
        self._runs = TrainingRunRepository(base_store)
        self._review_repository = TrainingReviewRepository(base_store, self._review)
        self._markets = TrainingMarketRepository(base_store, self._review)
        self._liquidations = TrainingLiquidationRepository(base_store, self._review)
        self._advances = TrainingAdvanceRepository(base_store)
        self._curves = TrainingCurveRepository(base_store)
        self._hedge_risk_fingerprints: dict[str, str] = {}

    async def start(self) -> None:
        now = self.base_store._validated_now_ms()

        def migrate(connection: sqlite3.Connection) -> None:
            migrate_training_schema(connection, now_ms=now)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_replay_training_contract_order_active
                ON replay_training_contract_order(run_id, track_id, order_id)
                WHERE json_extract(order_json, '$.status')
                    IN ('OPEN', 'PARTIALLY_FILLED')
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO replay_training_account_history(
                    run_id, account_data_mode, status, fidelity,
                    archive_proof_hash, degraded_reason, auditor_status,
                    auditor_proof_hash, auditor_differences_json,
                    created_at_ms, updated_at_ms
                )
                SELECT run_id, account_data_mode, 'ACTIVE',
                       COALESCE(account_fidelity, 'REVEALED_PRICE_PROXY_MODELLED_ACCOUNT'),
                       NULL, NULL, 'NOT_RUN', NULL, '[]', ?, ?
                FROM replay_training_run
                """,
                (now, now),
            )
            connection.execute(
                """
                UPDATE replay_training_fast_forward_summary_set
                SET status = 'FAILED', active = 0,
                    error_code = 'PROCESS_RESTARTED',
                    error_message = 'summary preparation was interrupted by restart',
                    updated_at_ms = ?
                WHERE status = 'PREPARING'
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE replay_training_selection_preparation
                SET status = 'FAILED', error_code = 'PROCESS_RESTARTED',
                    error_message = 'data preparation was interrupted by restart',
                    updated_at_ms = ?
                WHERE status = 'PREPARING_DATA'
                """,
                (now,),
            )
            backfill_archive_segments(connection, now_ms=now)
            connection.execute(
                """
                DELETE FROM replay_data_segment
                WHERE storage_kind = 'EMBEDDED_ARCHIVE'
                  AND NOT EXISTS(
                      SELECT 1 FROM replay_data_segment_ref AS ref
                      WHERE ref.segment_id = replay_data_segment.segment_id
                  )
                """
            )
            self._review.backfill(connection, now_ms=now)

        await self.base_store.run_extension_write(migrate)
        self.base_store.register_session_summary_writer(self._sync_session_summary)
        self._recorded_interval_plans: dict[str, dict[str, object]] = {}
        self.base_store.register_session_trajectory_writer(self._sync_session_trajectory)
        self.base_store.register_session_mutation_writer(self._sync_session_mutation)
        self.base_store.register_session_review_writer(self._sync_review_event)

    async def create_selection_preparation(
        self,
        *,
        preparation_id: str,
        start_mode: str,
        random_seed: int | None,
        catalog_epoch: str,
        source_fingerprint: str,
        selected_start_ms: int,
        required_start_ms: int,
        required_end_ms: int,
        interval_ms: int,
        request: TrainingRunCreateRequest,
        selection: Mapping[str, object],
    ) -> dict[str, object]:
        return await self._runs.create_selection_preparation(preparation_id=preparation_id, start_mode=start_mode, random_seed=random_seed, catalog_epoch=catalog_epoch, source_fingerprint=source_fingerprint, selected_start_ms=selected_start_ms, required_start_ms=required_start_ms, required_end_ms=required_end_ms, interval_ms=interval_ms, request=request, selection=selection)

    async def fail_selection_preparation(
        self,
        preparation_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        return await self._runs.fail_selection_preparation(preparation_id, error_code=error_code, error_message=error_message)

    async def claim_selection_preparation_retry(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        return await self._runs.claim_selection_preparation_retry(preparation_id)

    async def selection_preparation(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        return await self._runs.selection_preparation(preparation_id)

    def _sync_review_event(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        context: Mapping[str, object],
        state: Mapping[str, object],
        component_state: Mapping[str, object],
        checkpoint: bytes | None,
        now_ms: int,
    ) -> None:
        self._review.sync(
            connection,
            session_id,
            context,
            state,
            component_state,
            checkpoint,
            now_ms,
        )

    def _append_review_timeline_event(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        session_id: str,
        context: Mapping[str, object],
        state: Mapping[str, object] | None,
        checkpoint: bytes | None,
        now_ms: int,
    ) -> tuple[str, ...]:
        return self._review.append(
            connection,
            run_id=run_id,
            session_id=session_id,
            context=context,
            state=state,
            checkpoint=checkpoint,
            now_ms=now_ms,
        )

    async def create_empty_run(
        self,
        *,
        run_id: str,
        request: TrainingRunSetupRequest,
        committed_start_ms: int,
        random_seed: int | None,
    ) -> None:
        """Persist a run identity and immutable T0 before any market exists."""
        return await self._runs.create_empty_run(run_id=run_id, request=request, committed_start_ms=committed_start_ms, random_seed=random_seed)

    async def get_time_commitment(self, run_id: str) -> dict[str, object]:
        return await self._runs.get_time_commitment(run_id)

    async def get_run_setup(
        self,
        run_id: str,
        *,
        require_awaiting_market: bool = True,
    ) -> TrainingRunSetupRequest:
        return await self._runs.get_run_setup(run_id, require_awaiting_market=require_awaiting_market)

    def initial_run_writer(
        self,
        *,
        run_id: str,
        request: TrainingRunCreateRequest,
        adapter_session_id: str,
        session_state: Mapping[str, object],
        component_state: Mapping[str, object],
        broker_config: Mapping[str, object],
        dataset_ref: Mapping[str, object],
        dataset_blob: Mapping[str, object],
        actual_replay_start_ms: int,
        actual_replay_end_ms: int,
        history_policy: ResolvedHistoryPolicy,
        source_fingerprint: str,
        historical_book_binding: PreparedHistoricalBookBinding | None = None,
        account_history_binding: PreparedAccountHistoryBinding | None = None,
        hedge_input_binding: PreparedHedgeInputBinding | None = None,
        existing_shell: bool = False,
        preparation_id: str | None = None,
    ) -> Callable[[sqlite3.Connection, int], None]:
        def write(connection: sqlite3.Connection, now_ms: int) -> None:
            cursor = session_state.get("cursor")
            if not isinstance(cursor, Mapping):
                raise TypeError("training adapter cursor must be an object")
            account = component_state.get("account")
            if not isinstance(account, Mapping) or not isinstance(
                account.get("equity"), str
            ):
                raise TypeError("training adapter account equity is missing")
            name = run_records_ops._safe_name(
                request.name,
                fallback=f"{request.symbol} 训练 {run_id[-8:]}",
            )
            rule = request.to_dict(redact_hidden_start=True)
            run_records_ops.validated_selection_preparation(
                connection,
                preparation_id=preparation_id or run_id,
                request=request,
                history_policy=history_policy,
                source_fingerprint=source_fingerprint,
                actual_replay_start_ms=actual_replay_start_ms,
                actual_replay_end_ms=actual_replay_end_ms,
            )
            run_values = {
                "run_id": run_id,
                "adapter_session_id": adapter_session_id,
                "name": name,
                "state": str(session_state["state"]),
                "source_kind": request.source_kind.value,
                "start_mode": request.start_mode.value,
                "integrity_mode": request.integrity_mode.value,
                "time_disclosure_policy": request.time_disclosure_policy.value,
                "book_mode": request.book_mode.value,
                "margin_mode": request.margin_mode.value,
                "position_mode": request.position_mode.value,
                "funding_mode": request.funding_mode.value,
                "account_data_mode": request.account_data_mode.value,
                "hedge_public_history_ref_json": (
                    None
                    if request.hedge_public_history_ref is None
                    else canonical_json(request.hedge_public_history_ref.to_dict())
                ),
                "simulation_manifest_ref_json": (
                    None
                    if request.simulation_manifest_ref is None
                    else canonical_json(request.simulation_manifest_ref.to_dict())
                ),
                "simulation_contract_hash": (
                    None
                    if request.simulation_manifest_ref is None
                    else request.simulation_manifest_ref.contract_hash
                ),
                "simulation_model_version": (
                    None
                    if request.simulation_manifest_ref is None
                    else request.simulation_manifest_ref.model_version
                ),
                "account_fidelity": request.account_fidelity,
                "insurance_adl_fidelity": request.insurance_adl_fidelity,
                "allow_rule_changes": int(request.allow_rule_changes),
                "exchange": request.exchange,
                "market_type": request.market_type,
                "last_symbol": request.symbol,
                "settlement_asset": request.settlement_asset,
                "base_interval": request.base_interval,
                "display_interval": request.display_interval,
                "initial_equity": request.initial_equity,
                "current_equity": str(account["equity"]),
                "summary_revision": int(session_state["revision"]),
                "revision": int(session_state["revision"]),
                "source_sequence": int(session_state["source_sequence"]),
                "virtual_time_ms": int(cursor["virtual_time_ms"]),
                "catalog_epoch": request.catalog_epoch,
                "dataset_epoch": str(session_state["data_epoch"]),
                "compatibility": "READY",
                "now_ms": now_ms,
            }
            if existing_shell:
                updated = connection.execute(
                    """
                    UPDATE replay_training_run
                    SET adapter_session_id = :adapter_session_id,
                        state = :state, source_kind = :source_kind,
                        start_mode = :start_mode,
                        integrity_mode = :integrity_mode,
                        time_disclosure_policy = :time_disclosure_policy,
                        book_mode = :book_mode, margin_mode = :margin_mode,
                        position_mode = :position_mode,
                        funding_mode = :funding_mode,
                        account_data_mode = :account_data_mode,
                        hedge_public_history_ref_json = :hedge_public_history_ref_json,
                        simulation_manifest_ref_json = :simulation_manifest_ref_json,
                        simulation_contract_hash = :simulation_contract_hash,
                        simulation_model_version = :simulation_model_version,
                        account_fidelity = :account_fidelity,
                        insurance_adl_fidelity = :insurance_adl_fidelity,
                        allow_rule_changes = :allow_rule_changes,
                        exchange = :exchange, market_type = :market_type,
                        last_symbol = :last_symbol,
                        settlement_asset = :settlement_asset,
                        base_interval = :base_interval,
                        display_interval = :display_interval,
                        initial_equity = :initial_equity,
                        current_equity = :current_equity,
                        summary_revision = :summary_revision,
                        revision = :revision,
                        source_sequence = :source_sequence,
                        virtual_time_ms = :virtual_time_ms,
                        active_rule_revision = 1,
                        catalog_epoch = :catalog_epoch,
                        dataset_epoch = :dataset_epoch,
                        compatibility = :compatibility,
                        updated_at_ms = :now_ms,
                        saved_at_ms = :now_ms
                    WHERE run_id = :run_id
                      AND state = 'AWAITING_MARKET'
                      AND adapter_session_id IS NULL
                    """,
                    run_values,
                )
                if updated.rowcount != 1:
                    raise TrainingRunError(
                        "TRAINING_RUN_ALREADY_INITIALIZED",
                        "training run already has a market clock",
                        status_code=409,
                    )
            else:
                run_records_ops.insert_run(connection, run_values)
            run_records_ops.insert_launch_context(
                connection,
                run_id=run_id,
                context=request.resolved_launch_context(),
                now_ms=now_ms,
            )
            run_records_ops.insert_start_selection(
                connection,
                run_id=run_id,
                start_mode=request.start_mode.value,
                seed_source=(
                    "SERVER" if request.start_mode.value == "RANDOM" else "MANUAL"
                ),
                random_seed=request.random_seed,
                actual_start_ms=actual_replay_start_ms,
                actual_end_ms=actual_replay_end_ms,
                dataset_epoch=str(session_state["data_epoch"]),
                parent_selection_hash=None,
                now_ms=now_ms,
            )
            preparation_update = connection.execute(
                """
                UPDATE replay_training_selection_preparation
                SET status = 'READY', dataset_epoch = ?, error_code = NULL,
                    error_message = NULL, updated_at_ms = ?
                WHERE preparation_id = ? AND status = 'PREPARING_DATA'
                """,
                (
                    str(session_state["data_epoch"]),
                    now_ms,
                    preparation_id or run_id,
                ),
            )
            if preparation_update.rowcount != 1:
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training selection preparation could not be finalized",
                    status_code=503,
                )
            run_records_ops.insert_data_policy(
                connection,
                run_id=run_id,
                policy=history_policy,
                actual_replay_start_ms=actual_replay_start_ms,
                now_ms=now_ms,
            )
            run_records_ops.insert_track(
                connection,
                run_id=run_id,
                adapter_session_id=adapter_session_id,
                source_kind=request.source_kind.value,
                exchange=request.exchange,
                market_type=request.market_type,
                symbol=request.symbol,
                settlement_asset=request.settlement_asset,
                dataset_epoch=str(session_state["data_epoch"]),
                cursor={**cursor, "revision": int(session_state["revision"])},
                component_state=component_state,
                now_ms=now_ms,
            )
            run_records_ops.insert_contract_account(
                connection,
                run_id=run_id,
                request=request,
                broker_config=broker_config,
                virtual_time_ms=int(cursor["virtual_time_ms"]),
                now_ms=now_ms,
            )
            if request.account_data_mode.value == "HISTORICAL_EXACT":
                if account_history_binding is None:
                    raise TypeError(
                        "exact account run is missing its verified archive binding"
                    )
                bind_account_history_archive(
                    connection,
                    run_id=run_id,
                    track_id="track-1",
                    binding=account_history_binding,
                    bound_range_start_ms=actual_replay_start_ms,
                    bound_range_end_ms=actual_replay_end_ms,
                    source_kind=request.source_kind.value,
                    now_ms=now_ms,
                )
            else:
                run_records_ops.insert_modelled_account_history(
                    connection,
                    run_id=run_id,
                    account_data_mode=request.account_data_mode.value,
                    fidelity=(
                        request.account_fidelity
                        or "REVEALED_PRICE_PROXY_MODELLED_ACCOUNT"
                    ),
                    now_ms=now_ms,
                )
            initialized_viewer = ViewerState(
                run_id=run_id,
                selected_track_id="track-1",
                display_interval=request.display_interval,
                chart_type="candles",
                visible_range=None,
                pane_layout={},
                rail_layout={},
                semantic_view_revision=1 if existing_shell else 0,
            )
            if existing_shell:
                viewer_payload = initialized_viewer.to_dict()
                viewer_update = connection.execute(
                    """
                    UPDATE replay_training_viewer_state
                    SET selected_track_id = ?, display_interval = ?,
                        chart_type = ?, visible_range_json = NULL,
                        pane_layout_json = '{}', rail_layout_json = '{}',
                        semantic_view_revision = 1, updated_at_ms = ?
                    WHERE run_id = ? AND selected_track_id IS NULL
                    """,
                    (
                        initialized_viewer.selected_track_id,
                        initialized_viewer.display_interval,
                        initialized_viewer.chart_type,
                        now_ms,
                        run_id,
                    ),
                )
                if viewer_update.rowcount != 1:
                    raise TrainingRunError(
                        "TRAINING_RUN_ALREADY_INITIALIZED",
                        "training run viewer already selected a market",
                        status_code=409,
                    )
                connection.execute(
                    """
                    INSERT INTO replay_training_viewer_event(
                        run_id, semantic_view_revision, command_id, event_type,
                        request_json, viewer_state_json, created_at_ms
                    ) VALUES (?, 1, NULL, 'SELECT_INITIAL_MARKET', '{}', ?, ?)
                    """,
                    (run_id, canonical_json(viewer_payload), now_ms),
                )
            else:
                run_records_ops.insert_viewer_state(
                    connection,
                    initialized_viewer,
                    now_ms=now_ms,
                )
            run_records_ops.insert_rule(connection, run_id=run_id, rule=rule, now_ms=now_ms)
            if request.account_data_mode.value == "HISTORICAL_EXACT":
                account_marks_ops.apply_exact_mark_projection(
                    connection,
                    run_id=run_id,
                    track_id="track-1",
                    now_ms=now_ms,
                )
            market_action = {
                "schema": "replay.training.action.v2",
                "adapter_session_id": adapter_session_id,
                "source_kind": request.source_kind.value,
                "start_mode": request.start_mode.value,
                "exchange": request.exchange,
                "market_type": request.market_type,
                "symbol": request.symbol,
            }
            if existing_shell:
                connection.execute(
                    """
                    INSERT INTO replay_training_action(
                        run_id, action_sequence, action_type,
                        action_json, created_at_ms
                    ) VALUES (?, 2, 'SELECT_MARKET', ?, ?)
                    """,
                    (run_id, canonical_json(market_action), now_ms),
                )
            else:
                run_records_ops.insert_initial_action(
                    connection,
                    run_id=run_id,
                    action_type="CREATE_RUN",
                    action=market_action,
                    now_ms=now_ms,
                )
            run_records_ops.insert_pin(
                connection,
                run_id=run_id,
                track_id="track-1",
                adapter_session_id=adapter_session_id,
                dataset_epoch=str(session_state["data_epoch"]),
                now_ms=now_ms,
            )
            register_archive_segment(
                connection,
                run_id=run_id,
                track_id="track-1",
                adapter_session_id=adapter_session_id,
                source_kind=request.source_kind.value,
                dataset_ref=dataset_ref,
                dataset_blob=dataset_blob,
                actual_replay_start_ms=actual_replay_start_ms,
                actual_replay_end_ms=actual_replay_end_ms,
                history_policy=history_policy,
                now_ms=now_ms,
            )
            if request.book_mode.value == "BOOK_ASSISTED_REQUIRED":
                if historical_book_binding is None:
                    raise TypeError(
                        "book-assisted run is missing its verified L2 binding"
                    )
                bind_historical_book_archive(
                    connection,
                    run_id=run_id,
                    track_id="track-1",
                    binding=historical_book_binding,
                    bound_range_start_ms=actual_replay_start_ms,
                    bound_range_end_ms=actual_replay_end_ms,
                    now_ms=now_ms,
                )
            if request.position_mode.value == "HEDGE":
                if hedge_input_binding is None:
                    raise TypeError(
                        "HEDGE run is missing its verified public/simulation binding"
                    )
                bind_hedge_inputs(
                    connection,
                    run_id=run_id,
                    track_id="track-1",
                    source_kind=request.source_kind.value,
                    settlement_asset=request.settlement_asset,
                    binding=hedge_input_binding,
                    bound_range_start_ms=hedge_input_binding.bound_range_start_ms,
                    bound_range_end_ms=hedge_input_binding.bound_range_end_ms,
                    virtual_time_ms=int(cursor["virtual_time_ms"]),
                    now_ms=now_ms,
                )
                account_marks_ops.apply_hedge_mark_projection(
                    connection,
                    run_id=run_id,
                    now_ms=now_ms,
                )
                liquidation_ops.detect_contract_liquidations(
                    connection,
                    run_id=run_id,
                    now_ms=now_ms,
                    trigger_virtual_time_ms=int(cursor["virtual_time_ms"]),
                )
                portfolio_ops.refresh_contract_current_equity(
                    connection,
                    run_id=run_id,
                    now_ms=now_ms,
                )
            start_time_known = request.start_mode.value == "MANUAL"
            strict_eligible = (
                request.integrity_mode.value == "CHALLENGE"
                and not start_time_known
                and request.time_disclosure_policy.value != "NONE"
            )
            result_label = public_time_ops.result_label(
                integrity_mode=request.integrity_mode.value,
                start_time_known=start_time_known,
                strict_eligible=strict_eligible,
                revealed=False,
            )
            connection.execute(
                """
                INSERT INTO replay_training_integrity(
                    run_id, strict_eligible, start_time_known, revealed,
                    allowed_mutations_json, result_label, updated_at_ms
                ) VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    run_id,
                    int(strict_eligible),
                    int(start_time_known),
                    canonical_json(list(request.allowed_mutations)),
                    result_label,
                    now_ms,
                ),
            )
            public_time = public_time_ops.public_time(
                connection,
                session_id=adapter_session_id,
                policy=request.time_disclosure_policy.value,
                revealed=False,
                public_time_ms=int(cursor["virtual_time_ms"]),
                sequence=validate_v2_counter(
                    session_state["source_sequence"],
                    field_name="session source_sequence",
                ),
            )
            state_hash = str(session_state["state_hash"])
            connection.execute(
                """
                INSERT INTO replay_run_action_event(
                    run_id, action_sequence, event_id, command_id, event_type,
                    rule_revision, public_time_json, old_value_json,
                    new_value_json, reason, state_hash_before,
                    state_hash_after, created_at_ms
                ) VALUES (?, 1, 'action-00000001', NULL, ?, 1,
                          ?, '{}', ?, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    "SELECT_MARKET" if existing_shell else "CREATE_RUN",
                    canonical_json(public_time),
                    canonical_json(
                        {
                            "integrity_mode": request.integrity_mode.value,
                            "time_disclosure_policy": request.time_disclosure_policy.value,
                            "result_label": result_label,
                        }
                    ),
                    "initialize first market" if existing_shell else "atomic create",
                    state_hash,
                    now_ms,
                ),
            )
            curve_records_ops.upsert_equity_samples(
                connection,
                run_id=run_id,
                session_id=adapter_session_id,
                policy=request.time_disclosure_policy.value,
                revealed=False,
                state=session_state,
                component_state=component_state,
                now_ms=now_ms,
            )

        return write


    async def apply_account_history_events(
        self,
        run_id: str,
        *,
        events: Sequence[tuple[str, AccountHistoryEvent]],
        virtual_time_ms: int,
    ) -> tuple[StableMarketEvent, ...]:
        """Apply one ordered account-input phase with durable idempotency."""

        materialized = tuple(events)
        if not materialized:
            return ()

        def write(connection: sqlite3.Connection) -> tuple[StableMarketEvent, ...]:
            mode = connection.execute(
                """
                SELECT * FROM replay_training_account_history WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if (
                mode is None
                or mode["account_data_mode"] != "HISTORICAL_EXACT"
                or mode["status"] != "ACTIVE"
            ):
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_ARCHIVE_DEGRADED",
                    "exact account history is not active",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            now_ms = self.base_store._validated_now_ms()
            stable: list[StableMarketEvent] = []
            for track_id, event in materialized:
                stable_event = StableMarketEvent(
                    actual_event_time_ms=event.event_time_ms,
                    event_phase=event.event_phase,
                    market_track_stable_id=f"account:{track_id}",
                    source_sequence=event.event_sequence,
                )
                stable.append(stable_event)
                existing = connection.execute(
                    """
                    SELECT 1 FROM replay_account_history_applied_event
                    WHERE run_id = ? AND track_id = ?
                      AND archive_event_sequence = ?
                    """,
                    (run_id, track_id, event.event_sequence),
                ).fetchone()
                if existing is not None:
                    continue
                projection = connection.execute(
                    """
                    SELECT projection.*, track.source_kind,
                           track.source_sequence,
                           ref.bound_range_start_ms,
                           ref.bound_range_end_ms
                    FROM replay_account_history_projection AS projection
                    JOIN replay_training_market_track AS track
                      ON track.run_id = projection.run_id
                     AND track.track_id = projection.track_id
                    JOIN replay_account_history_ref AS ref
                      ON ref.run_id = projection.run_id
                     AND ref.track_id = projection.track_id
                     AND ref.archive_id = projection.archive_id
                     AND ref.active = 1
                    WHERE projection.run_id = ? AND projection.track_id = ?
                    """,
                    (run_id, track_id),
                ).fetchone()
                if projection is None or projection["status"] != "READY":
                    raise TrainingRunError(
                        "ACCOUNT_HISTORY_BINDING_MISSING",
                        "exact account projection is missing",
                        status_code=409,
                        details={
                            "track_id": track_id,
                            "fallback_applied": False,
                        },
                    )
                expected_sequence = int(projection["last_event_sequence"]) + 1
                if event.event_sequence != expected_sequence:
                    raise TrainingRunError(
                        "ACCOUNT_HISTORY_EVENT_GAP",
                        "account event sequence is not contiguous",
                        status_code=409,
                        details={
                            "track_id": track_id,
                            "expected_sequence": expected_sequence,
                            "actual_sequence": event.event_sequence,
                            "fallback_applied": False,
                        },
                    )
                if event.previous_hash != projection["input_chain_hash"]:
                    raise TrainingRunError(
                        "ACCOUNT_HISTORY_EVENT_CHAIN_MISMATCH",
                        "account event no longer follows the pinned input chain",
                        status_code=409,
                        details={"track_id": track_id, "fallback_applied": False},
                    )
                if event.event_kind == "RULE":
                    runtime_rule = runtime_instrument_rule(
                        event.payload,
                        track_id=track_id,
                        source_kind=str(projection["source_kind"]),
                        actual_replay_start_ms=event.event_time_ms,
                        virtual_replay_start_ms=virtual_time_ms,
                    )
                    revision = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(revision), 0) + 1
                            FROM replay_training_instrument_rule
                            WHERE run_id = ? AND track_id = ?
                            """,
                            (run_id, track_id),
                        ).fetchone()[0]
                    )
                    connection.execute(
                        """
                        INSERT INTO replay_training_instrument_rule(
                            run_id, track_id, revision,
                            effective_virtual_time_ms, rule_json, rule_hash,
                            fidelity, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            track_id,
                            revision,
                            virtual_time_ms,
                            canonical_json(runtime_rule),
                            canonical_sha256(runtime_rule),
                            "HISTORICAL_EXACT_VERSIONED_EXCHANGE_RULE",
                            now_ms,
                        ),
                    )
                elif event.event_kind == "MARK_INDEX":
                    pass
                elif event.event_kind == "FUNDING":
                    account = connection.execute(
                        """
                        SELECT account.*, run.settlement_asset
                        FROM replay_training_contract_account AS account
                        JOIN replay_training_run AS run USING(run_id)
                        WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()
                    if account is None:
                        raise TypeError("contract account is missing")
                    if account["funding_mode"] == "HISTORICAL_EXACT":
                        account_marks_ops.settle_exact_funding_event(
                            connection,
                            run_id=run_id,
                            track_id=track_id,
                            event=event,
                            virtual_time_ms=virtual_time_ms,
                            source_sequence=int(projection["source_sequence"] or 0),
                            settlement_asset=str(account["settlement_asset"]),
                            now_ms=now_ms,
                        )
                else:
                    raise TrainingRunError(
                        "ACCOUNT_HISTORY_EVENT_UNSUPPORTED",
                        "account archive event kind is unsupported",
                        status_code=409,
                    )
                last_rule = (
                    event.component_sequence
                    if event.event_kind == "RULE"
                    else int(projection["last_rule_sequence"])
                )
                last_mark = (
                    event.component_sequence
                    if event.event_kind == "MARK_INDEX"
                    else int(projection["last_mark_sequence"])
                )
                last_funding = (
                    event.component_sequence
                    if event.event_kind == "FUNDING"
                    else int(projection["last_funding_sequence"])
                )
                rule_json = (
                    canonical_json(event.payload)
                    if event.event_kind == "RULE"
                    else projection["current_rule_json"]
                )
                rule_hash = (
                    account_rule_component_hash(event.payload)
                    if event.event_kind == "RULE"
                    else projection["current_rule_hash"]
                )
                mark_price = (
                    event.payload["mark_price"]
                    if event.event_kind == "MARK_INDEX"
                    else projection["mark_price"]
                )
                index_price = (
                    event.payload["index_price"]
                    if event.event_kind == "MARK_INDEX"
                    else projection["index_price"]
                )
                connection.execute(
                    """
                    UPDATE replay_account_history_projection
                    SET last_event_sequence = ?, last_rule_sequence = ?,
                        last_mark_sequence = ?, last_funding_sequence = ?,
                        as_of_actual_time_ms = ?, as_of_virtual_time_ms = ?,
                        current_rule_json = ?, current_rule_hash = ?,
                        mark_price = ?, index_price = ?, input_chain_hash = ?,
                        status = 'READY', degraded_reason = NULL,
                        updated_at_ms = ?
                    WHERE run_id = ? AND track_id = ?
                    """,
                    (
                        event.event_sequence,
                        last_rule,
                        last_mark,
                        last_funding,
                        event.event_time_ms,
                        virtual_time_ms,
                        rule_json,
                        rule_hash,
                        mark_price,
                        index_price,
                        event.event_hash,
                        now_ms,
                        run_id,
                        track_id,
                    ),
                )
                applied_hash = canonical_sha256(
                    {
                        "run_id": run_id,
                        "track_id": track_id,
                        "virtual_time_ms": virtual_time_ms,
                        "event": {
                            "archive_id": event.archive_id,
                            "event_sequence": event.event_sequence,
                            "event_time_ms": event.event_time_ms,
                            "event_phase": event.event_phase,
                            "event_kind": event.event_kind,
                            "component_sequence": event.component_sequence,
                            "event_hash": event.event_hash,
                            "payload": dict(event.payload),
                        },
                    }
                )
                connection.execute(
                    """
                    INSERT INTO replay_account_history_applied_event(
                        run_id, track_id, archive_id, archive_event_sequence,
                        event_time_ms, event_phase, event_kind,
                        component_sequence, archive_event_hash,
                        applied_payload_hash, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        track_id,
                        event.archive_id,
                        event.event_sequence,
                        event.event_time_ms,
                        event.event_phase,
                        event.event_kind,
                        event.component_sequence,
                        event.event_hash,
                        applied_hash,
                        now_ms,
                    ),
                )
            return stable_market_event_order(stable)

        return await self.base_store.run_extension_write(write)


    async def apply_hedge_input_events(
        self,
        run_id: str,
        *,
        events: Sequence[HedgeInputEvent],
        virtual_time_ms: int,
        event_virtual_times_ms: Sequence[int] | None = None,
    ) -> tuple[StableMarketEvent, ...]:
        """Apply one ordered HEDGE input phase with durable idempotency."""

        if not events:
            return ()
        write = self._hedge_input_write_operation(
            run_id, events=events, virtual_time_ms=virtual_time_ms,
            event_virtual_times_ms=event_virtual_times_ms,
        )
        return await self.base_store.run_extension_write(write)

    def _hedge_input_write_operation(
        self, run_id: str, *, events: Sequence[HedgeInputEvent],
        virtual_time_ms: int, event_virtual_times_ms: Sequence[int] | None = None,
    ) -> Callable[[sqlite3.Connection], tuple[StableMarketEvent, ...]]:

        materialized = tuple(events)
        if not materialized:
            return lambda connection: ()
        applied_virtual_times = (
            (virtual_time_ms,) * len(materialized)
            if event_virtual_times_ms is None
            else tuple(event_virtual_times_ms)
        )
        if len(applied_virtual_times) != len(materialized):
            raise ValueError("HEDGE event virtual-time count must match event count")

        def write(connection: sqlite3.Connection) -> tuple[StableMarketEvent, ...]:
            binding = connection.execute(
                "SELECT * FROM replay_hedge_input_binding WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if binding is None or binding["status"] != "ACTIVE":
                raise TrainingRunError(
                    "HEDGE_INPUT_PAUSED",
                    "pinned HEDGE inputs are not active",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            now_ms = self.base_store._validated_now_ms()
            primary_track = connection.execute(
                """
                SELECT track_id FROM replay_training_market_track
                WHERE run_id = ? ORDER BY stable_ordinal, track_id LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if primary_track is None:
                raise TypeError("HEDGE primary track is missing")
            primary_track_id = str(primary_track["track_id"])
            if all(
                event.source_kind == "PUBLIC"
                and event.event_kind == "MARK_INDEX"
                and event.event_phase == 30
                and event.track_id == primary_track_id
                for event in materialized
            ):
                return account_marks_ops.apply_hedge_public_mark_batch(
                    connection,
                    run_id=run_id,
                    events=materialized,
                    virtual_times_ms=applied_virtual_times,
                    track_id=primary_track_id,
                    now_ms=now_ms,
                )
            stable: list[StableMarketEvent] = []
            funding_accounting_totals: dict[
                tuple[str, str], tuple[Decimal, Decimal, Decimal]
            ] | None = None
            for event, virtual_time_ms in zip(
                materialized, applied_virtual_times, strict=True
            ):
                stable.append(
                    StableMarketEvent(
                        actual_event_time_ms=event.event_time_ms,
                        event_phase=event.event_phase,
                        market_track_stable_id=event.stable_track_id,
                        source_sequence=event.event_sequence,
                    )
                )
                if event.source_kind == "PUBLIC":
                    if event.track_id is None:
                        raise TypeError("HEDGE public event lacks a track identity")
                    existing = connection.execute(
                        """
                        SELECT 1 FROM replay_hedge_track_public_applied_event
                        WHERE run_id = ? AND track_id = ? AND event_sequence = ?
                        """,
                        (run_id, event.track_id, event.event_sequence),
                    ).fetchone()
                else:
                    existing = connection.execute(
                        """
                        SELECT 1 FROM replay_hedge_input_applied_event
                        WHERE run_id = ? AND source_kind = ? AND event_sequence = ?
                        """,
                        (run_id, event.source_kind, event.event_sequence),
                    ).fetchone()
                if existing is not None:
                    continue
                projection = (
                    connection.execute(
                        """
                        SELECT * FROM replay_hedge_track_public_projection
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (run_id, event.track_id),
                    ).fetchone()
                    if event.source_kind == "PUBLIC"
                    else connection.execute(
                        """
                        SELECT * FROM replay_hedge_input_projection
                        WHERE run_id = ? AND source_kind = ?
                        """,
                        (run_id, event.source_kind),
                    ).fetchone()
                )
                if projection is None:
                    raise TrainingRunError(
                        "HEDGE_INPUT_PROJECTION_MISSING",
                        "HEDGE input projection is missing",
                        status_code=409,
                        details={"fallback_applied": False},
                    )
                expected = int(projection["last_event_sequence"]) + 1
                if event.event_sequence != expected:
                    raise TrainingRunError(
                        "HEDGE_INPUT_EVENT_GAP",
                        "HEDGE input event sequence is not contiguous",
                        status_code=409,
                        details={
                            "expected_sequence": expected,
                            "actual_sequence": event.event_sequence,
                            "fallback_applied": False,
                        },
                    )
                if event.previous_hash != projection["input_chain_hash"]:
                    raise TrainingRunError(
                        "HEDGE_INPUT_EVENT_CHAIN_MISMATCH",
                        "HEDGE input event no longer follows the pinned chain",
                        status_code=409,
                        details={"fallback_applied": False},
                    )
                state = json.loads(str(projection["state_json"]))
                if not isinstance(state, dict):
                    raise TypeError("HEDGE input projection state is invalid")
                if event.event_kind == "RULE":
                    state["rule"] = dict(event.payload)
                    track = connection.execute(
                        """
                        SELECT track_id, source_kind FROM replay_training_market_track
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (run_id, event.track_id),
                    ).fetchone()
                    if track is None:
                        raise TypeError("HEDGE FULL track is missing")
                    revision = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(revision), 0) + 1
                            FROM replay_training_instrument_rule
                            WHERE run_id = ? AND track_id = ?
                            """,
                            (run_id, track["track_id"]),
                        ).fetchone()[0]
                    )
                    rule = runtime_hedge_rule(
                        event.payload,
                        track_id=str(track["track_id"]),
                        source_kind=str(track["source_kind"]),
                        effective_virtual_time_ms=virtual_time_ms,
                    )
                    connection.execute(
                        """
                        INSERT INTO replay_training_instrument_rule(
                            run_id, track_id, revision,
                            effective_virtual_time_ms, rule_json, rule_hash,
                            fidelity, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?,
                                  'PINNED_HISTORICAL_EXCHANGE_RULE', ?)
                        """,
                        (
                            run_id,
                            track["track_id"],
                            revision,
                            virtual_time_ms,
                            canonical_json(rule),
                            canonical_sha256(rule),
                            now_ms,
                        ),
                    )
                elif event.event_kind == "FEE_POLICY":
                    state["fee_policy"] = dict(event.payload)
                    if event.track_id != primary_track_id:
                        active_fee = connection.execute(
                            """
                            SELECT policy.maker_fee_bps, policy.taker_fee_bps,
                                   extension.liquidation_fee_bps,
                                   extension.policy_version,
                                   extension.account_tier
                            FROM replay_training_fee_policy AS policy
                            JOIN replay_training_fee_policy_extension AS extension
                              ON extension.run_id = policy.run_id
                             AND extension.revision = policy.revision
                            WHERE policy.run_id = ?
                            ORDER BY policy.effective_virtual_time_ms DESC,
                                     policy.revision DESC LIMIT 1
                            """,
                            (run_id,),
                        ).fetchone()
                        expected_fee = (
                            str(event.payload["maker_fee_bps"]),
                            str(event.payload["taker_fee_bps"]),
                            str(event.payload["liquidation_fee_bps"]),
                            str(event.payload["policy_version"]),
                            str(event.payload["account_tier"]),
                        )
                        actual_fee = (
                            None
                            if active_fee is None
                            else (
                                str(active_fee["maker_fee_bps"]),
                                str(active_fee["taker_fee_bps"]),
                                str(active_fee["liquidation_fee_bps"]),
                                str(active_fee["policy_version"]),
                                str(active_fee["account_tier"]),
                            )
                        )
                        if actual_fee != expected_fee:
                            raise TrainingRunError(
                                "HEDGE_TRACK_FEE_POLICY_MISMATCH",
                                "track public fee event differs from account policy",
                                status_code=409,
                                details={
                                    "track_id": event.track_id,
                                    "fallback_applied": False,
                                },
                            )
                    else:
                        revision = int(
                            connection.execute(
                                """
                                SELECT COALESCE(MAX(revision), 0) + 1
                                FROM replay_training_fee_policy WHERE run_id = ?
                                """,
                                (run_id,),
                            ).fetchone()[0]
                        )
                        policy = {
                            "schema_version": "replay.training.fee-policy.v1",
                            "run_id": run_id,
                            "revision": revision,
                            "effective_virtual_time_ms": virtual_time_ms,
                            **dict(event.payload),
                            "fidelity": "PINNED_HISTORICAL_FEE_POLICY",
                        }
                        connection.execute(
                            """
                            INSERT INTO replay_training_fee_policy(
                                run_id, revision, effective_virtual_time_ms,
                                maker_fee_bps, taker_fee_bps, policy_hash,
                                fidelity, reason, created_at_ms
                            ) VALUES (?, ?, ?, ?, ?, ?,
                                      'PINNED_HISTORICAL_FEE_POLICY',
                                      'HEDGE public input event', ?)
                            """,
                            (
                                run_id,
                                revision,
                                virtual_time_ms,
                                event.payload["maker_fee_bps"],
                                event.payload["taker_fee_bps"],
                                canonical_sha256(policy),
                                now_ms,
                            ),
                        )
                        extension = {
                            "schema_version": "replay.training.fee-policy-extension.v1",
                            "run_id": run_id,
                            "revision": revision,
                            "policy_version": event.payload["policy_version"],
                            "account_tier": event.payload["account_tier"],
                            "liquidation_fee_bps": event.payload["liquidation_fee_bps"],
                            "source_kind": "PUBLIC",
                            "source_id": event.source_id,
                            "source_event_sequence": event.event_sequence,
                        }
                        connection.execute(
                            """
                            INSERT INTO replay_training_fee_policy_extension(
                                run_id, revision, policy_version, account_tier,
                                liquidation_fee_bps, source_kind, source_id,
                                source_event_sequence, component_hash, created_at_ms
                            ) VALUES (?, ?, ?, ?, ?, 'PUBLIC', ?, ?, ?, ?)
                            """,
                            (
                                run_id,
                                revision,
                                event.payload["policy_version"],
                                event.payload["account_tier"],
                                event.payload["liquidation_fee_bps"],
                                event.source_id,
                                event.event_sequence,
                                canonical_sha256(extension),
                                now_ms,
                            ),
                        )
                elif event.event_kind == "MARK_INDEX":
                    state["mark_index"] = dict(event.payload)
                elif event.event_kind == "FUNDING":
                    if funding_accounting_totals is None:
                        funding_accounting_totals = (
                            account_marks_ops.hedge_accounting_totals_by_leg(
                                connection,
                                run_id=run_id,
                            )
                        )
                    account_marks_ops.settle_hedge_funding_event(
                        connection,
                        run_id=run_id,
                        event=event,
                        virtual_time_ms=virtual_time_ms,
                        now_ms=now_ms,
                        accounting_totals=funding_accounting_totals,
                    )
                    state["funding"] = dict(event.payload)
                elif event.event_kind == "INSURANCE_INPUT":
                    state["insurance"] = dict(event.payload)
                    connection.execute(
                        """
                        UPDATE replay_training_insurance_fund
                        SET current_balance = ?, ledger_tail_hash = ?,
                            revision = revision + 1, updated_at_ms = ?
                        WHERE run_id = ?
                        """,
                        (
                            event.payload["balance_after"],
                            event.event_hash,
                            now_ms,
                            run_id,
                        ),
                    )
                elif event.event_kind == "ADL_COHORT_INPUT":
                    snapshots = dict(state.get("adl_snapshots", {}))
                    snapshots[str(event.payload["symbol"])] = dict(event.payload)
                    state["adl_snapshots"] = snapshots
                else:
                    raise TrainingRunError(
                        "HEDGE_INPUT_EVENT_UNSUPPORTED",
                        "HEDGE input event kind is unsupported",
                        status_code=409,
                    )
                if event.source_kind == "PUBLIC":
                    assert event.track_id is not None
                    projection_payload = {
                        "schema_version": "replay.hedge-track-public-projection.v1",
                        "run_id": run_id,
                        "track_id": event.track_id,
                        "last_event_sequence": event.event_sequence,
                        "as_of_actual_time_ms": event.event_time_ms,
                        "as_of_virtual_time_ms": virtual_time_ms,
                        "state": state,
                        "input_chain_hash": event.event_hash,
                    }
                    connection.execute(
                        """
                        UPDATE replay_hedge_track_public_projection
                        SET last_event_sequence = ?, as_of_actual_time_ms = ?,
                            as_of_virtual_time_ms = ?, state_json = ?,
                            input_chain_hash = ?, component_hash = ?, updated_at_ms = ?
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (
                            event.event_sequence,
                            event.event_time_ms,
                            virtual_time_ms,
                            canonical_json(state),
                            event.event_hash,
                            canonical_sha256(projection_payload),
                            now_ms,
                            run_id,
                            event.track_id,
                        ),
                    )
                    applied_hash = canonical_sha256(
                        {
                            "run_id": run_id,
                            "track_id": event.track_id,
                            "virtual_time_ms": virtual_time_ms,
                            "source_kind": event.source_kind,
                            "source_id": event.source_id,
                            "event_sequence": event.event_sequence,
                            "event_hash": event.event_hash,
                            "payload": dict(event.payload),
                        }
                    )
                    connection.execute(
                        """
                        INSERT INTO replay_hedge_track_public_applied_event(
                            run_id, track_id, event_sequence, event_time_ms,
                            event_phase, event_kind, component_sequence,
                            applied_virtual_time_ms, source_event_hash,
                            payload_json, applied_payload_hash, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            event.track_id,
                            event.event_sequence,
                            event.event_time_ms,
                            event.event_phase,
                            event.event_kind,
                            event.component_sequence,
                            virtual_time_ms,
                            event.event_hash,
                            canonical_json(event.payload),
                            applied_hash,
                            now_ms,
                        ),
                    )
                    if event.track_id == primary_track_id:
                        compatibility_payload = {
                            "schema_version": "replay.hedge-input-projection.v1",
                            "source_kind": "PUBLIC",
                            "last_event_sequence": event.event_sequence,
                            "as_of_actual_time_ms": event.event_time_ms,
                            "as_of_virtual_time_ms": virtual_time_ms,
                            "state": state,
                            "input_chain_hash": event.event_hash,
                        }
                        connection.execute(
                            """
                            UPDATE replay_hedge_input_projection
                            SET last_event_sequence = ?, as_of_actual_time_ms = ?,
                                as_of_virtual_time_ms = ?, state_json = ?,
                                input_chain_hash = ?, component_hash = ?,
                                updated_at_ms = ?
                            WHERE run_id = ? AND source_kind = 'PUBLIC'
                            """,
                            (
                                event.event_sequence,
                                event.event_time_ms,
                                virtual_time_ms,
                                canonical_json(state),
                                event.event_hash,
                                canonical_sha256(compatibility_payload),
                                now_ms,
                                run_id,
                            ),
                        )
                        compatibility_hash = canonical_sha256(
                            {
                                "run_id": run_id,
                                "virtual_time_ms": virtual_time_ms,
                                "source_kind": "PUBLIC",
                                "source_id": event.source_id,
                                "event_sequence": event.event_sequence,
                                "event_hash": event.event_hash,
                                "payload": dict(event.payload),
                            }
                        )
                        connection.execute(
                            """
                            INSERT INTO replay_hedge_input_applied_event(
                                run_id, source_kind, event_sequence,
                                event_time_ms, event_phase, event_kind,
                                component_sequence, applied_virtual_time_ms,
                                source_event_hash, payload_json,
                                applied_payload_hash, created_at_ms
                            ) VALUES (?, 'PUBLIC', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                run_id,
                                event.event_sequence,
                                event.event_time_ms,
                                event.event_phase,
                                event.event_kind,
                                event.component_sequence,
                                virtual_time_ms,
                                event.event_hash,
                                canonical_json(event.payload),
                                compatibility_hash,
                                now_ms,
                            ),
                        )
                else:
                    projection_payload = {
                        "schema_version": "replay.hedge-input-projection.v1",
                        "source_kind": event.source_kind,
                        "last_event_sequence": event.event_sequence,
                        "as_of_actual_time_ms": event.event_time_ms,
                        "as_of_virtual_time_ms": virtual_time_ms,
                        "state": state,
                        "input_chain_hash": event.event_hash,
                    }
                    connection.execute(
                        """
                        UPDATE replay_hedge_input_projection
                        SET last_event_sequence = ?, as_of_actual_time_ms = ?,
                            as_of_virtual_time_ms = ?, state_json = ?,
                            input_chain_hash = ?, component_hash = ?, updated_at_ms = ?
                        WHERE run_id = ? AND source_kind = ?
                        """,
                        (
                            event.event_sequence,
                            event.event_time_ms,
                            virtual_time_ms,
                            canonical_json(state),
                            event.event_hash,
                            canonical_sha256(projection_payload),
                            now_ms,
                            run_id,
                            event.source_kind,
                        ),
                    )
                    applied_hash = canonical_sha256(
                        {
                            "run_id": run_id,
                            "virtual_time_ms": virtual_time_ms,
                            "source_kind": event.source_kind,
                            "source_id": event.source_id,
                            "event_sequence": event.event_sequence,
                            "event_hash": event.event_hash,
                            "payload": dict(event.payload),
                        }
                    )
                    connection.execute(
                        """
                        INSERT INTO replay_hedge_input_applied_event(
                            run_id, source_kind, event_sequence, event_time_ms,
                            event_phase, event_kind, component_sequence,
                            applied_virtual_time_ms, source_event_hash,
                            payload_json, applied_payload_hash, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            event.source_kind,
                            event.event_sequence,
                            event.event_time_ms,
                            event.event_phase,
                            event.event_kind,
                            event.component_sequence,
                            virtual_time_ms,
                            event.event_hash,
                            canonical_json(event.payload),
                            applied_hash,
                            now_ms,
                        ),
                    )
            return stable_market_event_order(stable)

        return write


    async def pending_hedge_input_global_events(
        self, run_id: str
    ) -> tuple[StableMarketEvent, ...]:
        def read(connection: sqlite3.Connection) -> tuple[StableMarketEvent, ...]:
            public_rows = connection.execute(
                """
                SELECT applied.track_id, applied.event_sequence,
                       applied.event_time_ms, applied.event_phase,
                       binding.public_archive_id AS source_id
                FROM replay_hedge_track_public_applied_event AS applied
                JOIN replay_hedge_track_public_binding AS binding
                  ON binding.run_id = applied.run_id
                 AND binding.track_id = applied.track_id
                LEFT JOIN replay_training_global_event AS global_event
                  ON global_event.run_id = applied.run_id
                 AND global_event.track_id =
                     'hedge-public:' || binding.public_archive_id || ':' ||
                     applied.track_id
                 AND global_event.source_sequence = applied.event_sequence
                WHERE applied.run_id = ? AND global_event.global_sequence IS NULL
                """,
                (run_id,),
            ).fetchall()
            simulation_rows = connection.execute(
                """
                SELECT applied.event_sequence, applied.event_time_ms,
                       applied.event_phase,
                       binding.simulation_manifest_id AS source_id
                FROM replay_hedge_input_applied_event AS applied
                JOIN replay_hedge_input_binding AS binding USING(run_id)
                LEFT JOIN replay_training_global_event AS global_event
                  ON global_event.run_id = applied.run_id
                 AND global_event.track_id = 'hedge-simulation:' ||
                     binding.simulation_manifest_id
                 AND global_event.source_sequence = applied.event_sequence
                WHERE applied.run_id = ?
                  AND applied.source_kind = 'SIMULATION'
                  AND global_event.global_sequence IS NULL
                """,
                (run_id,),
            ).fetchall()
            compatibility_public_rows = connection.execute(
                """
                SELECT applied.event_sequence, applied.event_time_ms,
                       applied.event_phase, binding.public_archive_id AS source_id
                FROM replay_hedge_input_applied_event AS applied
                JOIN replay_hedge_input_binding AS binding USING(run_id)
                LEFT JOIN replay_training_global_event AS global_event
                  ON global_event.run_id = applied.run_id
                 AND global_event.track_id = 'hedge-public:' ||
                     binding.public_archive_id
                 AND global_event.source_sequence = applied.event_sequence
                WHERE applied.run_id = ?
                  AND applied.source_kind = 'PUBLIC'
                  AND global_event.global_sequence IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM replay_hedge_track_public_binding AS track_binding
                      WHERE track_binding.run_id = applied.run_id
                  )
                """,
                (run_id,),
            ).fetchall()
            public_events = tuple(
                StableMarketEvent(
                    actual_event_time_ms=int(row["event_time_ms"]),
                    event_phase=int(row["event_phase"]),
                    market_track_stable_id=(
                        f"hedge-public:{row['source_id']}:{row['track_id']}"
                    ),
                    source_sequence=int(row["event_sequence"]),
                )
                for row in public_rows
            )
            simulation_events = tuple(
                StableMarketEvent(
                    actual_event_time_ms=int(row["event_time_ms"]),
                    event_phase=int(row["event_phase"]),
                    market_track_stable_id=(f"hedge-simulation:{row['source_id']}"),
                    source_sequence=int(row["event_sequence"]),
                )
                for row in simulation_rows
            )
            compatibility_public_events = tuple(
                StableMarketEvent(
                    actual_event_time_ms=int(row["event_time_ms"]),
                    event_phase=int(row["event_phase"]),
                    market_track_stable_id=f"hedge-public:{row['source_id']}",
                    source_sequence=int(row["event_sequence"]),
                )
                for row in compatibility_public_rows
            )
            return stable_market_event_order(
                (*public_events, *simulation_events, *compatibility_public_events)
            )

        return await self.base_store.run_extension_read(read)

    async def commit_liquidation_cancellation(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
        canceled_orders: Sequence[Mapping[str, object]],
    ) -> None:
        return await self._liquidations.commit_liquidation_cancellation(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence, canceled_orders=canceled_orders)

    async def commit_liquidation_adl(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        return await self._liquidations.commit_liquidation_adl(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence)

    async def commit_liquidation_complete(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        return await self._liquidations.commit_liquidation_complete(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence)

    async def fail_liquidation_case(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        failure_code: str,
    ) -> None:
        return await self._liquidations.fail_liquidation_case(run_id=run_id, liquidation_id=liquidation_id, failure_code=failure_code)

    async def commit_liquidation_bankruptcy(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        return await self._liquidations.commit_liquidation_bankruptcy(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence)


    async def commit_liquidation_insurance(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        return await self._liquidations.commit_liquidation_insurance(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence)

    async def commit_liquidation_recheck(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        return await self._liquidations.commit_liquidation_recheck(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence)

    async def commit_liquidation_execution(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
        order_id: str,
    ) -> None:
        return await self._liquidations.commit_liquidation_execution(run_id=run_id, liquidation_id=liquidation_id, step_sequence=step_sequence, order_id=order_id)

    async def finalize_hedge_inputs(
        self, run_id: str, *, risk_virtual_time_ms: int | None = None,
    ) -> None:
        cached_fingerprint = self._hedge_risk_fingerprints.get(run_id)
        committed_fingerprint = await self.base_store.run_extension_write(
            lambda connection: self._finalize_hedge_inputs_in_transaction(
                connection, run_id=run_id, risk_virtual_time_ms=risk_virtual_time_ms,
                cached_fingerprint=cached_fingerprint,
            )
        )
        self._cache_committed_hedge_fingerprint(run_id, committed_fingerprint)

    async def held_mark_guard(
        self, run_id: str, *, track_id: str, mark: Decimal,
        current_virtual_time_ms: int, target_actual_time_ms: int,
    ) -> bool:
        """Reuse only a successfully checked, unchanged single-track risk state."""
        checked = self._hedge_risk_fingerprints.get(run_id)
        if checked is None:
            return False

        def read(connection: sqlite3.Connection) -> bool:
            account = connection.execute(
                "SELECT status FROM replay_training_contract_account WHERE run_id = ?", (run_id,),
            ).fetchone()
            if account is None or account["status"] != "ACTIVE":
                return False
            if connection.execute(
                """SELECT 1 FROM replay_training_liquidation_case WHERE run_id = ?
                   AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1""",
                (run_id,),
            ).fetchone() is not None:
                return False
            if account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id) != checked:
                return False
            row = connection.execute(
                """SELECT projection.*, binding.status AS binding_status, binding.bound_range_end_ms,
                          track.public_price
                   FROM replay_hedge_track_public_projection AS projection
                   JOIN replay_hedge_track_public_binding AS binding USING(run_id, track_id)
                   JOIN replay_training_market_track AS track USING(run_id, track_id)
                   WHERE projection.run_id = ? AND projection.track_id = ?""", (run_id, track_id),
            ).fetchone()
            if row is None or row["binding_status"] != "ACTIVE" or target_actual_time_ms > int(row["bound_range_end_ms"]):
                return False
            if int(row["as_of_virtual_time_ms"]) > current_virtual_time_ms:
                return False
            state = json.loads(str(row["state_json"]))
            material = {
                "schema_version": "replay.hedge-track-public-projection.v1",
                "run_id": run_id, "track_id": track_id,
                "last_event_sequence": int(row["last_event_sequence"]),
                "as_of_actual_time_ms": int(row["as_of_actual_time_ms"]),
                "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
                "state": state, "input_chain_hash": str(row["input_chain_hash"]),
            }
            if canonical_sha256(material) != row["component_hash"]:
                return False
            return Decimal(str(state["mark_index"]["mark_price"])) == mark == Decimal(str(row["public_price"]))

        return await self.base_store.run_extension_read(read)

    async def finalize_hedge_inputs_and_checkpoint(
        self, run_id: str, *, risk_virtual_time_ms: int,
        events: Sequence[StableMarketEvent],
    ) -> bool:
        """Commit one complete risk-safe market wave with its global checkpoint.

        Liquidations keep the original reconciliation boundary: commit risk,
        return False, and let the caller settle them before recording the wave.
        """
        ordered = stable_market_event_order(events)
        cached_fingerprint = self._hedge_risk_fingerprints.get(run_id)

        def write(connection: sqlite3.Connection) -> tuple[str | None, bool]:
            return self._checkpoint_hedge_wave_in_transaction(
                connection, run_id=run_id, risk_virtual_time_ms=risk_virtual_time_ms,
                ordered=ordered, cached_fingerprint=cached_fingerprint,
            )

        fingerprint, checkpointed = await self.base_store.run_extension_write(write)
        self._cache_committed_hedge_fingerprint(run_id, fingerprint)
        return checkpointed

    async def apply_hedge_inputs_and_checkpoint(
        self, run_id: str, *, risk_virtual_time_ms: int,
        input_events: Sequence[HedgeInputEvent],
        events: Sequence[StableMarketEvent],
        event_virtual_times_ms: Sequence[int] | None = None,
        checkpoint_market_wave: bool = True,
    ) -> tuple[tuple[StableMarketEvent, ...], bool]:
        """Commit mark inputs, exact risk history and the wave in one transaction."""
        if not input_events or any(
            event.source_kind != "PUBLIC" or event.event_kind != "MARK_INDEX"
            or event.event_phase != 30 for event in input_events
        ):
            raise ValueError("combined market wave requires public mark inputs")
        input_write = self._hedge_input_write_operation(
            run_id, events=input_events, virtual_time_ms=risk_virtual_time_ms,
            event_virtual_times_ms=event_virtual_times_ms,
        )
        market_events = tuple(events)
        cached_fingerprint = self._hedge_risk_fingerprints.get(run_id)

        def write(connection):
            applied = input_write(connection)
            if not checkpoint_market_wave:
                fingerprint = self._finalize_hedge_inputs_in_transaction(
                    connection, run_id=run_id, risk_virtual_time_ms=risk_virtual_time_ms,
                    cached_fingerprint=cached_fingerprint,
                )
                return applied, fingerprint, False
            fingerprint, checkpointed = self._checkpoint_hedge_wave_in_transaction(
                connection, run_id=run_id, risk_virtual_time_ms=risk_virtual_time_ms,
                ordered=stable_market_event_order((*market_events, *applied)),
                cached_fingerprint=cached_fingerprint,
            )
            return applied, fingerprint, checkpointed

        applied, fingerprint, checkpointed = await self.base_store.run_extension_write(write)
        self._cache_committed_hedge_fingerprint(run_id, fingerprint)
        return applied, checkpointed

    def _checkpoint_hedge_wave_in_transaction(
        self, connection: sqlite3.Connection, *, run_id: str,
        risk_virtual_time_ms: int, ordered: Sequence[StableMarketEvent],
        cached_fingerprint: str | None,
    ) -> tuple[str | None, bool]:
        fingerprint = self._finalize_hedge_inputs_in_transaction(
            connection, run_id=run_id, risk_virtual_time_ms=risk_virtual_time_ms,
            cached_fingerprint=cached_fingerprint,
        )
        pending = connection.execute(
            """SELECT 1 FROM replay_training_liquidation_case
               WHERE run_id = ? AND state NOT IN (
                   'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED', 'RECOVERED_AFTER_CANCEL'
               ) LIMIT 1""", (run_id,),
        ).fetchone()
        if fingerprint is None or pending is not None:
            return fingerprint, False
        self._record_global_events_in_transaction(
            connection, run_id=run_id, ordered=ordered, materialize_portfolio=False,
        )
        return fingerprint, True

    def _finalize_hedge_inputs_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        risk_virtual_time_ms: int | None,
        cached_fingerprint: str | None,
    ) -> str | None:
        run = connection.execute(
            """
            SELECT position_mode FROM replay_training_run WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run is None or run["position_mode"] != "HEDGE":
            return None
        now_ms = self.base_store._validated_now_ms()
        account_marks_ops.apply_hedge_mark_projection(
            connection,
            run_id=run_id,
            now_ms=now_ms,
        )
        interval = getattr(self, "_recorded_risk_context", None)
        if (
            interval is not None
            and interval["connection"] is connection
            and interval["run_id"] == run_id
        ):
            # The transaction checked the complete state on entry. Its only
            # permitted input is MARK_INDEX; broker interactions are rejected
            # before the market frame is synchronized. Update equity at each
            # mark; detailed risk state is needed only at a checkpoint or a
            # critical review event inside this proven interaction-free range.
            marked = connection.execute(
                "SELECT public_price, account_json FROM replay_training_market_track "
                "WHERE run_id=? AND track_id=?",
                (run_id, interval["track_id"]),
            ).fetchone()
            mark = marked["public_price"]
            if mark != interval["mark"]:
                equity = interval["base_equity"] + (
                    Decimal(json.loads(marked["account_json"])["equity"])
                    - interval["initial_equity"]
                )
                connection.execute(
                    "UPDATE replay_training_run SET current_equity=?, updated_at_ms=? WHERE run_id=?",
                    (decimal_to_string(equity, field_name="equity"), now_ms, run_id),
                )
                interval["dirty"] = True
                interval["virtual_time_ms"] = risk_virtual_time_ms
                interval["mark"] = mark
            return cached_fingerprint
        fingerprint = account_marks_ops.hedge_risk_fingerprint(
            connection,
            run_id=run_id,
        )
        if fingerprint == cached_fingerprint:
            return fingerprint
        liquidation_ops.detect_contract_liquidations(
            connection,
            run_id=run_id,
            now_ms=now_ms,
            trigger_virtual_time_ms=risk_virtual_time_ms,
            refresh_current_equity=True,
        )
        return account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id)

    def _cache_committed_hedge_fingerprint(
        self, run_id: str, committed_fingerprint: str | None,
    ) -> None:
        if committed_fingerprint is None:
            self._hedge_risk_fingerprints.pop(run_id, None)
            return
        self._hedge_risk_fingerprints.pop(run_id, None)
        self._hedge_risk_fingerprints[run_id] = committed_fingerprint
        while (
            len(self._hedge_risk_fingerprints)
            > account_marks_ops._HEDGE_RISK_FINGERPRINT_CACHE_MAX_RUNS
        ):
            oldest_run_id = next(iter(self._hedge_risk_fingerprints))
            self._hedge_risk_fingerprints.pop(oldest_run_id, None)

    def _materialize_recorded_risk(self, connection, *, run_id):
        interval = getattr(self, "_recorded_risk_context", None)
        if (
            interval is None
            or interval["connection"] is not connection
            or interval["run_id"] != run_id
            or not interval["dirty"]
        ):
            return
        liquidation_ops.detect_contract_liquidations(
            connection,
            run_id=run_id,
            now_ms=self.base_store._validated_now_ms(),
            trigger_virtual_time_ms=interval["virtual_time_ms"],
            refresh_current_equity=True,
            record_valuation_history=False,
        )
        if connection.execute(
            "SELECT 1 FROM replay_training_liquidation_case WHERE run_id=? "
            "AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
            (run_id,),
        ).fetchone():
            raise ValueError("recorded interval violated its risk envelope")
        interval["dirty"] = False


    async def pending_account_global_events(
        self,
        run_id: str,
    ) -> tuple[StableMarketEvent, ...]:
        def read(connection: sqlite3.Connection) -> tuple[StableMarketEvent, ...]:
            rows = connection.execute(
                """
                SELECT applied.track_id, applied.archive_event_sequence,
                       applied.event_time_ms, applied.event_phase
                FROM replay_account_history_applied_event AS applied
                LEFT JOIN replay_training_global_event AS global_event
                  ON global_event.run_id = applied.run_id
                 AND global_event.track_id = 'account:' || applied.track_id
                 AND global_event.source_sequence =
                     applied.archive_event_sequence
                WHERE applied.run_id = ? AND global_event.global_sequence IS NULL
                ORDER BY applied.event_time_ms, applied.event_phase,
                         applied.track_id, applied.archive_event_sequence
                """,
                (run_id,),
            ).fetchall()
            return tuple(
                StableMarketEvent(
                    actual_event_time_ms=int(row["event_time_ms"]),
                    event_phase=int(row["event_phase"]),
                    market_track_stable_id=f"account:{row['track_id']}",
                    source_sequence=int(row["archive_event_sequence"]),
                )
                for row in rows
            )

        return await self.base_store.run_extension_read(read)

    async def audit_account(
        self,
        run_id: str,
        *,
        authoritative_projections: (Mapping[str, Mapping[str, object]] | None) = None,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> dict[str, object]:
            return account_audit_ops.write_account_audit(
                connection,
                run_id=run_id,
                now_ms=self.base_store._validated_now_ms(),
                authoritative_projections=authoritative_projections,
            )

        return await self.base_store.run_extension_write(write)

    async def invalidate_account_audit(self, run_id: str) -> None:
        """Mark the cached audit head stale before continuous account mutation."""

        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                UPDATE replay_training_account_history
                SET auditor_status = 'NOT_RUN', auditor_proof_hash = NULL,
                    auditor_differences_json = '[]', updated_at_ms = ?
                WHERE run_id = ? AND auditor_status != 'NOT_RUN'
                """,
                (now_ms, run_id),
            )

        await self.base_store.run_extension_write(write)

    async def finalize_account_history(
        self,
        run_id: str,
        *,
        write_audit: bool = True,
        risk_virtual_time_ms: int | None = None,
    ) -> dict[str, object] | None:
        """Reapply authoritative marks, run risk, and emit an independent audit."""

        def write(connection: sqlite3.Connection) -> dict[str, object] | None:
            history = connection.execute(
                """
                SELECT account_data_mode, status
                FROM replay_training_account_history WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if history is None or history["account_data_mode"] != "HISTORICAL_EXACT":
                return None
            if history["status"] != "ACTIVE":
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_ARCHIVE_DEGRADED",
                    "exact account history is not active",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            now_ms = self.base_store._validated_now_ms()
            rows = connection.execute(
                """
                SELECT track_id FROM replay_training_market_track
                WHERE run_id = ? AND subscription_tier = 'FULL'
                ORDER BY stable_ordinal, track_id
                """,
                (run_id,),
            ).fetchall()
            for row in rows:
                account_marks_ops.apply_exact_mark_projection(
                    connection,
                    run_id=run_id,
                    track_id=str(row["track_id"]),
                    now_ms=now_ms,
                )
            liquidation_ops.detect_contract_liquidations(
                connection,
                run_id=run_id,
                now_ms=now_ms,
                trigger_virtual_time_ms=risk_virtual_time_ms,
            )
            portfolio_ops.refresh_contract_current_equity(
                connection,
                run_id=run_id,
                now_ms=now_ms,
            )
            if not write_audit:
                return None
            return account_audit_ops.write_account_audit(
                connection,
                run_id=run_id,
                now_ms=now_ms,
            )

        return await self.base_store.run_extension_write(write)


    def fork_run_writer(
        self,
        *,
        child_run_id: str,
        parent_run_id: str,
        parent_event_id: str,
        parent_checkpoint_id: int,
        parent_timeline_sequence: int | None = None,
        parent_anchor_set_hash: str | None = None,
    ) -> Callable[..., object]:
        """Build the v2 metadata half of an exact checkpoint fork."""

        def write(
            connection: sqlite3.Connection,
            now_ms: int,
            *,
            session_id: str,
            session_state: Mapping[str, object],
            component_state: Mapping[str, object],
            broker_config: Mapping[str, object],
            dataset_ref: Mapping[str, object],
            dataset_blob: Mapping[str, object],
            actual_replay_start_ms: int,
            actual_replay_end_ms: int,
        ) -> None:
            parent = connection.execute(
                """
                SELECT r.*, i.strict_eligible, i.start_time_known, i.revealed,
                       i.allowed_mutations_json, i.result_label,
                       rule.rule_json, rule.rule_hash,
                       history.account_data_mode, history.fidelity AS history_fidelity,
                       history.archive_proof_hash
                FROM replay_training_run AS r
                JOIN replay_training_integrity AS i USING(run_id)
                JOIN replay_training_rule AS rule
                  ON rule.run_id = r.run_id
                 AND rule.revision = r.active_rule_revision
                JOIN replay_training_account_history AS history USING(run_id)
                WHERE r.run_id = ?
                """,
                (parent_run_id,),
            ).fetchone()
            if parent is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "parent training run does not exist",
                    status_code=404,
                )
            checkpoint = connection.execute(
                """
                SELECT state_hash FROM replay_review_actor_anchor
                WHERE run_id = ? AND checkpoint_id = ?
                  AND adapter_session_id = ?
                """,
                (
                    parent_run_id,
                    parent_checkpoint_id,
                    parent["adapter_session_id"],
                ),
            ).fetchone()
            if checkpoint is None or str(checkpoint["state_hash"]) != str(
                session_state["state_hash"]
            ):
                raise TrainingRunError(
                    "REVIEW_FORK_MISMATCH",
                    "fork checkpoint state hash changed",
                    status_code=409,
                )
            cursor = session_state.get("cursor")
            account = component_state.get("account")
            if not isinstance(cursor, Mapping) or not isinstance(account, Mapping):
                raise TypeError("forked training snapshot is invalid")
            run_records_ops.insert_run(
                connection,
                {
                    "run_id": child_run_id,
                    "adapter_session_id": session_id,
                    "name": run_records_ops._safe_name(
                        f"{parent['name']} · Fork"[:80],
                        fallback=f"Fork {child_run_id[-8:]}",
                    ),
                    "state": str(session_state["state"]),
                    "source_kind": str(parent["source_kind"]),
                    "start_mode": str(parent["start_mode"]),
                    "integrity_mode": str(parent["integrity_mode"]),
                    "time_disclosure_policy": str(parent["time_disclosure_policy"]),
                    "book_mode": str(parent["book_mode"]),
                    "margin_mode": str(parent["margin_mode"]),
                    "position_mode": str(parent["position_mode"]),
                    "funding_mode": str(parent["funding_mode"]),
                    "account_data_mode": str(parent["account_data_mode"]),
                    "hedge_public_history_ref_json": parent[
                        "hedge_public_history_ref_json"
                    ],
                    "simulation_manifest_ref_json": parent[
                        "simulation_manifest_ref_json"
                    ],
                    "simulation_contract_hash": parent["simulation_contract_hash"],
                    "simulation_model_version": parent["simulation_model_version"],
                    "account_fidelity": parent["account_fidelity"],
                    "insurance_adl_fidelity": parent["insurance_adl_fidelity"],
                    "allow_rule_changes": int(parent["allow_rule_changes"]),
                    "exchange": str(parent["exchange"]),
                    "market_type": str(parent["market_type"]),
                    "last_symbol": str(parent["last_symbol"]),
                    "settlement_asset": str(parent["settlement_asset"]),
                    "base_interval": str(parent["base_interval"]),
                    "display_interval": str(parent["display_interval"]),
                    "initial_equity": str(parent["initial_equity"]),
                    "current_equity": str(account["equity"]),
                    "summary_revision": validate_v2_counter(
                        session_state["revision"], field_name="fork revision"
                    ),
                    "revision": validate_v2_counter(
                        session_state["revision"], field_name="fork revision"
                    ),
                    "source_sequence": validate_v2_counter(
                        session_state["source_sequence"],
                        field_name="fork source_sequence",
                    ),
                    "virtual_time_ms": int(cursor["virtual_time_ms"]),
                    "catalog_epoch": str(parent["catalog_epoch"]),
                    "dataset_epoch": str(parent["dataset_epoch"]),
                    "compatibility": "READY",
                    "now_ms": now_ms,
                },
            )
            if str(parent["account_data_mode"]) == "HISTORICAL_EXACT":
                connection.execute(
                    """
                    INSERT INTO replay_training_account_history(
                        run_id, account_data_mode, status, fidelity,
                        archive_proof_hash, degraded_reason, auditor_status,
                        auditor_proof_hash, auditor_differences_json,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, 'HISTORICAL_EXACT', 'ACTIVE', ?, ?, NULL,
                              'NOT_RUN', NULL, '[]', ?, ?)
                    """,
                    (
                        child_run_id,
                        parent["history_fidelity"],
                        parent["archive_proof_hash"],
                        now_ms,
                        now_ms,
                    ),
                )
            else:
                run_records_ops.insert_modelled_account_history(
                    connection,
                    run_id=child_run_id,
                    account_data_mode=str(parent["account_data_mode"]),
                    fidelity=str(parent["history_fidelity"]),
                    now_ms=now_ms,
                )
            run_records_ops.copy_launch_context(
                connection,
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
                now_ms=now_ms,
            )
            run_records_ops.copy_start_selection(
                connection,
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
                actual_start_ms=actual_replay_start_ms,
                actual_end_ms=actual_replay_end_ms,
                dataset_epoch=str(parent["dataset_epoch"]),
                now_ms=now_ms,
            )
            history_policy = run_records_ops.copy_data_policy(
                connection,
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
                actual_replay_start_ms=actual_replay_start_ms,
                now_ms=now_ms,
            )
            run_records_ops.insert_track(
                connection,
                run_id=child_run_id,
                adapter_session_id=session_id,
                source_kind=str(parent["source_kind"]),
                exchange=str(parent["exchange"]),
                market_type=str(parent["market_type"]),
                symbol=str(parent["last_symbol"]),
                settlement_asset=str(parent["settlement_asset"]),
                dataset_epoch=str(parent["dataset_epoch"]),
                cursor={
                    **cursor,
                    "revision": validate_v2_counter(
                        session_state["revision"], field_name="fork revision"
                    ),
                },
                component_state=component_state,
                now_ms=now_ms,
            )
            if str(parent["position_mode"]) == "HEDGE":
                fork_records_ops.copy_hedge_input_binding(
                    connection,
                    parent_run_id=parent_run_id,
                    child_run_id=child_run_id,
                    now_ms=now_ms,
                )
            if str(parent["book_mode"]) == "BOOK_ASSISTED_REQUIRED":
                fork_records_ops.copy_review_book_inputs(
                    connection,
                    child_run_id=child_run_id,
                    parent_run_id=parent_run_id,
                    parent_event_id=parent_event_id,
                    track_mapping={"track-1": "track-1"},
                    now_ms=now_ms,
                )
            fork_records_ops.insert_fork_contract_account(
                connection,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                parent_event_id=parent_event_id,
                source_kind=str(parent["source_kind"]),
                settlement_asset=str(parent["settlement_asset"]),
                virtual_time_ms=int(cursor["virtual_time_ms"]),
                source_sequence=validate_v2_counter(
                    session_state["source_sequence"],
                    field_name="fork source_sequence",
                ),
                component_state=component_state,
                broker_config=broker_config,
                now_ms=now_ms,
            )
            fork_records_ops.copy_review_rule_policies(
                connection,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                parent_event_id=parent_event_id,
                virtual_time_ms=int(cursor["virtual_time_ms"]),
                source_sequence=validate_v2_counter(
                    session_state["source_sequence"],
                    field_name="fork source_sequence",
                ),
                now_ms=now_ms,
            )
            if str(parent["account_data_mode"]) == "HISTORICAL_EXACT":
                fork_records_ops.copy_exact_review_fork_inputs(
                    connection,
                    child_run_id=child_run_id,
                    parent_run_id=parent_run_id,
                    parent_event_id=parent_event_id,
                    track_mapping={"track-1": "track-1"},
                    now_ms=now_ms,
                )
                account_marks_ops.apply_exact_mark_projection(
                    connection,
                    run_id=child_run_id,
                    track_id="track-1",
                    now_ms=now_ms,
                )
            parent_view = connection.execute(
                "SELECT * FROM replay_training_viewer_state WHERE run_id = ?",
                (parent_run_id,),
            ).fetchone()
            review_event = connection.execute(
                """
                SELECT projection_json FROM replay_review_timeline_event
                WHERE run_id = ? AND event_id = ?
                """,
                (parent_run_id, parent_event_id),
            ).fetchone()
            review_view: Mapping[str, object] | None = None
            if review_event is not None:
                review_projection = json.loads(str(review_event["projection_json"]))
                if isinstance(review_projection, Mapping) and isinstance(
                    review_projection.get("viewer_state"), Mapping
                ):
                    review_view = cast(
                        Mapping[str, object],
                        review_projection["viewer_state"],
                    )
            run_records_ops.insert_viewer_state(
                connection,
                ViewerState(
                    run_id=child_run_id,
                    selected_track_id=(
                        "track-1"
                        if review_view is None
                        else str(review_view["selected_track_id"])
                    ),
                    display_interval=(
                        str(parent["display_interval"])
                        if review_view is None
                        else str(review_view["display_interval"])
                    ),
                    chart_type=(
                        (
                            "candles"
                            if parent_view is None
                            else str(parent_view["chart_type"])
                        )
                        if review_view is None
                        else str(review_view["chart_type"])
                    ),
                    visible_range=(
                        None
                        if review_view is None
                        else cast(
                            Mapping[str, object] | None,
                            review_view.get("visible_range"),
                        )
                    ),
                    pane_layout=(
                        {}
                        if review_view is None
                        else cast(
                            Mapping[str, object],
                            review_view["pane_layout"],
                        )
                    ),
                    rail_layout=(
                        {}
                        if review_view is None
                        else cast(
                            Mapping[str, object],
                            review_view["rail_layout"],
                        )
                    ),
                    semantic_view_revision=(
                        0
                        if review_view is None
                        else int(review_view["semantic_view_revision"])
                    ),
                ),
                now_ms=now_ms,
            )
            rule = json.loads(str(parent["rule_json"]))
            run_records_ops.insert_rule(
                connection,
                run_id=child_run_id,
                rule=rule,
                now_ms=now_ms,
            )
            run_records_ops.insert_initial_action(
                connection,
                run_id=child_run_id,
                action_type="FORK_FROM_REVIEW",
                action={
                    "schema": "replay.training.action.v2",
                    "parent_run_id": parent_run_id,
                    "parent_event_id": parent_event_id,
                    "parent_checkpoint_id": parent_checkpoint_id,
                },
                now_ms=now_ms,
            )
            run_records_ops.insert_pin(
                connection,
                run_id=child_run_id,
                track_id="track-1",
                adapter_session_id=session_id,
                dataset_epoch=str(parent["dataset_epoch"]),
                now_ms=now_ms,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO replay_archive_pin(
                    run_id, track_id, source_revision,
                    exchange, market_type, symbol, base_interval,
                    range_start_ms, range_end_ms, dataset_epoch, created_at_ms
                )
                SELECT ?, 'track-1', source_revision,
                       exchange, market_type, symbol, base_interval,
                       range_start_ms, range_end_ms, ?, ?
                FROM replay_archive_pin
                WHERE run_id = ? AND track_id = 'track-1'
                """,
                (
                    child_run_id,
                    str(parent["dataset_epoch"]),
                    now_ms,
                    parent_run_id,
                ),
            )
            register_archive_segment(
                connection,
                run_id=child_run_id,
                track_id="track-1",
                adapter_session_id=session_id,
                source_kind=str(parent["source_kind"]),
                dataset_ref=dataset_ref,
                dataset_blob=dataset_blob,
                actual_replay_start_ms=actual_replay_start_ms,
                actual_replay_end_ms=actual_replay_end_ms,
                history_policy=history_policy,
                now_ms=now_ms,
            )
            result_label = f"{parent['integrity_mode']}_FORKED_REVIEW"
            connection.execute(
                """
                INSERT INTO replay_training_integrity(
                    run_id, strict_eligible, start_time_known, revealed,
                    allowed_mutations_json, result_label, updated_at_ms
                ) VALUES (?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    int(parent["start_time_known"]),
                    int(parent["revealed"]),
                    str(parent["allowed_mutations_json"]),
                    result_label,
                    now_ms,
                ),
            )
            event = connection.execute(
                """
                SELECT *
                FROM replay_review_timeline_event
                WHERE run_id = ? AND event_id = ?
                """,
                (parent_run_id, parent_event_id),
            ).fetchone()
            if event is None:
                raise TypeError("review fork event is missing")
            effective_timeline = (
                int(event["timeline_sequence"])
                if parent_timeline_sequence is None
                else parent_timeline_sequence
            )
            effective_anchor_set_hash = (
                str(event["anchor_set_hash"])
                if parent_anchor_set_hash is None
                else parent_anchor_set_hash
            )
            if effective_timeline != int(
                event["timeline_sequence"]
            ) or effective_anchor_set_hash != str(event["anchor_set_hash"]):
                raise TrainingRunError(
                    "REVIEW_FORK_MISMATCH",
                    "review lineage changed before fork commit",
                    status_code=409,
                )
            connection.execute(
                """
                INSERT INTO replay_review_fork_lineage(
                    child_run_id, parent_run_id, parent_event_id,
                    parent_timeline_sequence, anchor_set_hash,
                    parent_projection_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    parent_run_id,
                    parent_event_id,
                    effective_timeline,
                    effective_anchor_set_hash,
                    canonical_sha256(
                        ReviewRecorder.decode_event_projection(
                            connection,
                            event=event,
                        )
                    ),
                    now_ms,
                ),
            )
            drawing = connection.execute(
                """
                SELECT document.* FROM replay_review_drawing_document AS document
                JOIN replay_review_timeline_event AS event
                  ON event.run_id = document.run_id
                 AND json_extract(
                     event.projection_json, '$.drawing_document_hash'
                 ) = document.document_hash
                WHERE event.run_id = ? AND event.event_id = ?
                """,
                (parent_run_id, parent_event_id),
            ).fetchone()
            if drawing is not None:
                connection.execute(
                    """
                    INSERT INTO replay_review_drawing_document(
                        run_id, document_hash, revision, command_id,
                        document_json, document_bytes, entity_count,
                        virtual_time_ms, source_sequence, created_at_ms
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        child_run_id,
                        drawing["document_hash"],
                        f"fork-drawing-{child_run_id}",
                        drawing["document_json"],
                        drawing["document_bytes"],
                        drawing["entity_count"],
                        cursor["virtual_time_ms"],
                        session_state["source_sequence"],
                        now_ms,
                    ),
                )
            public_time = public_time_ops.public_time(
                connection,
                session_id=session_id,
                policy=str(parent["time_disclosure_policy"]),
                revealed=bool(parent["revealed"]),
                public_time_ms=int(cursor["virtual_time_ms"]),
                sequence=validate_v2_counter(
                    session_state["source_sequence"],
                    field_name="fork source_sequence",
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_run_action_event(
                    run_id, action_sequence, event_id, command_id, event_type,
                    rule_revision, public_time_json, old_value_json,
                    new_value_json, reason, state_hash_before,
                    state_hash_after, created_at_ms
                ) VALUES (?, 1, 'action-00000001', NULL, 'FORK_FROM_REVIEW', 1,
                          ?, ?, ?, 'continue from review event', ?, ?, ?)
                """,
                (
                    child_run_id,
                    canonical_json(public_time),
                    canonical_json(
                        {
                            "parent_run_id": parent_run_id,
                            "parent_event_id": parent_event_id,
                        }
                    ),
                    canonical_json({"result_label": result_label}),
                    session_state["state_hash"],
                    session_state["state_hash"],
                    now_ms,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_run_lineage(
                    child_run_id, parent_run_id, parent_event_id,
                    parent_checkpoint_id, dataset_epoch, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    parent_run_id,
                    parent_event_id,
                    parent_checkpoint_id,
                    parent["dataset_epoch"],
                    now_ms,
                ),
            )
            curve_records_ops.upsert_equity_samples(
                connection,
                run_id=child_run_id,
                session_id=session_id,
                policy=str(parent["time_disclosure_policy"]),
                revealed=bool(parent["revealed"]),
                state=session_state,
                component_state=component_state,
                now_ms=now_ms,
            )

        def factory(
            *,
            session_id: str,
            session_state: Mapping[str, object],
            component_state: Mapping[str, object],
            broker_config: Mapping[str, object],
            dataset_ref: Mapping[str, object],
            dataset_blob: Mapping[str, object],
            actual_replay_start_ms: int,
            actual_replay_end_ms: int,
        ) -> Callable[[sqlite3.Connection, int], None]:
            return lambda connection, now_ms: write(
                connection,
                now_ms,
                session_id=session_id,
                session_state=session_state,
                component_state=component_state,
                broker_config=broker_config,
                dataset_ref=dataset_ref,
                dataset_blob=dataset_blob,
                actual_replay_start_ms=actual_replay_start_ms,
                actual_replay_end_ms=actual_replay_end_ms,
            )

        return factory

    async def list_runs(
        self,
        *,
        limit: int,
        cursor: str | None,
        state: str | None,
        source_kind: str | None,
        compatibility: str | None,
    ) -> dict[str, object]:
        return await self._runs.list_runs(limit=limit, cursor=cursor, state=state, source_kind=source_kind, compatibility=compatibility)

    async def get_run(self, run_id: str) -> dict[str, object]:
        return await self._runs.get_run(run_id)

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
        return await self._runs.account_record_page(run_id, record_type=record_type, order_scope=order_scope, track_id=track_id, cursor=cursor, limit=limit)

    async def training_results(self, run_id: str, *, limit: int) -> dict[str, object]:
        return await self._runs.training_results(run_id, limit=limit)

    async def deletion_target(self, run_id: str) -> tuple[str, tuple[str, ...]]:
        """Return the archive kind and replay sessions that a delete would remove."""
        return await self._runs.deletion_target(run_id)

    async def delete_run(
        self,
        run_id: str,
        *,
        expected_session_ids: Sequence[str],
    ) -> tuple[str, ...]:
        """Delete one Hub archive and its replay sessions in one SQLite transaction."""
        return await self._runs.delete_run(run_id, expected_session_ids=expected_session_ids)

    async def run_id_for_session(self, session_id: str) -> str:
        return await self._runs.run_id_for_session(session_id)

    async def run_binding(self, run_id: str) -> dict[str, object]:
        return await self._runs.run_binding(run_id)

    async def integrity(self, run_id: str) -> dict[str, object]:
        return await self._runs.integrity(run_id)

    async def public_times(
        self,
        run_id: str,
        *,
        timeline_ms: tuple[int, ...],
        max_items: int,
    ) -> dict[str, object]:
        return await self._runs.public_times(run_id, timeline_ms=timeline_ms, max_items=max_items)

    async def equity(
        self,
        run_id: str,
        *,
        resolution: str,
        limit: int,
    ) -> dict[str, object]:
        return await self._curves.equity(run_id, resolution=resolution, limit=limit)

    async def record_view_action(
        self,
        *,
        run_id: str,
        command_id: str,
        event_type: str,
        semantic_key: str,
        value: Mapping[str, object],
        public_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        return await self._review_repository.record_view_action(run_id=run_id, command_id=command_id, event_type=event_type, semantic_key=semantic_key, value=value, public_time_ms=public_time_ms, source_sequence=source_sequence)

    async def run_rules(self, run_id: str) -> dict[str, object]:
        return await self._review_repository.run_rules(run_id)

    async def current_drawing_document(self, run_id: str) -> dict[str, object]:
        return await self._review_repository.current_drawing_document(run_id)

    async def record_drawing_document(
        self,
        *,
        run_id: str,
        command_id: str,
        document_hash: str,
        document: Mapping[str, object],
        entity_count: int,
    ) -> dict[str, object]:
        return await self._review_repository.record_drawing_document(run_id=run_id, command_id=command_id, document_hash=document_hash, document=document, entity_count=entity_count)

    async def record_review_marker(
        self,
        *,
        run_id: str,
        command_id: str,
        text: str,
    ) -> dict[str, object]:
        return await self._review_repository.record_review_marker(run_id=run_id, command_id=command_id, text=text)


    async def start_review(
        self,
        *,
        run_id: str,
        review_id: str,
        event_id: str | None,
    ) -> dict[str, object]:
        return await self._review_repository.start_review(run_id=run_id, review_id=review_id, event_id=event_id)

    async def checkpoint_for_event(
        self,
        run_id: str,
        event_id: str,
    ) -> dict[str, object]:
        return await self._review_repository.checkpoint_for_event(run_id, event_id)

    async def control_review(
        self,
        *,
        run_id: str,
        review_id: str,
        action: str,
        event_id: str | None,
        expected_cursor_revision: int,
        playback_rate: str | None,
    ) -> dict[str, object]:
        return await self._review_repository.control_review(run_id=run_id, review_id=review_id, action=action, event_id=event_id, expected_cursor_revision=expected_cursor_revision, playback_rate=playback_rate)

    async def get_viewer_state(self, run_id: str) -> ViewerState:
        return await self._review_repository.get_viewer_state(run_id)

    async def viewer_state_at_revision(
        self,
        run_id: str,
        revision: int,
    ) -> ViewerState:
        return await self._review_repository.viewer_state_at_revision(run_id, revision)

    async def set_display_interval(
        self,
        *,
        run_id: str,
        display_interval: str,
        expected_revision: int,
        command_id: str,
        command: Mapping[str, object],
    ) -> ViewerState:
        return await self._review_repository.set_display_interval(run_id=run_id, display_interval=display_interval, expected_revision=expected_revision, command_id=command_id, command=command)

    async def get_command_result(
        self,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
    ) -> dict[str, object] | None:
        return await self._advances.get_command_result(run_id, command_id, command)

    async def save_command_result(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
        result: Mapping[str, object],
    ) -> None:
        return await self._advances.save_command_result(run_id=run_id, command_id=command_id, command=command, result=result)


    async def begin_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
    ) -> dict[str, object]:
        """Persist a visible single-flight marker without publishing candidates."""
        return await self._advances.begin_period_summary_build(run_id=run_id, set_id=set_id)

    async def finish_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
        metadata: Mapping[str, object],
        build_proof_hash: str,
        candidates: Sequence[EncodedPeriodSummaryCandidate],
        source_event_count: int,
        build_wall_ms: int,
        build_cpu_ms: int,
    ) -> dict[str, object]:
        """Atomically publish a complete checksum-verified summary generation."""
        return await self._advances.finish_period_summary_build(run_id=run_id, set_id=set_id, metadata=metadata, build_proof_hash=build_proof_hash, candidates=candidates, source_event_count=source_event_count, build_wall_ms=build_wall_ms, build_cpu_ms=build_cpu_ms)

    async def fail_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
        cancelled: bool,
        error_code: str,
        error_message: str,
    ) -> None:
        return await self._advances.fail_period_summary_build(run_id=run_id, set_id=set_id, cancelled=cancelled, error_code=error_code, error_message=error_message)

    async def period_summary_status(self, run_id: str) -> dict[str, object]:
        return await self._advances.period_summary_status(run_id)

    async def period_summary_candidate(
        self,
        *,
        run_id: str,
        current_source_sequence: int,
        target_virtual_time_ms: int,
        identity: Mapping[str, object],
    ) -> dict[str, object]:
        """Load at most one active candidate and validate every persisted byte."""
        return await self._advances.period_summary_candidate(run_id=run_id, current_source_sequence=current_source_sequence, target_virtual_time_ms=target_virtual_time_ms, identity=identity)

    async def get_advance_intent(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
    ) -> dict[str, object] | None:
        return await self._advances.get_advance_intent(run_id=run_id, command_id=command_id, command=command)

    async def begin_advance_intent(self, **kwargs) -> dict[str, object]:
        return await self._advances.begin_advance_intent(**kwargs)

    def _advance_intent_writer(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
        session_id: str,
        initial_cursor: Mapping[str, object],
        target_virtual_time_ms: int,
        plan: Mapping[str, object],
        summary: ReplayPeriodSummary | None,
    ) -> Callable[[sqlite3.Connection], sqlite3.Row]:
        return self._advances._advance_intent_writer(run_id=run_id, command_id=command_id, command=command, session_id=session_id, initial_cursor=initial_cursor, target_virtual_time_ms=target_virtual_time_ms, plan=plan, summary=summary)

    async def update_advance_intent_cursor(
        self,
        *,
        run_id: str,
        command_id: str,
        cursor: Mapping[str, object],
    ) -> None:
        return await self._advances.update_advance_intent_cursor(run_id=run_id, command_id=command_id, cursor=cursor)

    async def finish_advance_intent(
        self,
        *,
        run_id: str,
        command_id: str,
        result: Mapping[str, object],
        cancelled: bool,
    ) -> None:
        return await self._advances.finish_advance_intent(run_id=run_id, command_id=command_id, result=result, cancelled=cancelled)

    def _finish_advance_intent_in_transaction(self, connection, *, run_id, command_id, result, cancelled):
        return self._advances._finish_advance_intent_in_transaction(connection, run_id=run_id, command_id=command_id, result=result, cancelled=cancelled)


    async def get_market_tracks(
        self,
        run_id: str,
        *,
        live_portfolio: bool = False,
    ) -> dict[str, object]:
        return await self._markets.get_market_tracks(run_id, live_portfolio=live_portfolio)

    async def get_market_track_heads(self, run_id: str) -> list[dict[str, object]]:
        """Read operational track state without materializing audit history."""
        return await self._markets.get_market_track_heads(run_id)

    async def get_market_track(
        self,
        run_id: str,
        track_id: str,
    ) -> dict[str, object]:
        return await self._markets.get_market_track(run_id, track_id)

    async def allocate_isolated_margin(
        self,
        *,
        run_id: str,
        track_id: str,
        position_side: str | None,
        amount: str,
        command_id: str,
        virtual_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        return await self._markets.allocate_isolated_margin(run_id=run_id, track_id=track_id, position_side=position_side, amount=amount, command_id=command_id, virtual_time_ms=virtual_time_ms, source_sequence=source_sequence)

    async def revise_contract_policy(
        self,
        *,
        run_id: str,
        command_id: str,
        command_type: str,
        payload: Mapping[str, object],
        virtual_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        return await self._markets.revise_contract_policy(run_id=run_id, command_id=command_id, command_type=command_type, payload=payload, virtual_time_ms=virtual_time_ms, source_sequence=source_sequence)


    async def pending_liquidations(self, run_id: str) -> tuple[dict[str, object], ...]:
        return await self._liquidations.pending_liquidations(run_id)

    async def reserve_market_track(
        self,
        *,
        run_id: str,
        exchange: str,
        market_type: str,
        symbol: str,
        settlement_asset: str,
        source_kind: str,
        subscription_tier: str,
    ) -> dict[str, object]:
        return await self._markets.reserve_market_track(run_id=run_id, exchange=exchange, market_type=market_type, symbol=symbol, settlement_asset=settlement_asset, source_kind=source_kind, subscription_tier=subscription_tier)

    def attach_market_track_writer(
        self,
        *,
        run_id: str,
        track_id: str,
        requested_tier: str,
        historical_book_binding: PreparedHistoricalBookBinding | None = None,
        account_history_binding: PreparedAccountHistoryBinding | None = None,
        hedge_track_public_binding: PreparedHedgeTrackPublicBinding | None = None,
        review_parent_run_id: str | None = None,
        review_parent_track_id: str | None = None,
        review_parent_event_id: str | None = None,
    ) -> Callable[..., Callable[[sqlite3.Connection, int], None]]:
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
        ) -> Callable[[sqlite3.Connection, int], None]:
            def write(connection: sqlite3.Connection, now_ms: int) -> None:
                row = connection.execute(
                    """
                    SELECT * FROM replay_training_market_track
                    WHERE run_id = ? AND track_id = ?
                    """,
                    (run_id, track_id),
                ).fetchone()
                if row is None or row["adapter_session_id"] is not None:
                    raise TrainingRunError(
                        "MARKET_TRACK_CONFLICT",
                        "training market track cannot attach an adapter session",
                        status_code=409,
                    )
                cursor = session_state.get("cursor")
                if not isinstance(cursor, Mapping):
                    raise TypeError("market track adapter cursor must be an object")
                position, account, open_orders, public_price = run_records_ops.track_components(
                    component_state
                )
                connection.execute(
                    """
                    UPDATE replay_training_market_track
                    SET adapter_session_id = ?, state = 'READY',
                        subscription_tier = ?, dataset_epoch = ?,
                        virtual_time_ms = ?, source_sequence = ?, revision = ?,
                        public_price = ?, position_json = ?, account_json = ?,
                        open_orders_json = ?, degraded_reason = NULL,
                        updated_at_ms = ?
                    WHERE run_id = ? AND track_id = ?
                    """,
                    (
                        session_id,
                        requested_tier,
                        str(session_state["data_epoch"]),
                        int(cursor["virtual_time_ms"]),
                        validate_v2_counter(
                            session_state["source_sequence"],
                            field_name="source_sequence",
                        ),
                        validate_v2_counter(
                            session_state["revision"],
                            field_name="revision",
                        ),
                        public_price,
                        canonical_json(position),
                        canonical_json(account),
                        canonical_json(open_orders),
                        now_ms,
                        run_id,
                        track_id,
                    ),
                )
                run_records_ops.insert_pin(
                    connection,
                    run_id=run_id,
                    track_id=track_id,
                    adapter_session_id=session_id,
                    dataset_epoch=str(session_state["data_epoch"]),
                    now_ms=now_ms,
                )
                policy_row = connection.execute(
                    """
                    SELECT * FROM replay_training_data_policy
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if policy_row is None:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "training data policy is missing",
                        status_code=503,
                    )
                history_policy = run_records_ops.data_policy_from_row(policy_row)
                register_archive_segment(
                    connection,
                    run_id=run_id,
                    track_id=track_id,
                    adapter_session_id=session_id,
                    source_kind=str(row["source_kind"]),
                    dataset_ref=dataset_ref,
                    dataset_blob=dataset_blob,
                    actual_replay_start_ms=actual_replay_start_ms,
                    actual_replay_end_ms=actual_replay_end_ms,
                    history_policy=history_policy,
                    now_ms=now_ms,
                )
                run = connection.execute(
                    "SELECT book_mode FROM replay_training_run WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if (
                    run is not None
                    and run["book_mode"] == "BOOK_ASSISTED_REQUIRED"
                    and requested_tier == "FULL"
                ):
                    if (
                        review_parent_run_id is not None
                        and review_parent_track_id is not None
                        and review_parent_event_id is not None
                    ):
                        fork_records_ops.copy_review_book_inputs(
                            connection,
                            child_run_id=run_id,
                            parent_run_id=review_parent_run_id,
                            parent_event_id=review_parent_event_id,
                            track_mapping={review_parent_track_id: track_id},
                            now_ms=now_ms,
                        )
                    elif historical_book_binding is None:
                        raise TypeError(
                            "book-assisted track is missing its verified L2 binding"
                        )
                    else:
                        bind_historical_book_archive(
                            connection,
                            run_id=run_id,
                            track_id=track_id,
                            binding=historical_book_binding,
                            bound_range_start_ms=actual_replay_start_ms,
                            bound_range_end_ms=actual_replay_end_ms,
                            now_ms=now_ms,
                        )
                history = connection.execute(
                    """
                    SELECT account_data_mode
                    FROM replay_training_account_history WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if (
                    history is not None
                    and history["account_data_mode"] == "HISTORICAL_EXACT"
                    and requested_tier in {"WARM", "FULL"}
                ):
                    if (
                        review_parent_run_id is not None
                        and review_parent_track_id is not None
                        and review_parent_event_id is not None
                    ):
                        fork_records_ops.copy_exact_review_fork_inputs(
                            connection,
                            child_run_id=run_id,
                            parent_run_id=review_parent_run_id,
                            parent_event_id=review_parent_event_id,
                            track_mapping={review_parent_track_id: track_id},
                            now_ms=now_ms,
                        )
                    elif account_history_binding is None:
                        raise TypeError(
                            "exact account track is missing its archive binding"
                        )
                    else:
                        bind_account_history_archive(
                            connection,
                            run_id=run_id,
                            track_id=track_id,
                            binding=account_history_binding,
                            bound_range_start_ms=actual_replay_start_ms,
                            bound_range_end_ms=actual_replay_end_ms,
                            source_kind=str(row["source_kind"]),
                            now_ms=now_ms,
                        )
                else:
                    run_records_ops.insert_contract_track_rule(
                        connection,
                        run_id=run_id,
                        track_id=track_id,
                        source_kind=str(row["source_kind"]),
                        broker_config=broker_config,
                        effective_virtual_time_ms=int(cursor["virtual_time_ms"]),
                        now_ms=now_ms,
                    )
                if (
                    run is not None
                    and connection.execute(
                        "SELECT position_mode FROM replay_training_run WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()["position_mode"]
                    == "HEDGE"
                    and requested_tier == "FULL"
                    and hedge_track_public_binding is not None
                ):
                    bind_hedge_track_public_input(
                        connection,
                        run_id=run_id,
                        track_id=track_id,
                        source_kind=str(row["source_kind"]),
                        binding=hedge_track_public_binding,
                        virtual_time_ms=int(cursor["virtual_time_ms"]),
                        now_ms=now_ms,
                        verify_account_fee_policy=True,
                    )
                account_marks_ops.sync_contract_components(
                    connection,
                    run_id=run_id,
                    track_id=track_id,
                    virtual_time_ms=int(cursor["virtual_time_ms"]),
                    source_sequence=validate_v2_counter(
                        session_state["source_sequence"],
                        field_name="source_sequence",
                    ),
                    component_state=component_state,
                    now_ms=now_ms,
                    fork_parent_run_id=review_parent_run_id,
                    fork_parent_track_id=review_parent_track_id,
                )
                if (
                    history is not None
                    and history["account_data_mode"] == "HISTORICAL_EXACT"
                ):
                    account_marks_ops.apply_exact_mark_projection(
                        connection,
                        run_id=run_id,
                        track_id=track_id,
                        now_ms=now_ms,
                    )
                if (
                    run is not None
                    and connection.execute(
                        "SELECT position_mode FROM replay_training_run WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()["position_mode"]
                    == "HEDGE"
                    and requested_tier == "FULL"
                ):
                    existing_hedge_binding = connection.execute(
                        """
                        SELECT 1 FROM replay_hedge_track_public_binding
                        WHERE run_id = ? AND track_id = ? AND status = 'ACTIVE'
                        """,
                        (run_id, track_id),
                    ).fetchone()
                    if existing_hedge_binding is None:
                        raise TypeError(
                            "HEDGE FULL track is missing its exact public input binding"
                        )
                    account_marks_ops.apply_hedge_mark_projection(
                        connection,
                        run_id=run_id,
                        now_ms=now_ms,
                    )

            return write

        return extension_factory

    async def mark_market_track_error(
        self,
        *,
        run_id: str,
        track_id: str,
        reason: str,
        degraded: bool = False,
    ) -> None:
        return await self._markets.mark_market_track_error(run_id=run_id, track_id=track_id, reason=reason, degraded=degraded)

    async def set_market_track_tier(
        self,
        *,
        run_id: str,
        track_id: str,
        subscription_tier: str,
        historical_book_binding: PreparedHistoricalBookBinding | None = None,
    ) -> dict[str, object]:
        return await self._markets.set_market_track_tier(run_id=run_id, track_id=track_id, subscription_tier=subscription_tier, historical_book_binding=historical_book_binding)

    async def clear_market_track_degradation(
        self,
        *,
        run_id: str,
        track_id: str,
    ) -> dict[str, object]:
        return await self._markets.clear_market_track_degradation(run_id=run_id, track_id=track_id)

    async def select_market_track(
        self,
        *,
        run_id: str,
        track_id: str,
        expected_viewer_revision: int,
        command_id: str,
        command: Mapping[str, object],
    ) -> ViewerState:
        return await self._markets.select_market_track(run_id=run_id, track_id=track_id, expected_viewer_revision=expected_viewer_revision, command_id=command_id, command=command)

    async def record_global_events(
        self,
        run_id: str,
        events: Sequence[StableMarketEvent],
        *,
        materialize_portfolio: bool = True,
    ) -> dict[str, object]:
        ordered = stable_market_event_order(events)

        return await self.base_store.run_extension_write(
            lambda connection: self._record_global_events_in_transaction(
                connection, run_id=run_id, ordered=ordered,
                materialize_portfolio=materialize_portfolio,
            )
        )

    def _record_global_events_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        ordered: Sequence[StableMarketEvent],
        materialize_portfolio: bool,
        checkpoint_boundary: bool = True,
        prepared_hashes=None,
    ) -> dict[str, object]:
        if prepared_hashes is not None:
            prepared_hashes.validate(ordered)
        tail_row = connection.execute(
            """
            SELECT global_sequence, actual_event_time_ms, event_phase,
                   track_id, source_sequence
            FROM replay_training_global_event
            WHERE run_id = ?
            ORDER BY global_sequence DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        global_sequence = 0 if tail_row is None else int(tail_row["global_sequence"])
        tail_key = (
            None
            if tail_row is None
            else (
                int(tail_row["actual_event_time_ms"]),
                int(tail_row["event_phase"]),
                str(tail_row["track_id"]),
                int(tail_row["source_sequence"]),
            )
        )
        now_ms = self.base_store._validated_now_ms()
        sequence_ranges: dict[str, tuple[int, int]] = {}
        for event in ordered:
            current_range = sequence_ranges.get(event.market_track_stable_id)
            if current_range is None:
                sequence_ranges[event.market_track_stable_id] = (
                    event.source_sequence,
                    event.source_sequence,
                )
            else:
                sequence_ranges[event.market_track_stable_id] = (
                    min(current_range[0], event.source_sequence),
                    max(current_range[1], event.source_sequence),
                )
        existing_by_identity: dict[tuple[str, int], Mapping[str, object]] = {}
        if sequence_ranges:
            range_clauses: list[str] = []
            range_parameters: list[object] = [run_id]
            for track_id, (first_sequence, last_sequence) in sorted(
                sequence_ranges.items()
            ):
                range_clauses.append(
                    "(track_id = ? AND source_sequence BETWEEN ? AND ?)"
                )
                range_parameters.extend((track_id, first_sequence, last_sequence))
            existing_rows = connection.execute(
                f"""
                SELECT global_sequence, actual_event_time_ms, event_phase,
                       track_id, source_sequence
                FROM replay_training_global_event
                WHERE run_id = ? AND ({" OR ".join(range_clauses)})
                """,
                tuple(range_parameters),
            ).fetchall()
            existing_by_identity = {
                (str(row["track_id"]), int(row["source_sequence"])): row
                for row in existing_rows
            }
        inserted = 0
        insert_rows: list[tuple[object, ...]] = []
        for event_index, event in enumerate(ordered):
            identity = (event.market_track_stable_id, event.source_sequence)
            exists = existing_by_identity.get(identity)
            if exists is not None:
                existing_key = (
                    int(exists["actual_event_time_ms"]),
                    int(exists["event_phase"]),
                    str(exists["track_id"]),
                    int(exists["source_sequence"]),
                )
                if existing_key != event.ordering_key:
                    raise TrainingRunError(
                        "GLOBAL_EVENT_IDENTITY_MISMATCH",
                        "a durable global event identity changed its ordering key",
                        status_code=503,
                        details={
                            "existing_ordering_key": list(existing_key),
                            "requested_ordering_key": list(event.ordering_key),
                        },
                    )
                continue
            if tail_key is not None and event.ordering_key < tail_key:
                raise TrainingRunError(
                    "GLOBAL_EVENT_ORDER_VIOLATION",
                    "global events cannot be appended behind a later durable event",
                    status_code=409,
                    details={
                        "durable_tail_ordering_key": list(tail_key),
                        "requested_ordering_key": list(event.ordering_key),
                    },
                )
            global_sequence += 1
            insert_rows.append(
                (
                    run_id,
                    global_sequence,
                    GLOBAL_ORDERING_VERSION,
                    event.actual_event_time_ms,
                    event.event_phase,
                    event.market_track_stable_id,
                    event.source_sequence,
                    (global_ordering_hash((event,)) if prepared_hashes is None
                     else prepared_hashes.values[event_index]),
                    now_ms,
                ),
            )
            existing_by_identity[identity] = {
                "global_sequence": global_sequence,
                "actual_event_time_ms": event.actual_event_time_ms,
                "event_phase": event.event_phase,
                "track_id": event.market_track_stable_id,
                "source_sequence": event.source_sequence,
            }
            inserted += 1
            tail_key = event.ordering_key
        connection.executemany(
            """
            INSERT INTO replay_training_global_event(
                run_id, global_sequence, ordering_version,
                actual_event_time_ms, event_phase, track_id,
                source_sequence, ordering_hash, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        if checkpoint_boundary:
            self._materialize_recorded_risk(connection, run_id=run_id)
        checkpoint = (
            portfolio_ops.insert_global_checkpoint(
                connection,
                run_id=run_id,
                now_ms=now_ms,
                materialize_portfolio=materialize_portfolio,
            )
            if checkpoint_boundary
            else None
        )
        selected = connection.execute(
            """
            SELECT track.adapter_session_id
            FROM replay_training_viewer_state AS viewer
            JOIN replay_training_market_track AS track
              ON track.run_id = viewer.run_id
             AND track.track_id = viewer.selected_track_id
            WHERE viewer.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if inserted and selected is not None:
            if checkpoint_boundary:
                from .multi_interval_store import record_portfolio_point
                record_portfolio_point(self, connection, run_id=run_id,
                    session_id=str(selected['adapter_session_id']),
                    actual_time_ms=ordered[-1].actual_event_time_ms,sequence=global_sequence)
            self._append_review_timeline_event(
                connection,
                run_id=run_id,
                session_id=str(selected["adapter_session_id"]),
                context={
                    "kind": "SOURCE_EVENT",
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
        if run_id in getattr(self, "_tape_intent_runs", ()):
            from .tape_phases import update_intent
            update_intent(self, connection, run_id)
        return {
            "ordering_version": GLOBAL_ORDERING_VERSION,
            "inserted": inserted,
            "global_sequence": global_sequence,
            "checkpoint": checkpoint,
        }

    async def checkpoint_market_tracks(
        self,
        run_id: str,
        *,
        materialize_portfolio: bool = True,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> dict[str, object]:
            result = portfolio_ops.insert_global_checkpoint(
                connection,
                run_id=run_id,
                now_ms=self.base_store._validated_now_ms(),
                materialize_portfolio=materialize_portfolio,
            )
            if run_id in getattr(self, "_tape_intent_runs", ()):
                from .tape_phases import update_intent
                update_intent(self, connection, run_id)
            return result

        return await self.base_store.run_extension_write(write)

    async def set_actor_segment_refs(self, run_id: str, *, active: bool) -> None:
        return await self._markets.set_actor_segment_refs(run_id, active=active)

    async def global_events(self, run_id: str) -> list[dict[str, object]]:
        return await self._markets.global_events(run_id)

    async def remove_market_track(self, run_id: str, track_id: str) -> str | None:
        return await self._markets.remove_market_track(run_id, track_id)

    async def history_archive_pin(
        self,
        *,
        run_id: str,
        track_id: str,
        interval: str,
    ) -> dict[str, object] | None:
        """Return the immutable archive revision bound to one chart interval."""
        return await self._markets.history_archive_pin(run_id=run_id, track_id=track_id, interval=interval)

    async def pin_history_archive_interval(
        self,
        *,
        run_id: str,
        track_id: str,
        source_revision: str,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        range_start_ms: int,
        range_end_ms: int,
    ) -> dict[str, object]:
        """Pin a native display catalog once, preserving later page stability."""
        return await self._markets.pin_history_archive_interval(run_id=run_id, track_id=track_id, source_revision=source_revision, exchange=exchange, market_type=market_type, symbol=symbol, interval=interval, range_start_ms=range_start_ms, range_end_ms=range_end_ms)

    async def history_binding(
        self,
        *,
        session_id: str,
        track_id: str,
    ) -> dict[str, object]:
        """Read the immutable source binding and latest durable public cursor.

        This query deliberately reads only replay-owned SQLite tables. The
        service may subsequently page pre-start chart history through its
        read-only replay repository when the bound policy is ALL_AVAILABLE.
        """
        return await self._markets.history_binding(session_id=session_id, track_id=track_id)


    async def recorded_interval_certificate(
        self,
        run_id: str,
        *,
        low: Decimal,
        high: Decimal,
        target_actual_time_ms: int | None = None,
        allow_empty: bool = False,
    ):
        """Conservative single-leg, single-tier envelope; no history is skipped."""
        checked = self._hedge_risk_fingerprints.get(run_id)
        if (
            checked is None
            or not low.is_finite()
            or not high.is_finite()
            or not 0 < low <= high
        ):
            return None

        def read(connection):
            if account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id) != checked:
                return None
            account = connection.execute(
                "SELECT * FROM replay_training_contract_account WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            tracks = connection.execute(
                "SELECT * FROM replay_training_market_track WHERE run_id = ? AND subscription_tier = 'FULL'",
                (run_id,),
            ).fetchall()
            if account is None or account["status"] != "ACTIVE" or len(tracks) != 1:
                return None
            if connection.execute(
                "SELECT 1 FROM replay_training_liquidation_case WHERE run_id = ? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
                (run_id,),
            ).fetchone():
                return None
            track = tracks[0]
            projection = connection.execute(
                """SELECT p.*, b.status AS binding_status, b.bound_range_end_ms
                   FROM replay_hedge_track_public_projection p
                   JOIN replay_hedge_track_public_binding b USING(run_id,track_id)
                   WHERE p.run_id=? AND p.track_id=?""",
                (run_id, track["track_id"]),
            ).fetchone()
            if projection is None or projection["binding_status"] != "ACTIVE":
                return None
            if target_actual_time_ms is not None and target_actual_time_ms > int(
                projection["bound_range_end_ms"]
            ):
                return None
            projected = json.loads(projection["state_json"])
            material = {
                "schema_version": "replay.hedge-track-public-projection.v1",
                "run_id": run_id,
                "track_id": track["track_id"],
                "last_event_sequence": int(projection["last_event_sequence"]),
                "as_of_actual_time_ms": int(projection["as_of_actual_time_ms"]),
                "as_of_virtual_time_ms": int(projection["as_of_virtual_time_ms"]),
                "state": projected,
                "input_chain_hash": projection["input_chain_hash"],
            }
            if canonical_sha256(material) != projection["component_hash"] or int(
                projection["as_of_virtual_time_ms"]
            ) > int(track["virtual_time_ms"]):
                return None
            if Decimal(projected["mark_index"]["mark_price"]) != Decimal(
                track["public_price"]
            ):
                return None
            price_low = min(low, Decimal(track["public_price"]))
            price_high = max(high, Decimal(track["public_price"]))
            position = json.loads(track["position_json"])
            legs = [(name, position.get(name)) for name in ("long", "short")]
            legs = [
                (name, leg)
                for name, leg in legs
                if isinstance(leg, dict) and Decimal(leg["quantity"]) != 0
            ]
            if position.get("position_mode") == "HEDGE" and not legs and allow_empty:
                return checked
            if position.get("position_mode") != "HEDGE" or len(legs) != 1:
                return None
            row = connection.execute(
                "SELECT rule_json,rule_hash,effective_virtual_time_ms FROM replay_training_instrument_rule WHERE run_id = ? AND track_id = ? ORDER BY revision DESC LIMIT 1",
                (run_id, track["track_id"]),
            ).fetchone()
            rule = InstrumentRule.from_mapping(json.loads(row["rule_json"]))
            if row["rule_hash"] != rule.rule_hash or int(
                row["effective_virtual_time_ms"]
            ) > int(track["virtual_time_ms"]):
                return None
            side, leg = legs[0]
            quantity = abs(Decimal(leg["quantity"])) * Decimal(rule.contract_size)
            if (
                rule.active_maintenance_tier(
                    price_low * quantity, extend_last_tier=True
                )[0]
                != rule.active_maintenance_tier(
                    price_high * quantity, extend_last_tier=True
                )[0]
            ):
                return None
            entry = Decimal(leg["entry_price"])
            worst = price_low if side == "long" else price_high
            pnl = (worst - entry) * quantity * (1 if side == "long" else -1)
            if account["margin_mode"] == "CROSS":
                checked_equity = connection.execute(
                    "SELECT current_equity FROM replay_training_run WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
                cash = Decimal(checked_equity) - Decimal(leg["unrealized_pnl"])
            else:
                cash = Decimal(
                    json.loads(account["isolated_margin_json"]).get(
                        isolated_margin_key(track["track_id"], side.upper()), "0"
                    )
                )
            quote = Decimal(rule.quote_step)
            if (
                max(abs(cash), abs(pnl), price_high * quantity).adjusted()
                - quote.as_tuple().exponent
                > getcontext().prec - 4
            ):
                return None
            maintenance = rule.maintenance_margin(
                price_high * quantity, extend_last_tier=True
            )
            if account["margin_mode"] == "CROSS":
                maintenance += sum(
                    (Decimal(str(order.get("reserved_margin", "0")))
                     for order in json.loads(track["open_orders_json"])
                     if order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                     and order.get("reduce_only") is not True),
                    Decimal(0),
                )
            if cash + pnl <= maintenance + quote * 2:
                return None
            return checked

        return await self.base_store.run_extension_read(read)

    def _sync_session_trajectory(self, *args):
        try:
            if args[2].get("type") == InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL.value:
                from .multi_interval_store import stage_track
                return stage_track(self, *args)
            if args[2].get("type") in {InternalCommandType.INDEXED_INTERVAL.value, InternalCommandType.SHARED_INDEXED_INTERVAL.value}:
                return self._sync_indexed_trajectory(*args)
            return self._sync_recorded_trajectory(*args)
        finally:
            self._recorded_review_frame = None
            self._recorded_risk_context = None

    async def indexed_review_minimum(self, run_id, mark):
        return await self._review_repository.indexed_review_minimum(run_id, mark)

    async def prepare_indexed_curve(self, run_id, index):
        return await self._curves.prepare_indexed_curve(run_id, index)

    def _sync_indexed_trajectory(
        self,
        connection,
        session_id,
        command,
        frames,
        final_state,
        final_components,
        previous_components,
        now_ms,
    ):
        plan = self._recorded_interval_plans.get(session_id)
        if plan is None or plan["command_id"] != command["command_id"]:
            raise ValueError("indexed interval lacks its coordinator plan")
        run_id = plan["run_id"]
        if (
            account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id)
            != plan["fingerprint"]
        ):
            raise ValueError("indexed interval risk state changed")
        for key in ("orders", "fills", "ledger", "closed_trades", "warnings"):
            if final_components.get(key) != previous_components.get(key):
                raise ValueError("indexed interval contained an interaction")
        pending_samples = {}
        self._sync_session_summary(
            connection,
            session_id,
            final_state,
            final_components,
            previous_components,
            now_ms,
            recorded_history=True,
            equity_samples=pending_samples,
        )
        indexed = frames[0]["indexed"]
        low, high = indexed["index"].closes.range_bounds(
            start=indexed["start"], end=indexed["end"]
        )
        result_records_ops.sync_trade_results_projection(
            connection,
            run_id=run_id,
            track_id=plan["track_id"],
            component_state=final_components,
            revealed_event_low=low,
            revealed_event_high=high,
            now_ms=now_ms,
        )
        first, last = plan["first_mark"], plan["last_mark"]
        stable = []
        if first is not None:
            projection = connection.execute(
                "SELECT last_event_sequence,input_chain_hash FROM replay_hedge_track_public_projection WHERE run_id=? AND track_id=?",
                (run_id, plan["track_id"]),
            ).fetchone()
            if (
                projection["last_event_sequence"] + 1 != first.event_sequence
                or projection["input_chain_hash"] != first.previous_hash
            ):
                raise ValueError("indexed mark span no longer follows its cursor")
            connection.execute(
                "INSERT INTO replay_hedge_mark_span VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    plan["track_id"],
                    first.event_sequence,
                    last.event_sequence,
                    first.previous_hash,
                    last.event_hash,
                    first.source_id,
                ),
            )
            # The archive-indexed span accounts for the intervening MARKs. The
            # ordinary terminal-mark writer still owns the resulting projection.
            connection.execute(
                "UPDATE replay_hedge_track_public_projection SET last_event_sequence=?,input_chain_hash=? WHERE run_id=? AND track_id=?",
                (last.event_sequence - 1, last.previous_hash, run_id, plan["track_id"]),
            )
            stable.extend(
                account_marks_ops.apply_hedge_public_mark_batch(
                    connection,
                    run_id=run_id,
                    events=(last,),
                    virtual_times_ms=(last.event_time_ms - plan["actual_delta"],),
                    track_id=plan["track_id"],
                    now_ms=now_ms,
                )
            )
        account_marks_ops.apply_hedge_mark_projection(connection, run_id=run_id, now_ms=now_ms)
        liquidation_ops.detect_contract_liquidations(
            connection,
            run_id=run_id,
            now_ms=now_ms,
            trigger_virtual_time_ms=final_state["cursor"]["virtual_time_ms"],
            refresh_current_equity=True,
            record_valuation_history=False,
        )
        if connection.execute(
            "SELECT 1 FROM replay_training_liquidation_case WHERE run_id=? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
            (run_id,),
        ).fetchone():
            raise ValueError("indexed interval violated its risk envelope")
        stable.append(
            StableMarketEvent(
                actual_event_time_ms=final_state["cursor"]["virtual_time_ms"]
                + plan["actual_delta"],
                event_phase=20,
                market_track_stable_id=plan["track_id"],
                source_sequence=final_state["source_sequence"],
            )
        )
        ordered = stable_market_event_order(stable)
        mutation_id = connection.execute(
            "SELECT mutation_id FROM replay_mutation_log WHERE session_id=? AND command_id=? AND kind='command' ORDER BY mutation_id DESC LIMIT 1",
            (session_id, command["command_id"]),
        ).fetchone()[0]
        self._recorded_review_frame = {
            "connection": connection,
            "session_id": session_id,
            "frame": frames[0],
            "mutation_id": mutation_id,
            "plan": plan,
        }
        self._record_global_events_in_transaction(
            connection, run_id=run_id, ordered=ordered, materialize_portfolio=False
        )
        curve = {
            "schema": "indexed-curve.v1",
            "curve_id": plan["curve_id"],
            "start": plan["start"],
            "end": plan["end"],
            "session_id": session_id,
            "revision_base": final_state["revision"] - (plan["end"] - plan["start"]),
            "policy": plan["policy"],
            "revealed": final_state["revealed"],
        }
        curve["created_at_ms"] = now_ms
        indexed = frames[0]["indexed"]
        index = indexed["index"]
        start = int(plan["start"])
        end = int(plan["end"])
        start_time_ms = int(index.times[start]) if end > start else None
        end_time_ms = int(index.times[end - 1]) if end > start else None
        start_sequence = int(index.start) + start + 1
        connection.execute(
            """
            INSERT INTO replay_interval_curve(
                run_id, command_id, end_sequence, samples_json,
                start_sequence, start_time_ms, end_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                command["command_id"],
                final_state["source_sequence"],
                canonical_json(curve),
                start_sequence,
                start_time_ms,
                end_time_ms,
            ),
        )
        plan["stable"] = tuple(ordered)
        plan["fingerprint_after"] = account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id)

    def _recorded_review_checkpoint(self, connection, session_id, now_ms):
        context = getattr(self, "_recorded_review_frame", None)
        if (
            context is None
            or context["connection"] is not connection
            or context["session_id"] != session_id
        ):
            return None
        if "encoded" not in context:
            self._materialize_recorded_actor_frame(
                connection, run_id=context["plan"]["run_id"]
            )
            frame = context["frame"]
            state = frame["state"]
            cursor = frame["checkpoint_cursor"]
            components = {
                key: value
                for key, value in frame["components"].items()
                if key != "journal"
            }
            payload = {
                **frame["checkpoint_base"],
                "component_state": components,
                "state_hash": state["state_hash"],
                "virtual_time_ms": state["cursor"]["virtual_time_ms"],
                "source_sequence": state["source_sequence"],
                "revision": state["revision"],
                "event_sequence": state["event_sequence"],
                "event_chain_hash": frame["event_chain_hash"],
                "source_cursor": {
                    "source_sequence": cursor.source_sequence,
                    "last_event_time_ms": cursor.last_event_time_ms,
                    "last_base_bar_open_ms": cursor.last_base_bar_open_ms,
                    "at_end": cursor.at_end,
                },
            }
            encoded = CheckpointCodec().encode(payload)
            self.base_store._insert_checkpoint(
                connection,
                session_id=session_id,
                state=frame["state"],
                payload=encoded,
                initial=False,
                mutation_id=context["mutation_id"],
                now_ms=now_ms,
            )
            context["encoded"] = encoded
        return context["encoded"]

    def _materialize_recorded_actor_frame(self, connection, *, run_id):
        context = getattr(self, "_recorded_review_frame", None)
        if (
            context is None
            or context["connection"] is not connection
            or context["plan"]["run_id"] != run_id
        ):
            return None
        frame = context["frame"]
        materialize = frame.get("materialize_components")
        if materialize is not None:
            components, state_hash = materialize()
            frame["components"] = {
                **components,
                "journal": frame["components"]["journal"],
            }
            frame["state"]["state_hash"] = state_hash
            frame["materialize_components"] = None
            self.base_store._update_session(
                connection,
                context["session_id"],
                frame["state"],
                now_ms=self.base_store._validated_now_ms(),
            )
        return frame["state"]["state_hash"]

    def _sync_recorded_trajectory(
        self,
        connection,
        session_id,
        command,
        frames,
        final_state,
        final_components,
        previous_components,
        now_ms,
    ):
        plan = self._recorded_interval_plans.get(session_id)
        if (
            plan is None
            or command.get("command_id") != plan["command_id"]
            or command.get("type") != InternalCommandType.RECORDED_INTERVAL.value
        ):
            raise ValueError("recorded interval lacks its coordinator plan")
        run_id = str(plan["run_id"])
        if (
            account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id)
            != plan["fingerprint"]
        ):
            raise ValueError("recorded interval risk state changed after preflight")
        times = plan["times"]
        if len(frames) != len(times) or len(frames) > 32:
            raise ValueError("recorded interval history length differs from preflight")
        inputs = list(plan["inputs"])
        if any(
            event.source_kind != "PUBLIC"
            or event.event_kind != "MARK_INDEX"
            or event.event_phase != 30
            or event.track_id != plan["track_id"]
            for event, _virtual in inputs
        ):
            raise ValueError("recorded interval contains a non-mark input")
        account_basis = connection.execute(
            "SELECT run.initial_equity, account.overlay_cash FROM replay_training_run AS run "
            "JOIN replay_training_contract_account AS account USING(run_id) WHERE run_id=?",
            (run_id,),
        ).fetchone()
        initial_equity = Decimal(account_basis["initial_equity"])
        self._recorded_risk_context = {
            "connection": connection,
            "run_id": run_id,
            "track_id": plan["track_id"],
            "initial_equity": initial_equity,
            "base_equity": initial_equity + Decimal(account_basis["overlay_cash"]),
            "dirty": False,
            "mark": connection.execute(
                "SELECT public_price FROM replay_training_market_track "
                "WHERE run_id=? AND track_id=?",
                (run_id, plan["track_id"]),
            ).fetchone()[0],
        }
        equity_samples = {}
        input_index = 0
        fingerprint = plan["fingerprint"]
        pending = []
        stable = []
        prior = previous_components
        risk_equity = connection.execute(
            "SELECT current_equity FROM replay_training_run WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        mutation_id = connection.execute(
            "SELECT mutation_id FROM replay_mutation_log WHERE session_id = ? AND command_id = ? AND kind = 'command' ORDER BY mutation_id DESC LIMIT 1",
            (session_id, command["command_id"]),
        ).fetchone()[0]

        def apply_inputs_at(virtual):
            nonlocal input_index, fingerprint, risk_equity
            group = []
            while input_index < len(inputs) and inputs[input_index][1] == virtual:
                group.append(inputs[input_index][0])
                input_index += 1
            applied = self._hedge_input_write_operation(
                run_id, events=group, virtual_time_ms=virtual
            )(connection)
            pending.extend(applied)
            fingerprint = self._finalize_hedge_inputs_in_transaction(
                connection,
                run_id=run_id,
                risk_virtual_time_ms=virtual,
                cached_fingerprint=fingerprint,
            )
            risk_equity = connection.execute(
                "SELECT current_equity FROM replay_training_run WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            if connection.execute(
                "SELECT 1 FROM replay_training_liquidation_case WHERE run_id = ? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
                (run_id,),
            ).fetchone():
                raise ValueError("recorded interval violated its risk envelope")

        for index, frame in enumerate(frames):
            state, components = frame["state"], frame["components"]
            virtual = int(state["cursor"]["virtual_time_ms"])
            sequence = int(state["source_sequence"])
            if (
                virtual != times[index]
                or sequence != int(plan["start_sequence"]) + index + 1
            ):
                raise ValueError("recorded interval cursor differs from preflight")
            while input_index < len(inputs) and inputs[input_index][1] < virtual:
                apply_inputs_at(inputs[input_index][1])
            self._recorded_review_frame = {
                "connection": connection,
                "session_id": session_id,
                "frame": frame,
                "mutation_id": mutation_id,
                "plan": plan,
            }
            self.base_store._update_session(
                connection, session_id, state, now_ms=now_ms
            )
            for key in (
                "orders",
                "fills",
                "ledger",
                "closed_trades",
                "warnings",
                "journal",
            ):
                if components.get(key) != previous_components.get(key):
                    raise ValueError("recorded interval contains a broker interaction")
            self._sync_session_summary(
                connection,
                session_id,
                state,
                components,
                prior,
                now_ms,
                recorded_history=True,
                equity_samples=equity_samples,
            )
            # Internal adapter steps publish review only at the global market
            # checkpoint below, after applying the pinned mark and risk phase.
            pending.append(
                StableMarketEvent(
                    actual_event_time_ms=virtual + int(plan["actual_delta"]),
                    event_phase=20,
                    market_track_stable_id=str(plan["track_id"]),
                    source_sequence=sequence,
                )
            )
            # Broker samples above retain the raw market valuation. Risk uses
            # the last checked pinned valuation until a public mark changes.
            # Restoring that exact value lets the existing fingerprint skip a
            # duplicate risk pass; any other changed risk input still misses.
            connection.execute(
                "UPDATE replay_training_run SET current_equity=? WHERE run_id=?",
                (risk_equity, run_id),
            )
            if input_index < len(inputs) and inputs[input_index][1] == virtual:
                apply_inputs_at(virtual)
            else:
                fingerprint = self._finalize_hedge_inputs_in_transaction(
                    connection,
                    run_id=run_id,
                    risk_virtual_time_ms=virtual,
                    cached_fingerprint=fingerprint,
                )
                risk_equity = connection.execute(
                    "SELECT current_equity FROM replay_training_run WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            if connection.execute(
                "SELECT 1 FROM replay_training_liquidation_case WHERE run_id = ? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
                (run_id,),
            ).fetchone():
                raise ValueError("recorded interval violated its risk envelope")
            ordered = stable_market_event_order(pending)
            self._record_global_events_in_transaction(
                connection,
                run_id=run_id,
                ordered=ordered,
                materialize_portfolio=False,
                checkpoint_boundary=index == len(frames) - 1,
            )
            stable.extend(ordered)
            pending.clear()
            prior = components
        if (
            input_index != len(inputs)
            or frames[-1]["state"]["state_hash"] != final_state["state_hash"]
        ):
            raise ValueError(
                "recorded interval terminal history does not match checkpoint"
            )
        self.base_store._update_session(
            connection, session_id, final_state, now_ms=now_ms
        )
        # Published to the coordinator only after the enclosing commit succeeds.
        curve_records_ops.write_interval_curve(
            connection,
            run_id=run_id,
            command_id=command["command_id"],
            end_sequence=final_state["source_sequence"],
            rows=equity_samples.values(),
        )
        for resolution, _bucket_ms, limit in curve_records_ops._EQUITY_RESOLUTIONS:
            curve_records_ops.prune_equity_resolution(
                connection, run_id=run_id, resolution=resolution, limit=limit
            )
        plan["fingerprint_after"] = account_marks_ops.hedge_risk_fingerprint(
            connection, run_id=run_id
        )
        plan["stable"] = tuple(stable)

    def _sync_session_summary(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        state: Mapping[str, object],
        component_state: Mapping[str, object],
        previous_component_state: Mapping[str, object] | None,
        now_ms: int,
        recorded_history: bool = False,
        equity_samples: dict | None = None,
        phase_summary: PhaseSummary | None = None,
        revealed_price_bounds: tuple[Decimal, Decimal] | None = None,
    ) -> None:
        if revealed_price_bounds is None:
            revealed_price_bounds = getattr(self, "_tape_interval_bounds", {}).get(session_id)
        cursor = state.get("cursor")
        if not isinstance(cursor, Mapping):
            return
        track = (
            phase_summary.tracks[session_id]
            if phase_summary is not None
            else connection.execute(
                """
            SELECT t.*, viewer.selected_track_id, r.time_disclosure_policy,
                   r.position_mode,
                   COALESCE(integrity.revealed, 0) AS revealed
            FROM replay_training_market_track AS t
            JOIN replay_training_run AS r USING(run_id)
            JOIN replay_training_viewer_state AS viewer USING(run_id)
            LEFT JOIN replay_training_integrity AS integrity USING(run_id)
            WHERE t.adapter_session_id = ?
            """,
                (session_id,),
            ).fetchone()
        )
        if track is None:
            return
        history_guard = (
            phase_summary.account_history
            if phase_summary is not None
            else connection.execute(
                """
            SELECT account_data_mode, status, degraded_reason
            FROM replay_training_account_history WHERE run_id = ?
            """,
                (track["run_id"],),
            ).fetchone()
        )
        if (
            history_guard is not None
            and history_guard["account_data_mode"] == "HISTORICAL_EXACT"
            and history_guard["status"] != "ACTIVE"
        ):
            # Never let an adapter pause/checkpoint overwrite the last exact
            # mark after its immutable input has degraded.
            connection.execute(
                """
                UPDATE replay_training_run
                SET state = 'PAUSED', compatibility = 'DEGRADED',
                    updated_at_ms = ?, saved_at_ms = ?
                WHERE run_id = ?
                """,
                (now_ms, now_ms, track["run_id"]),
            )
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET state = 'DEGRADED',
                    degraded_reason = COALESCE(degraded_reason, ?),
                    updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (
                    history_guard["degraded_reason"],
                    now_ms,
                    track["run_id"],
                    track["track_id"],
                ),
            )
            return
        account = component_state.get("account")
        equity = account.get("equity") if isinstance(account, Mapping) else None
        selected = str(track["selected_track_id"]) == str(track["track_id"])
        if selected and isinstance(equity, str):
            connection.execute(
                """
                UPDATE replay_training_run
                SET state = ?, revision = ?, source_sequence = ?, virtual_time_ms = ?,
                    current_equity = ?, summary_revision = ?, updated_at_ms = ?, saved_at_ms = ?
                WHERE run_id = ?
                """,
                (
                    state["state"],
                    state["revision"],
                    state["source_sequence"],
                    cursor["virtual_time_ms"],
                    equity,
                    state["revision"],
                    now_ms,
                    now_ms,
                    track["run_id"],
                ),
            )
        elif selected:
            connection.execute(
                """
                UPDATE replay_training_run
                SET state = ?, revision = ?, source_sequence = ?, virtual_time_ms = ?,
                    updated_at_ms = ?, saved_at_ms = ?
                WHERE run_id = ?
                """,
                (
                    state["state"],
                    state["revision"],
                    state["source_sequence"],
                    cursor["virtual_time_ms"],
                    now_ms,
                    now_ms,
                    track["run_id"],
                ),
            )
        position, account_payload, open_orders, public_price = run_records_ops.track_components(
            component_state
        )
        automatic_reasons = {
            "VIEWED",
            "OPEN_POSITION",
            "OPEN_ORDER",
            "CONDITIONAL_ORDER",
            "LIQUIDATION_RISK",
        }
        try:
            stored_reasons = json.loads(str(track["forced_full_reasons_json"]))
        except json.JSONDecodeError as exc:
            raise TypeError("track forced_full_reasons are invalid") from exc
        if not isinstance(stored_reasons, list) or any(
            not isinstance(reason, str) for reason in stored_reasons
        ):
            raise TypeError("track forced_full_reasons are invalid")
        reasons = {
            reason for reason in stored_reasons if reason not in automatic_reasons
        }
        if selected:
            reasons.add("VIEWED")
        quantity = position.get("quantity")
        hedge_open = False
        if position.get("position_mode") == "HEDGE":
            for leg_name in ("long", "short"):
                leg = position.get(leg_name)
                if isinstance(leg, Mapping):
                    leg_quantity = leg.get("quantity")
                    if isinstance(leg_quantity, str) and Decimal(leg_quantity) != 0:
                        hedge_open = True
                        break
        if (isinstance(quantity, str) and Decimal(quantity) != 0) or hedge_open:
            reasons.update({"OPEN_POSITION", "LIQUIDATION_RISK"})
        if open_orders:
            reasons.add("OPEN_ORDER")
            if any(
                order.get("order_type") in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
                for order in open_orders
                if isinstance(order, Mapping)
            ):
                reasons.add("CONDITIONAL_ORDER")
        tier = "FULL" if reasons else str(track["subscription_tier"])
        track_state = (
            "ERROR"
            if state["state"] == "ERROR"
            else ("DORMANT" if tier == "NONE" else "READY")
        )
        connection.execute(
            """
            UPDATE replay_training_market_track
            SET state = CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM replay_historical_book_projection AS book
                        WHERE book.run_id = replay_training_market_track.run_id
                          AND book.track_id = replay_training_market_track.track_id
                          AND book.status IN ('CLEARED', 'DISABLED')
                    ) THEN 'DEGRADED'
                    ELSE ?
                END,
                subscription_tier = ?, virtual_time_ms = ?,
                source_sequence = ?, revision = ?, forced_full_reasons_json = ?,
                public_price = ?, position_json = ?, account_json = ?,
                open_orders_json = ?, degraded_reason = CASE
                    WHEN ? = 'ERROR' THEN COALESCE(degraded_reason, 'ADAPTER_ERROR')
                    WHEN EXISTS(
                        SELECT 1
                        FROM replay_historical_book_projection AS book
                        WHERE book.run_id = replay_training_market_track.run_id
                          AND book.track_id = replay_training_market_track.track_id
                          AND book.status IN ('CLEARED', 'DISABLED')
                    ) THEN COALESCE(degraded_reason, 'HISTORICAL_BOOK_UNAVAILABLE')
                    ELSE NULL END,
                updated_at_ms = ?
            WHERE adapter_session_id = ?
            """,
            (
                track_state,
                tier,
                cursor["virtual_time_ms"],
                state["source_sequence"],
                state["revision"],
                canonical_json(sorted(reasons)),
                public_price,
                canonical_json(position),
                canonical_json(account_payload),
                canonical_json(open_orders),
                state["state"],
                now_ms,
                session_id,
            ),
        )
        run_id = str(track["run_id"])
        track_id = str(track["track_id"])
        revealed_event_low: Decimal | None = None
        revealed_event_high: Decimal | None = None
        latest_mutation = (
            None
            if phase_summary is not None
            else connection.execute(
                """
            SELECT kind, source_sequence, payload_json FROM replay_mutation_log
            WHERE session_id = ? ORDER BY mutation_id DESC LIMIT 1
            """,
                (session_id,),
            ).fetchone()
        )
        previous_component_hash = (
            previous_component_state.get("state_hash")
            if previous_component_state is not None
            else None
        )
        component_hash = component_state.get("state_hash")
        if isinstance(previous_component_hash, str) and isinstance(component_hash, str):
            component_projection_changed = previous_component_hash != component_hash
        else:
            projection_component_keys = (
                "orders",
                "fills",
                "ledger",
                "position",
                "account",
                "bar_builder",
                "closed_trades",
                "warnings",
            )
            component_projection_changed = previous_component_state is None or any(
                previous_component_state.get(key) != component_state.get(key)
                for key in projection_component_keys
            )
        if component_projection_changed and not recorded_history:
            account_marks_ops.sync_contract_components(
                connection,
                run_id=run_id,
                track_id=track_id,
                virtual_time_ms=int(cursor["virtual_time_ms"]),
                source_sequence=int(state["source_sequence"]),
                component_state=component_state,
                now_ms=now_ms,
                previous_component_state=previous_component_state,
            )
        if (
            latest_mutation is not None
            and latest_mutation["kind"] == "source_event"
            and latest_mutation["source_sequence"] is not None
            and int(latest_mutation["source_sequence"]) == int(state["source_sequence"])
        ):
            source_row = connection.execute(
                """
                SELECT event_json FROM replay_source_event
                WHERE session_id = ? AND source_sequence = ?
                """,
                (session_id, state["source_sequence"]),
            ).fetchone()
            if source_row is None:
                raise TypeError("revealed source event is missing")
            source_event = json.loads(str(source_row["event_json"]))
            if not isinstance(source_event, Mapping):
                raise TypeError("revealed source event must be an object")
            raw_low = source_event.get("low", source_event.get("price"))
            raw_high = source_event.get("high", source_event.get("price"))
            if raw_low is not None and raw_high is not None:
                try:
                    revealed_event_low = Decimal(str(raw_low))
                    revealed_event_high = Decimal(str(raw_high))
                except InvalidOperation as exc:
                    raise TypeError(
                        "revealed source event price range is invalid"
                    ) from exc
                if (
                    not revealed_event_low.is_finite()
                    or not revealed_event_high.is_finite()
                    or revealed_event_low <= 0
                    or revealed_event_high < revealed_event_low
                ):
                    raise TypeError("revealed source event price range is invalid")
        if revealed_price_bounds is not None:
            revealed_event_low, revealed_event_high = revealed_price_bounds
        if component_projection_changed or revealed_price_bounds is not None:
            result_records_ops.sync_trade_results_projection(
                connection,
                run_id=run_id,
                track_id=track_id,
                component_state=component_state,
                revealed_event_low=revealed_event_low,
                revealed_event_high=revealed_event_high,
                now_ms=now_ms,
            )
        account_history = (
            phase_summary.account_history
            if phase_summary is not None
            else connection.execute(
                """
            SELECT account_data_mode, status
            FROM replay_training_account_history WHERE run_id = ?
            """,
                (run_id,),
            ).fetchone()
        )
        exact_account = (
            account_history is not None
            and account_history["account_data_mode"] == "HISTORICAL_EXACT"
        )
        if exact_account:
            account_marks_ops.apply_exact_mark_projection(
                connection,
                run_id=run_id,
                track_id=track_id,
                now_ms=now_ms,
            )
        mutation_command_type: object | None = (
            InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL.value
            if phase_summary is not None
            else None
        )
        if latest_mutation is not None and latest_mutation["kind"] == "command":
            try:
                mutation_payload = json.loads(str(latest_mutation["payload_json"]))
            except json.JSONDecodeError as exc:
                raise TypeError("latest replay command mutation is invalid") from exc
            if not isinstance(mutation_payload, Mapping):
                raise TypeError("latest replay command mutation must be an object")
            mutation_command_type = mutation_payload.get("type")
        source_event_in_coordinated_hedge_advance = (
            latest_mutation is not None
            and latest_mutation["kind"] == "source_event"
            and latest_mutation["source_sequence"] is not None
            and int(latest_mutation["source_sequence"]) == int(state["source_sequence"])
        )
        # A HEDGE TrainingRun owns every adapter source-event clock. Its
        # coordinator applies all same-time market/account/input phases and
        # performs the one authoritative funding/liquidation pass afterwards.
        # Internal liquidation closes are likewise followed immediately by
        # commit_liquidation_execution(), which performs the durable recheck.
        coordinated_hedge_mutation = str(track["position_mode"]) == "HEDGE" and (
            source_event_in_coordinated_hedge_advance
            or mutation_command_type
            in {
                "step",
                "advance_by",
                InternalCommandType.EXECUTE_HISTORICAL_BOOK_CLOSE.value,
                InternalCommandType.EXECUTE_REVEALED_REFERENCE_CLOSE.value,
                "_training_fast_forward_final_state",
                InternalCommandType.RECORDED_INTERVAL.value,
                InternalCommandType.INDEXED_INTERVAL.value,
                InternalCommandType.SHARED_INDEXED_INTERVAL.value,
                InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL.value,
            }
        )
        if component_projection_changed and not coordinated_hedge_mutation:
            account_marks_ops.settle_contract_funding(
                connection,
                run_id=run_id,
                now_ms=now_ms,
            )
            if not exact_account:
                liquidation_ops.detect_contract_liquidations(
                    connection,
                    run_id=run_id,
                    now_ms=now_ms,
                )
        account_model = (
            None
            if phase_summary is not None
            else connection.execute(
                """
            SELECT account_model FROM replay_training_contract_account
            WHERE run_id = ?
            """,
                (run_id,),
            ).fetchone()
        )
        if (
            account_model is not None
            and str(account_model["account_model"]) == CONTRACT_ACCOUNT_MODEL
        ):
            portfolio_ops.refresh_contract_current_equity(
                connection,
                run_id=run_id,
                now_ms=now_ms,
                summary_revision=int(state["revision"]),
            )

        if phase_summary is not None:
            phase_summary.last_revision = int(state["revision"])

        if selected:
            curve_records_ops.upsert_equity_samples(
                connection,
                run_id=str(track["run_id"]),
                session_id=session_id,
                policy=str(track["time_disclosure_policy"]),
                revealed=bool(track["revealed"]),
                state=state,
                component_state=component_state,
                now_ms=now_ms,
                retain=not recorded_history,
                pending_samples=equity_samples,
            )

    def _sync_session_mutation(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        command: Mapping[str, object],
        accepted: bool,
        result: Mapping[str, object] | None,
        state: Mapping[str, object],
        component_state: Mapping[str, object],
        now_ms: int,
    ) -> None:
        if not accepted:
            return
        command_type = command.get("type")
        if command_type not in {
            "place_order",
            "_training_adjust_capital",
            "_training_reveal_history",
        }:
            return
        run = connection.execute(
            """
            SELECT r.run_id, r.integrity_mode, r.time_disclosure_policy,
                   r.active_rule_revision, r.current_equity,
                   i.start_time_known, i.strict_eligible, i.revealed,
                   track.track_id
            FROM replay_training_run AS r
            JOIN replay_training_integrity AS i USING(run_id)
            JOIN replay_training_market_track AS track USING(run_id)
            WHERE track.adapter_session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if run is None:
            return
        payload = command.get("payload")
        if not isinstance(payload, Mapping):
            raise TypeError("training policy command payload must be an object")
        cursor = state.get("cursor")
        if not isinstance(cursor, Mapping):
            raise TypeError("training policy command cursor must be an object")
        command_id = str(command["command_id"])
        if command_type == "place_order":
            trade_plan = payload.get("trade_plan")
            if trade_plan is None:
                return
            if not isinstance(trade_plan, Mapping):
                raise TypeError("accepted trade plan must be an object")
            if result is None:
                raise TypeError("accepted trade plan is missing its command result")
            result_data = result.get("data")
            raw_orders = (
                result_data.get("orders") if isinstance(result_data, Mapping) else None
            )
            if not isinstance(raw_orders, list):
                raise TypeError("accepted trade plan result has no order projection")
            client_order_id = str(payload.get("client_order_id", ""))
            order = next(
                (
                    item
                    for item in raw_orders
                    if isinstance(item, Mapping)
                    and item.get("client_order_id") == client_order_id
                ),
                None,
            )
            if not isinstance(order, Mapping):
                raise TypeError("accepted trade plan could not bind its order")
            if (
                trade_plan.get("track_id") != run["track_id"]
                or trade_plan.get("client_order_id") != client_order_id
                or trade_plan.get("side") != payload.get("side")
                or trade_plan.get("order_type") != payload.get("order_type")
                or trade_plan.get("quantity") != payload.get("quantity")
            ):
                raise TypeError("accepted trade plan does not match its order")
            sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(plan_sequence), 0) + 1
                    FROM replay_training_trade_plan WHERE run_id = ?
                    """,
                    (run["run_id"],),
                ).fetchone()[0]
            )
            previous = connection.execute(
                """
                SELECT plan_hash FROM replay_training_trade_plan
                WHERE run_id = ? ORDER BY plan_sequence DESC LIMIT 1
                """,
                (run["run_id"],),
            ).fetchone()
            previous_hash = (
                "sha256:" + ("0" * 64)
                if previous is None
                else str(previous["plan_hash"])
            )
            plan_id = f"trade-plan-{sequence:08d}"
            material = {
                "schema_version": "replay.trade-plan.log.v1",
                "run_id": str(run["run_id"]),
                "plan_sequence": sequence,
                "plan_id": plan_id,
                "command_id": command_id,
                "track_id": str(run["track_id"]),
                "order_id": str(order["order_id"]),
                "virtual_time_ms": int(cursor["virtual_time_ms"]),
                "source_sequence": validate_v2_counter(
                    state["source_sequence"],
                    field_name="trade-plan source_sequence",
                ),
                "state_hash": str(state["state_hash"]),
                "plan": dict(trade_plan),
                "previous_plan_hash": previous_hash,
            }
            plan_hash = canonical_sha256(material)
            connection.execute(
                """
                INSERT INTO replay_training_trade_plan(
                    run_id, plan_sequence, plan_id, command_id, track_id,
                    order_id, client_order_id, side, order_type, sizing_mode,
                    risk_amount, risk_percent, account_equity, entry_price,
                    invalidation_price, target_price, risk_per_unit,
                    reward_risk_ratio, quantity, reason, virtual_time_ms,
                    source_sequence, state_hash, previous_plan_hash, plan_hash,
                    plan_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    sequence,
                    plan_id,
                    command_id,
                    run["track_id"],
                    order["order_id"],
                    client_order_id,
                    trade_plan["side"],
                    trade_plan["order_type"],
                    trade_plan["sizing_mode"],
                    trade_plan["risk_amount"],
                    trade_plan["risk_percent"],
                    trade_plan["account_equity"],
                    trade_plan["entry_price"],
                    trade_plan["invalidation_price"],
                    trade_plan["target_price"],
                    trade_plan["risk_per_unit"],
                    trade_plan["reward_risk_ratio"],
                    trade_plan["quantity"],
                    trade_plan["reason"],
                    cursor["virtual_time_ms"],
                    material["source_sequence"],
                    state["state_hash"],
                    previous_hash,
                    plan_hash,
                    canonical_json({**material, "plan_hash": plan_hash}),
                    now_ms,
                ),
            )
            return
        sequence_row = connection.execute(
            """
            SELECT COALESCE(MAX(action_sequence), 0) + 1 AS next_sequence
            FROM replay_run_action_event WHERE run_id = ?
            """,
            (run["run_id"],),
        ).fetchone()
        action_sequence = int(sequence_row["next_sequence"])
        previous = connection.execute(
            """
            SELECT state_hash_after FROM replay_run_action_event
            WHERE run_id = ? ORDER BY action_sequence DESC LIMIT 1
            """,
            (run["run_id"],),
        ).fetchone()
        state_hash_after = str(state["state_hash"])
        revealed = bool(run["revealed"])
        old_value: dict[str, object]
        new_value: dict[str, object]
        if command_type == "_training_adjust_capital":
            account = component_state.get("account")
            if not isinstance(account, Mapping) or not isinstance(
                account.get("equity"), str
            ):
                raise TypeError("capital adjustment account projection is missing")
            kind = str(payload.get("kind", ""))
            if kind not in {"deposit", "withdraw"}:
                raise TypeError("capital adjustment kind is invalid")
            event_type = kind.upper()
            old_value = {"equity": str(run["current_equity"])}
            new_value = {"equity": str(account["equity"])}
            reason = str(payload.get("reason", ""))
        else:
            event_type = "REVEAL_TIME"
            old_value = {
                "revealed": revealed,
                "time_disclosure_policy": str(run["time_disclosure_policy"]),
            }
            revealed = True
            new_value = {"revealed": True, "time_disclosure_policy": "NONE"}
            reason = str(payload.get("reason", "user reveal"))
            result_label = public_time_ops.result_label(
                integrity_mode=str(run["integrity_mode"]),
                start_time_known=bool(run["start_time_known"]),
                strict_eligible=False,
                revealed=True,
            )
            connection.execute(
                """
                UPDATE replay_training_integrity
                SET strict_eligible = 0, revealed = 1,
                    result_label = ?, updated_at_ms = ?
                WHERE run_id = ?
                """,
                (result_label, now_ms, run["run_id"]),
            )
        public_time = public_time_ops.public_time(
            connection,
            session_id=session_id,
            policy=str(run["time_disclosure_policy"]),
            revealed=revealed,
            public_time_ms=int(cursor["virtual_time_ms"]),
            sequence=validate_v2_counter(
                state["source_sequence"], field_name="source_sequence"
            ),
        )
        connection.execute(
            """
            INSERT INTO replay_run_action_event(
                run_id, action_sequence, event_id, command_id, event_type,
                rule_revision, public_time_json, old_value_json,
                new_value_json, reason, state_hash_before,
                state_hash_after, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["run_id"],
                action_sequence,
                f"action-{action_sequence:08d}",
                command_id,
                event_type,
                int(run["active_rule_revision"]),
                canonical_json(public_time),
                canonical_json(old_value),
                canonical_json(new_value),
                reason,
                None if previous is None else str(previous["state_hash_after"]),
                state_hash_after,
                now_ms,
            ),
        )


__all__ = ["TrainingRunStore"]
