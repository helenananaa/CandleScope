"""Liquidation operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import cast

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    CONTRACT_ACCOUNT_MODEL,
    InstrumentRule,
    isolated_margin_key,
    ledger_chain_hash,
    round_to_step,
)
from ..errors import TrainingRunError
from ..hedge_simulation_contract import (
    LIQUIDATION_FORMULA_VERSION,
)
from ..historical_book import (
    HISTORICAL_L2_LIQUIDATION_FIDELITY,
)
from ..phase_projection import load_track_rules
from . import account_marks as account_marks_ops
from . import account_math as account_math_ops
from . import ledger as ledger_ops


def append_insurance_posting(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    asset: str,
    case_id: str,
    step_sequence: int,
    cash_delta: Decimal,
    reason: str,
    now_ms: int,
) -> str:
    fund = connection.execute(
        """
        SELECT * FROM replay_training_insurance_fund
        WHERE run_id = ? AND asset = ?
        """,
        (run_id, asset),
    ).fetchone()
    if fund is None:
        raise TrainingRunError(
            "LIQUIDATION_SIMULATION_INPUT_MISSING",
            "insurance fund simulation state is unavailable",
            status_code=409,
        )
    current = Decimal(str(fund["current_balance"]))
    balance_after = current + cash_delta
    if balance_after < 0:
        raise TrainingRunError(
            "LIQUIDATION_INSURANCE_OVERDRAFT",
            "insurance fund posting would overdraw the pinned simulation balance",
            status_code=409,
        )
    sequence = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(posting_sequence), 0) + 1
            FROM replay_training_insurance_posting
            WHERE run_id = ? AND asset = ?
            """,
            (run_id, asset),
        ).fetchone()[0]
    )
    posting_id = f"insurance:{case_id}:{step_sequence}:{reason.lower()}"
    previous_hash = str(fund["ledger_tail_hash"])
    payload = {
        "posting_id": posting_id,
        "case_id": case_id,
        "step_sequence": step_sequence,
        "cash_delta": decimal_to_string(cash_delta, field_name="insurance cash delta"),
        "balance_after": decimal_to_string(
            balance_after, field_name="insurance balance"
        ),
        "reason": reason,
    }
    posting_hash = ledger_chain_hash(
        previous_hash=previous_hash,
        ledger_sequence=sequence,
        posting=payload,
    )
    connection.execute(
        """
        INSERT INTO replay_training_insurance_posting(
            run_id, asset, posting_sequence, posting_id, case_id,
            step_sequence, cash_delta, balance_after, reason,
            previous_hash, posting_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            asset,
            sequence,
            posting_id,
            case_id,
            step_sequence,
            payload["cash_delta"],
            payload["balance_after"],
            reason,
            previous_hash,
            posting_hash,
            now_ms,
        ),
    )
    connection.execute(
        """
        UPDATE replay_training_insurance_fund
        SET current_balance = ?, ledger_tail_hash = ?, revision = revision + 1,
            updated_at_ms = ?
        WHERE run_id = ? AND asset = ?
        """,
        (payload["balance_after"], posting_hash, now_ms, run_id, asset),
    )
    return posting_hash


def liquidation_risk_state(
    connection: sqlite3.Connection,
    *,
    run_id: str,
) -> dict[str, object]:
    account = connection.execute(
        """
        SELECT account.*, run.initial_equity, run.settlement_asset,
               run.position_mode, run.book_mode
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None:
        raise TypeError("liquidation account is missing")
    initial = Decimal(str(account["initial_equity"]))
    equity = initial + Decimal(str(account["overlay_cash"]))
    track_rows = tuple(
        connection.execute(
            """
            SELECT track_id, stable_ordinal, account_json, open_orders_json,
                   position_json, virtual_time_ms, source_sequence, symbol,
                   adapter_session_id
            FROM replay_training_market_track
            WHERE run_id = ? AND subscription_tier = 'FULL'
            ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    )
    tracks = {str(row["track_id"]): row for row in track_rows}
    reserved = Decimal(0)
    for track in track_rows:
        raw_account = json.loads(str(track["account_json"]))
        if isinstance(raw_account, Mapping) and raw_account.get("equity") is not None:
            equity += Decimal(str(raw_account["equity"])) - initial
        raw_orders = json.loads(str(track["open_orders_json"]))
        if not isinstance(raw_orders, list):
            raise TypeError("liquidation open-order projection is invalid")
        reserved += sum(
            (
                Decimal(str(order.get("reserved_margin", "0")))
                for order in raw_orders
                if isinstance(order, Mapping)
                and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                and order.get("reduce_only") is not True
            ),
            Decimal(0),
        )
    leg_rows = tuple(
        connection.execute(
            """
            SELECT leg.*, rule.rule_json
            FROM replay_training_position_leg AS leg
            JOIN replay_training_instrument_rule AS rule
              ON rule.run_id = leg.run_id
             AND rule.track_id = leg.track_id
             AND rule.revision = leg.rule_revision
            WHERE leg.run_id = ?
            ORDER BY leg.track_id, leg.position_side
            """,
            (run_id,),
        ).fetchall()
    )
    isolated = json.loads(str(account["isolated_margin_json"]))
    if not isinstance(isolated, dict):
        raise TypeError("liquidation isolated margin projection is invalid")
    total_initial = Decimal(0)
    total_maintenance = Decimal(0)
    active_legs: list[dict[str, object]] = []
    for row in leg_rows:
        quantity = Decimal(str(row["absolute_quantity"]))
        track_id = str(row["track_id"])
        track = tracks.get(track_id)
        if track is None:
            raise TypeError("liquidation leg lost its FULL market track")
        current_position = json.loads(str(track["position_json"]))
        if not isinstance(current_position, Mapping):
            raise TypeError("liquidation position projection is invalid")
        if current_position.get("position_mode") == "HEDGE":
            current_leg = current_position.get(str(row["position_side"]).lower())
            current_quantity = (
                abs(Decimal(str(current_leg.get("quantity", "0"))))
                if isinstance(current_leg, Mapping)
                else Decimal(0)
            )
        else:
            current_quantity = abs(Decimal(str(current_position.get("quantity", "0"))))
        if quantity <= 0 or current_quantity <= 0:
            continue
        rule = InstrumentRule.from_mapping(json.loads(str(row["rule_json"])))
        initial_margin = Decimal(str(row["initial_margin"]))
        maintenance = Decimal(str(row["maintenance_margin"]))
        total_initial += initial_margin
        total_maintenance += maintenance
        isolated_equity = Decimal(str(row["isolated_wallet"])) + Decimal(
            str(row["unrealized_pnl"])
        )
        active_legs.append(
            {
                **dict(row),
                "rule": rule,
                "track": track,
                "isolated_equity": isolated_equity,
            }
        )
    cross_breached = bool(active_legs) and equity <= total_maintenance + reserved
    affected = (
        list(active_legs)
        if str(account["margin_mode"]) == "CROSS" and cross_breached
        else [
            leg
            for leg in active_legs
            if str(account["margin_mode"]) == "ISOLATED"
            and Decimal(str(leg["isolated_equity"]))
            <= Decimal(str(leg["maintenance_margin"]))
        ]
    )
    return {
        "account": account,
        "equity": equity,
        "available_balance": equity - total_initial - reserved,
        "total_initial_margin": total_initial,
        "total_maintenance_margin": total_maintenance,
        "reserved_margin": reserved,
        "active_legs": active_legs,
        "affected_legs": affected,
        "breached": bool(affected),
    }


def capture_liquidation_risk_snapshot(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    step_sequence: int,
    label: str,
    account_status: str,
    now_ms: int,
) -> tuple[str, dict[str, object]]:
    snapshot_id = f"risk-{case_id}-{step_sequence:03d}-{label.lower()}"
    existing = connection.execute(
        """
        SELECT * FROM replay_training_risk_snapshot
        WHERE run_id = ? AND snapshot_id = ?
        """,
        (run_id, snapshot_id),
    ).fetchone()
    risk = liquidation_risk_state(connection, run_id=run_id)
    if existing is not None:
        return snapshot_id, risk
    active_legs = cast(list[dict[str, object]], risk["active_legs"])
    trigger_time = max(
        (
            int(cast(sqlite3.Row, leg["track"])["virtual_time_ms"] or 0)
            for leg in active_legs
        ),
        default=0,
    )
    source_sequence = max(
        (
            int(cast(sqlite3.Row, leg["track"])["source_sequence"] or 0)
            for leg in active_legs
        ),
        default=0,
    )
    rule_revision = max(
        (int(leg["rule_revision"]) for leg in active_legs),
        default=1,
    )
    snapshot_sequence = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(snapshot_sequence), 0) + 1
            FROM replay_training_risk_snapshot WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]
    )
    equity = cast(Decimal, risk["equity"])
    maintenance = cast(Decimal, risk["total_maintenance_margin"])
    input_rows = tuple(
        connection.execute(
            """
            SELECT source_kind, input_chain_hash
            FROM replay_hedge_input_projection
            WHERE run_id = ? ORDER BY source_kind
            """,
            (run_id,),
        ).fetchall()
    )
    stored_account_status = (
        account_status
        if account_status
        in {
            "ACTIVE",
            "RISK_BREACH_DETECTED",
            "LIQUIDATING",
            "BANKRUPT",
            "FAILED_CLOSED",
        }
        else "LIQUIDATING"
    )
    payload = {
        "schema_version": "replay.risk-snapshot.v2",
        "snapshot_id": snapshot_id,
        "case_id": case_id,
        "step_sequence": step_sequence,
        "label": label,
        "account_status": stored_account_status,
        "liquidation_state": account_status,
        "equity": decimal_to_string(equity, field_name="liquidation equity"),
        "available_balance": decimal_to_string(
            cast(Decimal, risk["available_balance"]),
            field_name="liquidation available balance",
        ),
        "total_initial_margin": decimal_to_string(
            cast(Decimal, risk["total_initial_margin"]),
            field_name="liquidation total initial margin",
        ),
        "total_maintenance_margin": decimal_to_string(
            maintenance,
            field_name="liquidation total maintenance margin",
        ),
        "position_hashes": [str(leg["component_hash"]) for leg in active_legs],
        "input_chain_hashes": [
            {
                "source_kind": str(row["source_kind"]),
                "hash": str(row["input_chain_hash"]),
            }
            for row in input_rows
        ],
    }
    connection.execute(
        """
        INSERT INTO replay_training_risk_snapshot(
            run_id, snapshot_id, snapshot_sequence, virtual_time_ms,
            source_sequence, account_status, equity, available_balance,
            total_initial_margin, total_maintenance_margin, risk_ratio,
            active_rule_revision, public_input_hash, component_hash,
            created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            snapshot_id,
            snapshot_sequence,
            trigger_time,
            source_sequence,
            stored_account_status,
            payload["equity"],
            payload["available_balance"],
            payload["total_initial_margin"],
            payload["total_maintenance_margin"],
            (
                None
                if maintenance == 0
                else decimal_to_string(equity / maintenance, field_name="risk ratio")
            ),
            rule_revision,
            canonical_sha256(payload["input_chain_hashes"]),
            canonical_sha256(payload),
            now_ms,
        ),
    )
    return snapshot_id, risk


def insert_liquidation_step(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    step_type: str,
    before_snapshot_id: str,
    plan: Mapping[str, object],
    now_ms: int,
) -> int:
    sequence = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(step_sequence), 0) + 1
            FROM replay_training_liquidation_step
            WHERE run_id = ? AND case_id = ?
            """,
            (run_id, case_id),
        ).fetchone()[0]
    )
    reason = canonical_json({"cause": "MAINTENANCE_MARGIN_BREACH", "plan": dict(plan)})
    payload = {
        "schema_version": "replay.liquidation-step.v2",
        "case_id": case_id,
        "step_sequence": sequence,
        "step_type": step_type,
        "before_snapshot_id": before_snapshot_id,
        "reason": reason,
    }
    connection.execute(
        """
        INSERT INTO replay_training_liquidation_step(
            run_id, case_id, step_sequence, step_type, state,
            before_snapshot_id, after_snapshot_id, reason,
            idempotency_key, step_hash, created_at_ms, committed_at_ms
        ) VALUES (?, ?, ?, ?, 'PENDING', ?, NULL, ?, ?, ?, ?, NULL)
        """,
        (
            run_id,
            case_id,
            sequence,
            step_type,
            before_snapshot_id,
            reason,
            f"{case_id}:{sequence}:{step_type}",
            canonical_sha256(payload),
            now_ms,
        ),
    )
    return sequence


def next_liquidation_trade_plan(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    require_breach: bool = True,
) -> tuple[str, dict[str, object]] | None:
    risk = liquidation_risk_state(connection, run_id=run_id)
    if require_breach and not bool(risk["breached"]):
        return None
    case_legs = {
        (str(row["track_id"]), str(row["position_side"])): row
        for row in connection.execute(
            """
            SELECT * FROM replay_training_liquidation_leg
            WHERE run_id = ? AND case_id = ?
            """,
            (run_id, case_id),
        ).fetchall()
    }
    risk_legs = (
        cast(list[dict[str, object]], risk["affected_legs"])
        if bool(risk["breached"])
        else cast(list[dict[str, object]], risk["active_legs"])
    )
    candidates = [
        leg
        for leg in risk_legs
        if (str(leg["track_id"]), str(leg["position_side"])) in case_legs
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda leg: (
            -Decimal(str(leg["maintenance_margin"])),
            -Decimal(str(leg["notional"])),
            str(leg["track_id"]),
            0 if str(leg["position_side"]) == "LONG" else 1,
        )
    )
    leg = candidates[0]
    rule = cast(InstrumentRule, leg["rule"])
    quantity = Decimal(str(leg["absolute_quantity"]))
    mark = Decimal(str(leg["mark_price"]))
    notional = Decimal(str(leg["notional"]))
    tier_index, _tier = rule.active_maintenance_tier(
        notional,
        extend_last_tier=True,
    )
    close_quantity = quantity
    step_type = "FULL_LIQUIDATION"
    if require_breach and tier_index > 1:
        previous_cap = Decimal(rule.maintenance_tiers[tier_index - 2].notional_cap)
        target_quantity = previous_cap / (mark * Decimal(rule.contract_size))
        raw_close = max(Decimal(0), quantity - target_quantity)
        close_quantity = min(
            quantity,
            round_to_step(raw_close, Decimal(rule.quantity_step), upward=True),
        )
        if close_quantity > 0 and close_quantity < quantity:
            step_type = "PARTIAL_LIQUIDATION"
    if close_quantity <= 0:
        raise TrainingRunError(
            "LIQUIDATION_PLAN_INVALID",
            "liquidation tier step produced a non-positive close quantity",
            status_code=409,
        )
    case_leg = case_legs[(str(leg["track_id"]), str(leg["position_side"]))]
    plan: dict[str, object] = {
        "liquidation_leg_id": str(case_leg["liquidation_leg_id"]),
        "track_id": str(leg["track_id"]),
        "adapter_session_id": str(
            cast(sqlite3.Row, leg["track"])["adapter_session_id"]
        ),
        "position_side": str(leg["position_side"]),
        "position_mode": str(cast(sqlite3.Row, risk["account"])["position_mode"]),
        "side": "SELL" if str(leg["position_side"]) == "LONG" else "BUY",
        "quantity": decimal_to_string(
            close_quantity, field_name="liquidation close quantity"
        ),
        "rule_revision": int(leg["rule_revision"]),
        "quantity_step": rule.quantity_step,
        "quote_step": rule.quote_step,
        "contract_size": rule.contract_size,
        "liquidation_fee_bps": rule.liquidation_fee_bps,
        "tier_before": tier_index,
        "target": "PREVIOUS_TIER_CAP" if step_type == "PARTIAL_LIQUIDATION" else "ZERO",
    }
    risk_account = cast(sqlite3.Row, risk["account"])
    if str(risk_account["position_mode"]) == "HEDGE":
        if str(risk_account["book_mode"]) == "BOOK_ASSISTED_REQUIRED":
            plan["execution_model"] = HISTORICAL_L2_LIQUIDATION_FIDELITY
            plan["book_execution"] = historical_book_liquidation_plan(
                connection,
                run_id=run_id,
                case_id=case_id,
                track_id=str(leg["track_id"]),
                side=str(plan["side"]),
                quantity=close_quantity,
                price_tick=Decimal(rule.price_tick),
                quantity_step=Decimal(rule.quantity_step),
            )
        else:
            plan["execution_model"] = (
                account_math_ops.TOUCH_OR_TAPE_LIQUIDATION_FIDELITY
            )
            price_proof = connection.execute(
                """
                SELECT mark_price
                FROM replay_training_liquidation_leg_price_proof
                WHERE run_id = ? AND case_id = ? AND liquidation_leg_id = ?
                """,
                (run_id, case_id, plan["liquidation_leg_id"]),
            ).fetchone()
            if price_proof is None:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "no-book liquidation lost its frozen revealed mark proof",
                    status_code=409,
                )
            reference_mark = Decimal(str(price_proof["mark_price"]))
            broker_row = connection.execute(
                """
                SELECT broker_config_json FROM replay_session
                WHERE session_id = ?
                """,
                (plan["adapter_session_id"],),
            ).fetchone()
            if broker_row is None:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "no-book liquidation lost its pinned broker execution policy",
                    status_code=409,
                )
            broker_config = json.loads(str(broker_row["broker_config_json"]))
            if not isinstance(broker_config, Mapping):
                raise TypeError("no-book broker execution policy is invalid")
            market_slippage_bps = Decimal(str(broker_config["market_slippage_bps"]))
            if not market_slippage_bps.is_finite() or market_slippage_bps < 0:
                raise TypeError("no-book market slippage policy is invalid")
            slipped = reference_mark * (
                Decimal(1)
                + market_slippage_bps
                / Decimal(10_000)
                * (Decimal(1) if str(plan["side"]) == "BUY" else Decimal(-1))
            )
            if slipped <= 0:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "no-book adverse slippage produced a non-positive execution price",
                    status_code=409,
                )
            execution_price = round_to_step(
                slipped,
                Decimal(rule.price_tick),
                upward=str(plan["side"]) == "BUY",
            )
            plan["reference_mark"] = decimal_to_string(
                reference_mark,
                field_name="liquidation revealed reference mark",
            )
            plan["market_slippage_bps"] = decimal_to_string(
                market_slippage_bps,
                field_name="liquidation market slippage bps",
            )
            plan["price_tick"] = rule.price_tick
            plan["execution_price"] = decimal_to_string(
                execution_price,
                field_name="liquidation no-book execution price",
            )
    return step_type, plan


def historical_book_liquidation_plan(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    track_id: str,
    side: str,
    quantity: Decimal,
    price_tick: Decimal,
    quantity_step: Decimal,
) -> dict[str, object]:
    run = connection.execute(
        "SELECT book_mode FROM replay_training_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    case = connection.execute(
        """
        SELECT trigger_virtual_time_ms FROM replay_training_liquidation_case
        WHERE run_id = ? AND case_id = ?
        """,
        (run_id, case_id),
    ).fetchone()
    projection = connection.execute(
        """
        SELECT snapshot.*, archive.health AS archive_health
        FROM replay_training_liquidation_book_snapshot AS snapshot
        JOIN replay_historical_book_archive AS archive
          ON archive.archive_id = snapshot.archive_id
        WHERE snapshot.run_id = ? AND snapshot.case_id = ?
          AND snapshot.track_id = ?
          AND EXISTS (
              SELECT 1 FROM replay_historical_book_ref AS ref
              WHERE ref.run_id = snapshot.run_id
                AND ref.track_id = snapshot.track_id
                AND ref.archive_id = snapshot.archive_id
                AND ref.active = 1
          )
        """,
        (run_id, case_id, track_id),
    ).fetchone()
    if (
        run is None
        or str(run["book_mode"]) != "BOOK_ASSISTED_REQUIRED"
        or case is None
        or projection is None
        or str(projection["archive_health"]) != "READY"
        or int(projection["queue_exact"]) != 0
        or int(projection["as_of_virtual_time_ms"])
        != int(case["trigger_virtual_time_ms"])
    ):
        raise TrainingRunError(
            "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
            "an exact current historical L2 projection is required for HEDGE liquidation",
            status_code=409,
        )
    snapshot_payload = {
        "schema_version": "replay.liquidation-book-snapshot.v1",
        "case_id": case_id,
        "track_id": track_id,
        "archive_id": str(projection["archive_id"]),
        "as_of_actual_time_ms": int(projection["as_of_actual_time_ms"]),
        "as_of_virtual_time_ms": int(projection["as_of_virtual_time_ms"]),
        "last_update_id": int(projection["last_update_id"]),
        "bids": json.loads(str(projection["bids_json"])),
        "asks": json.loads(str(projection["asks_json"])),
        "book_hash": str(projection["book_hash"]),
        "execution_fidelity": str(projection["execution_fidelity"]),
        "queue_exact": False,
    }
    if str(
        projection["execution_fidelity"]
    ) != HISTORICAL_L2_LIQUIDATION_FIDELITY or canonical_sha256(
        snapshot_payload
    ) != str(projection["snapshot_hash"]):
        raise TrainingRunError(
            "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
            "frozen liquidation historical L2 snapshot hash verification failed",
            status_code=409,
        )
    raw_levels = json.loads(
        str(projection["bids_json"] if side == "SELL" else projection["asks_json"])
    )
    if not isinstance(raw_levels, list) or not raw_levels:
        raise TrainingRunError(
            "HISTORICAL_BOOK_DEPTH_EXHAUSTED",
            "historical L2 has no visible depth on the liquidation side",
            status_code=409,
        )
    normalized: list[tuple[int, Decimal, Decimal]] = []
    previous_price: Decimal | None = None
    for level_index, raw_level in enumerate(raw_levels, start=1):
        if (
            not isinstance(raw_level, list)
            or len(raw_level) != 2
            or isinstance(raw_level[0], bool)
            or isinstance(raw_level[1], bool)
        ):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "historical L2 contains an invalid visible level",
                status_code=409,
            )
        try:
            price = Decimal(str(raw_level[0]))
            level_quantity = Decimal(str(raw_level[1]))
        except InvalidOperation as exc:
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "historical L2 contains a non-decimal visible level",
                status_code=409,
            ) from exc
        if (
            price <= 0
            or level_quantity <= 0
            or not price.is_finite()
            or not level_quantity.is_finite()
        ):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "historical L2 contains a non-positive visible level",
                status_code=409,
            )
        if price_tick <= 0 or price % price_tick != 0:
            raise TrainingRunError(
                "HISTORICAL_BOOK_PRICE_FILTER_CONFLICT",
                "historical L2 price conflicts with the pinned instrument price tick",
                status_code=409,
            )
        if quantity_step <= 0 or level_quantity % quantity_step != 0:
            raise TrainingRunError(
                "HISTORICAL_BOOK_QUANTITY_FILTER_CONFLICT",
                "historical L2 quantity conflicts with the pinned instrument quantity step",
                status_code=409,
            )
        if previous_price is not None and (
            (side == "SELL" and price >= previous_price)
            or (side == "BUY" and price <= previous_price)
        ):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "historical L2 visible levels are not in adverse execution order",
                status_code=409,
            )
        previous_price = price
        normalized.append((level_index, price, level_quantity))

    expected_hash = canonical_sha256(
        {
            "archive_id": str(projection["archive_id"]),
            "actual_time_ms": int(projection["as_of_actual_time_ms"]),
            "last_update_id": int(projection["last_update_id"]),
            "bids": json.loads(str(projection["bids_json"])),
            "asks": json.loads(str(projection["asks_json"])),
        }
    )
    if expected_hash != str(projection["book_hash"]):
        raise TrainingRunError(
            "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
            "historical L2 projection hash verification failed",
            status_code=409,
        )

    consumed: dict[int, Decimal] = {}
    prior_rows = connection.execute(
        """
        SELECT proof.step_sequence, proof.levels_json
        FROM replay_training_liquidation_book_execution AS proof
        WHERE proof.run_id = ? AND proof.case_id = ? AND proof.track_id = ?
          AND proof.side = ? AND proof.book_hash = ?
        ORDER BY proof.step_sequence
        """,
        (run_id, case_id, track_id, side, projection["book_hash"]),
    ).fetchall()
    for prior in prior_rows:
        prior_levels = json.loads(str(prior["levels_json"]))
        if not isinstance(prior_levels, list):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "prior historical L2 liquidation proof is invalid",
                status_code=409,
            )
        for level in prior_levels:
            if not isinstance(level, Mapping):
                raise TrainingRunError(
                    "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                    "prior historical L2 liquidation level proof is invalid",
                    status_code=409,
                )
            index = int(level["book_level"])
            consumed[index] = consumed.get(index, Decimal(0)) + Decimal(
                str(level["quantity"])
            )

    remaining_visible = sum(
        (
            max(Decimal(0), level_quantity - consumed.get(level_index, Decimal(0)))
            for level_index, _price, level_quantity in normalized
        ),
        Decimal(0),
    )
    if remaining_visible < quantity:
        raise TrainingRunError(
            "HISTORICAL_BOOK_DEPTH_EXHAUSTED",
            "historical L2 visible depth cannot fully execute the liquidation step",
            status_code=409,
            details={
                "requested_quantity": decimal_to_string(
                    quantity, field_name="historical book requested quantity"
                ),
                "visible_quantity": decimal_to_string(
                    remaining_visible,
                    field_name="historical book visible quantity",
                ),
            },
        )
    remaining = quantity
    levels: list[dict[str, object]] = []
    for level_index, price, level_quantity in normalized:
        available = max(
            Decimal(0), level_quantity - consumed.get(level_index, Decimal(0))
        )
        if available <= 0:
            continue
        take = min(remaining, available)
        levels.append(
            {
                "book_level": level_index,
                "price": decimal_to_string(price, field_name="historical book price"),
                "quantity": decimal_to_string(
                    take, field_name="historical book execution quantity"
                ),
            }
        )
        remaining -= take
        if remaining == 0:
            break
    if remaining != 0:
        raise TrainingRunError(
            "HISTORICAL_BOOK_DEPTH_EXHAUSTED",
            "historical L2 consumption plan is incomplete",
            status_code=409,
        )
    payload: dict[str, object] = {
        "archive_id": str(projection["archive_id"]),
        "as_of_virtual_time_ms": int(projection["as_of_virtual_time_ms"]),
        "last_update_id": int(projection["last_update_id"]),
        "side": side,
        "requested_quantity": decimal_to_string(
            quantity, field_name="historical book requested quantity"
        ),
        "visible_quantity": decimal_to_string(
            remaining_visible, field_name="historical book visible quantity"
        ),
        "levels": levels,
        "book_hash": str(projection["book_hash"]),
        "execution_fidelity": HISTORICAL_L2_LIQUIDATION_FIDELITY,
        "queue_exact": False,
    }
    payload["execution_plan_hash"] = canonical_sha256(payload)
    return payload


def freeze_liquidation_book_snapshots(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    track_ids: Sequence[str],
    virtual_time_ms: int,
    now_ms: int,
) -> None:
    for track_id in sorted(set(track_ids)):
        projection = connection.execute(
            """
            SELECT projection.*, archive.health AS archive_health
            FROM replay_historical_book_projection AS projection
            JOIN replay_historical_book_archive AS archive
              ON archive.archive_id = projection.archive_id
            WHERE projection.run_id = ? AND projection.track_id = ?
              AND EXISTS (
                  SELECT 1 FROM replay_historical_book_ref AS ref
                  WHERE ref.run_id = projection.run_id
                    AND ref.track_id = projection.track_id
                    AND ref.archive_id = projection.archive_id
                    AND ref.active = 1
              )
            """,
            (run_id, track_id),
        ).fetchone()
        if (
            projection is None
            or str(projection["capability_state"]) != "AVAILABLE_EXACT"
            or str(projection["status"]) != "READY"
            or str(projection["archive_health"]) != "READY"
            or int(projection["queue_exact"]) != 0
            or projection["as_of_actual_ms"] is None
            or projection["as_of_virtual_ms"] is None
            or projection["last_update_id"] is None
            or projection["book_hash"] is None
            or int(projection["as_of_virtual_ms"]) != virtual_time_ms
        ):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "liquidation trigger cannot freeze an exact same-time historical L2 snapshot",
                status_code=409,
            )
        bids = json.loads(str(projection["bids_json"]))
        asks = json.loads(str(projection["asks_json"]))
        expected_book_hash = canonical_sha256(
            {
                "archive_id": str(projection["archive_id"]),
                "actual_time_ms": int(projection["as_of_actual_ms"]),
                "last_update_id": int(projection["last_update_id"]),
                "bids": bids,
                "asks": asks,
            }
        )
        if expected_book_hash != str(projection["book_hash"]):
            raise TrainingRunError(
                "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                "liquidation trigger historical L2 hash verification failed",
                status_code=409,
            )
        payload = {
            "schema_version": "replay.liquidation-book-snapshot.v1",
            "case_id": case_id,
            "track_id": track_id,
            "archive_id": str(projection["archive_id"]),
            "as_of_actual_time_ms": int(projection["as_of_actual_ms"]),
            "as_of_virtual_time_ms": int(projection["as_of_virtual_ms"]),
            "last_update_id": int(projection["last_update_id"]),
            "bids": bids,
            "asks": asks,
            "book_hash": str(projection["book_hash"]),
            "execution_fidelity": HISTORICAL_L2_LIQUIDATION_FIDELITY,
            "queue_exact": False,
        }
        connection.execute(
            """
            INSERT INTO replay_training_liquidation_book_snapshot(
                run_id, case_id, track_id, archive_id,
                as_of_actual_time_ms, as_of_virtual_time_ms,
                last_update_id, bids_json, asks_json, book_hash,
                execution_fidelity, queue_exact, snapshot_hash, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                run_id,
                case_id,
                track_id,
                projection["archive_id"],
                projection["as_of_actual_ms"],
                projection["as_of_virtual_ms"],
                projection["last_update_id"],
                canonical_json(bids),
                canonical_json(asks),
                projection["book_hash"],
                HISTORICAL_L2_LIQUIDATION_FIDELITY,
                canonical_sha256(payload),
                now_ms,
            ),
        )


