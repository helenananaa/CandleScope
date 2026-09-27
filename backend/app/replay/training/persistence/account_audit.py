"""Account audit operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from typing import cast

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    InstrumentRule,
    fee_for_notional,
    initial_ledger_hash,
    ledger_chain_hash,
    round_to_step,
)
from ..account_history import (
    ACCOUNT_AUDIT_SCHEMA_VERSION,
)
from ..errors import TrainingRunError
from ..hedge_simulation_contract import (
    ADL_MODEL_VERSION,
    rank_adl_candidates,
    select_adl_candidates,
    settle_insurance_fund,
)
from ..historical_book import (
    HISTORICAL_L2_LIQUIDATION_FIDELITY,
)
from . import account_marks as account_marks_ops
from . import portfolio as portfolio_ops


def audit_exact_account_state(
    connection: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    account: sqlite3.Row,
    ledger_rows: Sequence[sqlite3.Row],
    portfolio: Mapping[str, object],
    differences: list[dict[str, object]],
) -> dict[str, object]:
    """Independently rebuild exact account state from immutable source records."""

    run_id = str(run["run_id"])

    def add_difference(
        field: str,
        expected: object,
        actual: object,
    ) -> None:
        differences.append(
            {
                "field": field,
                "expected": expected,
                "actual": actual,
            }
        )

    def compare_decimal(
        field: str,
        expected: Decimal,
        actual: object,
    ) -> None:
        expected_value = decimal_to_string(expected, field_name=field)
        try:
            actual_decimal = Decimal(str(actual))
        except (InvalidOperation, TypeError, ValueError):
            add_difference(field, expected_value, actual)
            return
        if actual_decimal != expected:
            add_difference(field, expected_value, actual)

    rule_rows = connection.execute(
        """
        SELECT * FROM replay_training_instrument_rule
        WHERE run_id = ? ORDER BY track_id, revision
        """,
        (run_id,),
    ).fetchall()
    rules: dict[tuple[str, int], InstrumentRule] = {}
    rule_times: dict[tuple[str, int], int] = {}
    for row in rule_rows:
        key = (str(row["track_id"]), int(row["revision"]))
        try:
            rule = InstrumentRule.from_mapping(json.loads(str(row["rule_json"])))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            add_difference(
                f"instrument_rule[{key[0]}:{key[1]}]",
                "VALID_VERSIONED_RULE",
                f"INVALID:{type(exc).__name__}",
            )
            continue
        rules[key] = rule
        rule_times[key] = int(row["effective_virtual_time_ms"])
        if rule.rule_hash != row["rule_hash"]:
            add_difference(
                f"instrument_rule[{key[0]}:{key[1]}].rule_hash",
                rule.rule_hash,
                row["rule_hash"],
            )

    policy_rows = connection.execute(
        """
        SELECT * FROM replay_training_fee_policy
        WHERE run_id = ? ORDER BY revision
        """,
        (run_id,),
    ).fetchall()
    policies: dict[int, sqlite3.Row] = {}
    for row in policy_rows:
        revision = int(row["revision"])
        policies[revision] = row
        policy_payload = {
            "schema_version": "replay.training.fee-policy.v1",
            "run_id": run_id,
            "revision": revision,
            "effective_virtual_time_ms": int(row["effective_virtual_time_ms"]),
            "maker_fee_bps": str(row["maker_fee_bps"]),
            "taker_fee_bps": str(row["taker_fee_bps"]),
            "fidelity": str(row["fidelity"]),
        }
        policy_hash = canonical_sha256(policy_payload)
        if policy_hash != row["policy_hash"]:
            add_difference(
                f"fee_policy[{revision}].policy_hash",
                policy_hash,
                row["policy_hash"],
            )

    ledger_by_posting = {str(row["posting_id"]): row for row in ledger_rows}
    ledger_by_sequence = {int(row["ledger_sequence"]): row for row in ledger_rows}
    expected_postings: set[str] = set()
    initial = Decimal(str(run["initial_equity"]))
    settlement_asset = str(run["settlement_asset"])
    initial_posting = ledger_by_posting.get("initial-capital")
    if initial_posting is None:
        add_difference("ledger.initial-capital", "PRESENT", "MISSING")
    else:
        expected_postings.add("initial-capital")
        compare_decimal(
            "ledger.initial-capital.cash_delta",
            initial,
            initial_posting["cash_delta"],
        )
        if initial_posting["asset"] != settlement_asset:
            add_difference(
                "ledger.initial-capital.asset",
                settlement_asset,
                initial_posting["asset"],
            )

    fill_rows = connection.execute(
        """
        SELECT * FROM replay_training_contract_fill
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    fills: list[tuple[sqlite3.Row, Mapping[str, object]]] = []
    for row in fill_rows:
        try:
            raw = json.loads(str(row["fill_json"]))
        except json.JSONDecodeError as exc:
            add_difference(
                f"fill[{row['track_id']}:{row['fill_id']}].json",
                "VALID_JSON_OBJECT",
                f"INVALID:{type(exc).__name__}",
            )
            continue
        if not isinstance(raw, Mapping):
            add_difference(
                f"fill[{row['track_id']}:{row['fill_id']}].json",
                "JSON_OBJECT",
                type(raw).__name__,
            )
            continue
        fills.append((row, raw))
    fills.sort(
        key=lambda item: (
            int(item[1].get("event_time_ms", 0)),
            int(item[1].get("source_sequence", 0)),
            str(item[0]["track_id"]),
            str(item[0]["fill_id"]),
        )
    )

    position_state: dict[str, dict[str, Decimal | None]] = {}
    broker_fees_by_track: dict[str, Decimal] = {}
    configured_fees = Decimal(0)
    realized_total = Decimal(0)
    realized_by_fill: dict[tuple[str, str], Decimal] = {}

    def apply_fill(
        *,
        state: dict[str, Decimal | None],
        side: str,
        quantity: Decimal,
        price: Decimal,
        contract_size: Decimal,
    ) -> Decimal:
        old_quantity = cast(Decimal, state["quantity"])
        old_entry = cast(Decimal | None, state["entry_price"])
        delta = quantity if side == "BUY" else -quantity
        new_quantity = old_quantity + delta
        realized = Decimal(0)
        with localcontext() as context:
            context.prec = 60
            if old_quantity == 0:
                new_entry: Decimal | None = price
            elif old_quantity * delta > 0:
                if old_entry is None:
                    raise TypeError("non-flat audited position has no entry")
                new_entry = (abs(old_quantity) * old_entry + abs(delta) * price) / abs(
                    new_quantity
                )
            else:
                if old_entry is None:
                    raise TypeError("non-flat audited position has no entry")
                closed = min(abs(old_quantity), abs(delta))
                realized = (
                    (price - old_entry)
                    * closed
                    * (Decimal(1) if old_quantity > 0 else Decimal(-1))
                    * contract_size
                )
                if new_quantity == 0:
                    new_entry = None
                elif old_quantity * new_quantity > 0:
                    new_entry = old_entry
                else:
                    new_entry = price
        state["quantity"] = new_quantity
        state["entry_price"] = new_entry
        state["realized_pnl"] = cast(Decimal, state["realized_pnl"]) + realized
        return realized

    for row, raw in fills:
        track_id = str(row["track_id"])
        fill_id = str(row["fill_id"])
        field_prefix = f"fill[{track_id}:{fill_id}]"
        rule_revision = int(row["rule_revision"])
        fee_revision = int(row["fee_policy_revision"])
        rule = rules.get((track_id, rule_revision))
        policy = policies.get(fee_revision)
        if rule is None:
            add_difference(
                f"{field_prefix}.rule_revision",
                "EXISTING_RULE",
                rule_revision,
            )
            continue
        if policy is None:
            add_difference(
                f"{field_prefix}.fee_policy_revision",
                "EXISTING_POLICY",
                fee_revision,
            )
            continue
        try:
            quantity = Decimal(str(raw["quantity"]))
            price = Decimal(str(raw["price"]))
            broker_notional = Decimal(str(raw["notional"]))
            contract_size = Decimal(rule.contract_size)
            account_notional = quantity * price * contract_size
            if broker_notional != quantity * price:
                compare_decimal(
                    f"{field_prefix}.notional",
                    quantity * price,
                    raw["notional"],
                )
            compare_decimal(
                f"{field_prefix}.account_notional",
                account_notional,
                raw.get("account_notional"),
            )
            if raw.get("contract_size") != rule.contract_size:
                add_difference(
                    f"{field_prefix}.contract_size",
                    rule.contract_size,
                    raw.get("contract_size"),
                )
            configured_fee = fee_for_notional(
                notional=account_notional,
                liquidity=str(raw["liquidity"]),
                maker_bps=str(policy["maker_fee_bps"]),
                taker_bps=str(policy["taker_fee_bps"]),
                quote_step=rule.quote_step,
            )
            compare_decimal(
                f"{field_prefix}.configured_fee",
                configured_fee,
                row["configured_fee"],
            )
            configured_fees += configured_fee
            broker_fee = Decimal(str(raw["fee"]))
            broker_fees_by_track[track_id] = (
                broker_fees_by_track.get(track_id, Decimal(0)) + broker_fee
            )
            state = position_state.setdefault(
                track_id,
                {
                    "quantity": Decimal(0),
                    "entry_price": None,
                    "realized_pnl": Decimal(0),
                },
            )
            realized = apply_fill(
                state=state,
                side=str(raw["side"]),
                quantity=quantity,
                price=price,
                contract_size=contract_size,
            )
            realized_total += realized
            realized_by_fill[(track_id, fill_id)] = realized
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            add_difference(
                field_prefix,
                "VALID_REPLAY_FILL",
                f"INVALID:{type(exc).__name__}",
            )
            continue

        fee_posting_id = f"fee:{track_id}:{fill_id}"
        fee_posting = ledger_by_posting.get(fee_posting_id)
        if fee_posting is None:
            add_difference(
                f"ledger[{fee_posting_id}]",
                "PRESENT",
                "MISSING",
            )
        else:
            expected_postings.add(fee_posting_id)
            compare_decimal(
                f"ledger[{fee_posting_id}].cash_delta",
                -configured_fee,
                fee_posting["cash_delta"],
            )
            if int(fee_posting["rule_revision"]) != rule_revision:
                add_difference(
                    f"ledger[{fee_posting_id}].rule_revision",
                    rule_revision,
                    int(fee_posting["rule_revision"]),
                )

    realized_ledger_by_fill: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in ledger_rows:
        if row["kind"] != "BROKER_REALIZED_PNL":
            continue
        try:
            metadata = json.loads(str(row["metadata_json"]))
        except json.JSONDecodeError:
            metadata = None
        fill_id = metadata.get("fill_id") if isinstance(metadata, Mapping) else None
        if isinstance(fill_id, str) and isinstance(row["track_id"], str):
            realized_ledger_by_fill.setdefault(
                (str(row["track_id"]), fill_id),
                [],
            ).append(row)
    for key, realized in realized_by_fill.items():
        postings = realized_ledger_by_fill.get(key, [])
        if realized == 0:
            if postings:
                add_difference(
                    f"realized_ledger[{key[0]}:{key[1]}].count",
                    0,
                    len(postings),
                )
            continue
        if len(postings) != 1:
            add_difference(
                f"realized_ledger[{key[0]}:{key[1]}].count",
                1,
                len(postings),
            )
            continue
        posting = postings[0]
        posting_id = str(posting["posting_id"])
        expected_postings.add(posting_id)
        compare_decimal(
            f"ledger[{posting_id}].cash_delta",
            realized,
            posting["cash_delta"],
        )

    funding_total = Decimal(0)
    funding_rows = connection.execute(
        """
        SELECT * FROM replay_training_funding_settlement
        WHERE run_id = ? ORDER BY settlement_time_ms, track_id
        """,
        (run_id,),
    ).fetchall()
    for row in funding_rows:
        track_id = str(row["track_id"])
        field_prefix = f"funding[{track_id}:{int(row['settlement_time_ms'])}]"
        ledger = ledger_by_sequence.get(int(row["ledger_sequence"]))
        if ledger is None:
            add_difference(
                f"{field_prefix}.ledger_sequence",
                "LINKED_LEDGER_ENTRY",
                int(row["ledger_sequence"]),
            )
            continue
        posting_id = str(ledger["posting_id"])
        expected_postings.add(posting_id)
        rule = rules.get((track_id, int(ledger["rule_revision"])))
        if rule is None:
            add_difference(
                f"{field_prefix}.rule_revision",
                "EXISTING_RULE",
                int(ledger["rule_revision"]),
            )
            continue
        try:
            quantity = Decimal(str(row["position_quantity"]))
            mark = Decimal(str(row["mark_price"]))
            rate = Decimal(str(row["funding_rate"]))
            raw_delta = -quantity * mark * Decimal(rule.contract_size) * rate
            rounded = round_to_step(
                abs(raw_delta),
                Decimal(rule.quote_step),
                upward=True,
            )
            expected_delta = rounded.copy_sign(raw_delta) if raw_delta else Decimal(0)
        except (InvalidOperation, TypeError, ValueError) as exc:
            add_difference(
                field_prefix,
                "VALID_EXACT_FUNDING",
                f"INVALID:{type(exc).__name__}",
            )
            continue
        compare_decimal(
            f"{field_prefix}.cash_delta",
            expected_delta,
            row["cash_delta"],
        )
        compare_decimal(
            f"ledger[{posting_id}].cash_delta",
            expected_delta,
            ledger["cash_delta"],
        )
        if ledger["kind"] != "FUNDING_SETTLEMENT":
            add_difference(
                f"ledger[{posting_id}].kind",
                "FUNDING_SETTLEMENT",
                ledger["kind"],
            )
        funding_total += expected_delta

    allocation_state: dict[str, Decimal] = {}
    for row in ledger_rows:
        if row["kind"] not in {"MARGIN_ALLOCATION", "MARGIN_RELEASE"}:
            continue
        expected_postings.add(str(row["posting_id"]))
        compare_decimal(
            f"ledger[{row['posting_id']}].cash_delta",
            Decimal(0),
            row["cash_delta"],
        )
        track_id = row["track_id"]
        if not isinstance(track_id, str):
            add_difference(
                f"ledger[{row['posting_id']}].track_id",
                "TRACK_ID",
                track_id,
            )
            continue
        try:
            metadata = json.loads(str(row["metadata_json"]))
        except json.JSONDecodeError:
            metadata = None
        target = (
            metadata.get("new_allocation") if isinstance(metadata, Mapping) else None
        )
        if target is None:
            allocation_state.pop(track_id, None)
            continue
        try:
            amount = Decimal(str(target))
        except (InvalidOperation, TypeError, ValueError):
            add_difference(
                f"ledger[{row['posting_id']}].new_allocation",
                "DECIMAL",
                target,
            )
            continue
        if amount == 0:
            allocation_state.pop(track_id, None)
        else:
            allocation_state[track_id] = amount

    liquidation_total = Decimal(0)
    liquidation_rows = connection.execute(
        """
        SELECT case_row.*, leg.liquidation_leg_id, leg.track_id,
               leg.position_side, leg.trigger_quantity,
               leg.trigger_notional, leg.maintenance_margin,
               leg.bankruptcy_price, leg.liquidation_fee,
               leg.state AS leg_state
        FROM replay_training_liquidation_case AS case_row
        JOIN replay_training_liquidation_leg AS leg
          ON leg.run_id = case_row.run_id AND leg.case_id = case_row.case_id
        WHERE case_row.run_id = ?
        ORDER BY case_row.case_sequence, leg.leg_sequence
        """,
        (run_id,),
    ).fetchall()
    pending_case_ids: set[str] = set()
    bankrupt = False
    case_fees: dict[str, Decimal] = {}
    for row in liquidation_rows:
        liquidation_id = str(row["case_id"])
        track_id = str(row["track_id"])
        position_side = str(row["position_side"])
        field_prefix = f"liquidation[{liquidation_id}].leg[{position_side}]"
        rule_candidates = [
            (key, rule)
            for key, rule in rules.items()
            if key[0] == track_id
            and rule_times[key] <= int(row["trigger_virtual_time_ms"])
        ]
        rule = (
            None
            if not rule_candidates
            else max(
                rule_candidates,
                key=lambda item: (rule_times[item[0]], item[0][1]),
            )[1]
        )
        if rule is None:
            add_difference(
                f"{field_prefix}.rule",
                "ACTIVE_RULE",
                "MISSING",
            )
            continue
        try:
            notional = Decimal(str(row["trigger_notional"]))
            expected_maintenance = rule.maintenance_margin(
                notional,
                extend_last_tier=True,
            )
            expected_fee = rule.liquidation_fee(notional)
        except (InvalidOperation, TypeError, ValueError) as exc:
            add_difference(
                field_prefix,
                "VALID_LIQUIDATION_INPUTS",
                f"INVALID:{type(exc).__name__}",
            )
            continue
        compare_decimal(
            f"{field_prefix}.maintenance_margin",
            expected_maintenance,
            row["maintenance_margin"],
        )
        compare_decimal(
            f"{field_prefix}.liquidation_fee",
            expected_fee,
            row["liquidation_fee"],
        )
        try:
            quantity = Decimal(str(row["trigger_quantity"]))
            if quantity <= 0:
                raise ValueError("liquidation leg quantity is not positive")
            if row["bankruptcy_price"] is None:
                raise ValueError("liquidation leg bankruptcy price is missing")
            Decimal(str(row["bankruptcy_price"]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            add_difference(
                f"{field_prefix}.bankruptcy_reconstruction",
                "PER_LEG_CANONICAL_DECIMAL",
                f"INVALID:{type(exc).__name__}",
            )
        case_fees.setdefault(liquidation_id, Decimal(0))
        if row["state"] not in {
            "COMPLETED",
            "BANKRUPT",
            "FAILED_CLOSED",
            "RECOVERED_AFTER_CANCEL",
        }:
            pending_case_ids.add(liquidation_id)
        bankrupt = bankrupt or row["state"] == "BANKRUPT"

    for liquidation_id in case_fees:
        state = next(
            str(row["state"])
            for row in liquidation_rows
            if str(row["case_id"]) == liquidation_id
        )
        if state != "COMPLETED":
            continue
        fill_fees = [
            Decimal(str(row["liquidation_fee"]))
            for row in connection.execute(
                """
                SELECT liquidation_fee
                FROM replay_training_liquidation_fill
                WHERE run_id = ? AND case_id = ?
                """,
                (run_id, liquidation_id),
            ).fetchall()
        ]
        expected_fee = sum(fill_fees, Decimal(0))
        matching_postings = [
            row
            for posting_id, row in ledger_by_posting.items()
            if posting_id == f"liquidation-fee:{liquidation_id}"
            or posting_id.startswith(f"liquidation-fee:{liquidation_id}:")
        ]
        if not matching_postings and expected_fee != 0:
            add_difference(
                f"ledger[liquidation-fee:{liquidation_id}]",
                "PRESENT",
                "MISSING",
            )
        actual_fee = Decimal(0)
        for posting in matching_postings:
            posting_id = str(posting["posting_id"])
            expected_postings.add(posting_id)
            actual_fee -= Decimal(str(posting["cash_delta"]))
        compare_decimal(
            f"ledger[liquidation-fee:{liquidation_id}].cash_delta",
            expected_fee,
            actual_fee,
        )
        liquidation_total -= expected_fee
    pending_liquidations = len(pending_case_ids)

    for row in ledger_rows:
        posting_id = str(row["posting_id"])
        if row["kind"] == "POLICY_REVISION":
            expected_postings.add(posting_id)
            compare_decimal(
                f"ledger[{posting_id}].cash_delta",
                Decimal(0),
                row["cash_delta"],
            )
        if posting_id not in expected_postings and Decimal(str(row["cash_delta"])) != 0:
            add_difference(
                f"ledger[{posting_id}].source_link",
                "SOURCE_BACKED_POSTING",
                str(row["kind"]),
            )

    raw_tracks = connection.execute(
        """
        SELECT * FROM replay_training_market_track
        WHERE run_id = ? ORDER BY stable_ordinal, track_id
        """,
        (run_id,),
    ).fetchall()
    projections = {
        str(row["track_id"]): row
        for row in connection.execute(
            """
            SELECT * FROM replay_account_history_projection
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    }
    active_rule_policy = connection.execute(
        """
        SELECT max_leverage
        FROM replay_training_leverage_policy
        WHERE run_id = ?
        ORDER BY effective_virtual_time_ms DESC, source_sequence DESC,
                 revision DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if active_rule_policy is None:
        raise TypeError("training leverage policy is missing")
    configured_max_leverage = Decimal(str(active_rule_policy["max_leverage"]))
    expected_unrealized = Decimal(0)
    expected_margin = Decimal(0)
    expected_reserved = Decimal(0)
    expected_maintenance = Decimal(0)
    per_track: list[dict[str, object]] = []
    for track in raw_tracks:
        track_id = str(track["track_id"])
        if track["subscription_tier"] != "FULL":
            continue
        state = position_state.get(
            track_id,
            {
                "quantity": Decimal(0),
                "entry_price": None,
                "realized_pnl": Decimal(0),
            },
        )
        quantity = cast(Decimal, state["quantity"])
        entry = cast(Decimal | None, state["entry_price"])
        realized = cast(Decimal, state["realized_pnl"])
        current_rules = [
            (key, rule)
            for key, rule in rules.items()
            if key[0] == track_id
            and rule_times[key] <= int(track["virtual_time_ms"] or 0)
        ]
        active_rule = (
            None
            if not current_rules
            else max(
                current_rules,
                key=lambda item: (rule_times[item[0]], item[0][1]),
            )[1]
        )
        projection = projections.get(track_id)
        if active_rule is None or projection is None:
            add_difference(
                f"track[{track_id}].exact_inputs",
                "ACTIVE_RULE_AND_MARK_PROJECTION",
                "MISSING",
            )
            continue
        if projection["status"] != "READY" or projection["mark_price"] is None:
            add_difference(
                f"track[{track_id}].mark",
                "READY_AUTHORITATIVE_MARK",
                f"{projection['status']}:{projection['mark_price']}",
            )
            continue
        mark = Decimal(str(projection["mark_price"]))
        contract_size = Decimal(active_rule.contract_size)
        notional = abs(quantity) * mark * contract_size
        unrealized = (
            Decimal(0)
            if quantity == 0 or entry is None
            else (mark - entry) * quantity * contract_size
        )
        leverage = min(
            configured_max_leverage,
            Decimal(active_rule.max_leverage),
        )
        broker_margin = notional / leverage
        margin = active_rule.initial_margin(notional, leverage)
        maintenance = active_rule.maintenance_margin(
            notional,
            extend_last_tier=True,
        )
        open_orders = json.loads(str(track["open_orders_json"]))
        broker_reserved = Decimal(0)
        reserved = Decimal(0)
        if not isinstance(open_orders, list):
            add_difference(
                f"track[{track_id}].open_orders",
                "JSON_ARRAY",
                type(open_orders).__name__,
            )
            open_orders = []
        for order in open_orders:
            if not isinstance(order, Mapping) or order.get("status") in {
                "FILLED",
                "CANCELED",
                "REJECTED",
                "EXPIRED",
            }:
                continue
            order_quantity = Decimal(
                str(order.get("remaining_quantity") or order.get("quantity") or "0")
            )
            reference = order.get("limit_price") or order.get("stop_price") or mark
            order_notional = (
                abs(order_quantity) * Decimal(str(reference)) * contract_size
            )
            order_leverage = min(
                Decimal(str(order.get("leverage") or leverage)),
                configured_max_leverage,
                Decimal(active_rule.max_leverage),
            )
            broker_reserved += order_notional / order_leverage
            reserved += active_rule.initial_margin(
                order_notional,
                order_leverage,
            )
        expected_unrealized += unrealized
        expected_margin += margin
        expected_reserved += reserved
        expected_maintenance += maintenance
        expected_track_cash = (
            initial + realized - broker_fees_by_track.get(track_id, Decimal(0))
        )
        position = json.loads(str(track["position_json"]))
        track_account = json.loads(str(track["account_json"]))
        if not isinstance(position, Mapping) or not isinstance(track_account, Mapping):
            add_difference(
                f"track[{track_id}].projection",
                "POSITION_AND_ACCOUNT_OBJECTS",
                "INVALID",
            )
            continue
        compare_decimal(
            f"track[{track_id}].position.quantity",
            quantity,
            position.get("quantity"),
        )
        expected_entry = (
            None
            if entry is None
            else decimal_to_string(entry, field_name="audited entry")
        )
        if (
            position.get("entry_price") is not None or expected_entry is not None
        ) and str(position.get("entry_price")) != str(expected_entry):
            add_difference(
                f"track[{track_id}].position.entry_price",
                expected_entry,
                position.get("entry_price"),
            )
        for field, expected, actual in (
            ("mark_price", mark, position.get("mark_price")),
            ("notional", notional, position.get("notional")),
            ("realized_pnl", realized, position.get("realized_pnl")),
            (
                "unrealized_pnl",
                unrealized,
                position.get("unrealized_pnl"),
            ),
            (
                "cash_balance",
                expected_track_cash,
                track_account.get("cash_balance"),
            ),
            (
                "equity",
                expected_track_cash + unrealized,
                track_account.get("equity"),
            ),
            (
                "margin_used",
                broker_margin,
                track_account.get("margin_used"),
            ),
            (
                "reserved_margin",
                broker_reserved,
                track_account.get("reserved_margin"),
            ),
            (
                "available_equity",
                expected_track_cash + unrealized - broker_margin - broker_reserved,
                track_account.get("available_equity"),
            ),
            (
                "realized_pnl",
                realized,
                track_account.get("realized_pnl"),
            ),
            (
                "unrealized_pnl",
                unrealized,
                track_account.get("unrealized_pnl"),
            ),
            (
                "fees_paid",
                broker_fees_by_track.get(track_id, Decimal(0)),
                track_account.get("fees_paid"),
            ),
        ):
            compare_decimal(
                f"track[{track_id}].{field}",
                expected,
                actual,
            )
        per_track.append(
            {
                "track_id": track_id,
                "quantity": decimal_to_string(quantity, field_name="audited quantity"),
                "entry_price": expected_entry,
                "mark_price": decimal_to_string(mark, field_name="audited mark"),
                "realized_pnl": decimal_to_string(
                    realized, field_name="audited realized pnl"
                ),
                "unrealized_pnl": decimal_to_string(
                    unrealized, field_name="audited unrealized pnl"
                ),
                "notional": decimal_to_string(notional, field_name="audited notional"),
                "margin_used": decimal_to_string(margin, field_name="audited margin"),
                "maintenance_margin": decimal_to_string(
                    maintenance, field_name="audited maintenance"
                ),
            }
        )

    expected_cash = (
        initial + realized_total - configured_fees + funding_total + liquidation_total
    )
    expected_equity = expected_cash + expected_unrealized
    expected_available = (
        expected_equity - expected_margin - expected_reserved
        if account["margin_mode"] == "CROSS"
        else expected_equity - sum(allocation_state.values(), Decimal(0))
    )
    expected_overlay = (
        sum(broker_fees_by_track.values(), Decimal(0))
        - configured_fees
        + funding_total
        + liquidation_total
    )
    expected_status = (
        "LIQUIDATING" if pending_liquidations else "BANKRUPT" if bankrupt else "ACTIVE"
    )
    compare_decimal(
        "contract_account.overlay_cash",
        expected_overlay,
        account["overlay_cash"],
    )
    expected_allocations = {
        key: decimal_to_string(value, field_name="audited allocation")
        for key, value in sorted(allocation_state.items())
    }
    try:
        actual_allocations = json.loads(str(account["isolated_margin_json"]))
    except json.JSONDecodeError:
        actual_allocations = "INVALID_JSON"
    if expected_allocations != actual_allocations:
        add_difference(
            "contract_account.isolated_margin",
            expected_allocations,
            actual_allocations,
        )
    if account["status"] != expected_status:
        add_difference(
            "contract_account.status",
            expected_status,
            account["status"],
        )
    for field, expected in (
        ("cash_balance", expected_cash),
        ("equity", expected_equity),
        ("available_equity", expected_available),
        ("reserved_margin", expected_reserved),
        ("margin_used", expected_margin),
        ("maintenance_margin", expected_maintenance),
        ("realized_pnl", realized_total),
        ("unrealized_pnl", expected_unrealized),
        ("fees_paid", configured_fees),
        ("funding_cashflow", funding_total),
        ("liquidation_fees_paid", -liquidation_total),
    ):
        compare_decimal(
            f"portfolio.{field}",
            expected,
            portfolio.get(field),
        )
    if portfolio.get("status") != expected_status:
        add_difference(
            "portfolio.status",
            expected_status,
            portfolio.get("status"),
        )
    return {
        "initial_equity": decimal_to_string(
            initial, field_name="audited initial equity"
        ),
        "cash_balance": decimal_to_string(
            expected_cash, field_name="audited cash balance"
        ),
        "equity": decimal_to_string(expected_equity, field_name="audited equity"),
        "available_equity": decimal_to_string(
            expected_available, field_name="audited available equity"
        ),
        "reserved_margin": decimal_to_string(
            expected_reserved, field_name="audited reserved margin"
        ),
        "margin_used": decimal_to_string(
            expected_margin, field_name="audited margin used"
        ),
        "maintenance_margin": decimal_to_string(
            expected_maintenance,
            field_name="audited maintenance margin",
        ),
        "realized_pnl": decimal_to_string(
            realized_total, field_name="audited realized pnl"
        ),
        "unrealized_pnl": decimal_to_string(
            expected_unrealized, field_name="audited unrealized pnl"
        ),
        "configured_fees": decimal_to_string(
            configured_fees, field_name="audited configured fees"
        ),
        "funding_cashflow": decimal_to_string(
            funding_total, field_name="audited funding"
        ),
        "liquidation_fees_paid": decimal_to_string(
            -liquidation_total, field_name="audited liquidation fees"
        ),
        "status": expected_status,
        "isolated_allocations": expected_allocations,
        "positions": per_track,
        "source_counts": {
            "fills": len(fills),
            "funding_settlements": len(funding_rows),
            "liquidations": len(liquidation_rows),
            "instrument_rules": len(rule_rows),
            "fee_policies": len(policy_rows),
            "ledger_entries": len(ledger_rows),
        },
    }


def audit_hedge_account_state(
    connection: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    account: sqlite3.Row,
    ledger_rows: Sequence[sqlite3.Row],
    portfolio: Mapping[str, object],
    differences: list[dict[str, object]],
) -> dict[str, object]:
    """Rebuild both HEDGE legs from fills and pinned public settlements."""

    run_id = str(run["run_id"])

    def add_difference(field: str, expected: object, actual: object) -> None:
        differences.append({"field": field, "expected": expected, "actual": actual})

    def compare_decimal(field: str, expected: Decimal, actual: object) -> None:
        expected_value = decimal_to_string(expected, field_name=field)
        try:
            value = Decimal(str(actual))
        except (InvalidOperation, TypeError, ValueError):
            add_difference(field, expected_value, actual)
            return
        if value != expected:
            add_difference(field, expected_value, actual)

    rules: dict[tuple[str, int], InstrumentRule] = {}
    for row in connection.execute(
        """
        SELECT * FROM replay_training_instrument_rule
        WHERE run_id = ? ORDER BY track_id, revision
        """,
        (run_id,),
    ).fetchall():
        key = (str(row["track_id"]), int(row["revision"]))
        try:
            rule = InstrumentRule.from_mapping(json.loads(str(row["rule_json"])))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            add_difference(
                f"instrument_rule[{key[0]}:{key[1]}]",
                "VALID_VERSIONED_RULE",
                f"INVALID:{type(exc).__name__}",
            )
            continue
        rules[key] = rule
        if rule.rule_hash != row["rule_hash"]:
            add_difference(
                f"instrument_rule[{key[0]}:{key[1]}].rule_hash",
                rule.rule_hash,
                row["rule_hash"],
            )

    policies: dict[int, sqlite3.Row] = {}
    for row in connection.execute(
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
        WHERE policy.run_id = ? ORDER BY policy.revision
        """,
        (run_id,),
    ).fetchall():
        revision = int(row["revision"])
        policies[revision] = row
        if row["policy_version"] is None:
            add_difference(
                f"fee_policy[{revision}].extension",
                "PRESENT",
                "MISSING",
            )
            continue
        policy_payload = {
            "schema_version": "replay.training.fee-policy.v1",
            "run_id": run_id,
            "revision": revision,
            "effective_virtual_time_ms": int(row["effective_virtual_time_ms"]),
            "maker_fee_bps": str(row["maker_fee_bps"]),
            "taker_fee_bps": str(row["taker_fee_bps"]),
            "liquidation_fee_bps": str(row["liquidation_fee_bps"]),
            "policy_version": str(row["policy_version"]),
            "account_tier": str(row["account_tier"]),
            "fidelity": str(row["fidelity"]),
        }
        expected_policy_hash = canonical_sha256(policy_payload)
        if expected_policy_hash != row["policy_hash"]:
            add_difference(
                f"fee_policy[{revision}].policy_hash",
                expected_policy_hash,
                row["policy_hash"],
            )
        extension_payload = {
            "schema_version": "replay.training.fee-policy-extension.v1",
            "run_id": run_id,
            "revision": revision,
            "policy_version": str(row["policy_version"]),
            "account_tier": str(row["account_tier"]),
            "liquidation_fee_bps": str(row["liquidation_fee_bps"]),
            "source_kind": str(row["source_kind"]),
            "source_id": str(row["source_id"]),
            "source_event_sequence": int(row["source_event_sequence"]),
        }
        expected_extension_hash = canonical_sha256(extension_payload)
        if expected_extension_hash != row["extension_hash"]:
            add_difference(
                f"fee_policy[{revision}].extension_hash",
                expected_extension_hash,
                row["extension_hash"],
            )

    ledger_by_sequence = {int(row["ledger_sequence"]): row for row in ledger_rows}
    ledger_by_posting = {str(row["posting_id"]): row for row in ledger_rows}

    def causal_ledger_sequence(
        ledger: sqlite3.Row,
        metadata: Mapping[str, object],
    ) -> int:
        child_sequence = int(ledger["ledger_sequence"])
        raw_parent_sequence = metadata.get("fork_parent_ledger_sequence")
        if raw_parent_sequence is None:
            return child_sequence
        parent_run_id = metadata.get("fork_parent_run_id")
        field = f"ledger[{ledger['posting_id']}].fork_parent_ledger_sequence"
        if (
            isinstance(raw_parent_sequence, bool)
            or not isinstance(raw_parent_sequence, int)
            or raw_parent_sequence < 1
            or not isinstance(parent_run_id, str)
            or not parent_run_id
        ):
            add_difference(field, "VALID_PARENT_SEQUENCE", raw_parent_sequence)
            return child_sequence
        parent = connection.execute(
            """
            SELECT kind, reference_type, reference_id
            FROM replay_training_contract_ledger
            WHERE run_id = ? AND ledger_sequence = ?
            """,
            (parent_run_id, raw_parent_sequence),
        ).fetchone()
        if (
            parent is None
            or parent["kind"] != ledger["kind"]
            or parent["reference_type"] != ledger["reference_type"]
            or parent["reference_id"] != ledger["reference_id"]
        ):
            add_difference(field, "MATCHING_IMMUTABLE_PARENT_POSTING", "MISSING")
        return raw_parent_sequence

    fill_events: dict[
        int,
        tuple[sqlite3.Row, Mapping[str, object], int],
    ] = {}
    configured_fee_by_leg: dict[tuple[str, str], Decimal] = {}
    broker_fee_total = Decimal(0)
    configured_fee_total = Decimal(0)
    for row in connection.execute(
        """
        SELECT * FROM replay_training_contract_fill
        WHERE run_id = ? ORDER BY track_id, fill_id
        """,
        (run_id,),
    ).fetchall():
        track_id = str(row["track_id"])
        fill_id = str(row["fill_id"])
        prefix = f"fill[{track_id}:{fill_id}]"
        try:
            raw = json.loads(str(row["fill_json"]))
        except json.JSONDecodeError as exc:
            add_difference(prefix, "VALID_FILL", f"INVALID:{type(exc).__name__}")
            continue
        if not isinstance(raw, Mapping):
            add_difference(prefix, "JSON_OBJECT", type(raw).__name__)
            continue
        position_side = raw.get("position_side")
        if position_side not in {"LONG", "SHORT"}:
            add_difference(
                f"{prefix}.position_side",
                "LONG_OR_SHORT",
                position_side,
            )
            continue
        rule = rules.get((track_id, int(row["rule_revision"])))
        policy = policies.get(int(row["fee_policy_revision"]))
        if rule is None or policy is None or policy["policy_version"] is None:
            add_difference(
                f"{prefix}.effective_policy",
                "EXISTING_COMPLETE_RULE_AND_FEE_POLICY",
                "MISSING",
            )
            continue
        try:
            quantity = Decimal(str(raw["quantity"]))
            price = Decimal(str(raw["price"]))
            notional = quantity * price * Decimal(rule.contract_size)
            expected_fee = fee_for_notional(
                notional=notional,
                liquidity=str(raw["liquidity"]),
                maker_bps=str(policy["maker_fee_bps"]),
                taker_bps=str(policy["taker_fee_bps"]),
                quote_step=rule.quote_step,
            )
            compare_decimal(
                f"{prefix}.configured_fee", expected_fee, row["configured_fee"]
            )
            broker_fee_total += Decimal(str(raw["fee"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            add_difference(prefix, "VALID_HEDGE_FILL", f"INVALID:{type(exc).__name__}")
            continue
        configured_fee_total += expected_fee
        leg_key = (track_id, str(position_side))
        configured_fee_by_leg[leg_key] = (
            configured_fee_by_leg.get(leg_key, Decimal(0)) + expected_fee
        )
        posting_id = f"fee:{track_id}:{fill_id}"
        posting = ledger_by_posting.get(posting_id)
        if posting is None:
            add_difference(f"ledger[{posting_id}]", "PRESENT", "MISSING")
            continue
        compare_decimal(
            f"ledger[{posting_id}].cash_delta",
            -expected_fee,
            posting["cash_delta"],
        )
        try:
            metadata = json.loads(str(posting["metadata_json"]))
        except json.JSONDecodeError:
            metadata = None
        for field, expected in (
            ("position_side", position_side),
            ("fee_policy_revision", int(row["fee_policy_revision"])),
            ("fee_policy_version", policy["policy_version"]),
            ("account_tier", policy["account_tier"]),
            ("liquidation_fee_bps", policy["liquidation_fee_bps"]),
        ):
            actual = metadata.get(field) if isinstance(metadata, Mapping) else None
            if actual != expected:
                add_difference(
                    f"ledger[{posting_id}].{field}",
                    expected,
                    actual,
                )
        fill_events[int(posting["ledger_sequence"])] = (
            row,
            raw,
            causal_ledger_sequence(posting, metadata or {}),
        )

    funding_rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_hedge_funding_settlement
            WHERE run_id = ? ORDER BY ledger_sequence
            """,
            (run_id,),
        ).fetchall()
    )
    funding_by_sequence = {int(row["ledger_sequence"]): row for row in funding_rows}
    state: dict[tuple[str, str], dict[str, Decimal | None]] = {}
    funding_by_leg: dict[tuple[str, str], Decimal] = {}
    realized_total = Decimal(0)

    def leg_state(track_id: str, position_side: str) -> dict[str, Decimal | None]:
        return state.setdefault(
            (track_id, position_side),
            {
                "quantity": Decimal(0),
                "entry_price": None,
                "realized_pnl": Decimal(0),
            },
        )

    def apply_fill(
        target: dict[str, Decimal | None],
        *,
        position_side: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        contract_size: Decimal,
    ) -> Decimal:
        signed_delta = quantity if side == "BUY" else -quantity
        old_quantity = cast(Decimal, target["quantity"])
        if position_side == "LONG" and signed_delta < 0:
            signed_delta = -min(abs(signed_delta), abs(old_quantity))
        if position_side == "SHORT" and signed_delta > 0:
            signed_delta = min(signed_delta, abs(old_quantity))
        new_quantity = old_quantity + signed_delta
        old_entry = cast(Decimal | None, target["entry_price"])
        realized = Decimal(0)
        with localcontext() as context:
            context.prec = 60
            if old_quantity == 0:
                new_entry = price if signed_delta else None
            elif old_quantity * signed_delta > 0:
                if old_entry is None:
                    raise TypeError("non-flat HEDGE leg has no entry")
                new_entry = (
                    abs(old_quantity) * old_entry + abs(signed_delta) * price
                ) / abs(new_quantity)
            else:
                if old_entry is None:
                    raise TypeError("non-flat HEDGE leg has no entry")
                closed = min(abs(old_quantity), abs(signed_delta))
                realized = (
                    (price - old_entry)
                    * closed
                    * (Decimal(1) if old_quantity > 0 else Decimal(-1))
                    * contract_size
                )
                new_entry = None if new_quantity == 0 else old_entry
        target["quantity"] = new_quantity
        target["entry_price"] = new_entry
        target["realized_pnl"] = cast(Decimal, target["realized_pnl"]) + realized
        return realized

    # A broker fill is timestamped in the Run's virtual-time domain while
    # pinned public funding keeps its source's actual event time as well as
    # the mapped settlement time.  Those clocks are deliberately not
    # comparable when a Run starts inside a larger frozen archive.  The
    # append-only contract ledger is the canonical account mutation order,
    # so both full replay and point-in-time funding reconstruction must use
    # its sequence rather than sorting the two time domains together.
    ordered_fills = tuple(
        (ledger_sequence, fill_row, raw, causal_sequence)
        for ledger_sequence, (fill_row, raw, causal_sequence) in sorted(
            fill_events.items(),
            key=lambda item: (item[1][2], item[0]),
        )
    )
    for _ledger_sequence, fill_row, raw, _causal_sequence in ordered_fills:
        track_id = str(fill_row["track_id"])
        position_side = str(raw["position_side"])
        rule = rules[(track_id, int(fill_row["rule_revision"]))]
        try:
            realized_total += apply_fill(
                leg_state(track_id, position_side),
                position_side=position_side,
                side=str(raw["side"]),
                quantity=Decimal(str(raw["quantity"])),
                price=Decimal(str(raw["price"])),
                contract_size=Decimal(rule.contract_size),
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            add_difference(
                f"fill[{track_id}:{fill_row['fill_id']}].position_replay",
                "VALID_PER_LEG_TRANSITION",
                f"INVALID:{type(exc).__name__}",
            )

    for sequence in sorted(funding_by_sequence):
        row = funding_by_sequence[sequence]
        track_id = str(row["track_id"])
        position_side = str(row["position_side"])
        prefix = (
            f"hedge_funding[{track_id}:{position_side}:"
            f"{int(row['settlement_time_ms'])}]"
        )
        rule = rules.get((track_id, int(row["rule_revision"])))
        ledger = ledger_by_sequence.get(sequence)
        if rule is None or ledger is None:
            add_difference(f"{prefix}.source_link", "RULE_AND_LEDGER", "MISSING")
            continue
        pre_state: dict[str, Decimal | None] = {
            "quantity": Decimal(0),
            "entry_price": None,
            "realized_pnl": Decimal(0),
        }
        try:
            funding_metadata = json.loads(str(ledger["metadata_json"]))
        except json.JSONDecodeError:
            funding_metadata = None
        if not isinstance(funding_metadata, Mapping):
            add_difference(f"{prefix}.ledger_metadata", "JSON_OBJECT", "INVALID")
            funding_metadata = {}
        funding_boundary = causal_ledger_sequence(ledger, funding_metadata)
        for (
            _fill_ledger_sequence,
            fill_row,
            raw,
            fill_causal_sequence,
        ) in ordered_fills:
            if (
                str(fill_row["track_id"]) != track_id
                or str(raw["position_side"]) != position_side
                or fill_causal_sequence >= funding_boundary
            ):
                continue
            fill_rule = rules[(track_id, int(fill_row["rule_revision"]))]
            apply_fill(
                pre_state,
                position_side=position_side,
                side=str(raw["side"]),
                quantity=Decimal(str(raw["quantity"])),
                price=Decimal(str(raw["price"])),
                contract_size=Decimal(fill_rule.contract_size),
            )
        expected_pre = cast(Decimal, pre_state["quantity"])
        compare_decimal(
            f"{prefix}.pre_settlement_signed_quantity",
            expected_pre,
            row["pre_settlement_signed_quantity"],
        )
        compare_decimal(
            f"{prefix}.pre_settlement_absolute_quantity",
            abs(expected_pre),
            row["pre_settlement_absolute_quantity"],
        )
        applied = connection.execute(
            """
            SELECT * FROM replay_hedge_track_public_applied_event
            WHERE run_id = ? AND track_id = ? AND event_sequence = ?
            """,
            (run_id, track_id, int(row["source_event_sequence"])),
        ).fetchone()
        if applied is None or applied["event_kind"] != "FUNDING":
            add_difference(f"{prefix}.public_event", "APPLIED_FUNDING", "MISSING")
            continue
        payload = json.loads(str(applied["payload_json"]))
        if not isinstance(payload, Mapping):
            add_difference(
                f"{prefix}.public_payload", "JSON_OBJECT", type(payload).__name__
            )
            continue
        for field, expected, actual in (
            (
                "source_event_hash",
                applied["source_event_hash"],
                row["source_event_hash"],
            ),
            ("mark_price", payload.get("mark_price"), row["mark_price"]),
            ("funding_rate", payload.get("funding_rate"), row["funding_rate"]),
        ):
            if str(expected) != str(actual):
                add_difference(f"{prefix}.{field}", expected, actual)
        mark = Decimal(str(payload["mark_price"]))
        rate = Decimal(str(payload["funding_rate"]))
        raw_delta = -expected_pre * mark * Decimal(rule.contract_size) * rate
        rounded = round_to_step(abs(raw_delta), Decimal(rule.quote_step), upward=True)
        expected_delta = rounded.copy_sign(raw_delta) if raw_delta else Decimal(0)
        compare_decimal(f"{prefix}.cash_delta", expected_delta, row["cash_delta"])
        compare_decimal(
            f"ledger[{ledger['posting_id']}].cash_delta",
            expected_delta,
            ledger["cash_delta"],
        )
        component = {
            "schema_version": "replay.training.hedge-funding-settlement.v1",
            "run_id": run_id,
            "track_id": track_id,
            "position_side": position_side,
            "settlement_time_ms": int(row["settlement_time_ms"]),
            "actual_settlement_time_ms": int(row["actual_settlement_time_ms"]),
            "source_kind": str(row["source_kind"]),
            "source_id": str(row["source_id"]),
            "source_event_sequence": int(row["source_event_sequence"]),
            "source_event_hash": str(row["source_event_hash"]),
            "pre_settlement_signed_quantity": str(
                row["pre_settlement_signed_quantity"]
            ),
            "pre_settlement_absolute_quantity": str(
                row["pre_settlement_absolute_quantity"]
            ),
            "mark_price": str(row["mark_price"]),
            "funding_rate": str(row["funding_rate"]),
            "contract_size": str(row["contract_size"]),
            "cash_delta": str(row["cash_delta"]),
            "rounding": str(row["rounding"]),
            "fidelity": str(row["fidelity"]),
            "rule_revision": int(row["rule_revision"]),
        }
        expected_component_hash = canonical_sha256(component)
        if expected_component_hash != row["component_hash"]:
            add_difference(
                f"{prefix}.component_hash",
                expected_component_hash,
                row["component_hash"],
            )
        leg_key = (track_id, position_side)
        funding_by_leg[leg_key] = (
            funding_by_leg.get(leg_key, Decimal(0)) + expected_delta
        )

    liquidation_by_leg: dict[tuple[str, str], Decimal] = {}
    liquidation_total = Decimal(0)
    for ledger in ledger_rows:
        if ledger["kind"] != "LIQUIDATION_FEE":
            continue
        metadata = json.loads(str(ledger["metadata_json"]))
        if not isinstance(metadata, Mapping):
            add_difference(
                f"ledger[{ledger['posting_id']}].metadata",
                "JSON_OBJECT",
                type(metadata).__name__,
            )
            continue
        position_side = metadata.get("position_side")
        track_id = ledger["track_id"]
        fee = -Decimal(str(ledger["cash_delta"]))
        liquidation_total += fee
        if position_side in {"LONG", "SHORT"} and isinstance(track_id, str):
            liquidation_by_leg[(track_id, str(position_side))] = (
                liquidation_by_leg.get((track_id, str(position_side)), Decimal(0)) + fee
            )

    positions: list[dict[str, object]] = []
    expected_unrealized = Decimal(0)
    expected_margin = Decimal(0)
    expected_maintenance = Decimal(0)
    for row in connection.execute(
        """
        SELECT * FROM replay_training_position_leg
        WHERE run_id = ? ORDER BY track_id, position_side
        """,
        (run_id,),
    ).fetchall():
        track_id = str(row["track_id"])
        position_side = str(row["position_side"])
        leg_key = (track_id, position_side)
        target = leg_state(track_id, position_side)
        expected_quantity = cast(Decimal, target["quantity"])
        compare_decimal(
            f"position_leg[{track_id}:{position_side}].signed_quantity",
            expected_quantity,
            row["signed_quantity"],
        )
        compare_decimal(
            f"position_leg[{track_id}:{position_side}].absolute_quantity",
            abs(expected_quantity),
            row["absolute_quantity"],
        )
        expected_funding = funding_by_leg.get(leg_key, Decimal(0))
        expected_fees = configured_fee_by_leg.get(leg_key, Decimal(0))
        expected_liquidation = liquidation_by_leg.get(leg_key, Decimal(0))
        compare_decimal(
            f"position_leg[{track_id}:{position_side}].accumulated_funding",
            expected_funding,
            row["accumulated_funding"],
        )
        compare_decimal(
            f"position_leg[{track_id}:{position_side}].trading_fees",
            expected_fees,
            row["trading_fees"],
        )
        compare_decimal(
            f"position_leg[{track_id}:{position_side}].liquidation_fees",
            expected_liquidation,
            row["liquidation_fees"],
        )
        component = account_marks_ops.position_leg_component(
            row,
            accumulated_funding=str(row["accumulated_funding"]),
            trading_fees=str(row["trading_fees"]),
            liquidation_fees=str(row["liquidation_fees"]),
        )
        expected_hash = canonical_sha256(component)
        if expected_hash != row["component_hash"]:
            add_difference(
                f"position_leg[{track_id}:{position_side}].component_hash",
                expected_hash,
                row["component_hash"],
            )
        unrealized = Decimal(str(row["unrealized_pnl"]))
        expected_unrealized += unrealized
        expected_margin += Decimal(str(row["initial_margin"]))
        expected_maintenance += Decimal(str(row["maintenance_margin"]))
        positions.append(
            {
                "track_id": track_id,
                "position_side": position_side,
                "signed_quantity": decimal_to_string(
                    expected_quantity,
                    field_name="audited HEDGE signed quantity",
                ),
                "realized_pnl": decimal_to_string(
                    cast(Decimal, target["realized_pnl"]),
                    field_name="audited HEDGE realized pnl",
                ),
                "accumulated_funding": decimal_to_string(
                    expected_funding,
                    field_name="audited HEDGE funding",
                ),
                "trading_fees": decimal_to_string(
                    expected_fees,
                    field_name="audited HEDGE fees",
                ),
            }
        )

    funding_total = sum(funding_by_leg.values(), Decimal(0))
    expected_cash = (
        Decimal(str(run["initial_equity"]))
        + realized_total
        - configured_fee_total
        + funding_total
        - liquidation_total
    )
    expected_equity = expected_cash + expected_unrealized
    compare_decimal(
        "portfolio.cash_balance", expected_cash, portfolio.get("cash_balance")
    )
    compare_decimal("portfolio.equity", expected_equity, portfolio.get("equity"))
    compare_decimal(
        "portfolio.fees_paid", configured_fee_total, portfolio.get("fees_paid")
    )
    compare_decimal(
        "portfolio.funding_cashflow",
        funding_total,
        portfolio.get("funding_cashflow"),
    )
    compare_decimal(
        "portfolio.liquidation_fees_paid",
        liquidation_total,
        portfolio.get("liquidation_fees_paid"),
    )
    expected_overlay = (
        broker_fee_total - configured_fee_total + funding_total - liquidation_total
    )
    compare_decimal(
        "contract_account.overlay_cash",
        expected_overlay,
        account["overlay_cash"],
    )
    return {
        "schema_version": "replay.training.hedge-account-audit.v1",
        "cash_balance": decimal_to_string(
            expected_cash,
            field_name="audited HEDGE cash balance",
        ),
        "equity": decimal_to_string(
            expected_equity,
            field_name="audited HEDGE equity",
        ),
        "configured_fees": decimal_to_string(
            configured_fee_total,
            field_name="audited HEDGE configured fees",
        ),
        "funding_cashflow": decimal_to_string(
            funding_total,
            field_name="audited HEDGE funding cashflow",
        ),
        "liquidation_fees_paid": decimal_to_string(
            liquidation_total,
            field_name="audited HEDGE liquidation fees",
        ),
        "margin_used": decimal_to_string(
            expected_margin,
            field_name="audited HEDGE margin",
        ),
        "maintenance_margin": decimal_to_string(
            expected_maintenance,
            field_name="audited HEDGE maintenance",
        ),
        "positions": positions,
        "source_counts": {
            "fills": len(fill_events),
            "funding_settlements": len(funding_rows),
            "fee_policies": len(policies),
            "ledger_entries": len(ledger_rows),
        },
    }


def audit_hedge_insurance_and_adl(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    differences: list[dict[str, object]],
) -> dict[str, object]:
    """Independently rebuild simulated insurance and ADL evidence chains."""

    def difference(field: str, expected: object, actual: object) -> None:
        differences.append({"field": field, "expected": expected, "actual": actual})

    def compare(field: str, expected: object, actual: object) -> None:
        if expected != actual:
            difference(field, expected, actual)

    def normalized_decimal(value: object, *, field: str) -> str | None:
        try:
            return decimal_to_string(Decimal(str(value)), field_name=field)
        except (InvalidOperation, TypeError, ValueError):
            difference(field, "VALID_DECIMAL", value)
            return None

    insurance_funds = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_insurance_fund
            WHERE run_id = ? ORDER BY asset
            """,
            (run_id,),
        ).fetchall()
    )
    insurance_posting_count = 0
    insurance_tails: dict[str, str] = {}
    for fund in insurance_funds:
        asset = str(fund["asset"])
        prefix = f"insurance_fund[{asset}]"
        try:
            current_balance = Decimal(str(fund["opening_balance"]))
        except (InvalidOperation, TypeError, ValueError):
            difference(
                f"{prefix}.opening_balance",
                "VALID_NON_NEGATIVE_DECIMAL",
                fund["opening_balance"],
            )
            continue
        if current_balance < 0:
            difference(
                f"{prefix}.opening_balance",
                "NON_NEGATIVE_DECIMAL",
                fund["opening_balance"],
            )

        postings = tuple(
            connection.execute(
                """
                SELECT posting.*, case_row.trigger_virtual_time_ms
                FROM replay_training_insurance_posting AS posting
                JOIN replay_training_liquidation_case AS case_row
                  ON case_row.run_id = posting.run_id
                 AND case_row.case_id = posting.case_id
                WHERE posting.run_id = ? AND posting.asset = ?
                ORDER BY posting.posting_sequence
                """,
                (run_id, asset),
            ).fetchall()
        )
        input_events = tuple(
            connection.execute(
                """
                SELECT * FROM replay_hedge_input_applied_event
                WHERE run_id = ? AND source_kind = 'SIMULATION'
                  AND event_kind = 'INSURANCE_INPUT'
                ORDER BY applied_virtual_time_ms, event_sequence
                """,
                (run_id,),
            ).fetchall()
        )
        actions: list[tuple[int, int, int, str, sqlite3.Row]] = []
        actions.extend(
            (
                int(row["applied_virtual_time_ms"]),
                0,
                int(row["event_sequence"]),
                "INPUT",
                row,
            )
            for row in input_events
        )
        actions.extend(
            (
                int(row["trigger_virtual_time_ms"]),
                1,
                int(row["posting_sequence"]),
                "POSTING",
                row,
            )
            for row in postings
        )
        actions.sort(key=lambda item: item[:3])
        expected_tail: str | None = None
        expected_revision = 0
        expected_posting_sequence = 0
        for _virtual_time, _phase, _sequence, action_type, row in actions:
            if action_type == "INPUT":
                try:
                    payload = json.loads(str(row["payload_json"]))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    difference(
                        f"{prefix}.input[{row['event_sequence']}]",
                        "VALID_JSON_OBJECT",
                        type(exc).__name__,
                    )
                    continue
                if not isinstance(payload, Mapping):
                    difference(
                        f"{prefix}.input[{row['event_sequence']}]",
                        "JSON_OBJECT",
                        type(payload).__name__,
                    )
                    continue
                balance = normalized_decimal(
                    payload.get("balance_after"),
                    field=f"{prefix}.input[{row['event_sequence']}].balance_after",
                )
                if balance is None:
                    continue
                current_balance = Decimal(balance)
                expected_tail = str(row["source_event_hash"])
                expected_revision += 1
                continue

            expected_posting_sequence += 1
            insurance_posting_count += 1
            posting_prefix = (
                f"{prefix}.posting[{row['posting_sequence']}:{row['posting_id']}]"
            )
            compare(
                f"{posting_prefix}.posting_sequence",
                expected_posting_sequence,
                int(row["posting_sequence"]),
            )
            if expected_tail is None:
                # The start projection hash is independently verified by the
                # HEDGE input audit; the first posting durably anchors it here.
                expected_tail = str(row["previous_hash"])
            compare(
                f"{posting_prefix}.previous_hash",
                expected_tail,
                str(row["previous_hash"]),
            )
            cash_delta = normalized_decimal(
                row["cash_delta"], field=f"{posting_prefix}.cash_delta"
            )
            if cash_delta is None:
                continue
            expected_balance = current_balance + Decimal(cash_delta)
            expected_balance_text = decimal_to_string(
                expected_balance, field_name=f"{posting_prefix}.balance_after"
            )
            compare(
                f"{posting_prefix}.balance_after",
                expected_balance_text,
                str(row["balance_after"]),
            )
            payload = {
                "posting_id": str(row["posting_id"]),
                "case_id": str(row["case_id"]),
                "step_sequence": int(row["step_sequence"]),
                "cash_delta": cash_delta,
                "balance_after": expected_balance_text,
                "reason": str(row["reason"]),
            }
            expected_hash = ledger_chain_hash(
                previous_hash=expected_tail,
                ledger_sequence=expected_posting_sequence,
                posting=payload,
            )
            compare(
                f"{posting_prefix}.posting_hash",
                expected_hash,
                str(row["posting_hash"]),
            )
            current_balance = expected_balance
            expected_tail = expected_hash
            expected_revision += 1

        current_balance_text = decimal_to_string(
            current_balance, field_name=f"{prefix}.current_balance"
        )
        compare(
            f"{prefix}.current_balance",
            current_balance_text,
            str(fund["current_balance"]),
        )
        compare(
            f"{prefix}.revision",
            expected_revision,
            int(fund["revision"]),
        )
        if expected_tail is not None:
            compare(
                f"{prefix}.ledger_tail_hash",
                expected_tail,
                str(fund["ledger_tail_hash"]),
            )
        insurance_tails[asset] = str(fund["ledger_tail_hash"])

        insurance_steps = tuple(
            connection.execute(
                """
                SELECT step.* FROM replay_training_liquidation_step AS step
                WHERE step.run_id = ?
                  AND step.step_type = 'INSURANCE_FUND_SETTLEMENT'
                ORDER BY step.case_id, step.step_sequence
                """,
                (run_id,),
            ).fetchall()
        )
        for step in insurance_steps:
            step_prefix = f"insurance_step[{step['case_id']}:{step['step_sequence']}]"
            try:
                reason = json.loads(str(step["reason"]))
                plan = reason["plan"]
                deficit = Decimal(str(plan["bankruptcy_deficit"]))
            except (
                InvalidOperation,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                difference(step_prefix, "VALID_INSURANCE_PLAN", type(exc).__name__)
                continue
            step_postings = tuple(
                row
                for row in postings
                if str(row["case_id"]) == str(step["case_id"])
                and int(row["step_sequence"]) == int(step["step_sequence"])
            )
            fee_rows = connection.execute(
                """
                SELECT liquidation_fee
                FROM replay_training_liquidation_fill
                WHERE run_id = ? AND case_id = ?
                """,
                (run_id, step["case_id"]),
            ).fetchall()
            fee_inflow = sum(
                (Decimal(str(row["liquidation_fee"])) for row in fee_rows),
                Decimal(0),
            )
            if step_postings:
                first = step_postings[0]
                balance_before = Decimal(str(first["balance_after"])) - Decimal(
                    str(first["cash_delta"])
                )
                settlement = settle_insurance_fund(
                    balance=decimal_to_string(
                        balance_before, field_name=f"{step_prefix}.balance_before"
                    ),
                    deficit=decimal_to_string(
                        deficit, field_name=f"{step_prefix}.deficit"
                    ),
                    liquidation_fee_inflow=decimal_to_string(
                        fee_inflow, field_name=f"{step_prefix}.fee_inflow"
                    ),
                )
                expected_postings: list[tuple[str, str]] = []
                if fee_inflow > 0:
                    expected_postings.append(
                        (
                            "LIQUIDATION_FEE_INFLOW",
                            decimal_to_string(
                                fee_inflow,
                                field_name=f"{step_prefix}.fee_inflow",
                            ),
                        )
                    )
                coverage = Decimal(str(settlement["coverage"]))
                if coverage > 0:
                    expected_postings.append(
                        (
                            "BANKRUPTCY_DEFICIT_DEBIT",
                            decimal_to_string(
                                -coverage,
                                field_name=f"{step_prefix}.coverage",
                            ),
                        )
                    )
                actual_postings = [
                    (str(row["reason"]), str(row["cash_delta"]))
                    for row in step_postings
                ]
                compare(
                    f"{step_prefix}.postings",
                    expected_postings,
                    actual_postings,
                )
            elif fee_inflow > 0:
                difference(
                    f"{step_prefix}.postings",
                    "LIQUIDATION_FEE_INFLOW",
                    "MISSING",
                )

    projection = connection.execute(
        """
        SELECT * FROM replay_hedge_input_projection
        WHERE run_id = ? AND source_kind = 'SIMULATION'
        """,
        (run_id,),
    ).fetchone()
    raw_snapshots: dict[str, Mapping[str, object]] = {}
    input_chain_hashes: set[str] = set()
    if projection is not None:
        input_chain_hashes.add(str(projection["input_chain_hash"]))
        try:
            state = json.loads(str(projection["state_json"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            state = None
        snapshots = state.get("adl_snapshots") if isinstance(state, Mapping) else None
        if isinstance(snapshots, Mapping):
            for raw in snapshots.values():
                if isinstance(raw, Mapping) and isinstance(
                    raw.get("snapshot_hash"), str
                ):
                    raw_snapshots[str(raw["snapshot_hash"])] = raw
    for row in connection.execute(
        """
        SELECT * FROM replay_hedge_input_applied_event
        WHERE run_id = ? AND source_kind = 'SIMULATION'
        ORDER BY event_sequence
        """,
        (run_id,),
    ).fetchall():
        input_chain_hashes.add(str(row["source_event_hash"]))
        if row["event_kind"] != "ADL_COHORT_INPUT":
            continue
        try:
            raw = json.loads(str(row["payload_json"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(raw, Mapping) and isinstance(raw.get("snapshot_hash"), str):
            raw_snapshots[str(raw["snapshot_hash"])] = raw

    adl_snapshots = tuple(
        connection.execute(
            """
            SELECT snapshot.*, step.reason
            FROM replay_training_adl_snapshot AS snapshot
            JOIN replay_training_liquidation_step AS step
              ON step.run_id = snapshot.run_id
             AND step.case_id = snapshot.case_id
             AND step.step_sequence = snapshot.step_sequence
            WHERE snapshot.run_id = ?
            ORDER BY snapshot.case_id, snapshot.step_sequence
            """,
            (run_id,),
        ).fetchall()
    )
    adl_candidate_count = 0
    adl_selection_count = 0
    adl_counterparty_count = 0
    for snapshot in adl_snapshots:
        snapshot_prefix = f"adl_snapshot[{snapshot['snapshot_id']}]"
        try:
            reason = json.loads(str(snapshot["reason"]))
            plan = cast(Mapping[str, object], reason["plan"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            difference(snapshot_prefix, "VALID_ADL_PLAN", type(exc).__name__)
            continue
        raw = next(
            (
                candidate
                for candidate in raw_snapshots.values()
                if candidate.get("symbol") == snapshot["symbol"]
                and candidate.get("snapshot_hash")
                and isinstance(candidate.get("candidates"), list)
                and any(
                    canonical_sha256(
                        {
                            "source_snapshot_hash": candidate["snapshot_hash"],
                            "input_chain_hash": chain_hash,
                        }
                    )
                    == snapshot["input_hash"]
                    for chain_hash in input_chain_hashes
                )
            ),
            None,
        )
        if raw is None:
            difference(
                f"{snapshot_prefix}.input_hash",
                "REHYDRATABLE_PINNED_ADL_INPUT",
                snapshot["input_hash"],
            )
            continue
        chain_hash = next(
            chain
            for chain in input_chain_hashes
            if canonical_sha256(
                {
                    "source_snapshot_hash": raw["snapshot_hash"],
                    "input_chain_hash": chain,
                }
            )
            == snapshot["input_hash"]
        )
        try:
            ranked = rank_adl_candidates(
                cast(Sequence[Mapping[str, object]], raw["candidates"]),
                bankrupt_position_side=str(plan["bankrupt_position_side"]),
                quote_step=plan["quote_step"],
            )
            selected = select_adl_candidates(
                cast(Sequence[Mapping[str, object]], raw["candidates"]),
                bankrupt_position_side=str(plan["bankrupt_position_side"]),
                takeover_quantity=plan["takeover_quantity"],
                quote_step=plan["quote_step"],
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            difference(snapshot_prefix, "VALID_ADL_INPUT", type(exc).__name__)
            continue
        compare(
            f"{snapshot_prefix}.model_version",
            ADL_MODEL_VERSION,
            str(snapshot["model_version"]),
        )
        snapshot_payload = {
            "snapshot_id": str(snapshot["snapshot_id"]),
            "case_id": str(snapshot["case_id"]),
            "step_sequence": int(snapshot["step_sequence"]),
            "symbol": str(snapshot["symbol"]),
            "model_version": ADL_MODEL_VERSION,
            "source_snapshot_hash": raw["snapshot_hash"],
            "input_chain_hash": chain_hash,
            "ranked_candidate_ids": [item["candidate_id"] for item in ranked],
        }
        compare(
            f"{snapshot_prefix}.snapshot_hash",
            canonical_sha256(snapshot_payload),
            str(snapshot["snapshot_hash"]),
        )
        candidate_rows = tuple(
            connection.execute(
                """
                SELECT * FROM replay_training_adl_candidate
                WHERE run_id = ? AND snapshot_id = ? ORDER BY rank
                """,
                (run_id, snapshot["snapshot_id"]),
            ).fetchall()
        )
        adl_candidate_count += len(candidate_rows)
        compare(
            f"{snapshot_prefix}.candidate_count",
            len(ranked),
            len(candidate_rows),
        )
        for rank, candidate in enumerate(ranked, start=1):
            if rank > len(candidate_rows):
                break
            row = candidate_rows[rank - 1]
            candidate_payload = {
                "snapshot_id": str(snapshot["snapshot_id"]),
                "candidate_id": candidate["candidate_id"],
                "rank": rank,
                "position_side": candidate["position_side"],
                "quantity": candidate["quantity"],
                "entry_price": candidate["entry_price"],
                "mark_price": candidate["mark_price"],
                "profit_ratio": candidate["profit_ratio"],
                "effective_leverage": candidate["effective_leverage"],
                "score": candidate["score"],
            }
            for field, expected in candidate_payload.items():
                actual = int(row[field]) if field == "rank" else str(row[field])
                compare(
                    f"{snapshot_prefix}.candidate[{rank}].{field}",
                    expected,
                    actual,
                )
            compare(
                f"{snapshot_prefix}.candidate[{rank}].candidate_hash",
                canonical_sha256(candidate_payload),
                str(row["candidate_hash"]),
            )

        event = connection.execute(
            """
            SELECT * FROM replay_training_adl_event
            WHERE run_id = ? AND case_id = ? AND step_sequence = ?
            """,
            (run_id, snapshot["case_id"], snapshot["step_sequence"]),
        ).fetchone()
        if event is None:
            difference(f"{snapshot_prefix}.event", "PRESENT", "MISSING")
            continue
        takeover_price = Decimal(str(plan["takeover_price"]))
        takeover_quantity = Decimal(str(plan["takeover_quantity"]))
        contract_size = Decimal(str(plan["contract_size"]))
        completed_notional = decimal_to_string(
            takeover_price * takeover_quantity * contract_size,
            field_name=f"{snapshot_prefix}.completed_notional",
        )
        event_payload = {
            "adl_event_id": str(event["adl_event_id"]),
            "case_id": str(snapshot["case_id"]),
            "step_sequence": int(snapshot["step_sequence"]),
            "snapshot_id": str(snapshot["snapshot_id"]),
            "required_notional": str(plan["uncovered_deficit"]),
            "completed_notional": completed_notional,
        }
        for field, expected in event_payload.items():
            actual = (
                int(event[field]) if field == "step_sequence" else str(event[field])
            )
            compare(f"adl_event[{event['adl_event_id']}].{field}", expected, actual)
        compare(
            f"adl_event[{event['adl_event_id']}].state",
            "COMPLETED",
            str(event["state"]),
        )
        compare(
            f"adl_event[{event['adl_event_id']}].event_hash",
            canonical_sha256(event_payload),
            str(event["event_hash"]),
        )
        expected_selected = cast(list[dict[str, str]], selected["selected"])
        selection_rows = tuple(
            connection.execute(
                """
                SELECT * FROM replay_training_adl_selection
                WHERE run_id = ? AND adl_event_id = ?
                ORDER BY selection_sequence
                """,
                (run_id, event["adl_event_id"]),
            ).fetchall()
        )
        counterparty_rows = tuple(
            connection.execute(
                """
                SELECT * FROM replay_training_adl_counterparty_ledger
                WHERE run_id = ? AND adl_event_id = ? ORDER BY ledger_sequence
                """,
                (run_id, event["adl_event_id"]),
            ).fetchall()
        )
        adl_selection_count += len(selection_rows)
        adl_counterparty_count += len(counterparty_rows)
        compare(
            f"adl_event[{event['adl_event_id']}].selection_count",
            len(expected_selected),
            len(selection_rows),
        )
        compare(
            f"adl_event[{event['adl_event_id']}].counterparty_count",
            len(expected_selected),
            len(counterparty_rows),
        )
        ranked_by_id = {str(item["candidate_id"]): item for item in ranked}
        previous_hash = "sha256:" + "0" * 64
        for sequence, item in enumerate(expected_selected, start=1):
            if sequence > len(selection_rows) or sequence > len(counterparty_rows):
                break
            candidate = ranked_by_id[str(item["candidate_id"])]
            quantity = Decimal(str(item["quantity"]))
            entry_price = Decimal(str(candidate["entry_price"]))
            notional = decimal_to_string(
                quantity * takeover_price * contract_size,
                field_name=f"adl_event[{event['adl_event_id']}].notional",
            )
            cash_delta_value = (
                (takeover_price - entry_price) * quantity
                if candidate["position_side"] == "LONG"
                else (entry_price - takeover_price) * quantity
            ) * contract_size
            cash_delta = decimal_to_string(
                cash_delta_value,
                field_name=f"adl_event[{event['adl_event_id']}].cash_delta",
            )
            selection_payload = {
                "adl_event_id": str(event["adl_event_id"]),
                "selection_sequence": sequence,
                "candidate_id": str(item["candidate_id"]),
                "quantity": str(item["quantity"]),
                "price": str(plan["takeover_price"]),
                "notional": notional,
                "cash_delta": cash_delta,
            }
            selection_row = selection_rows[sequence - 1]
            for field, expected in selection_payload.items():
                actual = (
                    int(selection_row[field])
                    if field == "selection_sequence"
                    else str(selection_row[field])
                )
                compare(
                    f"adl_event[{event['adl_event_id']}].selection[{sequence}].{field}",
                    expected,
                    actual,
                )
            compare(
                f"adl_event[{event['adl_event_id']}].selection[{sequence}].hash",
                canonical_sha256(selection_payload),
                str(selection_row["selection_hash"]),
            )
            quantity_before = Decimal(str(candidate["quantity"]))
            quantity_after = decimal_to_string(
                quantity_before - quantity,
                field_name=f"adl_event[{event['adl_event_id']}].quantity_after",
            )
            counterparty_payload = {
                "adl_event_id": str(event["adl_event_id"]),
                "ledger_sequence": sequence,
                "candidate_id": str(item["candidate_id"]),
                "position_side": str(candidate["position_side"]),
                "quantity_before": str(candidate["quantity"]),
                "quantity_delta": decimal_to_string(
                    -quantity,
                    field_name=f"adl_event[{event['adl_event_id']}].quantity_delta",
                ),
                "quantity_after": quantity_after,
                "takeover_price": str(plan["takeover_price"]),
                "cash_delta": cash_delta,
            }
            counterparty_row = counterparty_rows[sequence - 1]
            for field, expected in counterparty_payload.items():
                actual = (
                    int(counterparty_row[field])
                    if field == "ledger_sequence"
                    else str(counterparty_row[field])
                )
                compare(
                    f"adl_event[{event['adl_event_id']}].counterparty[{sequence}].{field}",
                    expected,
                    actual,
                )
            compare(
                f"adl_event[{event['adl_event_id']}].counterparty[{sequence}].previous_hash",
                previous_hash,
                str(counterparty_row["previous_hash"]),
            )
            expected_entry_hash = ledger_chain_hash(
                previous_hash=previous_hash,
                ledger_sequence=sequence,
                posting=counterparty_payload,
            )
            compare(
                f"adl_event[{event['adl_event_id']}].counterparty[{sequence}].entry_hash",
                expected_entry_hash,
                str(counterparty_row["entry_hash"]),
            )
            previous_hash = expected_entry_hash

    return {
        "insurance_fund_count": len(insurance_funds),
        "insurance_posting_count": insurance_posting_count,
        "insurance_ledger_tails": insurance_tails,
        "adl_snapshot_count": len(adl_snapshots),
        "adl_candidate_count": adl_candidate_count,
        "adl_selection_count": adl_selection_count,
        "adl_counterparty_ledger_count": adl_counterparty_count,
    }


def audit_historical_book_liquidations(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    differences: list[dict[str, object]],
) -> int:
    proofs = connection.execute(
        """
        SELECT proof.*, step.reason
        FROM replay_training_liquidation_book_execution AS proof
        JOIN replay_training_liquidation_step AS step
          ON step.run_id = proof.run_id AND step.case_id = proof.case_id
         AND step.step_sequence = proof.step_sequence
        WHERE proof.run_id = ? ORDER BY proof.case_id, proof.step_sequence
        """,
        (run_id,),
    ).fetchall()

    def difference(field: str, expected: object, actual: object) -> None:
        differences.append({"field": field, "expected": expected, "actual": actual})

    snapshots = connection.execute(
        """
        SELECT snapshot.*, case_row.trigger_virtual_time_ms
        FROM replay_training_liquidation_book_snapshot AS snapshot
        JOIN replay_training_liquidation_case AS case_row
          ON case_row.run_id = snapshot.run_id
         AND case_row.case_id = snapshot.case_id
        WHERE snapshot.run_id = ? ORDER BY snapshot.case_id, snapshot.track_id
        """,
        (run_id,),
    ).fetchall()
    expected_snapshot_count = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT leg.case_id, leg.track_id
                FROM replay_training_liquidation_leg AS leg
                JOIN replay_training_run AS run USING(run_id)
                WHERE leg.run_id = ? AND run.book_mode = 'BOOK_ASSISTED_REQUIRED'
            )
            """,
            (run_id,),
        ).fetchone()[0]
    )
    if expected_snapshot_count != len(snapshots):
        difference(
            "historical_l2_liquidation_snapshot_count",
            expected_snapshot_count,
            len(snapshots),
        )
    for snapshot in snapshots:
        prefix = (
            f"liquidation[{snapshot['case_id']}].book_snapshot[{snapshot['track_id']}]"
        )
        try:
            payload = {
                "schema_version": "replay.liquidation-book-snapshot.v1",
                "case_id": str(snapshot["case_id"]),
                "track_id": str(snapshot["track_id"]),
                "archive_id": str(snapshot["archive_id"]),
                "as_of_actual_time_ms": int(snapshot["as_of_actual_time_ms"]),
                "as_of_virtual_time_ms": int(snapshot["as_of_virtual_time_ms"]),
                "last_update_id": int(snapshot["last_update_id"]),
                "bids": json.loads(str(snapshot["bids_json"])),
                "asks": json.loads(str(snapshot["asks_json"])),
                "book_hash": str(snapshot["book_hash"]),
                "execution_fidelity": str(snapshot["execution_fidelity"]),
                "queue_exact": False,
            }
            expected_hash = canonical_sha256(payload)
            if (
                int(snapshot["queue_exact"]) != 0
                or int(snapshot["as_of_virtual_time_ms"])
                != int(snapshot["trigger_virtual_time_ms"])
                or str(snapshot["execution_fidelity"])
                != HISTORICAL_L2_LIQUIDATION_FIDELITY
                or str(snapshot["snapshot_hash"]) != expected_hash
            ):
                difference(
                    prefix,
                    {
                        "snapshot_hash": expected_hash,
                        "trigger_virtual_time_ms": int(
                            snapshot["trigger_virtual_time_ms"]
                        ),
                        "queue_exact": False,
                        "execution_fidelity": HISTORICAL_L2_LIQUIDATION_FIDELITY,
                    },
                    {
                        "snapshot_hash": snapshot["snapshot_hash"],
                        "as_of_virtual_time_ms": snapshot["as_of_virtual_time_ms"],
                        "queue_exact": snapshot["queue_exact"],
                        "execution_fidelity": snapshot["execution_fidelity"],
                    },
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            difference(prefix, "VALID_HISTORICAL_L2_SNAPSHOT", type(exc).__name__)

    executed_steps = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM replay_training_liquidation_step AS step
            JOIN replay_training_liquidation_order AS order_row
              ON order_row.run_id = step.run_id
             AND order_row.case_id = step.case_id
             AND order_row.step_sequence = step.step_sequence
            JOIN replay_training_run AS run ON run.run_id = step.run_id
            WHERE step.run_id = ?
              AND run.book_mode = 'BOOK_ASSISTED_REQUIRED'
              AND step.step_type IN ('PARTIAL_LIQUIDATION', 'FULL_LIQUIDATION')
            """,
            (run_id,),
        ).fetchone()[0]
    )
    if executed_steps != len(proofs):
        difference(
            "historical_l2_liquidation_proof_count",
            executed_steps,
            len(proofs),
        )

    for proof in proofs:
        prefix = f"liquidation[{proof['case_id']}].step[{proof['step_sequence']}].book"
        try:
            levels = json.loads(str(proof["levels_json"]))
            if not isinstance(levels, list) or not levels:
                raise TypeError("levels must be a non-empty list")
            normalized_levels = []
            total = Decimal(0)
            previous_level = 0
            for raw in levels:
                if not isinstance(raw, Mapping):
                    raise TypeError("level must be an object")
                level = int(raw["book_level"])
                price = Decimal(str(raw["price"]))
                quantity = Decimal(str(raw["quantity"]))
                if level <= previous_level or price <= 0 or quantity <= 0:
                    raise ValueError("level ordering or decimal is invalid")
                previous_level = level
                total += quantity
                normalized_levels.append(
                    {
                        "book_level": level,
                        "price": str(raw["price"]),
                        "quantity": str(raw["quantity"]),
                    }
                )
            requested = Decimal(str(proof["requested_quantity"]))
            visible = Decimal(str(proof["visible_quantity"]))
            if total != requested or visible < requested:
                difference(
                    f"{prefix}.quantity",
                    {
                        "requested": str(proof["requested_quantity"]),
                        "visible_gte": True,
                    },
                    {
                        "level_sum": decimal_to_string(
                            total, field_name="book audit sum"
                        ),
                        "visible": str(proof["visible_quantity"]),
                    },
                )
            payload = {
                "archive_id": str(proof["archive_id"]),
                "as_of_virtual_time_ms": int(proof["as_of_virtual_time_ms"]),
                "last_update_id": int(proof["last_update_id"]),
                "side": str(proof["side"]),
                "requested_quantity": str(proof["requested_quantity"]),
                "visible_quantity": str(proof["visible_quantity"]),
                "levels": normalized_levels,
                "book_hash": str(proof["book_hash"]),
                "execution_fidelity": str(proof["execution_fidelity"]),
                "queue_exact": False,
            }
            expected_hash = canonical_sha256(payload)
            if expected_hash != proof["execution_plan_hash"]:
                difference(
                    f"{prefix}.execution_plan_hash",
                    expected_hash,
                    proof["execution_plan_hash"],
                )
            if (
                int(proof["queue_exact"]) != 0
                or str(proof["execution_fidelity"])
                != HISTORICAL_L2_LIQUIDATION_FIDELITY
            ):
                difference(
                    f"{prefix}.fidelity",
                    f"{HISTORICAL_L2_LIQUIDATION_FIDELITY}/queue_exact=false",
                    f"{proof['execution_fidelity']}/queue_exact={proof['queue_exact']}",
                )
            frozen = connection.execute(
                """
                SELECT book_hash, last_update_id, as_of_virtual_time_ms
                FROM replay_training_liquidation_book_snapshot
                WHERE run_id = ? AND case_id = ? AND track_id = ?
                """,
                (run_id, proof["case_id"], proof["track_id"]),
            ).fetchone()
            if frozen is None or (
                str(frozen["book_hash"]) != str(proof["book_hash"])
                or int(frozen["last_update_id"]) != int(proof["last_update_id"])
                or int(frozen["as_of_virtual_time_ms"])
                != int(proof["as_of_virtual_time_ms"])
            ):
                difference(
                    f"{prefix}.frozen_snapshot_link",
                    (
                        proof["book_hash"],
                        proof["last_update_id"],
                        proof["as_of_virtual_time_ms"],
                    ),
                    None
                    if frozen is None
                    else (
                        frozen["book_hash"],
                        frozen["last_update_id"],
                        frozen["as_of_virtual_time_ms"],
                    ),
                )
            reason = json.loads(str(proof["reason"]))
            durable_book = (
                reason.get("plan", {}).get("book_execution")
                if isinstance(reason, Mapping)
                and isinstance(reason.get("plan"), Mapping)
                else None
            )
            if not isinstance(durable_book, Mapping) or str(
                durable_book.get("execution_plan_hash")
            ) != str(proof["execution_plan_hash"]):
                difference(
                    f"{prefix}.durable_step_plan",
                    proof["execution_plan_hash"],
                    None
                    if not isinstance(durable_book, Mapping)
                    else durable_book.get("execution_plan_hash"),
                )
            order = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_order
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                ORDER BY order_sequence LIMIT 1
                """,
                (run_id, proof["case_id"], proof["step_sequence"]),
            ).fetchone()
            fills = (
                []
                if order is None
                else connection.execute(
                    """
                    SELECT * FROM replay_training_liquidation_fill
                    WHERE run_id = ? AND case_id = ? AND order_id = ?
                    ORDER BY fill_sequence
                    """,
                    (run_id, proof["case_id"], order["order_id"]),
                ).fetchall()
            )
            if order is None or len(fills) != len(normalized_levels):
                difference(
                    f"{prefix}.fill_count",
                    len(normalized_levels),
                    0 if order is None else len(fills),
                )
                continue
            for sequence, (level, fill) in enumerate(
                zip(normalized_levels, fills, strict=True), start=1
            ):
                expected_fill = (
                    int(level["book_level"]),
                    str(level["price"]),
                    str(level["quantity"]),
                )
                actual_fill = (
                    fill["book_level"],
                    str(fill["price"]),
                    str(fill["quantity"]),
                )
                if actual_fill != expected_fill:
                    difference(
                        f"{prefix}.fill[{sequence}]",
                        expected_fill,
                        actual_fill,
                    )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            difference(prefix, "VALID_HISTORICAL_L2_PROOF", type(exc).__name__)
    return len(proofs)


def write_account_audit(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
    authoritative_projections: (Mapping[str, Mapping[str, object]] | None) = None,
) -> dict[str, object]:
    run = connection.execute(
        """
        SELECT run.*, history.account_data_mode, history.status AS history_status
        FROM replay_training_run AS run
        JOIN replay_training_account_history AS history USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    account = connection.execute(
        """
        SELECT * FROM replay_training_contract_account WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if run is None or account is None:
        raise TrainingRunError(
            "TRAINING_RUN_NOT_FOUND",
            "training account does not exist",
            status_code=404,
        )
    differences: list[dict[str, object]] = []
    ledger_rows = connection.execute(
        """
        SELECT * FROM replay_training_contract_ledger
        WHERE run_id = ? ORDER BY ledger_sequence
        """,
        (run_id,),
    ).fetchall()
    previous = initial_ledger_hash(
        run_id=run_id,
        initial_equity=str(run["initial_equity"]),
        asset=str(run["settlement_asset"]),
    )
    ledger_total = Decimal(0)
    for expected, row in enumerate(ledger_rows, 1):
        posting = {
            "posting_id": row["posting_id"],
            "track_id": row["track_id"],
            "kind": row["kind"],
            "cash_delta": row["cash_delta"],
            "asset": row["asset"],
            "virtual_time_ms": row["virtual_time_ms"],
            "source_sequence": row["source_sequence"],
            "fidelity": row["fidelity"],
            "rule_revision": row["rule_revision"],
            "reference_type": row["reference_type"],
            "reference_id": row["reference_id"],
            "metadata": json.loads(str(row["metadata_json"])),
        }
        expected_hash = ledger_chain_hash(
            previous_hash=previous,
            ledger_sequence=expected,
            posting=posting,
        )
        if int(row["ledger_sequence"]) != expected:
            differences.append(
                {
                    "field": "ledger_sequence",
                    "expected": expected,
                    "actual": int(row["ledger_sequence"]),
                }
            )
        if row["previous_hash"] != previous:
            differences.append(
                {
                    "field": f"ledger[{expected}].previous_hash",
                    "expected": previous,
                    "actual": row["previous_hash"],
                }
            )
        if row["entry_hash"] != expected_hash:
            differences.append(
                {
                    "field": f"ledger[{expected}].entry_hash",
                    "expected": expected_hash,
                    "actual": row["entry_hash"],
                }
            )
        previous = str(row["entry_hash"])
        ledger_total += Decimal(str(row["cash_delta"]))
    if previous != account["ledger_tail_hash"]:
        differences.append(
            {
                "field": "ledger_tail_hash",
                "expected": previous,
                "actual": account["ledger_tail_hash"],
            }
        )
    tracks = [
        portfolio_ops.market_track_from_row(row)
        for row in connection.execute(
            """
            SELECT * FROM replay_training_market_track
            WHERE run_id = ? ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    ]
    portfolio = portfolio_ops.contract_portfolio_projection(
        connection,
        run_id=run_id,
        initial_equity=str(run["initial_equity"]),
        tracks=tracks,
    )
    if Decimal(str(portfolio["cash_balance"])) != ledger_total:
        differences.append(
            {
                "field": "cash_balance",
                "expected": decimal_to_string(ledger_total, field_name="audited cash"),
                "actual": portfolio["cash_balance"],
            }
        )
    independent_state: dict[str, object] | None = None
    projection_verification = "NOT_APPLICABLE"
    if run["position_mode"] == "HEDGE":
        projection_verification = "VERIFIED_PINNED_HEDGE_INPUTS"
        independent_state = audit_hedge_account_state(
            connection,
            run=run,
            account=account,
            ledger_rows=ledger_rows,
            portfolio=portfolio,
            differences=differences,
        )
        independent_state["insurance_and_adl"] = audit_hedge_insurance_and_adl(
            connection,
            run_id=run_id,
            differences=differences,
        )
        independent_state["historical_l2_liquidation_proof_count"] = (
            audit_historical_book_liquidations(
                connection,
                run_id=run_id,
                differences=differences,
            )
        )
    elif run["account_data_mode"] == "HISTORICAL_EXACT":
        projection_verification = (
            "VERIFIED_PINNED_ARCHIVE"
            if authoritative_projections is not None
            else "IN_PROCESS_HASH_CHAIN"
        )
        projections = connection.execute(
            """
            SELECT projection.*, ref.event_chain_tail,
                   archive.proof_hash, archive.health
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
        full_count = sum(1 for track in tracks if track["subscription_tier"] == "FULL")
        if len(projections) != full_count:
            differences.append(
                {
                    "field": "exact_projection_count",
                    "expected": full_count,
                    "actual": len(projections),
                }
            )
        for projection in projections:
            if projection["status"] != "READY" or projection["health"] != "READY":
                differences.append(
                    {
                        "field": f"projection[{projection['track_id']}].status",
                        "expected": "READY",
                        "actual": (f"{projection['status']}/{projection['health']}"),
                    }
                )
            if authoritative_projections is not None:
                expected = authoritative_projections.get(str(projection["track_id"]))
                if expected is None:
                    differences.append(
                        {
                            "field": (
                                f"projection[{projection['track_id']}]."
                                "authoritative_archive"
                            ),
                            "expected": "PINNED_ARCHIVE_PROJECTION",
                            "actual": "MISSING",
                        }
                    )
                else:
                    for field in (
                        "archive_id",
                        "archive_generation",
                        "last_event_sequence",
                        "last_rule_sequence",
                        "last_mark_sequence",
                        "last_funding_sequence",
                        "as_of_actual_time_ms",
                        "as_of_virtual_time_ms",
                        "current_rule_json",
                        "current_rule_hash",
                        "mark_price",
                        "index_price",
                        "input_chain_hash",
                    ):
                        if projection[field] != expected.get(field):
                            differences.append(
                                {
                                    "field": (
                                        f"projection[{projection['track_id']}].{field}"
                                    ),
                                    "expected": expected.get(field),
                                    "actual": projection[field],
                                }
                            )
            applied = connection.execute(
                """
                SELECT event_hash FROM (
                    SELECT archive_event_hash AS event_hash,
                           archive_event_sequence
                    FROM replay_account_history_applied_event
                    WHERE run_id = ? AND track_id = ?
                ) ORDER BY archive_event_sequence DESC LIMIT 1
                """,
                (run_id, projection["track_id"]),
            ).fetchone()
            if (
                applied is not None
                and applied["event_hash"] != projection["input_chain_hash"]
            ):
                differences.append(
                    {
                        "field": (
                            f"projection[{projection['track_id']}].input_chain_hash"
                        ),
                        "expected": applied["event_hash"],
                        "actual": projection["input_chain_hash"],
                    }
                )
        if authoritative_projections is not None and len(
            authoritative_projections
        ) != len(projections):
            differences.append(
                {
                    "field": "authoritative_projection_count",
                    "expected": len(projections),
                    "actual": len(authoritative_projections),
                }
            )
        independent_state = audit_exact_account_state(
            connection,
            run=run,
            account=account,
            ledger_rows=ledger_rows,
            portfolio=portfolio,
            differences=differences,
        )
    funding_orphans = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM replay_training_funding_settlement AS funding
            LEFT JOIN replay_training_contract_ledger AS ledger
              ON ledger.run_id = funding.run_id
             AND ledger.ledger_sequence = funding.ledger_sequence
            WHERE funding.run_id = ? AND (
                ledger.ledger_sequence IS NULL
                OR ledger.kind != 'FUNDING_SETTLEMENT'
                OR ledger.cash_delta != funding.cash_delta
            )
            """,
            (run_id,),
        ).fetchone()[0]
    )
    if funding_orphans:
        differences.append(
            {
                "field": "funding_ledger_links",
                "expected": 0,
                "actual": funding_orphans,
            }
        )
    hedge_funding_orphans = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM replay_training_hedge_funding_settlement AS funding
            LEFT JOIN replay_training_contract_ledger AS ledger
              ON ledger.run_id = funding.run_id
             AND ledger.ledger_sequence = funding.ledger_sequence
            WHERE funding.run_id = ? AND (
                ledger.ledger_sequence IS NULL
                OR ledger.kind != 'FUNDING_SETTLEMENT'
                OR ledger.cash_delta != funding.cash_delta
                OR json_extract(ledger.metadata_json, '$.position_side')
                   != funding.position_side
            )
            """,
            (run_id,),
        ).fetchone()[0]
    )
    if hedge_funding_orphans:
        differences.append(
            {
                "field": "hedge_funding_ledger_links",
                "expected": 0,
                "actual": hedge_funding_orphans,
            }
        )
    portfolio_fidelity = cast(Mapping[str, object], portfolio["fidelity"])
    risk_fidelity = {
        key: portfolio_fidelity[key]
        for key in (
            "instrument_rules",
            "maintenance_margin",
            "liquidation_projection",
            "maintenance_tier_extrapolation",
        )
    }
    position_maintenance_proofs = [
        {
            "track_id": str(position["track_id"]),
            "position_side": position.get("position_side"),
            "proof": position["maintenance_margin_proof"],
        }
        for position in cast(Sequence[Mapping[str, object]], portfolio["positions"])
        if "maintenance_margin_proof" in position
    ]
    snapshot = {
        "schema_version": ACCOUNT_AUDIT_SCHEMA_VERSION,
        "run_id": run_id,
        "account_data_mode": str(run["account_data_mode"]),
        "history_status": str(run["history_status"]),
        "ledger_entry_count": len(ledger_rows),
        "ledger_tail_hash": str(account["ledger_tail_hash"]),
        "ledger_cash_total": decimal_to_string(
            ledger_total, field_name="ledger cash total"
        ),
        "portfolio": {
            key: portfolio[key]
            for key in (
                "cash_balance",
                "equity",
                "available_equity",
                "margin_used",
                "maintenance_margin",
                "funding_cashflow",
                "liquidation_fees_paid",
                "status",
            )
        }
        | {
            "risk_fidelity": risk_fidelity,
            "position_maintenance_proofs": position_maintenance_proofs,
        },
        "authoritative_projection_verification": projection_verification,
        "independent_exact_state": independent_state,
        "differences": differences,
    }
    status = "PASS" if not differences else "FAIL"
    proof_hash = canonical_sha256(snapshot)
    sequence = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(audit_sequence), 0) + 1
            FROM replay_account_history_audit WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO replay_account_history_audit(
            run_id, audit_sequence, schema_version, status, proof_hash,
            differences_json, snapshot_json, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            sequence,
            ACCOUNT_AUDIT_SCHEMA_VERSION,
            status,
            proof_hash,
            canonical_json(differences),
            canonical_json(snapshot),
            now_ms,
        ),
    )
    connection.execute(
        """
        UPDATE replay_training_account_history
        SET auditor_status = ?, auditor_proof_hash = ?,
            auditor_differences_json = ?, updated_at_ms = ?
        WHERE run_id = ?
        """,
        (
            status,
            proof_hash,
            canonical_json(differences),
            now_ms,
            run_id,
        ),
    )
    if status == "FAIL" and run["position_mode"] == "HEDGE":
        connection.execute(
            """
            UPDATE replay_training_contract_account
            SET status = 'FAILED_CLOSED', updated_at_ms = ?
            WHERE run_id = ?
            """,
            (now_ms, run_id),
        )
        connection.execute(
            """
            UPDATE replay_training_run
            SET state = 'PAUSED', compatibility = 'DEGRADED',
                updated_at_ms = ?, saved_at_ms = ?
            WHERE run_id = ?
            """,
            (now_ms, now_ms, run_id),
        )
        connection.execute(
            """
            UPDATE replay_hedge_input_binding
            SET status = 'PAUSED', degraded_reason = 'ACCOUNT_AUDIT_FAILED',
                updated_at_ms = ?
            WHERE run_id = ? AND status = 'ACTIVE'
            """,
            (now_ms, run_id),
        )
        connection.execute(
            """
            UPDATE replay_hedge_track_public_binding
            SET status = 'PAUSED', degraded_reason = 'ACCOUNT_AUDIT_FAILED',
                updated_at_ms = ?
            WHERE run_id = ? AND status = 'ACTIVE'
            """,
            (now_ms, run_id),
        )
    return {
        "schema_version": ACCOUNT_AUDIT_SCHEMA_VERSION,
        "status": status,
        "proof_hash": proof_hash,
        "differences": differences,
        "snapshot": snapshot,
    }
