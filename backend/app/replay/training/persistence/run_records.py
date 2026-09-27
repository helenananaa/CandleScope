"""Run records operations on a caller-owned transaction."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal
from typing import cast

from app.replay.archive_pins import persisted_bar_archive_reference
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    CONFIGURED_FEE_FIDELITY,
    CONTRACT_ACCOUNT_MODEL,
    initial_ledger_hash,
    instrument_rule_from_broker_config,
)
from ..errors import TrainingRunError
from ..models import (
    CapabilityKind,
    CapabilityState,
    ReplayLaunchContext,
    TrainingRunCreateRequest,
    ViewerState,
    VisibleHistoryMode,
    validate_v2_counter,
)
from ..schema import (
    DATA_POLICY_SCHEMA_VERSION,
    RUN_RULES_SCHEMA_VERSION,
    SELECTION_PREPARATION_SCHEMA_VERSION,
    START_SELECTION_SCHEMA_VERSION,
    data_policy_hash,
    selection_preparation_hash,
    start_selection_hash,
)
from ..segments import (
    ResolvedHistoryPolicy,
)
from . import ledger as ledger_ops

_LIST_LIMIT_MAX = 100


_ACCOUNT_RECORD_LIMIT_MAX = 200


_ACCOUNT_RECORD_TYPES = {"ORDERS", "FILLS", "LEDGER"}


_ACCOUNT_ORDER_SCOPES = {"ACTIVE", "HISTORY", "ALL"}


_COMPATIBILITY_FILTERS = {"READY", "UNAVAILABLE"}


_STATES = {"AWAITING_MARKET", "PAUSED", "PLAYING", "ADVANCING", "ENDED", "ERROR"}


_SOURCES = {"BAR", "AGG_TRADE"}


_VIEW_EVENT_LIMIT = 2_048


_CARD_CTE = """
WITH cards AS (
    SELECT
        r.run_id AS run_id,
        'V2' AS kind,
        r.name AS name,
        CASE
            WHEN s.session_id IS NULL THEN r.state
            WHEN s.state = 'INITIALIZING' THEN 'PAUSED'
            ELSE s.state
        END AS state,
        r.source_kind AS source_kind,
        r.integrity_mode AS integrity_mode,
        r.time_disclosure_policy AS time_disclosure_policy,
        r.last_symbol AS last_symbol,
        (
            SELECT COUNT(*) FROM replay_training_market_track AS t
            WHERE t.run_id = r.run_id AND t.subscription_tier != 'NONE'
        ) AS subscribed_track_count,
        COALESCE(s.source_sequence, r.source_sequence) AS progress_sequence,
        CASE
            WHEN r.summary_revision = COALESCE(s.revision, r.revision)
            THEN r.current_equity
            ELSE NULL
        END AS equity,
        CASE
            WHEN r.summary_revision = COALESCE(s.revision, r.revision)
             AND r.current_equity IS NOT NULL THEN 'CURRENT'
            ELSE 'STALE'
        END AS equity_status,
        r.settlement_asset AS settlement_asset,
        CASE
            WHEN COALESCE(s.updated_at_ms, 0) > r.updated_at_ms THEN s.updated_at_ms
            ELSE r.updated_at_ms
        END AS updated_at_ms,
        CASE
            WHEN s.degraded_reason IS NULL AND r.compatibility = 'READY' THEN 'READY'
            ELSE 'UNAVAILABLE'
        END AS compatibility,
        CASE
            WHEN r.state = 'AWAITING_MARKET' AND r.compatibility = 'READY'
            THEN 'SELECT_MARKET'
            WHEN s.degraded_reason IS NULL AND r.compatibility = 'READY'
            THEN 'OPEN_ADAPTER'
            ELSE 'UNAVAILABLE'
        END AS resume_action,
        selected_track.adapter_session_id AS adapter_session_id,
        s.degraded_reason AS degraded_reason,
        s.status_reason AS status_reason,
        EXISTS(
            SELECT 1 FROM replay_report AS report
            WHERE report.session_id IN (
                SELECT adapter_session_id
                FROM replay_training_market_track
                WHERE run_id = r.run_id AND adapter_session_id IS NOT NULL
            )
        ) AS report_available,
        EXISTS(
            SELECT 1 FROM replay_equity_sample AS sample
            WHERE sample.run_id = r.run_id
        ) AS review_available
    FROM replay_training_run AS r
    JOIN replay_training_viewer_state AS viewer USING(run_id)
    LEFT JOIN replay_training_market_track AS selected_track
      ON selected_track.run_id = r.run_id
     AND selected_track.track_id = viewer.selected_track_id
    LEFT JOIN replay_session AS s ON s.session_id = selected_track.adapter_session_id
)
"""


def _safe_name(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback[:80]
    if not isinstance(value, str):
        raise TrainingRunError(
            "TRAINING_RUN_INVALID",
            "training name must be a string or null",
            status_code=422,
        )
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 80
        or any(ord(char) < 32 for char in normalized)
    ):
        raise TrainingRunError(
            "TRAINING_RUN_INVALID",
            "training name must contain 1-80 display-safe characters",
            status_code=422,
        )
    return normalized


def _phase1_capabilities(source_kind: str) -> dict[str, str]:
    capabilities = {
        kind.value: CapabilityState.UNSUPPORTED_NO_HISTORY.value
        for kind in CapabilityKind
    }
    capabilities[CapabilityKind.OHLCV.value] = CapabilityState.AVAILABLE_EXACT.value
    capabilities[CapabilityKind.INDICATORS.value] = (
        CapabilityState.AVAILABLE_EXACT.value
    )
    capabilities[CapabilityKind.SIMULATED_LIQUIDATION.value] = (
        CapabilityState.AVAILABLE_APPROX.value
    )
    if source_kind == "AGG_TRADE":
        capabilities[CapabilityKind.AGG_TRADE_TAPE.value] = (
            CapabilityState.AVAILABLE_EXACT.value
        )
        capabilities[CapabilityKind.ORDER_FLOW.value] = (
            CapabilityState.AVAILABLE_APPROX.value
        )
    else:
        capabilities[CapabilityKind.AGG_TRADE_TAPE.value] = (
            CapabilityState.UNSUPPORTED_SOURCE_MODE.value
        )
        capabilities[CapabilityKind.ORDER_FLOW.value] = (
            CapabilityState.UNSUPPORTED_SOURCE_MODE.value
        )
    return capabilities


def _cursor_payload(value: str | None) -> tuple[int, str, str] | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_INVALID_CURSOR",
            "run list cursor is invalid",
            status_code=422,
        ) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"updated_at_ms", "run_id", "kind"}
        or isinstance(payload["updated_at_ms"], bool)
        or not isinstance(payload["updated_at_ms"], int)
        or payload["updated_at_ms"] < 0
        or not isinstance(payload["run_id"], str)
        or not isinstance(payload["kind"], str)
    ):
        raise TrainingRunError(
            "TRAINING_RUN_INVALID_CURSOR",
            "run list cursor is invalid",
            status_code=422,
        )
    return payload["updated_at_ms"], payload["run_id"], payload["kind"]


def _encode_cursor(row: Mapping[str, object]) -> str:
    payload = canonical_json(
        {
            "updated_at_ms": int(row["updated_at_ms"]),
            "run_id": str(row["run_id"]),
            "kind": str(row["kind"]),
        }
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _account_record_cursor_payload(
    value: str | None,
    *,
    record_type: str,
    order_scope: str,
    track_id: str | None,
) -> tuple[int, str, str] | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "REPLAY_ACCOUNT_RECORD_CURSOR_INVALID",
            "account record cursor is invalid",
            status_code=422,
        ) from exc
    expected = {
        "schema_version",
        "record_type",
        "order_scope",
        "track_id",
        "sort_value",
        "sort_track_id",
        "record_id",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload["schema_version"] != "replay.training.account-record-cursor.v1"
        or payload["record_type"] != record_type
        or payload["order_scope"] != order_scope
        or payload["track_id"] != track_id
        or isinstance(payload["sort_value"], bool)
        or not isinstance(payload["sort_value"], int)
        or payload["sort_value"] < 0
        or not isinstance(payload["sort_track_id"], str)
        or not isinstance(payload["record_id"], str)
    ):
        raise TrainingRunError(
            "REPLAY_ACCOUNT_RECORD_CURSOR_INVALID",
            "account record cursor does not match the requested record page",
            status_code=422,
        )
    return (
        payload["sort_value"],
        payload["sort_track_id"],
        payload["record_id"],
    )


def _encode_account_record_cursor(
    *,
    record_type: str,
    order_scope: str,
    track_id: str | None,
    sort_value: int,
    sort_track_id: str,
    record_id: str,
) -> str:
    payload = canonical_json(
        {
            "schema_version": "replay.training.account-record-cursor.v1",
            "record_type": record_type,
            "order_scope": order_scope,
            "track_id": track_id,
            "sort_value": sort_value,
            "sort_track_id": sort_track_id,
            "record_id": record_id,
        }
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def insert_modelled_account_history(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    account_data_mode: str,
    fidelity: str,
    now_ms: int,
) -> None:
    if account_data_mode not in {"APPROX_PROXY", "DETERMINISTIC_SIMULATION"}:
        raise ValueError("modelled account history mode is invalid")
    connection.execute(
        """
        INSERT INTO replay_training_account_history(
            run_id, account_data_mode, status, fidelity,
            archive_proof_hash, degraded_reason, auditor_status,
            auditor_proof_hash, auditor_differences_json,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'ACTIVE', ?,
                  NULL, NULL, 'NOT_RUN', NULL, '[]', ?, ?)
        ON CONFLICT(run_id) DO NOTHING
        """,
        (run_id, account_data_mode, fidelity, now_ms, now_ms),
    )


def insert_contract_account(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    request: TrainingRunCreateRequest,
    broker_config: Mapping[str, object],
    virtual_time_ms: int,
    now_ms: int,
) -> None:
    interval = request.funding_interval_ms
    next_funding = (
        None if interval is None else ((virtual_time_ms // interval) + 1) * interval
    )
    root_hash = initial_ledger_hash(
        run_id=run_id,
        initial_equity=request.initial_equity,
        asset=request.settlement_asset,
    )
    connection.execute(
        """
        INSERT INTO replay_training_contract_account(
            run_id, account_model, margin_mode, funding_mode,
            fixed_funding_rate, funding_interval_ms, next_funding_time_ms,
            overlay_cash, isolated_margin_json, status, fidelity,
            ledger_tail_hash, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', '{}', 'ACTIVE', ?, ?, ?, ?)
        """,
        (
            run_id,
            CONTRACT_ACCOUNT_MODEL,
            request.margin_mode.value,
            request.funding_mode.value,
            request.fixed_funding_rate,
            interval,
            next_funding,
            "AVAILABLE_APPROX_NO_HISTORICAL_MARK_INDEX",
            root_hash,
            now_ms,
            now_ms,
        ),
    )
    if request.position_mode.value == "HEDGE":
        margin_component = {
            "schema_version": "replay.margin-bucket.v1",
            "bucket_id": f"cross:{request.settlement_asset}",
            "bucket_kind": "CROSS",
            "asset": request.settlement_asset,
            "wallet_balance": request.initial_equity,
            "initial_margin": "0",
            "maintenance_margin": "0",
            "reserved_margin": "0",
            "available_balance": request.initial_equity,
        }
        connection.execute(
            """
            INSERT INTO replay_training_margin_bucket(
                run_id, bucket_id, bucket_kind, track_id, position_side,
                asset, wallet_balance, initial_margin, maintenance_margin,
                reserved_margin, available_balance, component_revision,
                component_hash, updated_at_ms
            ) VALUES (?, ?, 'CROSS', NULL, NULL, ?, ?, '0', '0', '0', ?,
                      1, ?, ?)
            """,
            (
                run_id,
                margin_component["bucket_id"],
                request.settlement_asset,
                request.initial_equity,
                request.initial_equity,
                canonical_sha256(margin_component),
                now_ms,
            ),
        )
    insert_contract_track_rule(
        connection,
        run_id=run_id,
        track_id="track-1",
        source_kind=request.source_kind.value,
        broker_config=broker_config,
        effective_virtual_time_ms=virtual_time_ms,
        now_ms=now_ms,
    )
    policy = {
        "schema_version": "replay.training.fee-policy.v1",
        "run_id": run_id,
        "revision": 1,
        "effective_virtual_time_ms": virtual_time_ms,
        "maker_fee_bps": request.maker_fee_bps,
        "taker_fee_bps": request.taker_fee_bps,
        "fidelity": CONFIGURED_FEE_FIDELITY,
    }
    connection.execute(
        """
        INSERT INTO replay_training_fee_policy(
            run_id, revision, effective_virtual_time_ms, maker_fee_bps,
            taker_fee_bps, policy_hash, fidelity, reason, created_at_ms
        ) VALUES (?, 1, ?, ?, ?, ?, ?, 'creation policy', ?)
        """,
        (
            run_id,
            virtual_time_ms,
            request.maker_fee_bps,
            request.taker_fee_bps,
            canonical_sha256(policy),
            CONFIGURED_FEE_FIDELITY,
            now_ms,
        ),
    )
    leverage_policy = {
        "schema_version": RUN_RULES_SCHEMA_VERSION,
        "kind": "LEVERAGE_CAP",
        "run_id": run_id,
        "revision": 1,
        "effective_virtual_time_ms": virtual_time_ms,
        "source_sequence": 0,
        "max_leverage": request.max_leverage,
        "fidelity": "CONFIGURED_USER_CAP_EXACT",
    }
    connection.execute(
        """
        INSERT INTO replay_training_leverage_policy(
            run_id, revision, effective_virtual_time_ms, source_sequence,
            max_leverage, policy_hash, fidelity, reason, command_id,
            created_at_ms
        ) VALUES (?, 1, ?, 0, ?, ?, 'CONFIGURED_USER_CAP_EXACT',
                  'creation policy', NULL, ?)
        """,
        (
            run_id,
            virtual_time_ms,
            request.max_leverage,
            canonical_sha256(leverage_policy),
            now_ms,
        ),
    )
    funding_fidelity = (
        "HISTORICAL_EXACT_ARCHIVE_POLICY"
        if request.funding_mode.value == "HISTORICAL_EXACT"
        else "CONFIGURED_FUNDING_POLICY_EXACT"
    )
    funding_policy = {
        "schema_version": RUN_RULES_SCHEMA_VERSION,
        "kind": "FUNDING_POLICY",
        "run_id": run_id,
        "revision": 1,
        "effective_virtual_time_ms": virtual_time_ms,
        "source_sequence": 0,
        "funding_mode": request.funding_mode.value,
        "fixed_funding_rate": request.fixed_funding_rate,
        "funding_interval_ms": request.funding_interval_ms,
        "fidelity": funding_fidelity,
    }
    connection.execute(
        """
        INSERT INTO replay_training_funding_policy(
            run_id, revision, effective_virtual_time_ms, source_sequence,
            funding_mode, fixed_funding_rate, funding_interval_ms,
            policy_hash, fidelity, reason, command_id, created_at_ms
        ) VALUES (?, 1, ?, 0, ?, ?, ?, ?, ?, 'creation policy', NULL, ?)
        """,
        (
            run_id,
            virtual_time_ms,
            request.funding_mode.value,
            request.fixed_funding_rate,
            request.funding_interval_ms,
            canonical_sha256(funding_policy),
            funding_fidelity,
            now_ms,
        ),
    )
    ledger_ops.append_contract_ledger(
        connection,
        run_id=run_id,
        posting_id="initial-capital",
        track_id=None,
        kind="INITIAL_CAPITAL",
        cash_delta=Decimal(request.initial_equity),
        asset=request.settlement_asset,
        virtual_time_ms=virtual_time_ms,
        source_sequence=0,
        fidelity="CONFIGURED_INITIAL_CAPITAL_EXACT",
        rule_revision=1,
        reference_type="RUN",
        reference_id=run_id,
        metadata={
            "account_model": CONTRACT_ACCOUNT_MODEL,
            "margin_mode": request.margin_mode.value,
            "funding_mode": request.funding_mode.value,
            "fixed_funding_rate": request.fixed_funding_rate,
            "funding_interval_ms": request.funding_interval_ms,
        },
        now_ms=now_ms,
    )


def insert_contract_track_rule(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    source_kind: str,
    broker_config: Mapping[str, object],
    effective_virtual_time_ms: int,
    now_ms: int,
) -> None:
    account = connection.execute(
        """
        SELECT account.*, run.settlement_asset, run.position_mode
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        return
    existing = connection.execute(
        """
        SELECT 1 FROM replay_training_instrument_rule
        WHERE run_id = ? AND track_id = ?
        """,
        (run_id, track_id),
    ).fetchone()
    if existing is not None:
        return
    rule = instrument_rule_from_broker_config(
        track_id=track_id,
        source_kind=source_kind,
        broker_config=broker_config,
        effective_virtual_time_ms=effective_virtual_time_ms,
    )
    connection.execute(
        """
        INSERT INTO replay_training_instrument_rule(
            run_id, track_id, revision, effective_virtual_time_ms,
            rule_json, rule_hash, fidelity, created_at_ms
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            track_id,
            effective_virtual_time_ms,
            canonical_json(rule.to_dict()),
            rule.rule_hash,
            rule.rule_fidelity,
            now_ms,
        ),
    )


def insert_run(connection: sqlite3.Connection, values: Mapping[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO replay_training_run(
            run_id, adapter_session_id, protocol,
            schema_version, name, state, source_kind, start_mode,
            integrity_mode, time_disclosure_policy, book_mode, margin_mode,
            position_mode, funding_mode, account_data_mode,
            hedge_public_history_ref_json, simulation_manifest_ref_json,
            simulation_contract_hash, simulation_model_version,
            account_fidelity, insurance_adl_fidelity,
            execution_model, allow_rule_changes, exchange,
            market_type, last_symbol, settlement_asset, base_interval,
            display_interval, initial_equity, current_equity, summary_revision,
            revision, source_sequence, virtual_time_ms, active_rule_revision,
            catalog_epoch, dataset_epoch, compatibility, created_at_ms,
            updated_at_ms, saved_at_ms
        ) VALUES (
            :run_id, :adapter_session_id, 'replay.v3',
            'replay.training.v2', :name, :state, :source_kind, :start_mode,
            :integrity_mode, :time_disclosure_policy, :book_mode, :margin_mode,
            :position_mode, :funding_mode, :account_data_mode,
            :hedge_public_history_ref_json, :simulation_manifest_ref_json,
            :simulation_contract_hash, :simulation_model_version,
            :account_fidelity, :insurance_adl_fidelity,
            'TOUCH_OR_TAPE_V2', :allow_rule_changes, :exchange,
            :market_type, :last_symbol, :settlement_asset, :base_interval,
            :display_interval, :initial_equity, :current_equity, :summary_revision,
            :revision, :source_sequence, :virtual_time_ms, 1,
            :catalog_epoch, :dataset_epoch, :compatibility, :now_ms,
            :now_ms, :now_ms
        )
        """,
        dict(values),
    )


def insert_launch_context(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    context: ReplayLaunchContext,
    now_ms: int,
) -> None:
    payload = context.to_dict()
    connection.execute(
        """
        INSERT INTO replay_training_launch_context(
            run_id, schema_version, source, context_json,
            context_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            context.schema_version,
            context.source,
            canonical_json(payload),
            canonical_sha256(payload),
            now_ms,
        ),
    )


def copy_launch_context(
    connection: sqlite3.Connection,
    *,
    parent_run_id: str,
    child_run_id: str,
    now_ms: int,
) -> None:
    row = connection.execute(
        """
        SELECT context_json, context_hash
        FROM replay_training_launch_context
        WHERE run_id = ?
        """,
        (parent_run_id,),
    ).fetchone()
    if row is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent launch context is missing",
            status_code=503,
        )
    try:
        raw = json.loads(str(row["context_json"]))
        context = ReplayLaunchContext.from_dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent launch context is invalid",
            status_code=503,
        ) from exc
    if canonical_sha256(context.to_dict()) != str(row["context_hash"]):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent launch context failed its integrity check",
            status_code=503,
        )
    insert_launch_context(
        connection,
        run_id=child_run_id,
        context=context,
        now_ms=now_ms,
    )


def validated_selection_preparation(
    connection: sqlite3.Connection,
    *,
    preparation_id: str,
    request: TrainingRunCreateRequest,
    history_policy: ResolvedHistoryPolicy,
    source_fingerprint: str,
    actual_replay_start_ms: int,
    actual_replay_end_ms: int,
) -> None:
    row = connection.execute(
        """
        SELECT * FROM replay_training_selection_preparation
        WHERE preparation_id = ?
        """,
        (preparation_id,),
    ).fetchone()
    if row is None or str(row["status"]) != "PREPARING_DATA":
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training selection preparation is missing or not active",
            status_code=503,
        )
    expected_hash = selection_preparation_hash(
        preparation_id=str(row["preparation_id"]),
        start_mode=str(row["start_mode"]),
        seed_source=str(row["seed_source"]),
        random_seed=(None if row["random_seed"] is None else int(row["random_seed"])),
        catalog_epoch=str(row["catalog_epoch"]),
        source_fingerprint=str(row["source_fingerprint"]),
        selected_start_ms=int(row["selected_start_ms"]),
        required_start_ms=int(row["required_start_ms"]),
        required_end_ms=int(row["required_end_ms"]),
        interval_ms=int(row["interval_ms"]),
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
    try:
        stored_request = json.loads(str(row["request_json"]))
        stored_selection = json.loads(str(row["selection_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training selection preparation payload is unreadable",
            status_code=503,
        ) from exc
    seed_source = "SERVER" if request.start_mode.value == "RANDOM" else "MANUAL"
    expected_request = request.to_dict(redact_hidden_start=False)
    if request.launch_context is not None:
        expected_request["launch_context"] = request.launch_context.to_dict()
    if (
        expected_hash != str(row["selection_hash"])
        or not isinstance(stored_request, Mapping)
        or not isinstance(stored_selection, Mapping)
        or canonical_sha256(stored_request) != str(row["request_hash"])
        or canonical_sha256(stored_selection) != str(row["selection_json_hash"])
        or dict(stored_request) != expected_request
        or str(stored_selection.get("catalog_epoch")) != request.catalog_epoch
        or str(stored_selection.get("source_fingerprint")) != source_fingerprint
        or int(stored_selection.get("selected_start_ms", -1))
        != history_policy.actual_replay_start_ms
        or str(row["schema_version"]) != SELECTION_PREPARATION_SCHEMA_VERSION
        or str(row["start_mode"]) != request.start_mode.value
        or str(row["seed_source"]) != seed_source
        or (None if row["random_seed"] is None else int(row["random_seed"]))
        != request.random_seed
        or str(row["catalog_epoch"]) != request.catalog_epoch
        or str(row["source_fingerprint"]) != source_fingerprint
        or int(row["selected_start_ms"]) != history_policy.actual_replay_start_ms
        or int(row["required_start_ms"]) != required_start_ms
        or int(row["required_end_ms"]) != required_end_ms
        or int(row["interval_ms"]) != history_policy.interval_ms
        or actual_replay_start_ms != history_policy.actual_replay_start_ms
        or actual_replay_end_ms != required_end_ms
    ):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training selection preparation failed its commitment check",
            status_code=503,
        )


def insert_start_selection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    start_mode: str,
    seed_source: str,
    random_seed: int | None,
    actual_start_ms: int,
    actual_end_ms: int,
    dataset_epoch: str,
    parent_selection_hash: str | None,
    now_ms: int,
) -> None:
    if start_mode not in {"MANUAL", "RANDOM"}:
        raise TypeError("training start selection mode is invalid")
    if seed_source not in {"SERVER", "MANUAL", "FORK"}:
        raise TypeError("training start selection seed source is invalid")
    if seed_source == "MANUAL" and start_mode != "MANUAL":
        raise TypeError("manual seed source requires a manual start")
    if seed_source == "SERVER" and start_mode != "RANDOM":
        raise TypeError("random seed source requires a random start")
    if start_mode == "MANUAL" and random_seed is not None:
        raise TypeError("manual start selection cannot persist a random seed")
    if start_mode == "RANDOM" and random_seed is None:
        raise TypeError("random start selection must persist its private seed")
    if random_seed is not None and (
        isinstance(random_seed, bool)
        or not isinstance(random_seed, int)
        or not 0 <= random_seed <= 9_007_199_254_740_991
    ):
        raise TypeError("training start selection seed is invalid")
    if (
        isinstance(actual_start_ms, bool)
        or not isinstance(actual_start_ms, int)
        or actual_start_ms < 0
        or isinstance(actual_end_ms, bool)
        or not isinstance(actual_end_ms, int)
        or actual_end_ms < actual_start_ms
    ):
        raise TypeError("training start selection bounds are invalid")
    if not isinstance(dataset_epoch, str) or not dataset_epoch:
        raise TypeError("training start selection dataset epoch is invalid")
    if parent_selection_hash is not None and (
        not isinstance(parent_selection_hash, str)
        or len(parent_selection_hash) != 71
        or not parent_selection_hash.startswith("sha256:")
    ):
        raise TypeError("parent start selection hash is invalid")
    digest = start_selection_hash(
        run_id=run_id,
        start_mode=start_mode,
        seed_source=seed_source,
        random_seed=random_seed,
        actual_start_ms=actual_start_ms,
        actual_end_ms=actual_end_ms,
        dataset_epoch=dataset_epoch,
        parent_selection_hash=parent_selection_hash,
    )
    connection.execute(
        """
        INSERT INTO replay_training_start_selection(
            run_id, schema_version, start_mode, seed_source, random_seed,
            actual_start_ms, actual_end_ms, dataset_epoch,
            parent_selection_hash, selection_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            START_SELECTION_SCHEMA_VERSION,
            start_mode,
            seed_source,
            random_seed,
            actual_start_ms,
            actual_end_ms,
            dataset_epoch,
            parent_selection_hash,
            digest,
            now_ms,
        ),
    )


def insert_data_policy(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    policy: ResolvedHistoryPolicy,
    actual_replay_start_ms: int,
    now_ms: int,
) -> None:
    if not isinstance(policy, ResolvedHistoryPolicy):
        raise TypeError("history_policy must be a ResolvedHistoryPolicy")
    if policy.actual_replay_start_ms != actual_replay_start_ms:
        raise TypeError("history policy does not match the frozen replay start")
    digest = data_policy_hash(
        indicator_warmup_bars=policy.indicator_warmup_bars,
        visible_history_mode=policy.visible_history_mode.value,
        visible_history_lookback_ms=policy.visible_history_lookback_ms,
        visible_history_rows=policy.visible_history_rows,
        actual_visible_history_start_ms=policy.actual_visible_history_start_ms,
        actual_replay_start_ms=policy.actual_replay_start_ms,
        effective_warmup_bars=policy.effective_warmup_bars,
        forward_cache_ms=policy.forward_cache_ms,
        interval_ms=policy.interval_ms,
    )
    if digest != policy.policy_hash:
        raise TypeError("history policy hash implementation drifted")
    connection.execute(
        """
        INSERT INTO replay_training_data_policy(
            run_id, schema_version, indicator_warmup_bars,
            visible_history_mode, visible_history_lookback_ms,
            visible_history_rows, actual_visible_history_start_ms,
            actual_replay_start_ms, effective_warmup_bars,
            forward_cache_ms, interval_ms, policy_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            DATA_POLICY_SCHEMA_VERSION,
            policy.indicator_warmup_bars,
            policy.visible_history_mode.value,
            policy.visible_history_lookback_ms,
            policy.visible_history_rows,
            policy.actual_visible_history_start_ms,
            policy.actual_replay_start_ms,
            policy.effective_warmup_bars,
            policy.forward_cache_ms,
            policy.interval_ms,
            digest,
            now_ms,
        ),
    )


def data_policy_from_row(
    row: Mapping[str, object],
) -> ResolvedHistoryPolicy:
    if str(row["schema_version"]) != DATA_POLICY_SCHEMA_VERSION:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training data policy schema is unsupported",
            status_code=503,
        )
    try:
        policy = ResolvedHistoryPolicy(
            indicator_warmup_bars=int(row["indicator_warmup_bars"]),
            visible_history_mode=VisibleHistoryMode(str(row["visible_history_mode"])),
            visible_history_lookback_ms=(
                None
                if row["visible_history_lookback_ms"] is None
                else int(row["visible_history_lookback_ms"])
            ),
            visible_history_rows=int(row["visible_history_rows"]),
            actual_visible_history_start_ms=int(row["actual_visible_history_start_ms"]),
            actual_replay_start_ms=int(row["actual_replay_start_ms"]),
            effective_warmup_bars=int(row["effective_warmup_bars"]),
            forward_cache_ms=int(row["forward_cache_ms"]),
            interval_ms=int(row["interval_ms"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training data policy is invalid",
            status_code=503,
        ) from exc
    if policy.policy_hash != str(row["policy_hash"]):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training data policy failed its integrity check",
            status_code=503,
        )
    return policy


def copy_data_policy(
    connection: sqlite3.Connection,
    *,
    parent_run_id: str,
    child_run_id: str,
    actual_replay_start_ms: int,
    now_ms: int,
) -> ResolvedHistoryPolicy:
    row = connection.execute(
        """
        SELECT * FROM replay_training_data_policy
        WHERE run_id = ?
        """,
        (parent_run_id,),
    ).fetchone()
    if row is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent training data policy is missing",
            status_code=503,
        )
    policy = data_policy_from_row(row)
    insert_data_policy(
        connection,
        run_id=child_run_id,
        policy=policy,
        actual_replay_start_ms=actual_replay_start_ms,
        now_ms=now_ms,
    )
    return policy


def copy_start_selection(
    connection: sqlite3.Connection,
    *,
    parent_run_id: str,
    child_run_id: str,
    actual_start_ms: int,
    actual_end_ms: int,
    dataset_epoch: str,
    now_ms: int,
) -> None:
    row = connection.execute(
        """
        SELECT * FROM replay_training_start_selection
        WHERE run_id = ?
        """,
        (parent_run_id,),
    ).fetchone()
    if row is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent start selection commitment is missing",
            status_code=503,
        )
    expected_hash = start_selection_hash(
        run_id=parent_run_id,
        start_mode=str(row["start_mode"]),
        seed_source=str(row["seed_source"]),
        random_seed=(None if row["random_seed"] is None else int(row["random_seed"])),
        actual_start_ms=int(row["actual_start_ms"]),
        actual_end_ms=int(row["actual_end_ms"]),
        dataset_epoch=str(row["dataset_epoch"]),
        parent_selection_hash=row["parent_selection_hash"],
    )
    if expected_hash != str(row["selection_hash"]):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "parent start selection commitment failed validation",
            status_code=503,
        )
    if (
        int(row["actual_start_ms"]) != actual_start_ms
        or int(row["actual_end_ms"]) != actual_end_ms
        or str(row["dataset_epoch"]) != dataset_epoch
    ):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "forked dataset does not match the parent start selection",
            status_code=503,
        )
    insert_start_selection(
        connection,
        run_id=child_run_id,
        start_mode=str(row["start_mode"]),
        seed_source="FORK",
        random_seed=(None if row["random_seed"] is None else int(row["random_seed"])),
        actual_start_ms=actual_start_ms,
        actual_end_ms=actual_end_ms,
        dataset_epoch=dataset_epoch,
        parent_selection_hash=str(row["selection_hash"]),
        now_ms=now_ms,
    )


def launch_context_projection(
    row: Mapping[str, object],
) -> dict[str, object] | None:
    raw_json = row["launch_context_json"]
    raw_hash = row["launch_context_hash"]
    if raw_json is None and raw_hash is None:
        return None
    if raw_json is None or raw_hash is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "stored replay launch context is incomplete",
            status_code=503,
        )
    try:
        context = ReplayLaunchContext.from_dict(json.loads(str(raw_json)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "stored replay launch context is invalid",
            status_code=503,
        ) from exc
    payload = context.to_dict()
    if canonical_sha256(payload) != str(raw_hash):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "stored replay launch context failed its integrity check",
            status_code=503,
        )
    return payload


def insert_track(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    adapter_session_id: str,
    source_kind: str,
    exchange: str,
    market_type: str,
    symbol: str,
    settlement_asset: str,
    dataset_epoch: str,
    cursor: Mapping[str, object],
    component_state: Mapping[str, object] | None,
    now_ms: int,
) -> None:
    position, account, open_orders, public_price = track_components(component_state)
    connection.execute(
        """
        INSERT INTO replay_training_market_track(
            run_id, track_id, stable_ordinal, adapter_session_id,
            exchange, market_type, symbol, settlement_asset, source_kind,
            state, subscription_tier, dataset_epoch, virtual_time_ms,
            source_sequence, revision, forced_full_reasons_json,
            capabilities_json, public_price, position_json, account_json,
            open_orders_json, degraded_reason, created_at_ms, updated_at_ms
        ) VALUES (
            ?, 'track-1', 1, ?, ?, ?, ?, ?, ?, 'READY', 'FULL', ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, NULL, ?, ?
        )
        """,
        (
            run_id,
            adapter_session_id,
            exchange,
            market_type,
            symbol,
            settlement_asset,
            source_kind,
            dataset_epoch,
            validate_v2_counter(
                cursor["virtual_time_ms"], field_name="virtual_time_ms"
            ),
            validate_v2_counter(
                cursor["source_sequence"], field_name="source_sequence"
            ),
            validate_v2_counter(cursor["revision"], field_name="revision"),
            canonical_json(["VIEWED"]),
            canonical_json(_phase1_capabilities(source_kind)),
            public_price,
            canonical_json(position),
            canonical_json(account),
            canonical_json(open_orders),
            now_ms,
            now_ms,
        ),
    )


def track_components(
    component_state: Mapping[str, object] | None,
) -> tuple[dict[str, object], dict[str, object], list[object], str | None]:
    if not isinstance(component_state, Mapping):
        return {}, {}, [], None
    raw_position = component_state.get("position")
    raw_account = component_state.get("account")
    raw_orders = component_state.get("orders")
    position: dict[str, object] = (
        dict(cast(Mapping[str, object], raw_position))
        if isinstance(raw_position, Mapping)
        else {}
    )
    account: dict[str, object] = (
        dict(cast(Mapping[str, object], raw_account))
        if isinstance(raw_account, Mapping)
        else {}
    )
    orders: list[object] = (
        [
            dict(cast(Mapping[str, object], order))
            if isinstance(order, Mapping)
            else order
            for order in raw_orders
        ]
        if isinstance(raw_orders, (list, tuple))
        else []
    )
    mark = position.get("mark_price")
    public_price = mark if isinstance(mark, str) else None
    terminal = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
    open_orders: list[object] = [
        order
        for order in orders
        if isinstance(order, Mapping) and order.get("status") not in terminal
    ]
    return position, account, open_orders, public_price


def insert_viewer_state(
    connection: sqlite3.Connection,
    viewer: ViewerState,
    *,
    now_ms: int,
) -> None:
    payload = viewer.to_dict()
    connection.execute(
        """
        INSERT INTO replay_training_viewer_state(
            run_id, selected_track_id, display_interval, chart_type,
            visible_range_json, pane_layout_json, rail_layout_json,
            semantic_view_revision, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            viewer.run_id,
            viewer.selected_track_id,
            viewer.display_interval,
            viewer.chart_type,
            None
            if viewer.visible_range is None
            else canonical_json(viewer.visible_range),
            canonical_json(viewer.pane_layout),
            canonical_json(viewer.rail_layout),
            viewer.semantic_view_revision,
            now_ms,
        ),
    )
    connection.execute(
        """
        INSERT INTO replay_training_viewer_event(
            run_id, semantic_view_revision, command_id, event_type,
            request_json, viewer_state_json, created_at_ms
        ) VALUES (?, ?, NULL, 'INITIAL_VIEWER_STATE', '{}', ?, ?)
        """,
        (
            viewer.run_id,
            viewer.semantic_view_revision,
            canonical_json(payload),
            now_ms,
        ),
    )


def viewer_from_row(row: Mapping[str, object]) -> ViewerState:
    visible_raw = row["visible_range_json"]
    selected_track_id = row["selected_track_id"]
    return ViewerState(
        run_id=str(row["run_id"]),
        selected_track_id=(
            None if selected_track_id is None else str(selected_track_id)
        ),
        display_interval=str(row["display_interval"]),
        chart_type=str(row["chart_type"]),
        visible_range=(None if visible_raw is None else json.loads(str(visible_raw))),
        pane_layout=json.loads(str(row["pane_layout_json"])),
        rail_layout=json.loads(str(row["rail_layout_json"])),
        semantic_view_revision=int(row["semantic_view_revision"]),
    )


def action_from_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "action_sequence": validate_v2_counter(
            row["action_sequence"], field_name="action_sequence"
        ),
        "event_id": str(row["event_id"]),
        "command_id": row["command_id"],
        "event_type": str(row["event_type"]),
        "rule_revision": validate_v2_counter(
            row["rule_revision"], field_name="rule_revision"
        ),
        "public_time": json.loads(str(row["public_time_json"])),
        "old_value": json.loads(str(row["old_value_json"])),
        "new_value": json.loads(str(row["new_value_json"])),
        "reason": str(row["reason"]),
        "state_hash_before": row["state_hash_before"],
        "state_hash_after": str(row["state_hash_after"]),
    }


