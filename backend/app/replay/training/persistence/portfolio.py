"""Portfolio operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    CONFIGURED_FEE_FIDELITY,
    CONTRACT_ACCOUNT_MODEL,
    CONTRACT_ACCOUNT_SCHEMA_VERSION,
    SANDBOX_FUNDING_FIDELITY,
    InstrumentRule,
    isolated_margin_key,
)
from ..errors import TrainingRunError
from ..hedge_inputs import (
    HEDGE_INPUT_PROOF_SCHEMA_VERSION,
)
from ..historical_book import (
    BOOK_EXECUTION_FIDELITY,
    HISTORICAL_L2_LIQUIDATION_FIDELITY,
)
from ..liquidation_projection import load_public_liquidation_cases
from ..models import (
    HEDGE_INSURANCE_ADL_FIDELITY,
    CapabilityState,
    TimeDisclosurePolicy,
    validate_v2_counter,
)
from ..multitrack import (
    GLOBAL_ORDERING_VERSION,
)
from . import account_math as account_math_ops
from . import public_time as public_time_ops
from . import run_records as run_records_ops


def reason_list(row: Mapping[str, object]) -> list[str]:
    try:
        decoded = json.loads(str(row["forced_full_reasons_json"]))
    except json.JSONDecodeError as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "market track force reasons are invalid",
            status_code=503,
        ) from exc
    if not isinstance(decoded, list) or any(
        not isinstance(reason, str) for reason in decoded
    ):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "market track force reasons are invalid",
            status_code=503,
        )
    return sorted(set(decoded))


def historical_book_projection(
    row: Mapping[str, object] | None,
    *,
    book_mode: str,
    subscription_tier: str,
) -> dict[str, object]:
    if row is None:
        required = book_mode == "BOOK_ASSISTED_REQUIRED" and subscription_tier == "FULL"
        return {
            "mode": book_mode,
            "capability_state": (
                CapabilityState.DEGRADED.value
                if required
                else CapabilityState.UNSUPPORTED_NO_HISTORY.value
            ),
            "status": "CLEARED" if required else "OFF",
            "execution_fidelity": (
                BOOK_EXECUTION_FIDELITY
                if book_mode == "BOOK_ASSISTED_REQUIRED"
                else "NO_BOOK_TOUCH_OR_TAPE_APPROX"
            ),
            "queue_exact": False,
            "as_of_virtual_time_ms": None,
            "last_update_id": None,
            "bids": [],
            "asks": [],
            "book_hash": None,
            "message": (
                "缺少已 pin 的连续历史 L2；Run 必须保持暂停"
                if required
                else (
                    "该轨道不是 FULL；未激活历史盘口投影"
                    if book_mode == "BOOK_ASSISTED_REQUIRED"
                    else "历史盘口模式未启用"
                )
            ),
        }
    try:
        bids = json.loads(str(row["bids_json"]))
        asks = json.loads(str(row["asks_json"]))
    except json.JSONDecodeError as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "historical book projection JSON is invalid",
            status_code=503,
        ) from exc
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "historical book projection levels are invalid",
            status_code=503,
        )
    return {
        "mode": book_mode,
        "capability_state": str(row["capability_state"]),
        "status": str(row["status"]),
        "execution_fidelity": str(row["execution_fidelity"]),
        "queue_exact": bool(row["queue_exact"]),
        "as_of_virtual_time_ms": row["as_of_virtual_ms"],
        "last_update_id": row["last_update_id"],
        "bids": bids,
        "asks": asks,
        "book_hash": row["book_hash"],
        "message": str(row["message"]),
    }


def market_track_from_row(
    row: Mapping[str, object],
) -> dict[str, object]:
    def json_object(field_name: str) -> dict[str, object]:
        try:
            value = json.loads(str(row[field_name]))
        except json.JSONDecodeError as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                f"market track {field_name} is invalid",
                status_code=503,
            ) from exc
        if not isinstance(value, dict):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                f"market track {field_name} is invalid",
                status_code=503,
            )
        return value

    try:
        capabilities = json.loads(str(row["capabilities_json"]))
        open_orders = json.loads(str(row["open_orders_json"]))
    except json.JSONDecodeError as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "market track projection JSON is invalid",
            status_code=503,
        ) from exc
    if not isinstance(capabilities, dict) or not isinstance(open_orders, list):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "market track projection JSON is invalid",
            status_code=503,
        )
    cursor = None
    if row["virtual_time_ms"] is not None:
        if row["source_sequence"] is None or row["revision"] is None:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market track cursor is incomplete",
                status_code=503,
            )
        cursor = {
            "virtual_time_ms": validate_v2_counter(
                row["virtual_time_ms"], field_name="virtual_time_ms"
            ),
            "source_sequence": validate_v2_counter(
                row["source_sequence"], field_name="source_sequence"
            ),
            "revision": validate_v2_counter(row["revision"], field_name="revision"),
        }
    return {
        "run_id": str(row["run_id"]),
        "track_id": str(row["track_id"]),
        "stable_ordinal": validate_v2_counter(
            row["stable_ordinal"], field_name="stable_ordinal"
        ),
        "adapter_session_id": (
            None
            if row["adapter_session_id"] is None
            else str(row["adapter_session_id"])
        ),
        "exchange": str(row["exchange"]),
        "market_type": str(row["market_type"]),
        "symbol": str(row["symbol"]),
        "settlement_asset": str(row["settlement_asset"]),
        "state": str(row["state"]),
        "source_kind": str(row["source_kind"]),
        "subscription_tier": str(row["subscription_tier"]),
        "cursor": cursor,
        "forced_full_reasons": reason_list(row),
        "capabilities": capabilities,
        "public_price": row["public_price"],
        "position": json_object("position_json"),
        "open_order_count": len(open_orders),
        "degraded_reason": row["degraded_reason"],
        "account": json_object("account_json"),
    }


def portfolio_projection(
    *,
    initial_equity: str,
    tracks: list[dict[str, object]],
) -> dict[str, object]:
    try:
        initial = Decimal(initial_equity)
        equity = initial
        cash = initial
        available = initial
        reserved = Decimal(0)
        margin_used = Decimal(0)
        realized = Decimal(0)
        unrealized = Decimal(0)
        fees = Decimal(0)
        positions: list[dict[str, object]] = []
        position_mode = "ONE_WAY"
        for track in tracks:
            account = track.get("account")
            if isinstance(account, Mapping) and isinstance(account.get("equity"), str):
                equity += Decimal(str(account["equity"])) - initial
                cash += Decimal(str(account["cash_balance"])) - initial
                available += Decimal(str(account["available_equity"])) - initial
                reserved += Decimal(str(account["reserved_margin"]))
                margin_used += Decimal(str(account["margin_used"]))
                realized += Decimal(str(account["realized_pnl"]))
                unrealized += Decimal(str(account["unrealized_pnl"]))
                fees += Decimal(str(account["fees_paid"]))
            position = track.get("position")
            if (
                isinstance(position, Mapping)
                and position.get("position_mode") == "HEDGE"
            ):
                position_mode = "HEDGE"
                for leg_name, side in (("long", "LONG"), ("short", "SHORT")):
                    leg = position.get(leg_name)
                    if isinstance(leg, Mapping) and leg.get("quantity") not in {
                        None,
                        "0",
                    }:
                        positions.append(
                            {
                                "track_id": track["track_id"],
                                "symbol": track["symbol"],
                                "position_side": side,
                                "position": dict(leg),
                            }
                        )
            elif isinstance(position, Mapping) and position.get("quantity") not in {
                None,
                "0",
            }:
                positions.append(
                    {
                        "track_id": track["track_id"],
                        "symbol": track["symbol"],
                        "position": dict(position),
                    }
                )
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "multi-market account projection is invalid",
            status_code=503,
        ) from exc
    return {
        "schema_version": "replay.training.portfolio.v1",
        "fidelity": "PAPER_LINEAR_V1_MULTI_TRACK_ADAPTER",
        "settlement_account_shared": True,
        "position_mode": position_mode,
        "initial_equity": decimal_to_string(initial, field_name="initial_equity"),
        "equity": decimal_to_string(equity, field_name="equity"),
        "cash_balance": decimal_to_string(cash, field_name="cash_balance"),
        "available_equity": decimal_to_string(
            available,
            field_name="available_equity",
        ),
        "reserved_margin": decimal_to_string(
            reserved,
            field_name="reserved_margin",
        ),
        "margin_used": decimal_to_string(margin_used, field_name="margin_used"),
        "realized_pnl": decimal_to_string(realized, field_name="realized_pnl"),
        "unrealized_pnl": decimal_to_string(
            unrealized,
            field_name="unrealized_pnl",
        ),
        "fees_paid": decimal_to_string(fees, field_name="fees_paid"),
        "positions": positions,
    }


def contract_current_equity(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    initial_equity: str,
    tracks: list[dict[str, object]],
) -> str:
    """Return the contract-equity scalar without materializing full history."""

    base = portfolio_projection(
        initial_equity=initial_equity,
        tracks=tracks,
    )
    account = connection.execute(
        """
        SELECT account_model, overlay_cash
        FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        return str(base["equity"])
    try:
        equity = (
            Decimal(str(base["cash_balance"]))
            + Decimal(str(account["overlay_cash"]))
            + Decimal(str(base["unrealized_pnl"]))
        )
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "contract account equity is invalid",
            status_code=503,
        ) from exc
    return decimal_to_string(equity, field_name="equity")


