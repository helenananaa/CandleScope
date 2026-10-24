"""Cash held by active HEDGE isolated allocation lifecycles.

Principal labels remain separate from spendable cash. This projection is derived
from financial receipts once on migration/fork, then updated in their transaction;
ordinary marks do not rescan account history.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json

from ..errors import TrainingRunError

KINDS = frozenset({
    "MARGIN_ALLOCATION", "MARGIN_RELEASE", "TRADING_FEE", "BROKER_REALIZED_PNL",
    "FUNDING_SETTLEMENT", "LIQUIDATION_FEE", "ISOLATED_BANKRUPTCY_TRANSFER",
})


def _side(connection, run_id, track_id, metadata):
    side = metadata.get("position_side")
    if side is None and metadata.get("fill_id") is not None:
        fill = connection.execute(
            "SELECT fill_json FROM replay_training_contract_fill "
            "WHERE run_id=? AND track_id=? AND fill_id=?",
            (run_id, track_id, metadata["fill_id"]),
        ).fetchone()
        if fill is not None:
            side = json.loads(fill["fill_json"]).get("position_side")
    return side


def _apply(balances, *, track_id, side, kind, cash_delta, metadata):
    if side not in {"LONG", "SHORT"}:
        raise TrainingRunError(
            "ISOLATED_WALLET_INPUT_UNAVAILABLE",
            "isolated cash receipt has no position side", status_code=409,
        )
    key = f"{track_id}:{side}"
    if kind in {"MARGIN_ALLOCATION", "MARGIN_RELEASE"}:
        if "new_allocation" not in metadata:
            balances.pop(key, None)  # Automatic release after the final close.
            return
        old = Decimal(metadata["old_allocation"])
        new = Decimal(metadata["new_allocation"])
        if new == 0:
            balances.pop(key, None)
        elif old == 0:
            balances[key] = new
        elif key in balances:
            balances[key] += new - old
        else:
            raise TrainingRunError(
                "ISOLATED_WALLET_INPUT_UNAVAILABLE",
                "isolated allocation lifecycle is incomplete", status_code=409,
            )
    elif key in balances:
        balances[key] += Decimal(cash_delta)


def rebuild(connection: sqlite3.Connection, run_id: str, *, persist: bool = True) -> dict[str, Decimal]:
    from .ledger import contract_posting_order

    rows = connection.execute(
        "SELECT * FROM replay_training_contract_ledger WHERE run_id=? "
        "AND kind IN ('MARGIN_ALLOCATION','MARGIN_RELEASE','TRADING_FEE',"
        "'BROKER_REALIZED_PNL','FUNDING_SETTLEMENT','LIQUIDATION_FEE','ISOLATED_BANKRUPTCY_TRANSFER')",
        (run_id,),
    ).fetchall()
    balances: dict[str, Decimal] = {}
    for row in sorted(rows, key=contract_posting_order):
        metadata = json.loads(row["metadata_json"])
        _apply(
            balances, track_id=row["track_id"],
            side=_side(connection, run_id, row["track_id"], metadata),
            kind=row["kind"], cash_delta=row["cash_delta"], metadata=metadata,
        )
    if persist:
        save(connection, run_id, balances)
    return balances


def save(connection: sqlite3.Connection, run_id: str, balances: Mapping[str, Decimal]) -> None:
    payload = {
        key: decimal_to_string(value, field_name="isolated wallet")
        for key, value in balances.items()
    }
    connection.execute(
        "INSERT INTO replay_training_isolated_wallet(run_id,balances_json) VALUES (?,?) "
        "ON CONFLICT(run_id) DO UPDATE SET balances_json=excluded.balances_json",
        (run_id, canonical_json(payload)),
    )


def _decode(payload_json: str) -> dict[str, Decimal]:
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise TypeError("isolated wallet projection must be an object")
    if "error" in payload:
        raise TrainingRunError(
            "ISOLATED_WALLET_INPUT_UNAVAILABLE", payload["error"], status_code=409,
        )
    balances = {}
    for key, value in payload.items():
        if not isinstance(value, str) or not Decimal(value).is_finite():
            raise TypeError("isolated wallet balance must be a finite decimal string")
        balances[key] = Decimal(value)
    return balances


def read(connection: sqlite3.Connection, run_id: str, *, initialize: bool = False) -> dict[str, Decimal]:
    row = connection.execute(
        "SELECT balances_json FROM replay_training_isolated_wallet WHERE run_id=?", (run_id,),
    ).fetchone()
    if row is None:
        return rebuild(connection, run_id, persist=initialize)
    return _decode(row["balances_json"])


def append(connection, *, run_id, track_id, kind, cash_delta, metadata):
    if kind not in KINDS:
        return
    row = connection.execute(
        "SELECT balances_json FROM replay_training_isolated_wallet WHERE run_id=?", (run_id,),
    ).fetchone()
    if row is None:
        return  # Creation/fork assembles its receipts before initializing once.
    if "fork_parent_run_id" in metadata:
        connection.execute("DELETE FROM replay_training_isolated_wallet WHERE run_id=?", (run_id,))
        return  # Copied receipts arrive in storage order, not economic order.
    balances = _decode(row["balances_json"])
    _apply(
        balances, track_id=track_id, side=_side(connection, run_id, track_id, metadata),
        kind=kind, cash_delta=cash_delta, metadata=metadata,
    )
    save(connection, run_id, balances)


def migrate(connection: sqlite3.Connection, *, now_ms: int) -> None:
    from .liquidation import detect_contract_liquidations

    previous_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT run_id FROM replay_training_run "
            "WHERE margin_mode='ISOLATED' AND position_mode='HEDGE'"
        ).fetchall()
        for row in rows:
            try:
                rebuild(connection, row["run_id"])
                # Revalue current derived fields, preserving historical receipts
                # and cases. Normal resumed risk processing decides new cases.
                detect_contract_liquidations(
                    connection, run_id=row["run_id"], now_ms=now_ms,
                    include_dormant=True, record_valuation_history=False,
                    detect_new_cases=False,
                )
            except TrainingRunError as error:
                # A legacy fork without lifecycle provenance must not prevent
                # unrelated accounts from opening.
                connection.execute(
                    "INSERT INTO replay_training_isolated_wallet(run_id,balances_json) VALUES (?,?) "
                    "ON CONFLICT(run_id) DO UPDATE SET balances_json=excluded.balances_json",
                    (row["run_id"], canonical_json({"error": str(error)})),
                )
    finally:
        connection.row_factory = previous_factory