def view_action_from_row(
    row: Mapping[str, object],
    *,
    coalesced: bool,
) -> dict[str, object]:
    return {
        "view_sequence": validate_v2_counter(
            row["view_sequence"], field_name="view_sequence"
        ),
        "command_id": str(row["command_id"]),
        "event_type": str(row["event_type"]),
        "semantic_key": str(row["semantic_key"]),
        "value": json.loads(str(row["value_json"])),
        "sample_count": validate_v2_counter(
            row["sample_count"], field_name="sample_count"
        ),
        "first_public_time": json.loads(str(row["first_public_time_json"])),
        "last_public_time": json.loads(str(row["last_public_time_json"])),
        "coalesced": coalesced,
    }


def insert_rule(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    rule: Mapping[str, object],
    now_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO replay_training_rule(
            run_id, revision, rule_json, rule_hash, created_at_ms
        ) VALUES (?, 1, ?, ?, ?)
        """,
        (run_id, canonical_json(rule), canonical_sha256(rule), now_ms),
    )


def insert_initial_action(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    action_type: str,
    action: Mapping[str, object],
    now_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO replay_training_action(
            run_id, action_sequence, action_type, action_json, created_at_ms
        ) VALUES (?, 1, ?, ?, ?)
        """,
        (run_id, action_type, canonical_json(action), now_ms),
    )