def refresh_contract_current_equity(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
    summary_revision: int | None = None,
) -> str:
    rows = tuple(
        connection.execute(
            """
            SELECT account_json FROM replay_training_market_track
            WHERE run_id = ? ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    )
    tracks: list[dict[str, object]] = []
    for row in rows:
        try:
            account = json.loads(str(row["account_json"]))
        except json.JSONDecodeError as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market track account projection is invalid",
                status_code=503,
            ) from exc
        if not isinstance(account, dict):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "market track account projection is invalid",
                status_code=503,
            )
        tracks.append({"account": account})
    run = connection.execute(
        """
        SELECT initial_equity FROM replay_training_run WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if run is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training run account owner is missing",
            status_code=503,
        )
    current_equity = contract_current_equity(
        connection,
        run_id=run_id,
        initial_equity=str(run["initial_equity"]),
        tracks=tracks,
    )
    if summary_revision is None:
        connection.execute(
            """
            UPDATE replay_training_run
            SET current_equity = ?, updated_at_ms = ?
            WHERE run_id = ?
            """,
            (current_equity, now_ms, run_id),
        )
    else:
        connection.execute(
            """
            UPDATE replay_training_run
            SET current_equity = ?, summary_revision = ?, updated_at_ms = ?
            WHERE run_id = ?
            """,
            (current_equity, summary_revision, now_ms, run_id),
        )
    return current_equity


def hedge_input_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
) -> dict[str, object] | None:
    binding = connection.execute(
        "SELECT * FROM replay_hedge_input_binding WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if binding is None:
        return None
    public = connection.execute(
        "SELECT * FROM replay_hedge_public_archive WHERE archive_id = ?",
        (binding["public_archive_id"],),
    ).fetchone()
    simulation = connection.execute(
        "SELECT * FROM replay_hedge_simulation_manifest WHERE manifest_id = ?",
        (binding["simulation_manifest_id"],),
    ).fetchone()
    if public is None or simulation is None:
        raise TypeError("HEDGE input catalog binding is missing")
    expected_proof = canonical_sha256(
        {
            "schema_version": HEDGE_INPUT_PROOF_SCHEMA_VERSION,
            "public": {
                "archive_id": str(public["archive_id"]),
                "generation": int(public["generation"]),
                "dataset_epoch": str(public["dataset_epoch"]),
                "checksum_sha256": str(public["checksum_sha256"]),
                "event_chain_tail": str(public["event_chain_tail"]),
                "proof_hash": str(public["proof_hash"]),
            },
            "simulation": {
                "manifest_id": str(simulation["manifest_id"]),
                "generation": int(simulation["generation"]),
                "dataset_epoch": str(simulation["dataset_epoch"]),
                "checksum_sha256": str(simulation["checksum_sha256"]),
                "contract_hash": str(simulation["contract_hash"]),
                "proof_hash": str(simulation["proof_hash"]),
            },
            "bound_range_start_ms": int(binding["bound_range_start_ms"]),
            "bound_range_end_ms": int(binding["bound_range_end_ms"]),
        }
    )
    pinned_fields = (
        int(binding["public_generation"]) == int(public["generation"])
        and str(binding["public_dataset_epoch"]) == str(public["dataset_epoch"])
        and str(binding["public_checksum_sha256"]) == str(public["checksum_sha256"])
        and str(binding["public_event_chain_tail"]) == str(public["event_chain_tail"])
        and int(binding["simulation_generation"]) == int(simulation["generation"])
        and str(binding["simulation_dataset_epoch"]) == str(simulation["dataset_epoch"])
        and str(binding["simulation_checksum_sha256"])
        == str(simulation["checksum_sha256"])
        and str(binding["simulation_contract_hash"]) == str(simulation["contract_hash"])
    )
    if not pinned_fields or expected_proof != binding["input_proof_hash"]:
        raise TypeError("HEDGE input binding proof is invalid")
    projections: list[dict[str, object]] = []
    for row in connection.execute(
        """
        SELECT * FROM replay_hedge_input_projection
        WHERE run_id = ? ORDER BY source_kind
        """,
        (run_id,),
    ).fetchall():
        state = json.loads(str(row["state_json"]))
        payload = {
            "schema_version": "replay.hedge-input-projection.v1",
            "source_kind": str(row["source_kind"]),
            "last_event_sequence": int(row["last_event_sequence"]),
            "as_of_actual_time_ms": int(row["as_of_actual_time_ms"]),
            "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
            "state": state,
            "input_chain_hash": str(row["input_chain_hash"]),
        }
        if canonical_sha256(payload) != row["component_hash"]:
            raise TypeError("HEDGE input projection component hash is invalid")
        projections.append(
            {
                **payload,
                "component_hash": str(row["component_hash"]),
            }
        )
    if [item["source_kind"] for item in projections] != [
        "PUBLIC",
        "SIMULATION",
    ]:
        raise TypeError("HEDGE input projections are incomplete")
    track_public: list[dict[str, object]] = []
    for row in connection.execute(
        """
        SELECT track_binding.*, projection.last_event_sequence,
               projection.as_of_actual_time_ms,
               projection.as_of_virtual_time_ms,
               projection.state_json, projection.input_chain_hash,
               projection.component_hash
        FROM replay_hedge_track_public_binding AS track_binding
        JOIN replay_hedge_track_public_projection AS projection
          ON projection.run_id = track_binding.run_id
         AND projection.track_id = track_binding.track_id
        WHERE track_binding.run_id = ?
        ORDER BY track_binding.track_id
        """,
        (run_id,),
    ).fetchall():
        state = json.loads(str(row["state_json"]))
        payload = {
            "schema_version": "replay.hedge-track-public-projection.v1",
            "run_id": run_id,
            "track_id": str(row["track_id"]),
            "last_event_sequence": int(row["last_event_sequence"]),
            "as_of_actual_time_ms": int(row["as_of_actual_time_ms"]),
            "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
            "state": state,
            "input_chain_hash": str(row["input_chain_hash"]),
        }
        if canonical_sha256(payload) != row["component_hash"]:
            raise TypeError("HEDGE track public projection hash is invalid")
        track_public.append(
            {
                "track_id": str(row["track_id"]),
                "archive_id": str(row["public_archive_id"]),
                "generation": int(row["public_generation"]),
                "dataset_epoch": str(row["public_dataset_epoch"]),
                "checksum_sha256": str(row["public_checksum_sha256"]),
                "event_chain_tail": str(row["public_event_chain_tail"]),
                "input_proof_hash": str(row["input_proof_hash"]),
                "status": str(row["status"]),
                "degraded_reason": row["degraded_reason"],
                "projection": {
                    **payload,
                    "component_hash": str(row["component_hash"]),
                },
            }
        )
    audit = connection.execute(
        """
        SELECT * FROM replay_hedge_input_audit
        WHERE run_id = ? ORDER BY audit_sequence DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    return {
        "schema_version": "replay.hedge-input-view.v1",
        "status": str(binding["status"]),
        "degraded_reason": binding["degraded_reason"],
        "input_proof_hash": str(binding["input_proof_hash"]),
        "bound_range_start_ms": int(binding["bound_range_start_ms"]),
        "bound_range_end_ms": int(binding["bound_range_end_ms"]),
        "public": {
            "archive_id": str(public["archive_id"]),
            "generation": int(public["generation"]),
            "dataset_epoch": str(public["dataset_epoch"]),
            "checksum_sha256": str(public["checksum_sha256"]),
            "event_chain_tail": str(public["event_chain_tail"]),
            "proof_hash": str(public["proof_hash"]),
            "health": str(public["health"]),
        },
        "simulation": {
            "manifest_id": str(simulation["manifest_id"]),
            "generation": int(simulation["generation"]),
            "dataset_epoch": str(simulation["dataset_epoch"]),
            "checksum_sha256": str(simulation["checksum_sha256"]),
            "contract_hash": str(simulation["contract_hash"]),
            "model_version": str(simulation["model_version"]),
            "proof_hash": str(simulation["proof_hash"]),
            "health": str(simulation["health"]),
        },
        "projections": projections,
        "track_public": track_public,
        "auditor": {
            "status": "NOT_RUN" if audit is None else str(audit["status"]),
            "proof_hash": None if audit is None else str(audit["proof_hash"]),
            "differences": (
                [] if audit is None else json.loads(str(audit["differences_json"]))
            ),
        },
    }


def public_contract_portfolio_projection(
    portfolio: dict[str, object],
    *,
    time_disclosure_policy: str,
    revealed: bool,
    actual_start_ms: int,
    actual_end_ms: int,
    synthetic_origin_ms: int | None,
) -> dict[str, object]:
    """Replace the internal HEDGE input proof view with its public contract.

    The v1 view is deliberately retained inside checkpoints and auditors because
    its component hashes commit to exact exchange-input timestamps and states.
    API consumers receive v2 instead: a single disclosed timeline, hashes of the
    private states, and commitments back to the verified internal components.
    """

    raw = portfolio.get("hedge_inputs")
    if raw is None:
        return portfolio
    if not isinstance(raw, Mapping):
        raise TypeError("internal HEDGE input view is invalid")
    if raw.get("schema_version") != "replay.hedge-input-view.v1":
        raise TypeError("internal HEDGE input view schema is invalid")
    try:
        policy = TimeDisclosurePolicy(time_disclosure_policy)
    except ValueError as exc:
        raise TypeError("time disclosure policy is invalid") from exc
    if actual_start_ms < 0 or actual_end_ms < actual_start_ms:
        raise ValueError("HEDGE input time bounds are invalid")
    binding_start_ms = int(raw["bound_range_start_ms"])
    binding_end_ms = int(raw["bound_range_end_ms"])
    # Dataset refs end at the final source-bar open.  HEDGE inputs are bound
    # through that bar's close, so their proven upper bound may be later.
    if binding_start_ms != actual_start_ms or binding_end_ms < actual_end_ms:
        raise ValueError("HEDGE input and replay time bounds disagree")
    actual_end_ms = binding_end_ms

    configured_hidden = policy is not TimeDisclosurePolicy.NONE
    hidden = configured_hidden and not revealed
    actor_origin_ms = (
        public_time_ops.required_synthetic_origin(synthetic_origin_ms)
        if configured_hidden
        else actual_start_ms
    )
    public_origin_ms = actual_start_ms if not hidden else actor_origin_ms
    public_end_ms = public_origin_ms + actual_end_ms - actual_start_ms
    time_domain = "PUBLIC" if hidden else "ACTUAL"

    def public_time(actual_time_ms: object, virtual_time_ms: object) -> int:
        actual = int(actual_time_ms)
        virtual = int(virtual_time_ms)
        if actual < actual_start_ms or actual > actual_end_ms:
            raise ValueError("HEDGE input projection time is outside its binding")
        actor_time = actor_origin_ms + actual - actual_start_ms
        if virtual != actor_time:
            raise ValueError("HEDGE input public timeline is inconsistent")
        return actual if time_domain == "ACTUAL" else actor_time

    raw_projections = raw.get("projections")
    if not isinstance(raw_projections, list) or len(raw_projections) != 2:
        raise TypeError("internal HEDGE input projections are invalid")
    projections: list[dict[str, object]] = []
    for item in raw_projections:
        if not isinstance(item, Mapping):
            raise TypeError("internal HEDGE input projection is invalid")
        state = item.get("state")
        if not isinstance(state, Mapping):
            raise TypeError("internal HEDGE input state is invalid")
        projections.append(
            {
                "schema_version": "replay.hedge-input-public-projection.v1",
                "source_kind": str(item["source_kind"]),
                "last_event_sequence": int(item["last_event_sequence"]),
                "as_of_time_ms": public_time(
                    item["as_of_actual_time_ms"],
                    item["as_of_virtual_time_ms"],
                ),
                "time_domain": time_domain,
                "state_hash": canonical_sha256(state),
                "input_chain_hash": str(item["input_chain_hash"]),
                "source_component_hash": str(item["component_hash"]),
            }
        )

    raw_track_public = raw.get("track_public")
    if not isinstance(raw_track_public, list) or not raw_track_public:
        raise TypeError("internal HEDGE track input projections are invalid")
    track_public: list[dict[str, object]] = []
    for item in raw_track_public:
        if not isinstance(item, Mapping):
            raise TypeError("internal HEDGE track input binding is invalid")
        projection = item.get("projection")
        if not isinstance(projection, Mapping):
            raise TypeError("internal HEDGE track projection is invalid")
        state = projection.get("state")
        if not isinstance(state, Mapping):
            raise TypeError("internal HEDGE track state is invalid")
        track_public.append(
            {
                "track_id": str(item["track_id"]),
                "archive_id": str(item["archive_id"]),
                "generation": int(item["generation"]),
                "dataset_epoch": str(item["dataset_epoch"]),
                "checksum_sha256": str(item["checksum_sha256"]),
                "event_chain_tail": str(item["event_chain_tail"]),
                "input_proof_hash": str(item["input_proof_hash"]),
                "status": str(item["status"]),
                "degraded_reason": item["degraded_reason"],
                "projection": {
                    "schema_version": ("replay.hedge-track-public-projection.v2"),
                    "run_id": str(projection["run_id"]),
                    "track_id": str(projection["track_id"]),
                    "last_event_sequence": int(projection["last_event_sequence"]),
                    "as_of_time_ms": public_time(
                        projection["as_of_actual_time_ms"],
                        projection["as_of_virtual_time_ms"],
                    ),
                    "time_domain": time_domain,
                    "state_hash": canonical_sha256(state),
                    "input_chain_hash": str(projection["input_chain_hash"]),
                    "source_component_hash": str(projection["component_hash"]),
                },
            }
        )

    raw_auditor = raw.get("auditor")
    if not isinstance(raw_auditor, Mapping):
        raise TypeError("internal HEDGE input auditor is invalid")
    raw_differences = raw_auditor.get("differences")
    if not isinstance(raw_differences, list):
        raise TypeError("internal HEDGE input auditor differences are invalid")
    public_view = {
        "schema_version": "replay.hedge-input-view.v2",
        "status": str(raw["status"]),
        "degraded_reason": raw["degraded_reason"],
        "input_proof_hash": str(raw["input_proof_hash"]),
        "time_domain": time_domain,
        "bound_range_start_ms": public_origin_ms,
        "bound_range_end_ms": public_end_ms,
        "public": raw["public"],
        "simulation": raw["simulation"],
        "projections": projections,
        "track_public": track_public,
        "auditor": {
            "status": str(raw_auditor["status"]),
            "proof_hash": raw_auditor["proof_hash"],
            "difference_count": len(raw_differences),
            "difference_hashes": [
                canonical_sha256(difference) for difference in raw_differences
            ],
        },
    }
    return {**portfolio, "hedge_inputs": public_view}


def live_hedge_state_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    position_leg_rows: Sequence[sqlite3.Row],
    leg_accounting: Sequence[Mapping[str, object]],
    liquidations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return bounded current heads for the live stream, never audit history."""

    latest_risk = connection.execute(
        """
        SELECT snapshot_id, snapshot_sequence, virtual_time_ms,
               source_sequence, account_status, equity,
               available_balance, total_initial_margin,
               total_maintenance_margin, risk_ratio,
               active_rule_revision, public_input_hash,
               component_hash, created_at_ms
        FROM replay_training_risk_snapshot
        WHERE run_id = ? ORDER BY snapshot_sequence DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    payload = {
        "schema_version": "replay.hedge-relational-live.v1",
        "detail": "LIVE_HEADS",
        "audit_history": "AUTHORITATIVE_REST_FULL",
        "position_legs": [dict(row) for row in position_leg_rows],
        "leg_accounting": [dict(item) for item in leg_accounting],
        "margin_buckets": [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM replay_training_margin_bucket
                WHERE run_id = ? ORDER BY bucket_id
                """,
                (run_id,),
            ).fetchall()
        ],
        "insurance_funds": [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM replay_training_insurance_fund
                WHERE run_id = ? ORDER BY asset
                """,
                (run_id,),
            ).fetchall()
        ],
        "history_heads": {
            "latest_risk_snapshot": (
                None if latest_risk is None else dict(latest_risk)
            ),
        },
        "liquidation_case_hashes": [
            str(item["component_hash"]) for item in liquidations
        ],
    }
    return {**payload, "state_hash": canonical_sha256(payload)}


def contract_portfolio_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    initial_equity: str,
    tracks: list[dict[str, object]],
    live: bool = False,
) -> dict[str, object]:
    account = connection.execute(
        """
        SELECT * FROM replay_training_contract_account WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        return portfolio_projection(
            initial_equity=initial_equity,
            tracks=tracks,
        )
    run_contract = connection.execute(
        """
        SELECT book_mode, hedge_public_history_ref_json,
               simulation_manifest_ref_json, simulation_contract_hash,
               simulation_model_version, account_fidelity,
               insurance_adl_fidelity
        FROM replay_training_run WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if run_contract is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training run execution contract is missing",
            status_code=503,
        )

    def public_book_execution(row: sqlite3.Row) -> dict[str, object]:
        return {
            "case_id": str(row["case_id"]),
            "step_sequence": int(row["step_sequence"]),
            "track_id": str(row["track_id"]),
            "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
            "last_update_id": int(row["last_update_id"]),
            "side": str(row["side"]),
            "requested_quantity": str(row["requested_quantity"]),
            "visible_quantity": str(row["visible_quantity"]),
            "levels": json.loads(str(row["levels_json"])),
            "book_hash": str(row["book_hash"]),
            "execution_fidelity": str(row["execution_fidelity"]),
            "queue_exact": int(row["queue_exact"]),
            "execution_plan_hash": str(row["execution_plan_hash"]),
        }

    def public_book_snapshot(row: sqlite3.Row) -> dict[str, object]:
        return {
            "case_id": str(row["case_id"]),
            "track_id": str(row["track_id"]),
            "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
            "last_update_id": int(row["last_update_id"]),
            "book_hash": str(row["book_hash"]),
            "execution_fidelity": str(row["execution_fidelity"]),
            "queue_exact": int(row["queue_exact"]),
            "snapshot_hash": str(row["snapshot_hash"]),
        }

    account_history = connection.execute(
        """
        SELECT * FROM replay_training_account_history WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    account_data_mode = (
        "APPROX_PROXY"
        if account_history is None
        else str(account_history["account_data_mode"])
    )
    exact_account = account_data_mode == "HISTORICAL_EXACT"
    execution_fidelity = (
        BOOK_EXECUTION_FIDELITY
        if run_contract["book_mode"] == "BOOK_ASSISTED_REQUIRED"
        else "NO_BOOK_TOUCH_OR_TAPE_APPROX"
    )
    base = portfolio_projection(
        initial_equity=initial_equity,
        tracks=tracks,
    )
    try:
        hedge_inputs = hedge_input_projection(
            connection,
            run_id=run_id,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "HEDGE input proof or projection is invalid",
            status_code=503,
        ) from exc
    if base["position_mode"] == "HEDGE" and hedge_inputs is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "HEDGE run is missing its pinned input proof",
            status_code=503,
        )
    order_rows = tuple(
        connection.execute(
            """
            SELECT track_id, order_json, rule_revision
            FROM replay_training_contract_order
            WHERE run_id = ?
              AND json_extract(order_json, '$.status')
                  IN ('OPEN', 'PARTIALLY_FILLED')
            ORDER BY track_id, order_id
            """,
            (run_id,),
        ).fetchall()
    )
    orders = [
        {
            **json.loads(str(row["order_json"])),
            "track_id": str(row["track_id"]),
            "rule_revision": int(row["rule_revision"]),
        }
        for row in order_rows
    ]
    live_hedge_heads = live and base["position_mode"] == "HEDGE"
    live_fee_total = Decimal(0)
    ledger_rows = (
        ()
        if live_hedge_heads
        else tuple(
            connection.execute(
                """
                SELECT ledger.*,
                       json_type(ledger.metadata_json) AS metadata_type,
                       json_extract(
                           ledger.metadata_json,
                           '$.position_side'
                       ) AS accounting_position_side
                FROM replay_training_contract_ledger AS ledger
                WHERE ledger.run_id = ? ORDER BY ledger.ledger_sequence
                """,
                (run_id,),
            ).fetchall()
        )
    )
    ledger_entry_count = (
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM replay_training_contract_ledger
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        )
        if live_hedge_heads
        else len(ledger_rows)
    )
    ledger_total = Decimal(0)
    funding_total = Decimal(0)
    liquidation_fee_total = Decimal(0)
    ledger_entries_by_leg: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in ledger_rows:
        cash_delta = Decimal(str(row["cash_delta"]))
        ledger_total += cash_delta
        if row["kind"] == "FUNDING_SETTLEMENT":
            funding_total += cash_delta
        elif row["kind"] == "LIQUIDATION_FEE":
            liquidation_fee_total -= cash_delta
        if row["metadata_type"] != "object":
            raise TypeError("contract ledger metadata is invalid")
        raw_track_id = row["track_id"]
        raw_position_side = row["accounting_position_side"]
        if raw_track_id is None or not isinstance(raw_position_side, str):
            continue
        ledger_entries_by_leg.setdefault(
            (str(raw_track_id), raw_position_side), []
        ).append(row)
    position_leg_rows: tuple[sqlite3.Row, ...] | None = None
    try:
        cash = ledger_total
        position_items = list(base["positions"])  # type: ignore[arg-type]
        realized = Decimal(str(base["realized_pnl"]))
        if base["position_mode"] == "HEDGE":
            track_by_id = {str(track["track_id"]): track for track in tracks}
            position_items = []
            realized = Decimal(0)
            position_leg_rows = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_position_leg
                    WHERE run_id = ? ORDER BY track_id, position_side
                    """,
                    (run_id,),
                ).fetchall()
            )
            if live_hedge_heads:
                live_fee_total = sum(
                    (Decimal(str(row["trading_fees"])) for row in position_leg_rows),
                    Decimal(0),
                )
                funding_total = sum(
                    (
                        Decimal(str(row["accumulated_funding"]))
                        for row in position_leg_rows
                    ),
                    Decimal(0),
                )
                liquidation_fee_total = sum(
                    (
                        Decimal(str(row["liquidation_fees"]))
                        for row in position_leg_rows
                    ),
                    Decimal(0),
                )
            for row in position_leg_rows:
                protection = json.loads(str(row["protection_json"]))
                component = {
                    "schema_version": "replay.position-leg.v1",
                    "track_id": str(row["track_id"]),
                    "position_side": str(row["position_side"]),
                    "signed_quantity": str(row["signed_quantity"]),
                    "absolute_quantity": str(row["absolute_quantity"]),
                    "entry_price": row["entry_price"],
                    "mark_price": row["mark_price"],
                    "notional": str(row["notional"]),
                    "realized_pnl": str(row["realized_pnl"]),
                    "unrealized_pnl": str(row["unrealized_pnl"]),
                    "initial_margin": str(row["initial_margin"]),
                    "maintenance_margin": str(row["maintenance_margin"]),
                    "leverage": str(row["leverage"]),
                    "margin_mode": str(row["margin_mode"]),
                    "isolated_wallet": str(row["isolated_wallet"]),
                    "liquidation_price": row["liquidation_price"],
                    "bankruptcy_price": row["bankruptcy_price"],
                    "accumulated_funding": str(row["accumulated_funding"]),
                    "trading_fees": str(row["trading_fees"]),
                    "liquidation_fees": str(row["liquidation_fees"]),
                    "risk_tier": int(row["risk_tier"]),
                    "rule_revision": int(row["rule_revision"]),
                    "protection": protection,
                }
                if canonical_sha256(component) != row["component_hash"]:
                    raise TypeError("hedge position leg hash is invalid")
                realized += Decimal(str(row["realized_pnl"]))
                if Decimal(str(row["absolute_quantity"])) == 0:
                    continue
                track = track_by_id.get(str(row["track_id"]))
                if track is None:
                    raise TypeError("hedge position leg track is missing")
                position_items.append(
                    {
                        "track_id": str(row["track_id"]),
                        "symbol": track["symbol"],
                        "position_side": str(row["position_side"]),
                        "position": {
                            "quantity": str(row["signed_quantity"]),
                            "entry_price": row["entry_price"],
                            "mark_price": row["mark_price"],
                            "notional": str(row["notional"]),
                            "realized_pnl": str(row["realized_pnl"]),
                            "unrealized_pnl": str(row["unrealized_pnl"]),
                            "leverage": str(row["leverage"]),
                        },
                        "initial_margin": str(row["initial_margin"]),
                        "maintenance_margin": str(row["maintenance_margin"]),
                        "liquidation_price": row["liquidation_price"],
                        "bankruptcy_price": row["bankruptcy_price"],
                        "accumulated_funding": str(row["accumulated_funding"]),
                        "trading_fees": str(row["trading_fees"]),
                        "liquidation_fees": str(row["liquidation_fees"]),
                        "protection": protection,
                        "risk_tier": int(row["risk_tier"]),
                        "position_leg_hash": str(row["component_hash"]),
                    }
                )
            if live_hedge_heads:
                ledger_total = (
                    Decimal(initial_equity)
                    + realized
                    - live_fee_total
                    + funding_total
                    - liquidation_fee_total
                )
                cash = ledger_total
        unrealized = sum(
            (
                Decimal(str(item["position"]["unrealized_pnl"]))
                for item in position_items
                if isinstance(item, Mapping)
                and isinstance(item.get("position"), Mapping)
            ),
            Decimal(0),
        )
        equity = cash + unrealized
        margin_used = Decimal(0)
        reserved = sum(
            (
                Decimal(str(order.get("reserved_margin", "0")))
                for order in orders
                if order.get("reduce_only") is not True
            ),
            Decimal(0),
        )
        isolated_raw = json.loads(str(account["isolated_margin_json"]))
        if not isinstance(isolated_raw, dict):
            raise TypeError("isolated margin allocation must be an object")
        isolated = {
            str(key): Decimal(str(value)) for key, value in isolated_raw.items()
        }
        available = (
            equity - margin_used - reserved
            if str(account["margin_mode"]) == "CROSS"
            else equity - sum(isolated.values(), Decimal(0))
        )
        risk_positions: list[dict[str, object]] = []
        leverage_policy = connection.execute(
            """
            SELECT max_leverage FROM replay_training_leverage_policy
            WHERE run_id = ?
            ORDER BY effective_virtual_time_ms DESC,
                     source_sequence DESC, revision DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if leverage_policy is None:
            raise TypeError("active leverage policy is missing")
        configured_max_leverage = Decimal(str(leverage_policy["max_leverage"]))
        total_initial_margin = Decimal(0)
        total_maintenance = Decimal(0)
        maintenance_tier_extrapolated_positions = 0
        liquidation_tier_extrapolated_positions = 0
        active_rule_query_rows = tuple(
            connection.execute(
                """
                SELECT rule.track_id, rule.revision, rule.rule_json,
                       rule.rule_hash, rule.fidelity
                FROM replay_training_instrument_rule AS rule
                JOIN (
                    SELECT track_id, MAX(revision) AS revision
                    FROM replay_training_instrument_rule
                    WHERE run_id = ? GROUP BY track_id
                ) AS latest
                  ON latest.track_id = rule.track_id
                 AND latest.revision = rule.revision
                WHERE rule.run_id = ? ORDER BY rule.track_id
                """,
                (run_id, run_id),
            ).fetchall()
        )
        active_rule_rows: dict[str, sqlite3.Row] = {}
        rule_payloads: dict[str, object] = {}
        rules: list[dict[str, object]] = []
        for row in active_rule_query_rows:
            track_id = str(row["track_id"])
            rule_payload = json.loads(str(row["rule_json"]))
            active_rule_rows[track_id] = row
            rule_payloads[track_id] = rule_payload
            rules.append(
                {
                    "track_id": track_id,
                    "revision": int(row["revision"]),
                    "rule_hash": str(row["rule_hash"]),
                    "fidelity": str(row["fidelity"]),
                    "rule": rule_payload,
                }
            )
        parsed_rules: dict[str, InstrumentRule] = {}
        for item in position_items:
            if not isinstance(item, Mapping):
                continue
            position = item.get("position")
            if not isinstance(position, Mapping):
                continue
            track_id = str(item["track_id"])
            rule_row = active_rule_rows.get(track_id)
            if rule_row is None:
                raise TypeError("active instrument rule is missing")
            rule = parsed_rules.get(track_id)
            if rule is None:
                rule = InstrumentRule.from_mapping(rule_payloads[track_id])
                parsed_rules[track_id] = rule
            notional = Decimal(str(position["notional"]))
            leverage = Decimal(str(position.get("leverage") or configured_max_leverage))
            leverage = min(
                leverage,
                configured_max_leverage,
                Decimal(rule.max_leverage),
            )
            initial_margin = rule.initial_margin(notional, leverage)
            risk_tier, _tier = rule.active_maintenance_tier(
                notional,
                extend_last_tier=True,
            )
            maintenance = rule.maintenance_margin(
                notional,
                extend_last_tier=True,
            )
            if base["position_mode"] == "HEDGE":
                for field_name, expected_value in (
                    ("initial_margin", initial_margin),
                    ("maintenance_margin", maintenance),
                    ("risk_tier", Decimal(risk_tier)),
                ):
                    actual_value = Decimal(str(item.get(field_name)))
                    if actual_value != expected_value:
                        raise TypeError(f"hedge position leg {field_name} is invalid")
            total_initial_margin += initial_margin
            total_maintenance += maintenance
            allocation_key = isolated_margin_key(
                track_id,
                (
                    str(item["position_side"])
                    if base["position_mode"] == "HEDGE"
                    else None
                ),
            )
            allocation = isolated.get(allocation_key, Decimal(0))
            isolated_equity = allocation + Decimal(str(position["unrealized_pnl"]))
            denominator = (
                equity if str(account["margin_mode"]) == "CROSS" else isolated_equity
            )
            raw_liquidation_price = item.get("liquidation_price")
            liquidation_price = (
                None
                if raw_liquidation_price is None
                else Decimal(str(raw_liquidation_price))
            )
            maintenance_proof = account_math_ops._maintenance_margin_proof(
                rule=rule,
                rule_revision=int(rule_row["revision"]),
                rule_hash=str(rule_row["rule_hash"]),
                rule_fidelity=str(rule_row["fidelity"]),
                position_notional=notional,
                risk_tier=risk_tier,
                liquidation_price=liquidation_price,
                absolute_quantity=abs(Decimal(str(position["quantity"]))),
            )
            maintenance_tier_extrapolated_positions += int(
                maintenance_proof["position_tier_extrapolated"] is True
            )
            liquidation_tier_extrapolated_positions += int(
                maintenance_proof["liquidation_tier_extrapolated"] is True
            )
            risk_positions.append(
                {
                    **dict(item),
                    "leverage": decimal_to_string(
                        leverage,
                        field_name="position leverage",
                    ),
                    "initial_margin": decimal_to_string(
                        initial_margin,
                        field_name="initial margin",
                    ),
                    "maintenance_margin": decimal_to_string(
                        maintenance,
                        field_name="maintenance_margin",
                    ),
                    "isolated_margin": decimal_to_string(
                        allocation,
                        field_name="isolated_margin",
                    ),
                    "isolated_allocation_key": allocation_key,
                    "account_notional": decimal_to_string(
                        notional,
                        field_name="account notional",
                    ),
                    "risk_tier": risk_tier,
                    "margin_equity": decimal_to_string(
                        denominator,
                        field_name="margin_equity",
                    ),
                    "risk_ratio": (
                        None
                        if maintenance == 0
                        else decimal_to_string(
                            denominator / maintenance,
                            field_name="risk_ratio",
                        )
                    ),
                    "rule_revision": int(rule_row["revision"]),
                    "rule_hash": str(rule_row["rule_hash"]),
                    "mark_fidelity": rule.mark_fidelity,
                    "maintenance_margin_proof": maintenance_proof,
                }
            )
        margin_used = total_initial_margin
        available = (
            equity - margin_used - reserved
            if str(account["margin_mode"]) == "CROSS"
            else equity - sum(isolated.values(), Decimal(0))
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "contract account projection is invalid",
            status_code=503,
        ) from exc
    order_count = connection.execute(
        """
        SELECT COUNT(*) AS total_count
        FROM replay_training_contract_order
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if order_count is None:
        raise TypeError("contract order count is unavailable")
    order_total = int(order_count["total_count"])
    active_order_total = len(orders)
    fill_fee_rows = (
        ()
        if live_hedge_heads
        else tuple(
            connection.execute(
                """
                SELECT configured_fee FROM replay_training_contract_fill
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchall()
        )
    )
    fill_count = (
        int(
            connection.execute(
                """
                SELECT COUNT(*) FROM replay_training_contract_fill
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        )
        if live_hedge_heads
        else len(fill_fee_rows)
    )
    fee_total = (
        live_fee_total
        if live_hedge_heads
        else sum(
            (Decimal(str(row["configured_fee"])) for row in fill_fee_rows),
            Decimal(0),
        )
    )
    active_policy = connection.execute(
        """
        SELECT policy.*, extension.policy_version,
               extension.account_tier, extension.liquidation_fee_bps,
               extension.source_kind, extension.source_id,
               extension.source_event_sequence,
               extension.component_hash AS extension_hash
        FROM replay_training_fee_policy AS policy
        LEFT JOIN replay_training_fee_policy_extension AS extension
          ON extension.run_id = policy.run_id
         AND extension.revision = policy.revision
        WHERE policy.run_id = ? ORDER BY policy.revision DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    liquidations = load_public_liquidation_cases(connection, run_id=run_id)
    archive_bindings = [
        {
            "track_id": str(row["track_id"]),
            "archive_id": str(row["archive_id"]),
            "dataset_epoch": str(row["dataset_epoch"]),
            "checksum_sha256": str(row["checksum_sha256"]),
            "proof_hash": str(row["proof_hash"]),
            "event_chain_tail": str(row["event_chain_tail"]),
            "archive_generation": int(row["archive_generation"]),
            "last_event_sequence": int(row["last_event_sequence"]),
            "as_of_actual_time_ms": int(row["as_of_actual_time_ms"]),
            "as_of_virtual_time_ms": int(row["as_of_virtual_time_ms"]),
            "mark_price": row["mark_price"],
            "index_price": row["index_price"],
            "status": str(row["status"]),
        }
        for row in connection.execute(
            """
            SELECT projection.*, ref.dataset_epoch, ref.checksum_sha256,
                   ref.event_chain_tail, archive.proof_hash
            FROM replay_account_history_projection AS projection
            JOIN replay_account_history_ref AS ref
              ON ref.run_id = projection.run_id
             AND ref.track_id = projection.track_id
             AND ref.archive_id = projection.archive_id
             AND ref.active = 1
            JOIN replay_account_history_archive AS archive
              ON archive.archive_id = projection.archive_id
            WHERE projection.run_id = ?
            ORDER BY projection.track_id
            """,
            (run_id,),
        ).fetchall()
    ]
    if position_leg_rows is None:
        position_leg_rows = tuple(
            connection.execute(
                """
                SELECT * FROM replay_training_position_leg
                WHERE run_id = ? ORDER BY track_id, position_side
                """,
                (run_id,),
            ).fetchall()
        )
    funding_counts: dict[tuple[str, str], int] = {}
    if position_leg_rows:
        funding_counts = {
            (
                str(row["track_id"]),
                str(row["position_side"]),
            ): int(row["entry_count"])
            for row in connection.execute(
                """
                SELECT track_id, position_side, COUNT(*) AS entry_count
                FROM replay_training_hedge_funding_settlement
                WHERE run_id = ? GROUP BY track_id, position_side
                """,
                (run_id,),
            ).fetchall()
        }
    leg_accounting: list[dict[str, object]] = []
    for leg in position_leg_rows:
        track_id = str(leg["track_id"])
        position_side = str(leg["position_side"])
        funding_count = funding_counts.get((track_id, position_side), 0)
        if live_hedge_heads:
            leg_accounting.append(
                {
                    "schema_version": "replay.hedge-leg-accounting-live.v1",
                    "track_id": track_id,
                    "position_side": position_side,
                    "accumulated_funding": str(leg["accumulated_funding"]),
                    "trading_fees": str(leg["trading_fees"]),
                    "liquidation_fees": str(leg["liquidation_fees"]),
                    "funding_settlement_count": funding_count,
                    "position_component_hash": str(leg["component_hash"]),
                }
            )
            continue
        matching_entries = ledger_entries_by_leg.get((track_id, position_side), [])
        fee_entries = sum(entry["kind"] == "TRADING_FEE" for entry in matching_entries)
        mutation_entries = sum(
            entry["kind"]
            in {
                "POSITION_MUTATION",
                "POSITION_ACCOUNTING_MUTATION",
                "MARGIN_MUTATION",
            }
            for entry in matching_entries
        )
        last_entry = matching_entries[-1] if matching_entries else None
        leg_accounting.append(
            {
                "schema_version": "replay.hedge-leg-accounting.v1",
                "track_id": track_id,
                "position_side": position_side,
                "accumulated_funding": str(leg["accumulated_funding"]),
                "trading_fees": str(leg["trading_fees"]),
                "liquidation_fees": str(leg["liquidation_fees"]),
                "funding_settlement_count": funding_count,
                "fee_entry_count": fee_entries,
                "mutation_entry_count": mutation_entries,
                "ledger_entry_count": len(matching_entries),
                "last_ledger_sequence": (
                    None if last_entry is None else int(last_entry["ledger_sequence"])
                ),
                "last_ledger_hash": (
                    None if last_entry is None else str(last_entry["entry_hash"])
                ),
                "position_component_hash": str(leg["component_hash"]),
            }
        )
    hedge_state_payload = (
        {}
        if live
        else {
            "schema_version": "replay.hedge-relational-state.v1",
            "position_legs": [dict(row) for row in position_leg_rows],
            "leg_accounting": leg_accounting,
            "margin_buckets": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_margin_bucket
                WHERE run_id = ? ORDER BY bucket_id
                """,
                    (run_id,),
                ).fetchall()
            ],
            "risk_snapshots": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_risk_snapshot
                WHERE run_id = ? ORDER BY snapshot_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "liquidation_leg_price_proofs": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_liquidation_leg_price_proof
                WHERE run_id = ? ORDER BY case_id, liquidation_leg_id
                """,
                    (run_id,),
                ).fetchall()
            ],
            "liquidation_book_executions": [
                public_book_execution(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_liquidation_book_execution
                WHERE run_id = ? ORDER BY case_id, step_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "liquidation_book_snapshots": [
                public_book_snapshot(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_liquidation_book_snapshot
                WHERE run_id = ? ORDER BY case_id, track_id
                """,
                    (run_id,),
                ).fetchall()
            ],
            "insurance_funds": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_insurance_fund
                WHERE run_id = ? ORDER BY asset
                """,
                    (run_id,),
                ).fetchall()
            ],
            "insurance_postings": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_insurance_posting
                WHERE run_id = ? ORDER BY asset, posting_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "adl_snapshots": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_adl_snapshot
                WHERE run_id = ? ORDER BY case_id, cohort_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "adl_candidates": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_adl_candidate
                WHERE run_id = ? ORDER BY snapshot_id, rank, candidate_id
                """,
                    (run_id,),
                ).fetchall()
            ],
            "adl_events": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_adl_event
                WHERE run_id = ? ORDER BY case_id, step_sequence, adl_event_id
                """,
                    (run_id,),
                ).fetchall()
            ],
            "adl_selections": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_adl_selection
                WHERE run_id = ? ORDER BY adl_event_id, selection_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "adl_counterparty_ledger": [
                dict(row)
                for row in connection.execute(
                    """
                SELECT * FROM replay_training_adl_counterparty_ledger
                WHERE run_id = ? ORDER BY adl_event_id, ledger_sequence
                """,
                    (run_id,),
                ).fetchall()
            ],
            "liquidation_case_hashes": [
                str(item["component_hash"]) for item in liquidations
            ],
        }
    )
    hedge_state = (
        live_hedge_state_projection(
            connection,
            run_id=run_id,
            position_leg_rows=position_leg_rows,
            leg_accounting=leg_accounting,
            liquidations=liquidations,
        )
        if live
        else {
            **hedge_state_payload,
            "state_hash": canonical_sha256(hedge_state_payload),
        }
    )
    return {
        "schema_version": CONTRACT_ACCOUNT_SCHEMA_VERSION,
        "account_model": CONTRACT_ACCOUNT_MODEL,
        "execution_model": "TOUCH_OR_TAPE_V2",
        "execution_fidelity": execution_fidelity,
        "settlement_account_shared": str(account["margin_mode"]) == "CROSS",
        "position_mode": str(base["position_mode"]),
        "margin_mode": str(account["margin_mode"]),
        "funding_mode": str(account["funding_mode"]),
        "status": str(account["status"]),
        "initial_equity": initial_equity,
        "cash_balance": decimal_to_string(cash, field_name="cash_balance"),
        "equity": decimal_to_string(equity, field_name="equity"),
        "available_equity": decimal_to_string(
            available,
            field_name="available_equity",
        ),
        "reserved_margin": decimal_to_string(
            reserved,
            field_name="reserved_margin",
        ),
        "margin_used": decimal_to_string(
            margin_used,
            field_name="margin_used",
        ),
        "maintenance_margin": decimal_to_string(
            total_maintenance,
            field_name="maintenance_margin",
        ),
        "realized_pnl": decimal_to_string(
            realized,
            field_name="realized_pnl",
        ),
        "unrealized_pnl": decimal_to_string(
            unrealized,
            field_name="unrealized_pnl",
        ),
        "fees_paid": decimal_to_string(fee_total, field_name="fees_paid"),
        "funding_cashflow": decimal_to_string(
            funding_total,
            field_name="funding_cashflow",
        ),
        "liquidation_fees_paid": decimal_to_string(
            liquidation_fee_total,
            field_name="liquidation_fees_paid",
        ),
        "risk_ratio": (
            None
            if total_maintenance == 0
            else decimal_to_string(
                equity / total_maintenance,
                field_name="risk_ratio",
            )
        ),
        "positions": risk_positions,
        "orders": orders,
        "fills": [],
        "history": {
            "orders_total": order_total,
            "active_orders": active_order_total,
            "historical_orders": order_total - active_order_total,
            "fills_total": fill_count,
            "ledger_entries_total": ledger_entry_count,
            "page_limit_max": run_records_ops._ACCOUNT_RECORD_LIMIT_MAX,
        },
        "active_fee_policy": (
            None
            if active_policy is None
            else {
                "revision": int(active_policy["revision"]),
                "effective_virtual_time_ms": int(
                    active_policy["effective_virtual_time_ms"]
                ),
                "maker_fee_bps": str(active_policy["maker_fee_bps"]),
                "taker_fee_bps": str(active_policy["taker_fee_bps"]),
                "liquidation_fee_bps": active_policy["liquidation_fee_bps"],
                "policy_version": active_policy["policy_version"],
                "account_tier": active_policy["account_tier"],
                "source_kind": active_policy["source_kind"],
                "source_id": active_policy["source_id"],
                "source_event_sequence": active_policy["source_event_sequence"],
                "extension_hash": active_policy["extension_hash"],
                "policy_hash": str(active_policy["policy_hash"]),
                "fidelity": str(active_policy["fidelity"]),
            }
        ),
        "instrument_rules": rules,
        "isolated_allocations": {
            key: decimal_to_string(value, field_name="isolated allocation")
            for key, value in sorted(isolated.items())
        },
        "next_funding_time_ms": account["next_funding_time_ms"],
        "liquidations": [
            item for item in liquidations if item["state"] != "RECOVERED_AFTER_CANCEL"
        ],
        "liquidation_recoveries": [
            item for item in liquidations if item["state"] == "RECOVERED_AFTER_CANCEL"
        ],
        "hedge_state": hedge_state,
        "hedge_inputs": hedge_inputs,
        "account_history": {
            "mode": account_data_mode,
            "status": (
                "ACTIVE" if account_history is None else str(account_history["status"])
            ),
            "fidelity": (
                "REVEALED_PRICE_PROXY_MODELLED_ACCOUNT"
                if account_history is None
                else str(account_history["fidelity"])
            ),
            "archive_proof_hash": (
                None
                if account_history is None
                else account_history["archive_proof_hash"]
            ),
            "bindings": archive_bindings,
            "auditor": {
                "status": (
                    "NOT_RUN"
                    if account_history is None
                    else str(account_history["auditor_status"])
                ),
                "proof_hash": (
                    None
                    if account_history is None
                    else account_history["auditor_proof_hash"]
                ),
                "differences": (
                    []
                    if account_history is None
                    else json.loads(str(account_history["auditor_differences_json"]))
                ),
            },
        },
        "liquidation_channels": {
            "simulated_account": {
                "label": "模拟账户强平",
                "source": "MODELLED_ACCOUNT",
                "fidelity": (
                    "HISTORICAL_EXACT_INPUTS_MODELLED_ACCOUNT"
                    if exact_account
                    else HEDGE_INSURANCE_ADL_FIDELITY
                    if account_data_mode == "DETERMINISTIC_SIMULATION"
                    else "AVAILABLE_APPROX_SIMULATED_ACCOUNT"
                ),
            },
            "historical_market": {
                "label": "历史市场爆仓",
                "source": "INDEPENDENT_MARKET_LIQUIDATION_FEED",
                "fidelity": "UNSUPPORTED_NO_HISTORY",
            },
        },
        "ledger": {
            "chain_version": "replay.training.contract-ledger.v1",
            **({"detail": "LIVE_HEAD"} if live_hedge_heads else {}),
            "entry_count": ledger_entry_count,
            "tail_hash": str(account["ledger_tail_hash"]),
            "cash_total": decimal_to_string(
                ledger_total,
                field_name="ledger_cash_total",
            ),
            "reconciliation_delta": (
                None
                if live_hedge_heads
                else decimal_to_string(
                    cash - ledger_total,
                    field_name="ledger_reconciliation_delta",
                )
            ),
            "entries": [],
        },
        "fidelity": {
            "hedge_public_history_ref": (
                None
                if run_contract["hedge_public_history_ref_json"] is None
                else json.loads(str(run_contract["hedge_public_history_ref_json"]))
            ),
            "simulation_manifest_ref": (
                None
                if run_contract["simulation_manifest_ref_json"] is None
                else json.loads(str(run_contract["simulation_manifest_ref_json"]))
            ),
            "simulation_contract_hash": run_contract["simulation_contract_hash"],
            "simulation_model_version": run_contract["simulation_model_version"],
            "account": run_contract["account_fidelity"],
            "insurance_adl": run_contract["insurance_adl_fidelity"],
            "instrument_rules": (
                "HISTORICAL_EXACT_VERSIONED_EXCHANGE_RULE"
                if exact_account
                else "PINNED_PUBLIC_HISTORY_VERSIONED_RULE"
                if account_data_mode == "DETERMINISTIC_SIMULATION"
                else "AVAILABLE_APPROX_SIMULATION_RULES"
            ),
            "maintenance_margin": (
                account_math_ops.EXTRAPOLATED_MAINTENANCE_TIER_FIDELITY
                if maintenance_tier_extrapolated_positions > 0
                else account_math_ops.VERSIONED_MAINTENANCE_TIER_FIDELITY
            ),
            "liquidation_projection": (
                account_math_ops.EXTRAPOLATED_MAINTENANCE_TIER_FIDELITY
                if liquidation_tier_extrapolated_positions > 0
                else account_math_ops.VERSIONED_MAINTENANCE_TIER_FIDELITY
            ),
            "maintenance_tier_extrapolation": {
                "applied": (
                    maintenance_tier_extrapolated_positions > 0
                    or liquidation_tier_extrapolated_positions > 0
                ),
                "position_count": maintenance_tier_extrapolated_positions,
                "liquidation_projection_count": (
                    liquidation_tier_extrapolated_positions
                ),
                "reason": (
                    "EXISTING_POSITION_OR_PROJECTED_PRICE_ABOVE_LAST_VERSIONED_TIER_CAP"
                    if maintenance_tier_extrapolated_positions > 0
                    or liquidation_tier_extrapolated_positions > 0
                    else None
                ),
                "admission_policy": "STRICT_VERSIONED_ORDER_LIMITS_UNCHANGED",
            },
            "fees": (
                "PINNED_HISTORICAL_FEE_POLICY"
                if account_data_mode == "DETERMINISTIC_SIMULATION"
                else CONFIGURED_FEE_FIDELITY
            ),
            "funding": (
                "OFF"
                if str(account["funding_mode"]) == "OFF"
                else (
                    "HISTORICAL_EXACT_ARCHIVE_FUNDING"
                    if exact_account
                    else "PINNED_HISTORICAL_FUNDING"
                    if account_data_mode == "DETERMINISTIC_SIMULATION"
                    else SANDBOX_FUNDING_FIDELITY
                )
            ),
            "mark": (
                "HISTORICAL_EXACT_ARCHIVE_MARK"
                if exact_account
                else "PINNED_PUBLIC_HISTORY_MARK"
                if account_data_mode == "DETERMINISTIC_SIMULATION"
                else "REVEALED_PRICE_PROXY_NOT_HISTORICAL_MARK"
            ),
            "liquidation": (
                "HISTORICAL_EXACT_INPUTS_MODELLED_ACCOUNT"
                if exact_account
                else HEDGE_INSURANCE_ADL_FIDELITY
                if account_data_mode == "DETERMINISTIC_SIMULATION"
                else "AVAILABLE_APPROX_SIMULATED_ACCOUNT"
            ),
            "liquidation_execution": (
                HISTORICAL_L2_LIQUIDATION_FIDELITY
                if run_contract["book_mode"] == "BOOK_ASSISTED_REQUIRED"
                else account_math_ops.TOUCH_OR_TAPE_LIQUIDATION_FIDELITY
            ),
        },
    }


def assert_run_segments_ready(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    operation: str,
) -> None:
    unavailable = connection.execute(
        """
        SELECT s.segment_id, s.health
        FROM replay_data_segment_ref AS r
        JOIN replay_data_segment AS s USING(segment_id)
        WHERE r.run_id = ? AND r.owner_kind = 'RUN_ARCHIVE'
          AND s.health != 'READY'
        ORDER BY s.segment_id LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if unavailable is not None:
        raise TrainingRunError(
            "SEGMENT_NOT_READY",
            f"replay data segment must be ready before {operation}",
            status_code=409,
            details={
                "segment_id": str(unavailable["segment_id"]),
                "health": str(unavailable["health"]),
            },
        )


def contract_portfolio_checkpoint_commitment(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    initial_equity: str,
    tracks: list[dict[str, object]],
) -> dict[str, object]:
    """Commit current account heads without replaying immutable audit history."""

    account = connection.execute(
        """
        SELECT account_model, margin_mode, funding_mode, fixed_funding_rate,
               funding_interval_ms, next_funding_time_ms, overlay_cash,
               isolated_margin_json, status, fidelity, ledger_tail_hash
        FROM replay_training_contract_account WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        projection = portfolio_projection(
            initial_equity=initial_equity,
            tracks=tracks,
        )
        payload = {
            "schema_version": "replay.training.portfolio-checkpoint-head.v1",
            "account_model": (
                None if account is None else str(account["account_model"])
            ),
            "projection_hash": canonical_sha256(projection),
        }
        return {**payload, "commitment_hash": canonical_sha256(payload)}

    try:
        isolated_margin = json.loads(str(account["isolated_margin_json"]))
    except json.JSONDecodeError as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "contract account isolated margin JSON is invalid",
            status_code=503,
        ) from exc
    if not isinstance(isolated_margin, dict):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "contract account isolated margin JSON is invalid",
            status_code=503,
        )

    active_orders: list[dict[str, object]] = []
    for row in connection.execute(
        """
        SELECT track_id, order_id, order_json, rule_revision
        FROM replay_training_contract_order
        WHERE run_id = ?
          AND json_extract(order_json, '$.status')
              IN ('OPEN', 'PARTIALLY_FILLED')
        ORDER BY track_id, order_id
        """,
        (run_id,),
    ).fetchall():
        try:
            order = json.loads(str(row["order_json"]))
        except json.JSONDecodeError as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "contract order JSON is invalid",
                status_code=503,
            ) from exc
        if not isinstance(order, dict):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "contract order JSON is invalid",
                status_code=503,
            )
        order_head = {
            "track_id": str(row["track_id"]),
            "order_id": str(row["order_id"]),
            "rule_revision": int(row["rule_revision"]),
            "order": order,
        }
        active_orders.append(
            {
                "track_id": order_head["track_id"],
                "order_id": order_head["order_id"],
                "component_hash": canonical_sha256(order_head),
            }
        )

    component_rows = connection.execute(
        """
        SELECT component_kind, component_id, revision, component_hash
        FROM (
            SELECT 'POSITION_LEG' AS component_kind,
                   track_id || ':' || position_side AS component_id,
                   component_revision AS revision,
                   component_hash
            FROM replay_training_position_leg WHERE run_id = ?
            UNION ALL
            SELECT 'MARGIN_BUCKET', bucket_id, component_revision,
                   component_hash
            FROM replay_training_margin_bucket WHERE run_id = ?
            UNION ALL
            SELECT 'HEDGE_INPUT', source_kind, last_event_sequence,
                   component_hash
            FROM replay_hedge_input_projection WHERE run_id = ?
            UNION ALL
            SELECT 'TRACK_PUBLIC_INPUT', track_id, last_event_sequence,
                   component_hash
            FROM replay_hedge_track_public_projection WHERE run_id = ?
            UNION ALL
            SELECT 'INSURANCE_FUND', asset, revision, ledger_tail_hash
            FROM replay_training_insurance_fund WHERE run_id = ?
            UNION ALL
            SELECT 'RISK_SNAPSHOT', snapshot_id, snapshot_sequence,
                   component_hash
            FROM replay_training_risk_snapshot
            WHERE run_id = ? AND snapshot_sequence = (
                SELECT MAX(snapshot_sequence)
                FROM replay_training_risk_snapshot WHERE run_id = ?
            )
            UNION ALL
            SELECT 'LIQUIDATION_CASE', case_id, case_sequence,
                   component_hash
            FROM replay_training_liquidation_case
            WHERE run_id = ? AND state NOT IN (
                'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED',
                'RECOVERED_AFTER_CANCEL'
            )
            UNION ALL
            SELECT 'HISTORICAL_BOOK', track_id,
                   COALESCE(last_update_id, 0), book_hash
            FROM replay_historical_book_projection WHERE run_id = ?
        )
        ORDER BY component_kind, component_id
        """,
        (run_id,) * 9,
    ).fetchall()
    components = [
        {
            "kind": str(row["component_kind"]),
            "id": str(row["component_id"]),
            "revision": int(row["revision"]),
            "hash": row["component_hash"],
        }
        for row in component_rows
    ]

    rule_heads = [
        {
            "track_id": str(row["track_id"]),
            "revision": int(row["revision"]),
            "rule_hash": str(row["rule_hash"]),
        }
        for row in connection.execute(
            """
            SELECT rule.track_id, rule.revision, rule.rule_hash
            FROM replay_training_instrument_rule AS rule
            JOIN (
                SELECT track_id, MAX(revision) AS revision
                FROM replay_training_instrument_rule
                WHERE run_id = ? GROUP BY track_id
            ) AS latest
              ON latest.track_id = rule.track_id
             AND latest.revision = rule.revision
            WHERE rule.run_id = ? ORDER BY rule.track_id
            """,
            (run_id, run_id),
        ).fetchall()
    ]
    fee_policy = connection.execute(
        """
        SELECT policy.revision, policy.policy_hash, extension.component_hash
        FROM replay_training_fee_policy AS policy
        LEFT JOIN replay_training_fee_policy_extension AS extension
          ON extension.run_id = policy.run_id
         AND extension.revision = policy.revision
        WHERE policy.run_id = ? ORDER BY policy.revision DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    payload = {
        "schema_version": "replay.training.portfolio-checkpoint-head.v1",
        "account": {
            "account_model": str(account["account_model"]),
            "margin_mode": str(account["margin_mode"]),
            "funding_mode": str(account["funding_mode"]),
            "fixed_funding_rate": account["fixed_funding_rate"],
            "funding_interval_ms": account["funding_interval_ms"],
            "next_funding_time_ms": account["next_funding_time_ms"],
            "overlay_cash": str(account["overlay_cash"]),
            "isolated_margin": isolated_margin,
            "status": str(account["status"]),
            "fidelity": str(account["fidelity"]),
            "ledger_tail_hash": str(account["ledger_tail_hash"]),
        },
        "active_orders": active_orders,
        "components": components,
        "instrument_rules": rule_heads,
        "fee_policy": (
            None
            if fee_policy is None
            else {
                "revision": int(fee_policy["revision"]),
                "policy_hash": str(fee_policy["policy_hash"]),
                "extension_hash": fee_policy["component_hash"],
            }
        ),
    }
    return {**payload, "commitment_hash": canonical_sha256(payload)}


def insert_global_checkpoint(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
    materialize_portfolio: bool = True,
) -> dict[str, object]:
    assert_run_segments_ready(
        connection,
        run_id=run_id,
        operation="checkpoint",
    )
    rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_market_track
            WHERE run_id = ? AND subscription_tier = 'FULL'
            ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    )
    if not rows:
        raise TrainingRunError(
            "GLOBAL_CLOCK_UNAVAILABLE",
            "TrainingRun has no FULL market track",
            status_code=409,
        )
    tracks = [market_track_from_row(row) for row in rows]
    run = connection.execute(
        "SELECT initial_equity FROM replay_training_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise TrainingRunError(
            "TRAINING_RUN_NOT_FOUND",
            "training run does not exist",
            status_code=404,
        )
    portfolio = (
        contract_portfolio_projection(
            connection,
            run_id=run_id,
            initial_equity=str(run["initial_equity"]),
            tracks=tracks,
        )
        if materialize_portfolio
        else None
    )
    portfolio_commitment = (
        None
        if materialize_portfolio
        else contract_portfolio_checkpoint_commitment(
            connection,
            run_id=run_id,
            initial_equity=str(run["initial_equity"]),
            tracks=tracks,
        )
    )
    if any(not isinstance(track.get("cursor"), Mapping) for track in tracks):
        raise TrainingRunError(
            "GLOBAL_CLOCK_DIVERGED",
            "FULL market track cursor is unavailable",
            status_code=409,
        )
    cursor_times = {
        int(track["cursor"]["virtual_time_ms"])  # type: ignore[index]
        for track in tracks
    }
    if len(cursor_times) != 1:
        raise TrainingRunError(
            "GLOBAL_CLOCK_DIVERGED",
            "FULL market tracks do not share one VirtualTime",
            status_code=409,
        )
    virtual_time_ms = next(iter(cursor_times))
    tail = connection.execute(
        """
        SELECT global_sequence AS sequence, ordering_hash
        FROM replay_training_global_event
        WHERE run_id = ? ORDER BY global_sequence DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    checkpoint_row = connection.execute(
        """
        SELECT checkpoint_sequence, global_state_hash
        FROM replay_training_global_checkpoint
        WHERE run_id = ? ORDER BY checkpoint_sequence DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    checkpoint_sequence = (
        1 if checkpoint_row is None else int(checkpoint_row["checkpoint_sequence"]) + 1
    )
    global_event_sequence = 0 if tail is None else int(tail["sequence"])
    state: dict[str, object] = {
        "ordering_version": GLOBAL_ORDERING_VERSION,
        "global_event_sequence": global_event_sequence,
        "global_virtual_time_ms": virtual_time_ms,
        "tracks": tracks,
    }
    if materialize_portfolio:
        state["portfolio"] = portfolio
        checkpoint_schema_version = "replay.training.global-checkpoint.v1"
        stored_payload: dict[str, object] = {
            "tracks": tracks,
            "portfolio": portfolio,
        }
    else:
        state.update(
            {
                "global_event_tail_hash": (
                    None if tail is None else str(tail["ordering_hash"])
                ),
                "previous_global_state_hash": (
                    None
                    if checkpoint_row is None
                    else str(checkpoint_row["global_state_hash"])
                ),
                "portfolio_commitment": portfolio_commitment,
            }
        )
        checkpoint_schema_version = "replay.training.global-checkpoint.v2"
        stored_payload = {
            "schema_version": checkpoint_schema_version,
            "tracks": tracks,
            "global_event_sequence": global_event_sequence,
            "global_event_tail_hash": state["global_event_tail_hash"],
            "previous_global_state_hash": state["previous_global_state_hash"],
            "portfolio_commitment": portfolio_commitment,
        }
    state_hash = canonical_sha256(
        {
            "schema_version": checkpoint_schema_version,
            "state": state,
        }
    )
    connection.execute(
        """
        INSERT INTO replay_training_global_checkpoint(
            run_id, checkpoint_sequence, ordering_version,
            global_virtual_time_ms, global_state_hash, tracks_json,
            created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            checkpoint_sequence,
            GLOBAL_ORDERING_VERSION,
            virtual_time_ms,
            state_hash,
            canonical_json(stored_payload),
            now_ms,
        ),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO replay_data_segment_ref(
            segment_id, run_id, track_id, owner_kind, owner_id,
            active, created_at_ms, released_at_ms
        )
        SELECT segment_id, run_id, track_id, 'CHECKPOINT',
               'latest-global-checkpoint', 0, ?, ?
        FROM replay_data_segment_ref
        WHERE run_id = ? AND owner_kind = 'RUN_ARCHIVE'
        ON CONFLICT(segment_id, run_id, owner_kind, owner_id) DO UPDATE SET
            active = 0,
            released_at_ms = excluded.released_at_ms
        """,
        (now_ms, now_ms, run_id),
    )
    connection.execute(
        """
        UPDATE replay_training_run
        SET virtual_time_ms = ?, saved_at_ms = ?, updated_at_ms = ?
        WHERE run_id = ?
        """,
        (virtual_time_ms, now_ms, now_ms, run_id),
    )
    result = {
        "checkpoint_sequence": checkpoint_sequence,
        "global_virtual_time_ms": virtual_time_ms,
        "global_state_hash": state_hash,
    }
    if materialize_portfolio:
        result["portfolio"] = portfolio
    else:
        result["portfolio_commitment"] = portfolio_commitment
    return result