def detect_contract_liquidations(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
    trigger_virtual_time_ms: int | None = None,
    refresh_current_equity: bool = False,
    record_valuation_history: bool = True,
) -> None:
    account = connection.execute(
        """
        SELECT account.*, run.initial_equity, run.settlement_asset,
               run.position_mode, run.book_mode
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        return
    isolated = json.loads(str(account["isolated_margin_json"]))
    if not isinstance(isolated, dict):
        raise TypeError("isolated margin allocation is invalid")
    tracks = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_market_track
            WHERE run_id = ? AND subscription_tier = 'FULL'
            ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    )
    initial = Decimal(str(account["initial_equity"]))
    equity = initial + Decimal(str(account["overlay_cash"]))
    positions: list[
        tuple[
            sqlite3.Row,
            dict[str, object],
            InstrumentRule,
            Decimal,
            str | None,
            int,
        ]
    ] = []
    position_components: list[
        tuple[
            sqlite3.Row,
            dict[str, object],
            InstrumentRule,
            Decimal,
            str | None,
            int,
        ]
    ] = []
    total_maintenance = Decimal(0)
    rules = load_track_rules(connection, run_id, effective=False)
    for track in tracks:
        track_account = json.loads(str(track["account_json"]))
        position = json.loads(str(track["position_json"]))
        if isinstance(track_account, dict) and "equity" in track_account:
            equity += Decimal(str(track_account["equity"])) - initial
        if not isinstance(position, dict):
            continue
        legs: tuple[tuple[str | None, dict[str, object]], ...]
        if position.get("position_mode") == "HEDGE":
            legs = tuple(
                (side, leg)
                for side, leg in (
                    ("LONG", position.get("long")),
                    ("SHORT", position.get("short")),
                )
                if isinstance(leg, dict)
            )
        else:
            legs = (
                ((None, position),)
                if Decimal(str(position.get("quantity", "0"))) != 0
                else ()
            )
        if not legs:
            continue
        rule_row = rules.get(track["track_id"])
        if rule_row is None:
            raise TypeError("liquidation instrument rule is missing")
        rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
        for position_side, leg in legs:
            maintenance = rule.maintenance_margin(
                abs(Decimal(str(leg.get("notional", "0")))),
                extend_last_tier=True,
            )
            item = (
                track,
                leg,
                rule,
                maintenance,
                position_side,
                int(rule_row["revision"]),
            )
            position_components.append(item)
            if Decimal(str(leg.get("quantity", "0"))) != 0:
                total_maintenance += maintenance
                positions.append(item)

    def persist_current_equity() -> None:
        if not refresh_current_equity:
            return
        connection.execute(
            """
            UPDATE replay_training_run
            SET current_equity = ?, updated_at_ms = ? WHERE run_id = ?
            """,
            (
                decimal_to_string(equity, field_name="equity"),
                now_ms,
                run_id,
            ),
        )

    total_initial_margin = Decimal(0)
    total_unrealized = Decimal(0)
    total_reserved_margin = Decimal(0)
    hedge_accounting_totals = (
        account_marks_ops.hedge_accounting_totals_by_leg(connection, run_id=run_id)
        if str(account["position_mode"]) == "HEDGE"
        else {}
    )
    ledger_append_state = (
        ledger_ops.contract_ledger_append_state(connection, run_id=run_id)
        if record_valuation_history and str(account["position_mode"]) == "HEDGE"
        else None
    )
    for (
        track,
        leg,
        rule,
        maintenance,
        raw_position_side,
        rule_revision,
    ) in position_components:
        raw_quantity = Decimal(str(leg["quantity"]))
        position_side = raw_position_side or ("LONG" if raw_quantity > 0 else "SHORT")
        absolute_quantity = abs(raw_quantity)
        signed_quantity = (
            absolute_quantity if position_side == "LONG" else -absolute_quantity
        )
        notional = abs(Decimal(str(leg["notional"])))
        mark_price = Decimal(str(leg.get("mark_price", track["public_price"])))
        leverage = Decimal(str(leg.get("leverage", rule.max_leverage)))
        if leverage <= 0:
            leverage = Decimal(rule.max_leverage)
        initial_margin = rule.initial_margin(notional, leverage)
        total_initial_margin += initial_margin
        total_unrealized += Decimal(str(leg.get("unrealized_pnl", "0")))
        open_orders = json.loads(str(track["open_orders_json"]))
        if not isinstance(open_orders, list):
            raise TypeError("track open-order projection is invalid")
        protection_orders = [
            {
                "order_id": str(order["order_id"]),
                "order_type": str(order["order_type"]),
                "quantity": str(order["quantity"]),
                "remaining_quantity": str(order["remaining_quantity"]),
                "stop_price": order.get("stop_price"),
                "status": str(order["status"]),
            }
            for order in open_orders
            if isinstance(order, Mapping)
            and str(order.get("client_order_id", "")).startswith("protection-")
            and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
            and (
                raw_position_side is None or order.get("position_side") == position_side
            )
        ]
        reserved_margin = sum(
            (
                Decimal(str(order.get("reserved_margin", "0")))
                for order in open_orders
                if isinstance(order, Mapping)
                and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                and order.get("reduce_only") is not True
                and (
                    raw_position_side is None
                    or order.get("position_side") == position_side
                )
            ),
            Decimal(0),
        )
        total_reserved_margin += reserved_margin
        risk_tier, _active_tier = rule.active_maintenance_tier(
            notional,
            extend_last_tier=True,
        )
        allocation_key = isolated_margin_key(
            str(track["track_id"]),
            position_side if raw_position_side is not None else None,
        )
        isolated_wallet = Decimal(str(isolated.get(allocation_key, "0")))
        if raw_position_side is not None:
            funding_total, trading_fee_total, liquidation_fee_total = (
                hedge_accounting_totals.get(
                    (str(track["track_id"]), position_side),
                    (Decimal(0), Decimal(0), Decimal(0)),
                )
            )
            accumulated_funding = decimal_to_string(
                funding_total,
                field_name="position accumulated funding",
            )
            trading_fees = decimal_to_string(
                trading_fee_total,
                field_name="position trading fees",
            )
            liquidation_fees = decimal_to_string(
                liquidation_fee_total,
                field_name="position liquidation fees",
            )
        else:
            accumulated_funding = str(leg.get("accumulated_funding", "0"))
            trading_fees = str(leg.get("trading_fees", "0"))
            liquidation_fees = str(leg.get("liquidation_fees", "0"))
        if absolute_quantity > 0:
            scope_equity = (
                equity
                if str(account["margin_mode"]) == "CROSS"
                else isolated_wallet + Decimal(str(leg.get("unrealized_pnl", "0")))
            )
            scope_maintenance = (
                total_maintenance
                if str(account["margin_mode"]) == "CROSS"
                else maintenance
            )
            liquidation_price, bankruptcy_price = (
                account_math_ops._project_liquidation_price_pair(
                    mark_price=mark_price,
                    scope_equity=scope_equity,
                    scope_maintenance_margin=scope_maintenance,
                    absolute_quantity=absolute_quantity,
                    position_side=position_side,
                    rule=rule,
                )
            )
        else:
            liquidation_price = None
            bankruptcy_price = None
        component = {
            "schema_version": "replay.position-leg.v1",
            "track_id": str(track["track_id"]),
            "position_side": position_side,
            "signed_quantity": decimal_to_string(
                signed_quantity,
                field_name="position signed quantity",
            ),
            "absolute_quantity": decimal_to_string(
                absolute_quantity,
                field_name="position absolute quantity",
            ),
            "entry_price": leg.get("entry_price"),
            "mark_price": decimal_to_string(
                mark_price, field_name="position mark price"
            ),
            "notional": decimal_to_string(notional, field_name="position notional"),
            "realized_pnl": str(leg.get("realized_pnl", "0")),
            "unrealized_pnl": str(leg.get("unrealized_pnl", "0")),
            "initial_margin": decimal_to_string(
                initial_margin,
                field_name="position initial margin",
            ),
            "maintenance_margin": decimal_to_string(
                maintenance,
                field_name="position maintenance margin",
            ),
            "leverage": decimal_to_string(leverage, field_name="position leverage"),
            "margin_mode": str(account["margin_mode"]),
            "isolated_wallet": decimal_to_string(
                isolated_wallet,
                field_name="isolated wallet",
            ),
            "liquidation_price": (
                None
                if liquidation_price is None
                else decimal_to_string(
                    liquidation_price, field_name="position liquidation price"
                )
            ),
            "bankruptcy_price": (
                None
                if bankruptcy_price is None
                else decimal_to_string(
                    bankruptcy_price, field_name="position bankruptcy price"
                )
            ),
            "accumulated_funding": accumulated_funding,
            "trading_fees": trading_fees,
            "liquidation_fees": liquidation_fees,
            "risk_tier": risk_tier,
            "rule_revision": rule_revision,
            "protection": {"orders": protection_orders},
        }
        component_hash = canonical_sha256(component)
        prior_component = connection.execute(
            """
            SELECT component_revision, component_hash
            FROM replay_training_position_leg
            WHERE run_id = ? AND track_id = ? AND position_side = ?
            """,
            (run_id, track["track_id"], position_side),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO replay_training_position_leg(
                run_id, track_id, position_side, signed_quantity,
                absolute_quantity, entry_price, mark_price, notional,
                realized_pnl, unrealized_pnl, initial_margin,
                maintenance_margin, leverage, margin_mode, isolated_wallet,
                liquidation_price, bankruptcy_price, accumulated_funding,
                trading_fees, liquidation_fees, risk_tier, rule_revision,
                protection_json, component_revision, component_hash,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(run_id, track_id, position_side) DO UPDATE SET
                signed_quantity = excluded.signed_quantity,
                absolute_quantity = excluded.absolute_quantity,
                entry_price = excluded.entry_price,
                mark_price = excluded.mark_price,
                notional = excluded.notional,
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                initial_margin = excluded.initial_margin,
                maintenance_margin = excluded.maintenance_margin,
                leverage = excluded.leverage,
                margin_mode = excluded.margin_mode,
                isolated_wallet = excluded.isolated_wallet,
                liquidation_price = excluded.liquidation_price,
                bankruptcy_price = excluded.bankruptcy_price,
                accumulated_funding = excluded.accumulated_funding,
                trading_fees = excluded.trading_fees,
                liquidation_fees = excluded.liquidation_fees,
                risk_tier = excluded.risk_tier,
                rule_revision = excluded.rule_revision,
                protection_json = excluded.protection_json,
                component_revision = replay_training_position_leg.component_revision + 1,
                component_hash = excluded.component_hash,
                updated_at_ms = excluded.updated_at_ms
            WHERE replay_training_position_leg.component_hash
                  <> excluded.component_hash
            """,
            (
                run_id,
                track["track_id"],
                position_side,
                component["signed_quantity"],
                component["absolute_quantity"],
                component["entry_price"],
                component["mark_price"],
                component["notional"],
                component["realized_pnl"],
                component["unrealized_pnl"],
                component["initial_margin"],
                component["maintenance_margin"],
                component["leverage"],
                component["margin_mode"],
                component["isolated_wallet"],
                component["liquidation_price"],
                component["bankruptcy_price"],
                component["accumulated_funding"],
                component["trading_fees"],
                component["liquidation_fees"],
                risk_tier,
                rule_revision,
                canonical_json(component["protection"]),
                component_hash,
                now_ms,
                now_ms,
            ),
        )
        if (
            record_valuation_history
            and raw_position_side is not None
            and (
                prior_component is None
                or str(prior_component["component_hash"]) != component_hash
            )
        ):
            next_component_revision = (
                1
                if prior_component is None
                else int(prior_component["component_revision"]) + 1
            )
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=(
                    f"position-mutation:{track['track_id']}:{position_side}:"
                    f"{next_component_revision}:{component_hash}"
                ),
                track_id=str(track["track_id"]),
                kind="POSITION_MUTATION",
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=(
                    int(trigger_virtual_time_ms)
                    if trigger_virtual_time_ms is not None
                    else int(track["virtual_time_ms"] or 0)
                ),
                source_sequence=int(track["source_sequence"] or 0),
                fidelity="RELATIONAL_HEDGE_POSITION_EXACT",
                rule_revision=rule_revision,
                reference_type="POSITION_LEG",
                reference_id=f"{track['track_id']}:{position_side}",
                metadata={
                    "position_side": position_side,
                    "previous_component_hash": (
                        None
                        if prior_component is None
                        else str(prior_component["component_hash"])
                    ),
                    "component_hash": component_hash,
                    "component_revision": next_component_revision,
                },
                now_ms=now_ms,
                append_state=ledger_append_state,
            )
        bucket = {
            "schema_version": "replay.margin-bucket.v1",
            "bucket_id": f"position:{track['track_id']}:{position_side}",
            "bucket_kind": "POSITION",
            "track_id": str(track["track_id"]),
            "position_side": position_side,
            "asset": str(account["settlement_asset"]),
            "wallet_balance": "0",
            "initial_margin": component["initial_margin"],
            "maintenance_margin": component["maintenance_margin"],
            "reserved_margin": "0",
            "available_balance": "0",
        }
        bucket_hash = canonical_sha256(bucket)
        prior_bucket = connection.execute(
            """
            SELECT component_revision, component_hash
            FROM replay_training_margin_bucket
            WHERE run_id = ? AND bucket_id = ?
            """,
            (run_id, bucket["bucket_id"]),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO replay_training_margin_bucket(
                run_id, bucket_id, bucket_kind, track_id, position_side,
                asset, wallet_balance, initial_margin, maintenance_margin,
                reserved_margin, available_balance, component_revision,
                component_hash, updated_at_ms
            ) VALUES (?, ?, 'POSITION', ?, ?, ?, '0', ?, ?, '0', '0',
                      1, ?, ?)
            ON CONFLICT(run_id, bucket_id) DO UPDATE SET
                initial_margin = excluded.initial_margin,
                maintenance_margin = excluded.maintenance_margin,
                component_revision = replay_training_margin_bucket.component_revision + 1,
                component_hash = excluded.component_hash,
                updated_at_ms = excluded.updated_at_ms
            WHERE replay_training_margin_bucket.component_hash
                  <> excluded.component_hash
            """,
            (
                run_id,
                bucket["bucket_id"],
                track["track_id"],
                position_side,
                account["settlement_asset"],
                bucket["initial_margin"],
                bucket["maintenance_margin"],
                bucket_hash,
                now_ms,
            ),
        )
        if (
            record_valuation_history
            and raw_position_side is not None
            and (
                prior_bucket is None
                or str(prior_bucket["component_hash"]) != bucket_hash
            )
        ):
            next_bucket_revision = (
                1
                if prior_bucket is None
                else int(prior_bucket["component_revision"]) + 1
            )
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=(
                    f"margin-mutation:{bucket['bucket_id']}:"
                    f"{next_bucket_revision}:{bucket_hash}"
                ),
                track_id=str(track["track_id"]),
                kind="MARGIN_MUTATION",
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=(
                    int(trigger_virtual_time_ms)
                    if trigger_virtual_time_ms is not None
                    else int(track["virtual_time_ms"] or 0)
                ),
                source_sequence=int(track["source_sequence"] or 0),
                fidelity="RELATIONAL_MARGIN_BUCKET_EXACT",
                rule_revision=rule_revision,
                reference_type="MARGIN_BUCKET",
                reference_id=str(bucket["bucket_id"]),
                metadata={
                    "position_side": position_side,
                    "bucket_kind": "POSITION",
                    "previous_component_hash": (
                        None
                        if prior_bucket is None
                        else str(prior_bucket["component_hash"])
                    ),
                    "component_hash": bucket_hash,
                    "component_revision": next_bucket_revision,
                },
                now_ms=now_ms,
                append_state=ledger_append_state,
            )
        if str(account["margin_mode"]) == "ISOLATED":
            isolated_available = isolated_wallet - initial_margin - reserved_margin
            isolated_bucket = {
                "schema_version": "replay.margin-bucket.v1",
                "bucket_id": (f"isolated:{track['track_id']}:{position_side}"),
                "bucket_kind": "ISOLATED_LEG",
                "track_id": str(track["track_id"]),
                "position_side": position_side,
                "asset": str(account["settlement_asset"]),
                "wallet_balance": decimal_to_string(
                    isolated_wallet,
                    field_name="isolated wallet balance",
                ),
                "initial_margin": component["initial_margin"],
                "maintenance_margin": component["maintenance_margin"],
                "reserved_margin": decimal_to_string(
                    reserved_margin,
                    field_name="isolated reserved margin",
                ),
                "available_balance": decimal_to_string(
                    isolated_available,
                    field_name="isolated available balance",
                ),
            }
            isolated_bucket_hash = canonical_sha256(isolated_bucket)
            prior_isolated_bucket = connection.execute(
                """
                SELECT component_revision, component_hash
                FROM replay_training_margin_bucket
                WHERE run_id = ? AND bucket_id = ?
                """,
                (run_id, isolated_bucket["bucket_id"]),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO replay_training_margin_bucket(
                    run_id, bucket_id, bucket_kind, track_id, position_side,
                    asset, wallet_balance, initial_margin,
                    maintenance_margin, reserved_margin, available_balance,
                    component_revision, component_hash, updated_at_ms
                ) VALUES (?, ?, 'ISOLATED_LEG', ?, ?, ?, ?, ?, ?, ?, ?,
                          1, ?, ?)
                ON CONFLICT(run_id, bucket_id) DO UPDATE SET
                    wallet_balance = excluded.wallet_balance,
                    initial_margin = excluded.initial_margin,
                    maintenance_margin = excluded.maintenance_margin,
                    reserved_margin = excluded.reserved_margin,
                    available_balance = excluded.available_balance,
                    component_revision = replay_training_margin_bucket.component_revision + 1,
                    component_hash = excluded.component_hash,
                    updated_at_ms = excluded.updated_at_ms
                WHERE replay_training_margin_bucket.component_hash
                      <> excluded.component_hash
                """,
                (
                    run_id,
                    isolated_bucket["bucket_id"],
                    track["track_id"],
                    position_side,
                    account["settlement_asset"],
                    isolated_bucket["wallet_balance"],
                    isolated_bucket["initial_margin"],
                    isolated_bucket["maintenance_margin"],
                    isolated_bucket["reserved_margin"],
                    isolated_bucket["available_balance"],
                    isolated_bucket_hash,
                    now_ms,
                ),
            )
            if (
                record_valuation_history
                and raw_position_side is not None
                and (
                    prior_isolated_bucket is None
                    or str(prior_isolated_bucket["component_hash"])
                    != isolated_bucket_hash
                )
            ):
                next_isolated_revision = (
                    1
                    if prior_isolated_bucket is None
                    else int(prior_isolated_bucket["component_revision"]) + 1
                )
                ledger_ops.append_contract_ledger(
                    connection,
                    run_id=run_id,
                    posting_id=(
                        f"margin-mutation:{isolated_bucket['bucket_id']}:"
                        f"{next_isolated_revision}:{isolated_bucket_hash}"
                    ),
                    track_id=str(track["track_id"]),
                    kind="MARGIN_MUTATION",
                    cash_delta=Decimal(0),
                    asset=str(account["settlement_asset"]),
                    virtual_time_ms=(
                        int(trigger_virtual_time_ms)
                        if trigger_virtual_time_ms is not None
                        else int(track["virtual_time_ms"] or 0)
                    ),
                    source_sequence=int(track["source_sequence"] or 0),
                    fidelity="RELATIONAL_MARGIN_BUCKET_EXACT",
                    rule_revision=rule_revision,
                    reference_type="MARGIN_BUCKET",
                    reference_id=str(isolated_bucket["bucket_id"]),
                    metadata={
                        "position_side": position_side,
                        "bucket_kind": "ISOLATED_LEG",
                        "previous_component_hash": (
                            None
                            if prior_isolated_bucket is None
                            else str(prior_isolated_bucket["component_hash"])
                        ),
                        "component_hash": isolated_bucket_hash,
                        "component_revision": next_isolated_revision,
                    },
                    now_ms=now_ms,
                    append_state=ledger_append_state,
                )
    if position_components and str(account["margin_mode"]) == "CROSS":
        wallet_balance = equity - total_unrealized
        available_balance = equity - total_initial_margin - total_reserved_margin
        cross_bucket = {
            "schema_version": "replay.margin-bucket.v1",
            "bucket_id": f"cross:{account['settlement_asset']}",
            "bucket_kind": "CROSS",
            "asset": str(account["settlement_asset"]),
            "wallet_balance": decimal_to_string(
                wallet_balance,
                field_name="cross wallet balance",
            ),
            "initial_margin": decimal_to_string(
                total_initial_margin,
                field_name="cross initial margin",
            ),
            "maintenance_margin": decimal_to_string(
                total_maintenance,
                field_name="cross maintenance margin",
            ),
            "reserved_margin": decimal_to_string(
                total_reserved_margin,
                field_name="cross reserved margin",
            ),
            "available_balance": decimal_to_string(
                available_balance,
                field_name="cross available balance",
            ),
        }
        cross_bucket_hash = canonical_sha256(cross_bucket)
        prior_cross_bucket = connection.execute(
            """
            SELECT component_revision, component_hash
            FROM replay_training_margin_bucket
            WHERE run_id = ? AND bucket_id = ?
            """,
            (run_id, cross_bucket["bucket_id"]),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO replay_training_margin_bucket(
                run_id, bucket_id, bucket_kind, track_id, position_side,
                asset, wallet_balance, initial_margin, maintenance_margin,
                reserved_margin, available_balance, component_revision,
                component_hash, updated_at_ms
            ) VALUES (?, ?, 'CROSS', NULL, NULL, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(run_id, bucket_id) DO UPDATE SET
                wallet_balance = excluded.wallet_balance,
                initial_margin = excluded.initial_margin,
                maintenance_margin = excluded.maintenance_margin,
                reserved_margin = excluded.reserved_margin,
                available_balance = excluded.available_balance,
                component_revision = replay_training_margin_bucket.component_revision + 1,
                component_hash = excluded.component_hash,
                updated_at_ms = excluded.updated_at_ms
            WHERE replay_training_margin_bucket.component_hash
                  <> excluded.component_hash
            """,
            (
                run_id,
                cross_bucket["bucket_id"],
                account["settlement_asset"],
                cross_bucket["wallet_balance"],
                cross_bucket["initial_margin"],
                cross_bucket["maintenance_margin"],
                cross_bucket["reserved_margin"],
                cross_bucket["available_balance"],
                cross_bucket_hash,
                now_ms,
            ),
        )
        if (
            record_valuation_history
            and str(account["position_mode"]) == "HEDGE"
            and (
                prior_cross_bucket is None
                or str(prior_cross_bucket["component_hash"]) != cross_bucket_hash
            )
        ):
            next_cross_revision = (
                1
                if prior_cross_bucket is None
                else int(prior_cross_bucket["component_revision"]) + 1
            )
            cross_rule_revision = max(item[5] for item in position_components)
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=(
                    f"margin-mutation:{cross_bucket['bucket_id']}:"
                    f"{next_cross_revision}:{cross_bucket_hash}"
                ),
                track_id=None,
                kind="MARGIN_MUTATION",
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=(
                    int(trigger_virtual_time_ms)
                    if trigger_virtual_time_ms is not None
                    else max(
                        int(item[0]["virtual_time_ms"] or 0)
                        for item in position_components
                    )
                ),
                source_sequence=max(
                    int(item[0]["source_sequence"] or 0) for item in position_components
                ),
                fidelity="RELATIONAL_MARGIN_BUCKET_EXACT",
                rule_revision=cross_rule_revision,
                reference_type="MARGIN_BUCKET",
                reference_id=str(cross_bucket["bucket_id"]),
                metadata={
                    "bucket_kind": "CROSS",
                    "previous_component_hash": (
                        None
                        if prior_cross_bucket is None
                        else str(prior_cross_bucket["component_hash"])
                    ),
                    "component_hash": cross_bucket_hash,
                    "component_revision": next_cross_revision,
                },
                now_ms=now_ms,
                append_state=ledger_append_state,
            )
    if ledger_append_state is not None:
        ledger_ops.flush_contract_ledger_append_state(
            connection,
            run_id=run_id,
            state=ledger_append_state,
            now_ms=now_ms,
        )
    if not positions:
        pending = connection.execute(
            """
            SELECT 1 FROM replay_training_liquidation_case
            WHERE run_id = ?
              AND state NOT IN (
                  'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED',
                  'RECOVERED_AFTER_CANCEL'
              )
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if str(account["status"]) == "LIQUIDATING" and pending is None:
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET status = 'ACTIVE', updated_at_ms = ? WHERE run_id = ?
                """,
                (now_ms, run_id),
            )
        persist_current_equity()
        return
    affected: list[
        tuple[
            sqlite3.Row,
            dict[str, object],
            InstrumentRule,
            Decimal,
            str | None,
            int,
        ]
    ] = []
    if str(account["margin_mode"]) == "CROSS":
        if equity <= total_maintenance + total_reserved_margin:
            affected = positions
    else:
        for item in positions:
            track, position, _rule, maintenance, position_side, _revision = item
            allocation_key = isolated_margin_key(
                str(track["track_id"]),
                position_side,
            )
            allocated = Decimal(str(isolated.get(allocation_key, "0")))
            isolated_equity = allocated + Decimal(str(position["unrealized_pnl"]))
            if isolated_equity <= maintenance:
                affected.append(item)
    if not affected:
        persist_current_equity()
        return
    active_case = connection.execute(
        """
        SELECT 1 FROM replay_training_liquidation_case
        WHERE run_id = ?
          AND state NOT IN ('COMPLETED', 'BANKRUPT', 'FAILED_CLOSED', 'RECOVERED_AFTER_CANCEL')
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if active_case is not None:
        connection.execute(
            """
            UPDATE replay_training_contract_account
            SET status = 'LIQUIDATING', updated_at_ms = ? WHERE run_id = ?
            """,
            (now_ms, run_id),
        )
        persist_current_equity()
        return
    grouped: list[
        list[
            tuple[
                sqlite3.Row,
                dict[str, object],
                InstrumentRule,
                Decimal,
                str | None,
                int,
            ]
        ]
    ]
    if str(account["margin_mode"]) == "CROSS":
        grouped = [affected]
    else:
        grouped = [[item] for item in affected]
    for group in grouped:
        group.sort(
            key=lambda item: (
                -item[3],
                -abs(Decimal(str(item[1]["notional"]))),
                str(item[0]["track_id"]),
                0
                if (
                    item[4]
                    or ("LONG" if Decimal(str(item[1]["quantity"])) > 0 else "SHORT")
                )
                == "LONG"
                else 1,
            )
        )
        sequence = max(int(item[0]["source_sequence"] or 0) for item in group)
        case_sequence = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(case_sequence), 0) + 1
                FROM replay_training_liquidation_case WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        )
        scope = (
            "cross"
            if str(account["margin_mode"]) == "CROSS"
            else (f"{group[0][0]['track_id']}-{group[0][4] or 'net'}")
        )
        liquidation_id = f"liq-{scope}-{sequence:010d}-{case_sequence:04d}"
        virtual_time_ms = (
            max(int(item[0]["virtual_time_ms"] or 0) for item in group)
            if trigger_virtual_time_ms is None
            else trigger_virtual_time_ms
        )
        snapshot_id = f"risk-{liquidation_id}-trigger"
        snapshot_sequence = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(snapshot_sequence), 0) + 1
                FROM replay_training_risk_snapshot WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        )
        risk_payload = {
            "schema_version": "replay.risk-snapshot.v1",
            "snapshot_id": snapshot_id,
            "virtual_time_ms": virtual_time_ms,
            "source_sequence": sequence,
            "equity": decimal_to_string(equity, field_name="account equity"),
            "total_maintenance_margin": decimal_to_string(
                total_maintenance,
                field_name="total maintenance margin",
            ),
            "active_rule_revision": max(item[5] for item in group),
            "position_hashes": [
                str(
                    connection.execute(
                        """
                        SELECT component_hash FROM replay_training_position_leg
                        WHERE run_id = ? AND track_id = ? AND position_side = ?
                        """,
                        (
                            run_id,
                            item[0]["track_id"],
                            item[4]
                            or (
                                "LONG"
                                if Decimal(str(item[1]["quantity"])) > 0
                                else "SHORT"
                            ),
                        ),
                    ).fetchone()["component_hash"]
                )
                for item in group
            ],
        }
        risk_hash = canonical_sha256(risk_payload)
        risk_available = (
            equity - total_initial_margin - total_reserved_margin
            if str(account["margin_mode"]) == "CROSS"
            else equity
            - sum(
                (Decimal(str(value)) for value in isolated.values()),
                Decimal(0),
            )
        )
        connection.execute(
            """
            INSERT INTO replay_training_risk_snapshot(
                run_id, snapshot_id, snapshot_sequence, virtual_time_ms,
                source_sequence, account_status, equity, available_balance,
                total_initial_margin, total_maintenance_margin, risk_ratio,
                active_rule_revision, public_input_hash, component_hash,
                created_at_ms
            ) VALUES (?, ?, ?, ?, ?, 'RISK_BREACH_DETECTED', ?, ?, ?, ?, ?,
                      ?, ?, ?, ?)
            """,
            (
                run_id,
                snapshot_id,
                snapshot_sequence,
                virtual_time_ms,
                sequence,
                risk_payload["equity"],
                decimal_to_string(
                    risk_available,
                    field_name="available balance",
                ),
                decimal_to_string(
                    total_initial_margin,
                    field_name="risk total initial margin",
                ),
                risk_payload["total_maintenance_margin"],
                (
                    None
                    if equity == 0
                    else decimal_to_string(
                        equity / total_maintenance,
                        field_name="risk ratio",
                    )
                ),
                risk_payload["active_rule_revision"],
                canonical_sha256(
                    {
                        "dataset_epochs": [
                            {
                                "track_id": str(item[0]["track_id"]),
                                "dataset_epoch": str(item[0]["dataset_epoch"]),
                            }
                            for item in group
                        ],
                        "virtual_time_ms": virtual_time_ms,
                        "source_sequence": sequence,
                    }
                ),
                risk_hash,
                now_ms,
            ),
        )
        case_payload = {
            "schema_version": "replay.liquidation-case.v2",
            "case_id": liquidation_id,
            "case_sequence": case_sequence,
            "trigger_snapshot_id": snapshot_id,
            "margin_scope": "ACCOUNT_CROSS"
            if str(account["margin_mode"]) == "CROSS"
            else "ISOLATED_LEG",
            "legs": [
                {
                    "track_id": str(item[0]["track_id"]),
                    "position_side": item[4]
                    or ("LONG" if Decimal(str(item[1]["quantity"])) > 0 else "SHORT"),
                }
                for item in group
            ],
        }
        connection.execute(
            """
            INSERT INTO replay_training_liquidation_case(
                run_id, case_id, case_sequence, state, trigger_snapshot_id,
                final_snapshot_id, trigger_virtual_time_ms,
                trigger_source_sequence, reason, fidelity, component_hash,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, 'RISK_BREACH_DETECTED', ?, NULL, ?, ?,
                      'MAINTENANCE_MARGIN_BREACH', ?, ?, ?, ?)
            """,
            (
                run_id,
                liquidation_id,
                case_sequence,
                snapshot_id,
                virtual_time_ms,
                sequence,
                "ACCOUNT_CROSS_MULTI_TRACK_DETERMINISTIC"
                if str(account["margin_mode"]) == "CROSS"
                and str(account["position_mode"]) == "HEDGE"
                else group[0][2].mark_fidelity,
                canonical_sha256(case_payload),
                now_ms,
                now_ms,
            ),
        )
        if (
            str(account["position_mode"]) == "HEDGE"
            and str(account["book_mode"]) == "BOOK_ASSISTED_REQUIRED"
        ):
            freeze_liquidation_book_snapshots(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                track_ids=[str(item[0]["track_id"]) for item in group],
                virtual_time_ms=virtual_time_ms,
                now_ms=now_ms,
            )
        for leg_sequence, item in enumerate(group, start=1):
            track, leg, rule, maintenance, raw_side, rule_revision = item
            quantity = Decimal(str(leg["quantity"]))
            position_side = raw_side or ("LONG" if quantity > 0 else "SHORT")
            absolute_quantity = abs(quantity)
            notional = abs(Decimal(str(leg["notional"])))
            mark = Decimal(str(leg.get("mark_price", track["public_price"])))
            scope_equity = (
                equity
                if str(account["margin_mode"]) == "CROSS"
                else Decimal(
                    str(
                        isolated.get(
                            isolated_margin_key(str(track["track_id"]), position_side),
                            "0",
                        )
                    )
                )
                + Decimal(str(leg["unrealized_pnl"]))
            )
            scope_maintenance = (
                total_maintenance
                if str(account["margin_mode"]) == "CROSS"
                else maintenance
            )
            liquidation_price, bankruptcy = (
                account_math_ops._project_liquidation_price_pair(
                    mark_price=mark,
                    scope_equity=scope_equity,
                    scope_maintenance_margin=scope_maintenance,
                    absolute_quantity=absolute_quantity,
                    position_side=position_side,
                    rule=rule,
                )
            )
            takeover = bankruptcy
            fee = rule.liquidation_fee(notional)
            leg_id = (
                f"{liquidation_id}-{str(track['track_id']).lower()}-"
                f"{position_side.lower()}"
            )
            leg_payload = {
                "schema_version": "replay.liquidation-leg.v2",
                "case_id": liquidation_id,
                "liquidation_leg_id": leg_id,
                "track_id": str(track["track_id"]),
                "position_side": position_side,
                "trigger_quantity": decimal_to_string(
                    absolute_quantity,
                    field_name="liquidation leg quantity",
                ),
                "trigger_notional": decimal_to_string(
                    notional,
                    field_name="liquidation leg notional",
                ),
                "maintenance_margin": decimal_to_string(
                    maintenance,
                    field_name="liquidation leg maintenance",
                ),
                "liquidation_price": decimal_to_string(
                    liquidation_price,
                    field_name="liquidation price",
                ),
                "bankruptcy_price": decimal_to_string(
                    bankruptcy,
                    field_name="bankruptcy price",
                ),
                "takeover_price": decimal_to_string(
                    takeover,
                    field_name="takeover price",
                ),
                "liquidation_fee": decimal_to_string(
                    fee,
                    field_name="liquidation fee",
                ),
            }
            connection.execute(
                """
                INSERT INTO replay_training_liquidation_leg(
                    run_id, case_id, liquidation_leg_id, leg_sequence,
                    track_id, position_side, trigger_quantity,
                    trigger_notional, maintenance_margin, liquidation_price, bankruptcy_price,
                    takeover_price, liquidation_fee, target_quantity,
                    completed_quantity, state, component_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '0',
                          'PENDING', ?)
                """,
                (
                    run_id,
                    liquidation_id,
                    leg_id,
                    leg_sequence,
                    track["track_id"],
                    position_side,
                    leg_payload["trigger_quantity"],
                    leg_payload["trigger_notional"],
                    leg_payload["maintenance_margin"],
                    leg_payload["liquidation_price"],
                    leg_payload["bankruptcy_price"],
                    leg_payload["takeover_price"],
                    leg_payload["liquidation_fee"],
                    leg_payload["trigger_quantity"],
                    canonical_sha256(leg_payload),
                ),
            )
            proof = {
                "schema_version": "replay.liquidation-leg-price-proof.v1",
                "case_id": liquidation_id,
                "liquidation_leg_id": leg_id,
                "rule_revision": rule_revision,
                "price_tick": rule.price_tick,
                "mark_price": decimal_to_string(mark, field_name="price proof mark"),
                "scope_equity": decimal_to_string(
                    scope_equity, field_name="price proof equity"
                ),
                "scope_maintenance_margin": decimal_to_string(
                    scope_maintenance, field_name="price proof maintenance"
                ),
                "liquidation_price": leg_payload["liquidation_price"],
                "bankruptcy_price": leg_payload["bankruptcy_price"],
                "takeover_price": leg_payload["takeover_price"],
                "formula_version": LIQUIDATION_FORMULA_VERSION,
            }
            connection.execute(
                """
                INSERT INTO replay_training_liquidation_leg_price_proof(
                    run_id, case_id, liquidation_leg_id, rule_revision,
                    price_tick, mark_price, scope_equity,
                    scope_maintenance_margin, liquidation_price,
                    bankruptcy_price, takeover_price, formula_version,
                    proof_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    liquidation_id,
                    leg_id,
                    rule_revision,
                    proof["price_tick"],
                    proof["mark_price"],
                    proof["scope_equity"],
                    proof["scope_maintenance_margin"],
                    proof["liquidation_price"],
                    proof["bankruptcy_price"],
                    proof["takeover_price"],
                    proof["formula_version"],
                    canonical_sha256(proof),
                    now_ms,
                ),
            )
        cancellation_orders: list[dict[str, object]] = []
        allowed_tracks = {str(item[0]["track_id"]) for item in group}
        allowed_sides = {
            (
                str(item[0]["track_id"]),
                item[4]
                or ("LONG" if Decimal(str(item[1]["quantity"])) > 0 else "SHORT"),
            )
            for item in group
        }
        for track in tracks:
            if (
                str(account["margin_mode"]) != "CROSS"
                and str(track["track_id"]) not in allowed_tracks
            ):
                continue
            raw_orders = json.loads(str(track["open_orders_json"]))
            if not isinstance(raw_orders, list):
                raise TypeError("liquidation cancellation projection is invalid")
            for order in raw_orders:
                if not isinstance(order, Mapping):
                    continue
                if (
                    order.get("status") not in {"OPEN", "PARTIALLY_FILLED"}
                    or order.get("reduce_only") is True
                ):
                    continue
                if (
                    str(account["margin_mode"]) == "ISOLATED"
                    and (str(track["track_id"]), order.get("position_side"))
                    not in allowed_sides
                ):
                    continue
                cancellation_orders.append(
                    {
                        "track_id": str(track["track_id"]),
                        "order_id": str(order["order_id"]),
                    }
                )
        insert_liquidation_step(
            connection,
            run_id=run_id,
            case_id=liquidation_id,
            step_type="CANCEL_ORDERS",
            before_snapshot_id=snapshot_id,
            plan={
                "orders": cancellation_orders,
                "scope": case_payload["margin_scope"],
            },
            now_ms=now_ms,
        )
    if affected:
        connection.execute(
            """
            UPDATE replay_training_contract_account
            SET status = 'LIQUIDATING', updated_at_ms = ? WHERE run_id = ?
            """,
            (now_ms, run_id),
        )
    persist_current_equity()