def insert_pin(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    adapter_session_id: str,
    dataset_epoch: str,
    now_ms: int,
) -> None:
    pin_id = "primary-dataset" if track_id == "track-1" else f"{track_id}-dataset"
    connection.execute(
        """
        INSERT INTO replay_training_pin(
            run_id, pin_id, dataset_epoch, pin_kind, manifest_json, created_at_ms
        ) VALUES (?, ?, ?, 'V1_DATASET_REF', ?, ?)
        """,
        (
            run_id,
            pin_id,
            dataset_epoch,
            canonical_json(
                {
                    "schema": "replay.training.rehydration.v1",
                    "adapter_session_id": adapter_session_id,
                    "owner": "replay_dataset_ref",
                }
            ),
            now_ms,
        ),
    )
    dataset_row = connection.execute(
        """
        SELECT snapshot_ref_json, snapshot_blob
        FROM replay_dataset_ref
        WHERE session_id = ?
        """,
        (adapter_session_id,),
    ).fetchone()
    if dataset_row is None:
        return
    raw_bar_ref = persisted_bar_archive_reference(
        dataset_row["snapshot_ref_json"],
        dataset_row["snapshot_blob"],
        strict=True,
    )
    if raw_bar_ref is None:
        return
    source_revision = raw_bar_ref.get("source_revision")
    identity = raw_bar_ref.get("identity")
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != 71
        or not source_revision.startswith("sha256:")
        or not isinstance(identity, Mapping)
    ):
        return
    try:
        archive_values = (
            str(identity["exchange"]),
            str(identity["market_type"]),
            str(identity["symbol"]),
            str(raw_bar_ref["interval"]),
            int(raw_bar_ref["warmup_start_ms"]),
            int(raw_bar_ref["replay_end_open_ms"]),
        )
    except (KeyError, TypeError, ValueError):
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO replay_archive_pin(
            run_id, track_id, source_revision,
            exchange, market_type, symbol, base_interval,
            range_start_ms, range_end_ms, dataset_epoch, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            track_id,
            source_revision,
            *archive_values,
            dataset_epoch,
            now_ms,
        ),
    )


