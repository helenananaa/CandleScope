"""Ledger operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json

from ..account import (
    ledger_chain_hash,
)
from ..errors import TrainingRunError


def contract_posting_order(
    posting: sqlite3.Row, *, require_lifecycle: bool = True
) -> tuple[int, ...]:
    """Economic order across a fork's reconstructed and newly appended receipts."""
    metadata = json.loads(posting["metadata_json"])
    inherited = metadata.get("fork_ledger_order")
    incomplete = metadata.get("fork_ledger_order_incomplete") or (
        inherited is None and metadata.get("fork_parent_run_id") is not None
    )
    if incomplete and require_lifecycle:
        raise TrainingRunError(
            "ISOLATED_LOSS_PROOF_UNAVAILABLE",
            "legacy fork lacks allocation lifecycle order; fork from the original run",
            status_code=409,
        )
    if inherited is None:
        return (1, int(posting["ledger_sequence"]))
    if (
        not isinstance(inherited, list)
        or not inherited
        or any(type(value) is not int or value < 0 for value in inherited)
    ):
        raise TypeError("fork ledger order is invalid")
    return tuple(inherited)


def fork_posting_metadata(
    posting: sqlite3.Row, parent_run_id: str
) -> dict[str, object]:
    # Prefixing keeps every inherited receipt before child activity, and
    # preserves order through repeated forks without consulting an ancestor.
    metadata = json.loads(posting["metadata_json"])
    incomplete = metadata.get("fork_ledger_order_incomplete") or (
        metadata.get("fork_parent_run_id") is not None
        and "fork_ledger_order" not in metadata
    )
    return {
        **({"fork_ledger_order_incomplete": True} if incomplete else {}),
        "fork_parent_run_id": parent_run_id,
        "fork_parent_ledger_sequence": int(posting["ledger_sequence"]),
        "fork_ledger_order": [
            0,
            *contract_posting_order(posting, require_lifecycle=False),
        ],
    }


@dataclass(slots=True)
class _ContractLedgerAppendState:
    next_sequence: int
    tail_hash: str
    dirty: bool = False


def contract_ledger_append_state(
    connection: sqlite3.Connection,
    *,
    run_id: str,
) -> _ContractLedgerAppendState:
    row = connection.execute(
        """
        SELECT account.ledger_tail_hash,
               COALESCE((SELECT ledger.ledger_sequence
                         FROM replay_training_contract_ledger AS ledger
                         WHERE ledger.run_id = account.run_id
                         ORDER BY ledger.ledger_sequence DESC LIMIT 1), 0) + 1 AS next_sequence
        FROM replay_training_contract_account AS account
        WHERE account.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise TypeError("contract account is missing")
    return _ContractLedgerAppendState(
        next_sequence=int(row["next_sequence"]),
        tail_hash=str(row["ledger_tail_hash"]),
    )


def flush_contract_ledger_append_state(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    state: _ContractLedgerAppendState,
    now_ms: int,
) -> None:
    if not state.dirty:
        return
    connection.execute(
        """
        UPDATE replay_training_contract_account
        SET ledger_tail_hash = ?, updated_at_ms = ? WHERE run_id = ?
        """,
        (state.tail_hash, now_ms, run_id),
    )
    state.dirty = False


def append_contract_ledger(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    posting_id: str,
    track_id: str | None,
    kind: str,
    cash_delta: Decimal,
    asset: str,
    virtual_time_ms: int,
    source_sequence: int,
    fidelity: str,
    rule_revision: int,
    reference_type: str,
    reference_id: str,
    metadata: Mapping[str, object],
    now_ms: int,
    append_state: _ContractLedgerAppendState | None = None,
) -> int:
    existing = connection.execute(
        """
        SELECT ledger_sequence FROM replay_training_contract_ledger
        WHERE run_id = ? AND posting_id = ?
        """,
        (run_id, posting_id),
    ).fetchone()
    if existing is not None:
        return int(existing["ledger_sequence"])
    owns_append_state = append_state is None
    state = (
        contract_ledger_append_state(connection, run_id=run_id)
        if append_state is None
        else append_state
    )
    sequence = state.next_sequence
    amount = decimal_to_string(cash_delta, field_name="contract cash_delta")
    posting = {
        "posting_id": posting_id,
        "track_id": track_id,
        "kind": kind,
        "cash_delta": amount,
        "asset": asset,
        "virtual_time_ms": virtual_time_ms,
        "source_sequence": source_sequence,
        "fidelity": fidelity,
        "rule_revision": rule_revision,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "metadata": dict(metadata),
    }
    previous_hash = state.tail_hash
    entry_hash = ledger_chain_hash(
        previous_hash=previous_hash,
        ledger_sequence=sequence,
        posting=posting,
    )
    connection.execute(
        """
        INSERT INTO replay_training_contract_ledger(
            run_id, ledger_sequence, posting_id, track_id, kind,
            cash_delta, asset, virtual_time_ms, source_sequence, fidelity,
            rule_revision, reference_type, reference_id, metadata_json,
            previous_hash, entry_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            sequence,
            posting_id,
            track_id,
            kind,
            amount,
            asset,
            virtual_time_ms,
            source_sequence,
            fidelity,
            rule_revision,
            reference_type,
            reference_id,
            canonical_json(metadata),
            previous_hash,
            entry_hash,
            now_ms,
        ),
    )
    state.next_sequence += 1
    state.tail_hash = entry_hash
    state.dirty = True
    from . import isolated_wallets
    isolated_wallets.append(
        connection, run_id=run_id, track_id=track_id, kind=kind,
        cash_delta=cash_delta, metadata=metadata,
    )
    if owns_append_state:
        flush_contract_ledger_append_state(
            connection,
            run_id=run_id,
            state=state,
            now_ms=now_ms,
        )
    return sequence
