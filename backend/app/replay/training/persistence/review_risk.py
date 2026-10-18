"""Recover relational risk rows at an immutable review boundary.

Review already stores the public case/step state. Internal execution plans and
immutable book/ADL evidence remain in relational storage; join by their identities
instead of copying the parent's later mutable projections.
"""

from ..errors import TrainingRunError


class ReviewRiskSnapshot:
    def __init__(self, cases):
        self.tables = {}
        steps, legs, books, orders, fills, postings, adl, selections, ledger = ([] for _ in range(9))
        risk_ids = set()
        for case in cases:
            case_id = case["case_id"]
            risk_ids.update(value for value in (case["trigger_snapshot_id"], case["final_snapshot_id"]) if value)
            legs.extend({"case_id": case_id, **leg} for leg in case["legs"])
            books.extend(case["book_snapshots"])
            for step in case["steps"]:
                steps.append({"case_id": case_id, **step})
                risk_ids.update(value for value in (step["before_snapshot_id"], step["after_snapshot_id"]) if value)
                for order in step["orders"]:
                    orders.append({"case_id": case_id, **order})
                    fills.extend({"case_id": case_id, "order_id": order["order_id"], **fill} for fill in order["fills"])
                postings.extend(step["insurance_postings"])
                for event in step["adl_events"]:
                    adl.append(event)
                    selections.extend({"adl_event_id": event["adl_event_id"], **item} for item in event["selections"])
                    ledger.extend({"adl_event_id": event["adl_event_id"], **item} for item in event["counterparty_ledger"])
        self.risk_ids = risk_ids
        self.adl_snapshot_ids = {event["snapshot_id"] for event in adl}
        for name, keys, rows in (
            ("liquidation_case", ("case_id",), cases),
            ("liquidation_leg", ("case_id", "liquidation_leg_id"), legs),
            ("liquidation_leg_price_proof", ("case_id", "liquidation_leg_id"), legs),
            ("liquidation_book_snapshot", ("case_id", "track_id"), books),
            ("liquidation_step", ("case_id", "step_sequence"), steps),
            ("liquidation_book_execution", ("case_id", "step_sequence"),
             [step["book_execution"] for step in steps if step["book_execution"] is not None]),
            ("liquidation_order", ("case_id", "order_id"), orders),
            ("liquidation_fill", ("case_id", "order_id", "fill_id"), fills),
            ("insurance_posting", ("posting_id",), postings),
            ("adl_event", ("adl_event_id",), adl),
            ("adl_selection", ("adl_event_id", "selection_sequence"), selections),
            ("adl_counterparty_ledger", ("adl_event_id", "ledger_sequence"), ledger),
        ):
            self.tables[f"replay_training_{name}"] = (keys, {tuple(row[key] for key in keys): row for row in rows})

    def restore(self, table, rows):
        result = []
        for row in rows:
            values = dict(row)
            if table == "replay_training_risk_snapshot":
                if values["snapshot_id"] not in self.risk_ids:
                    continue
            elif table in {"replay_training_adl_snapshot", "replay_training_adl_candidate"}:
                if values["snapshot_id"] not in self.adl_snapshot_ids:
                    continue
            elif table in self.tables:
                keys, index = self.tables[table]
                historical = index.get(tuple(values[key] for key in keys))
                if historical is None:
                    continue
                if table == "replay_training_liquidation_step":
                    # The opaque execution plan must be exactly the one which
                    # produced this selected step, even if it is now APPLIED.
                    if values["step_hash"] != historical["step_hash"]:
                        raise TrainingRunError("REVIEW_RISK_SNAPSHOT_UNAVAILABLE",
                                               "selected liquidation execution plan is unavailable", status_code=409)
                    values["committed_at_ms"] = None if historical["state"] == "PENDING" else values["committed_at_ms"]
                for key, value in historical.items():
                    if key in values and key != "run_id" and not isinstance(value, (list, dict)):
                        if table == "replay_training_liquidation_step" and key == "reason":
                            continue  # Review's public cause omits the execution plan.
                        values[key] = value
            result.append(values)
        return tuple(result)