def card_from_row(row: Mapping[str, object]) -> dict[str, object]:
    unavailable = row["compatibility"] == "UNAVAILABLE"
    if unavailable:
        status = {
            "code": "UNAVAILABLE",
            "message": "存档当前不可恢复；请检查服务端诊断或导出记录。",
        }
    elif row["state"] == "AWAITING_MARKET":
        status = {
            "code": "AWAITING_MARKET",
            "message": "回放已创建，请选择第一个商品。",
        }
    elif row["state"] == "ENDED":
        status = {"code": "ENDED", "message": "训练已结束，可打开复盘。"}
    else:
        status = {"code": "READY", "message": "训练可继续"}
    return {
        "run_id": str(row["run_id"]),
        "kind": str(row["kind"]),
        "name": str(row["name"]),
        "state": str(row["state"]),
        "source_kind": str(row["source_kind"]),
        "integrity_mode": row["integrity_mode"],
        "time_disclosure_policy": str(row["time_disclosure_policy"]),
        "last_symbol": (
            None if row["last_symbol"] is None else str(row["last_symbol"])
        ),
        "subscribed_track_count": int(row["subscribed_track_count"]),
        "progress": {"source_sequence": int(row["progress_sequence"])},
        "equity": row["equity"],
        "equity_status": str(row["equity_status"]),
        "settlement_asset": str(row["settlement_asset"]),
        "updated_at_ms": int(row["updated_at_ms"]),
        "compatibility": str(row["compatibility"]),
        "resume_action": str(row["resume_action"]),
        "adapter_session_id": (
            None
            if row["adapter_session_id"] is None
            else str(row["adapter_session_id"])
        ),
        "status": status,
        "report_available": bool(row["report_available"]),
        "review_available": bool(row["review_available"]),
    }
