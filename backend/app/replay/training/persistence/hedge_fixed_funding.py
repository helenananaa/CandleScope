"""Explicit fixed-model HEDGE funding, owned by the complete-cohort writer."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from decimal import Decimal

from app.replay.broker.models import decimal_to_string

from ..account import SANDBOX_FUNDING_FIDELITY, round_to_step
from ..errors import TrainingRunError
from . import account_math, ledger

FIXED_LEG_SCHEMA = "replay.training.hedge-fixed-funding.v1"


def settle(
    connection: sqlite3.Connection, *, run_id: str,
    virtual_time_ms: int | None, now_ms: int,
) -> None:
    if virtual_time_ms is None:
        return
    account = connection.execute(
        "SELECT a.*,r.settlement_asset FROM replay_training_contract_account a "
        "JOIN replay_training_run r USING(run_id) WHERE run_id=? AND r.position_mode='HEDGE'",
        (run_id,),
    ).fetchone()
    if account is None or account["funding_mode"] != "SANDBOX_FIXED":
        return
    boundary = int(account["next_funding_time_ms"])
    if boundary > virtual_time_ms:
        return
    # The coordinator must visit each calendar boundary before later market or
    # order mutations. Never value several missed periods at today's holdings.
    if boundary < virtual_time_ms:
        raise TrainingRunError("HEDGE_FIXED_FUNDING_BOUNDARY_MISSED",
                               "fixed funding requires its ordered calendar boundary", status_code=409)
    policy = connection.execute(
        "SELECT * FROM replay_training_funding_policy WHERE run_id=? "
        "AND effective_virtual_time_ms<=? ORDER BY revision DESC LIMIT 1",
        (run_id, boundary),
    ).fetchone()
    if policy is None or policy["funding_mode"] != "SANDBOX_FIXED":
        raise TypeError("fixed funding effective policy is missing")
    rate = Decimal(str(policy["fixed_funding_rate"]))
    tracks = connection.execute(
        "SELECT * FROM replay_training_market_track WHERE run_id=? "
        "AND subscription_tier='FULL' ORDER BY stable_ordinal,track_id", (run_id,),
    ).fetchall()
    delta = Decimal(0)
    for track in tracks:
        rule_row = connection.execute(
            "SELECT revision,rule_json FROM replay_training_instrument_rule WHERE run_id=? "
            "AND track_id=? AND effective_virtual_time_ms<=? "
            "ORDER BY effective_virtual_time_ms DESC,revision DESC LIMIT 1",
            (run_id, track["track_id"], boundary),
        ).fetchone()
        if rule_row is None:
            raise TypeError("fixed funding effective rule is missing")
        rule = account_math._stored_instrument_rule(str(rule_row["rule_json"]))
        legs = connection.execute(
            "SELECT * FROM replay_training_position_leg WHERE run_id=? AND track_id=? "
            "ORDER BY CASE position_side WHEN 'LONG' THEN 0 ELSE 1 END",
            (run_id, track["track_id"]),
        ).fetchall()
        if tuple(x["position_side"] for x in legs) != ("LONG", "SHORT"):
            raise TypeError("fixed funding requires both HEDGE legs")
        # The phase-30 mark overlay is authoritative here. Relational leg risk
        # caches are refreshed by the following risk pass and can still contain
        # the previous mark while a same-time market cohort is being finished.
        marked_position = json.loads(str(track["position_json"]))
        for leg in legs:
            quantity = Decimal(str(leg["signed_quantity"]))
            mark = Decimal(str(marked_position[str(leg["position_side"]).lower()]["mark_price"]))
            if quantity and mark <= 0:
                raise TrainingRunError("HISTORICAL_MARK_UNAVAILABLE",
                                       "fixed funding lacks a revealed leg mark", status_code=409)
            raw = -quantity * mark * Decimal(rule.contract_size) * rate
            rounded = round_to_step(abs(raw), Decimal(rule.quote_step), upward=True)
            cash = rounded.copy_sign(raw) if raw else Decimal(0)
            metadata = {
                "schema_version": FIXED_LEG_SCHEMA,
                "position_side": leg["position_side"],
                "pre_settlement_signed_quantity": str(leg["signed_quantity"]),
                "pre_settlement_absolute_quantity": str(leg["absolute_quantity"]),
                "mark_price": decimal_to_string(mark, field_name="fixed funding mark"),
                "rate": str(policy["fixed_funding_rate"]),
                "contract_size": rule.contract_size,
                "rounding": "ABS_CEILING_QUOTE_STEP_THEN_SIGN",
                "funding_policy_revision": int(policy["revision"]),
            }
            # Existing append-only ledger postings are the durable per-leg
            # records; fixed model entries never masquerade as public events.
            ledger.append_contract_ledger(
                connection, run_id=run_id,
                posting_id=f"fixed-hedge-funding:{track['track_id']}:{leg['position_side']}:{boundary}",
                track_id=str(track["track_id"]), kind="FUNDING_SETTLEMENT", cash_delta=cash,
                asset=str(account["settlement_asset"]), virtual_time_ms=boundary,
                source_sequence=int(track["source_sequence"] or 0),
                fidelity=SANDBOX_FUNDING_FIDELITY, rule_revision=int(rule_row["revision"]),
                reference_type="SANDBOX_FIXED_POLICY", reference_id=str(policy["revision"]),
                metadata=metadata, now_ms=now_ms,
            )
            delta += cash
    connection.execute(
        "UPDATE replay_training_contract_account SET overlay_cash=?,next_funding_time_ms=?,"
        "updated_at_ms=? WHERE run_id=?",
        (decimal_to_string(Decimal(account["overlay_cash"]) + delta, field_name="fixed funding cash"),
         boundary + int(policy["funding_interval_ms"]), now_ms, run_id),
    )
    from .account_marks import refresh_hedge_leg_accounting

    for track in tracks:
        refresh_hedge_leg_accounting(connection, run_id=run_id, track_id=str(track["track_id"]),
                                     virtual_time_ms=boundary,
                                     source_sequence=int(track["source_sequence"] or 0),
                                     now_ms=now_ms, reason="FUNDING_SETTLEMENT")


def fixed_leg_postings(
    connection: sqlite3.Connection, run_id: str,
) -> Iterator[tuple[sqlite3.Row, dict[str, object]]]:
    """Read model postings with their explicit per-leg metadata."""
    for row in connection.execute(
        "SELECT * FROM replay_training_contract_ledger WHERE run_id=? "
        "AND kind='FUNDING_SETTLEMENT' AND reference_type='SANDBOX_FIXED_POLICY' "
        "ORDER BY ledger_sequence", (run_id,),
    ).fetchall():
        metadata = json.loads(str(row["metadata_json"]))
        if metadata.get("schema_version") != FIXED_LEG_SCHEMA:
            raise TypeError("fixed HEDGE funding metadata is invalid")
        yield row, metadata
