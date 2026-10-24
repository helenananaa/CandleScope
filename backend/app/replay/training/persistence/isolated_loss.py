"""Resolve a closed isolated scope without spending unrelated collateral."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

from app.replay.broker.models import decimal_to_string

from ..errors import TrainingRunError
from . import ledger as ledger_ops

TRANSFER_KIND = "ISOLATED_BANKRUPTCY_TRANSFER"


def isolated_case(connection: sqlite3.Connection, run_id: str, case_id: str) -> bool:
    row = connection.execute(
        "SELECT reason FROM replay_training_liquidation_step "
        "WHERE run_id=? AND case_id=? AND step_type='CANCEL_ORDERS'",
        (run_id, case_id),
    ).fetchone()
    return (
        row is not None
        and json.loads(row["reason"]).get("plan", {}).get("scope") == "ISOLATED_LEG"
    )


def closed_scope_deficit(
    connection: sqlite3.Connection, run_id: str, case_id: str
) -> Decimal:
    """Settle the allocated leg lifecycle, including earlier partial closes and fees."""
    rows = connection.execute(
        "SELECT leg.*, proof.mark_price, proof.scope_equity, rule.rule_json "
        "FROM replay_training_liquidation_leg AS leg "
        "LEFT JOIN replay_training_liquidation_leg_price_proof AS proof "
        "ON proof.run_id=leg.run_id AND proof.case_id=leg.case_id "
        "AND proof.liquidation_leg_id=leg.liquidation_leg_id "
        "LEFT JOIN replay_training_instrument_rule AS rule "
        "ON rule.run_id=leg.run_id AND rule.track_id=leg.track_id "
        "AND rule.revision=proof.rule_revision "
        "WHERE leg.run_id=? AND leg.case_id=?",
        (run_id, case_id),
    ).fetchall()
    if not rows or any(
        row["scope_equity"] is None or row["rule_json"] is None for row in rows
    ):
        raise TrainingRunError(
            "ISOLATED_LOSS_PROOF_UNAVAILABLE",
            "isolated close lost its frozen scope",
            status_code=409,
        )
    total = Decimal(0)
    for row in rows:
        fills = connection.execute(
            "SELECT fill.* FROM replay_training_liquidation_fill AS fill "
            "JOIN replay_training_liquidation_order AS orders "
            "ON orders.run_id=fill.run_id AND orders.case_id=fill.case_id AND orders.order_id=fill.order_id "
            "WHERE orders.run_id=? AND orders.case_id=? AND orders.liquidation_leg_id=?",
            (run_id, case_id, row["liquidation_leg_id"]),
        ).fetchall()
        quantity = sum((Decimal(f["quantity"]) for f in fills), Decimal(0))
        if quantity != Decimal(row["trigger_quantity"]):
            raise TrainingRunError(
                "ISOLATED_LOSS_SCOPE_OPEN",
                "isolated deficit requires a fully closed scope",
                status_code=409,
            )
        balance = closed_wallet_balance(
            connection,
            run_id,
            case_id,
            row["track_id"],
            row["position_side"],
        )
        total += max(Decimal(0), -balance)
    return total


def closed_wallet_balance(connection, run_id, case_id, track_id, position_side):
    # Explicit fully closed liquidation boundary only; ordinary mark/bar updates
    # never reconstruct history. Forks retain the original economic order.
    entries = connection.execute(
        "SELECT ledger.*, COALESCE(json_extract(ledger.metadata_json,'$.position_side'), "
        "json_extract(fill.fill_json,'$.position_side')) AS leg_side "
        "FROM replay_training_contract_ledger AS ledger "
        "LEFT JOIN replay_training_contract_fill AS fill "
        "ON fill.run_id=ledger.run_id AND fill.track_id=ledger.track_id "
        "AND fill.fill_id=json_extract(ledger.metadata_json,'$.fill_id') "
        "WHERE ledger.run_id=? AND ledger.track_id=? "
        "AND ledger.kind IN ('MARGIN_ALLOCATION','MARGIN_RELEASE','TRADING_FEE',"
        "'BROKER_REALIZED_PNL','FUNDING_SETTLEMENT','LIQUIDATION_FEE','ISOLATED_BANKRUPTCY_TRANSFER')",
        (run_id, track_id),
    ).fetchall()
    ordered = sorted(
        (entry for entry in entries if entry["leg_side"] == position_side),
        key=ledger_ops.contract_posting_order,
    )
    endpoints = [
        index
        for index, entry in enumerate(ordered)
        if entry["kind"] == "LIQUIDATION_FEE"
        and json.loads(entry["metadata_json"]).get("case_id") == case_id
    ]
    if not endpoints:
        raise TrainingRunError(
            "ISOLATED_LOSS_PROOF_UNAVAILABLE",
            "isolated close has no final fee receipt",
            status_code=409,
        )
    balance = None
    for entry in ordered[: endpoints[-1] + 1]:
        metadata = json.loads(entry["metadata_json"])
        if entry["kind"] in {"MARGIN_ALLOCATION", "MARGIN_RELEASE"}:
            if "new_allocation" not in metadata:
                # Automatic release closes the allocation label, without
                # refunding the original budget before deficit settlement.
                continue
            old, new = (
                Decimal(metadata["old_allocation"]),
                Decimal(metadata["new_allocation"]),
            )
            if old == 0 and new > 0:
                balance = Decimal(0)
            if balance is not None:
                balance += new - old
        elif balance is not None:
            balance += Decimal(entry["cash_delta"])
    if balance is None:
        raise TrainingRunError(
            "ISOLATED_LOSS_PROOF_UNAVAILABLE",
            "isolated close has no allocation lifecycle",
            status_code=409,
        )
    return balance


def transfer_deficit(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    case_id: str,
    deficit: Decimal,
    now_ms: int,
) -> None:
    """The bankruptcy step owns this credit and commits it with its receipt."""
    expected = closed_scope_deficit(connection, run_id, case_id)
    if deficit != expected or deficit <= 0:
        raise TrainingRunError(
            "ISOLATED_LOSS_DEFICIT_MISMATCH",
            "isolated deficit does not match frozen scope and fills",
            status_code=409,
        )
    case = connection.execute(
        "SELECT case_row.*, run.settlement_asset FROM replay_training_liquidation_case AS case_row "
        "JOIN replay_training_run AS run USING(run_id) WHERE case_row.run_id=? AND case_id=?",
        (run_id, case_id),
    ).fetchone()
    leg = connection.execute(
        "SELECT leg.track_id, leg.position_side, proof.rule_revision FROM replay_training_liquidation_leg AS leg "
        "JOIN replay_training_liquidation_leg_price_proof AS proof USING(run_id,case_id,liquidation_leg_id) "
        "WHERE run_id=? AND case_id=? ORDER BY leg_sequence LIMIT 1",
        (run_id, case_id),
    ).fetchone()
    account = connection.execute(
        "SELECT overlay_cash FROM replay_training_contract_account WHERE run_id=?",
        (run_id,),
    ).fetchone()
    ledger_ops.append_contract_ledger(
        connection,
        run_id=run_id,
        posting_id=f"isolated-bankruptcy:{case_id}",
        track_id=leg["track_id"],
        kind=TRANSFER_KIND,
        cash_delta=deficit,
        asset=case["settlement_asset"],
        virtual_time_ms=case["trigger_virtual_time_ms"],
        source_sequence=case["trigger_source_sequence"],
        fidelity="ISOLATED_ALLOCATION_LIFECYCLE_CAP_V1",
        rule_revision=leg["rule_revision"],
        reference_type="LIQUIDATION_CASE",
        reference_id=case_id,
        metadata={
            "case_id": case_id,
            "position_side": leg["position_side"],
            "scope": "ISOLATED_LEG",
            "policy": "ISOLATED_ALLOCATION_LIFECYCLE_CAP_V1",
        },
        now_ms=now_ms,
    )
    connection.execute(
        "UPDATE replay_training_contract_account SET overlay_cash=?, updated_at_ms=? WHERE run_id=?",
        (
            decimal_to_string(
                Decimal(account["overlay_cash"]) + deficit,
                field_name="isolated bankruptcy credit",
            ),
            now_ms,
            run_id,
        ),
    )
