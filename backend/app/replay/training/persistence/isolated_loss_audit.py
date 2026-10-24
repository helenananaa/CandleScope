"""Independent audit of isolated bankruptcy credits from allocation lifecycles and independently checked postings."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation


def audit_isolated_transfers(connection, run_id, ledger_rows, differences):
    def compare(field, expected, actual):
        if expected != actual:
            differences.append(
                {"field": field, "expected": str(expected), "actual": str(actual)}
            )

    def economic_order(posting):
        meta = json.loads(posting["metadata_json"])
        if meta.get("fork_ledger_order_incomplete") or (
            "fork_parent_run_id" in meta and "fork_ledger_order" not in meta
        ):
            raise ValueError("legacy fork allocation order unavailable")
        return tuple(meta.get("fork_ledger_order", [1, posting["ledger_sequence"]]))

    transfers = [
        row for row in ledger_rows if row["kind"] == "ISOLATED_BANKRUPTCY_TRANSFER"
    ]
    known = set()
    total = Decimal(0)
    for case in connection.execute(
        "SELECT * FROM replay_training_liquidation_case WHERE run_id=?",
        (run_id,),
    ):
        case_id = case["case_id"]
        first = connection.execute(
            "SELECT reason FROM replay_training_liquidation_step WHERE run_id=? AND case_id=? AND step_type='CANCEL_ORDERS'",
            (run_id, case_id),
        ).fetchone()
        if (
            first is None
            or json.loads(first["reason"])["plan"].get("scope") != "ISOLATED_LEG"
        ):
            continue
        known.add(case_id)
        prefix = f"isolated_loss[{case_id}]"
        expected_credit = Decimal(0)
        closed = True
        try:
            for leg in connection.execute(
                "SELECT leg.*, proof.mark_price, proof.scope_equity, rule.rule_json "
                "FROM replay_training_liquidation_leg AS leg "
                "LEFT JOIN replay_training_liquidation_leg_price_proof AS proof USING(run_id,case_id,liquidation_leg_id) "
                "LEFT JOIN replay_training_instrument_rule AS rule ON rule.run_id=leg.run_id "
                "AND rule.track_id=leg.track_id AND rule.revision=proof.rule_revision "
                "WHERE leg.run_id=? AND leg.case_id=?",
                (run_id, case_id),
            ):
                fills = connection.execute(
                    "SELECT fill.* FROM replay_training_liquidation_fill AS fill "
                    "JOIN replay_training_liquidation_order AS orders USING(run_id,case_id,order_id) "
                    "WHERE orders.run_id=? AND orders.case_id=? AND orders.liquidation_leg_id=?",
                    (run_id, case_id, leg["liquidation_leg_id"]),
                ).fetchall()
                amount = sum((Decimal(f["quantity"]) for f in fills), Decimal(0))
                if amount != Decimal(leg["trigger_quantity"]):
                    closed = False
                    continue
                end = max(
                    economic_order(posting)
                    for posting in ledger_rows
                    if posting["track_id"] == leg["track_id"]
                    and posting["kind"] == "LIQUIDATION_FEE"
                    and json.loads(posting["metadata_json"]).get("case_id") == case_id
                    and json.loads(posting["metadata_json"]).get("position_side")
                    == leg["position_side"]
                )
                receipts = []
                for posting in ledger_rows:
                    if (
                        posting["track_id"] != leg["track_id"]
                        or posting["kind"]
                        not in {
                            "MARGIN_ALLOCATION",
                            "MARGIN_RELEASE",
                            "TRADING_FEE",
                            "BROKER_REALIZED_PNL",
                            "FUNDING_SETTLEMENT",
                            "LIQUIDATION_FEE",
                            "ISOLATED_BANKRUPTCY_TRANSFER",
                        }
                        or economic_order(posting) > end
                    ):
                        continue
                    meta = json.loads(posting["metadata_json"])
                    side = meta.get("position_side")
                    if posting["kind"] == "BROKER_REALIZED_PNL":
                        fill = connection.execute(
                            "SELECT fill_json FROM replay_training_contract_fill WHERE run_id=? AND track_id=? AND fill_id=?",
                            (run_id, leg["track_id"], meta["fill_id"]),
                        ).fetchone()
                        side = json.loads(fill["fill_json"])["position_side"]
                    if side == leg["position_side"]:
                        receipts.append((posting, meta))
                opening = max(
                    economic_order(posting)
                    for posting, meta in receipts
                    if posting["kind"] == "MARGIN_ALLOCATION"
                    and Decimal(meta["old_allocation"]) == 0
                    and Decimal(meta["new_allocation"]) > 0
                )
                funded = Decimal(0)
                cashflows = Decimal(0)
                for posting, meta in receipts:
                    if economic_order(posting) < opening:
                        continue
                    if (
                        posting["kind"] in {"MARGIN_ALLOCATION", "MARGIN_RELEASE"}
                        and "new_allocation" in meta
                    ):
                        funded += Decimal(meta["new_allocation"]) - Decimal(
                            meta["old_allocation"]
                        )
                    elif posting["kind"] in {
                        "TRADING_FEE",
                        "BROKER_REALIZED_PNL",
                        "FUNDING_SETTLEMENT",
                        "LIQUIDATION_FEE",
                        "ISOLATED_BANKRUPTCY_TRANSFER",
                    }:
                        cashflows += Decimal(posting["cash_delta"])
                expected_credit += max(Decimal(0), -funded - cashflows)
        except (InvalidOperation, TypeError, ValueError, KeyError) as exc:
            compare(
                prefix + ".inputs", "ALLOCATION_LIFECYCLE_AND_EXECUTIONS", type(exc).__name__
            )
            continue
        step = connection.execute(
            "SELECT state,reason FROM replay_training_liquidation_step WHERE run_id=? AND case_id=? AND step_type='BANKRUPTCY_TRANSFER'",
            (run_id, case_id),
        ).fetchone()
        matching = [row for row in transfers if row["reference_id"] == case_id]
        committed = step is not None and step["state"] == "APPLIED"
        if (
            closed
            and expected_credit > 0
            and case["state"] in {"COMPLETED", "BANKRUPT"}
        ):
            compare(prefix + ".bankruptcy_step", True, committed)
        if step is not None and closed:
            compare(
                prefix + ".planned_deficit",
                expected_credit,
                Decimal(json.loads(step["reason"])["plan"]["bankruptcy_deficit"]),
            )
        owed = expected_credit if closed and committed else Decimal(0)
        compare(prefix + ".posting_count", 1 if owed else 0, len(matching))
        for posting in matching:
            compare(prefix + ".posting_amount", owed, Decimal(posting["cash_delta"]))
            compare(
                prefix + ".reference_type",
                "LIQUIDATION_CASE",
                posting["reference_type"],
            )
        total += owed
    for posting in transfers:
        compare(
            f"ledger[{posting['posting_id']}].isolated_case",
            True,
            posting["reference_id"] in known,
        )
    return total
