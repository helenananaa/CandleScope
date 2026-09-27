"""TrainingLiquidationRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import cast

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..account import (
    InstrumentRule,
    ledger_chain_hash,
    round_to_step,
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
from ..persistence import account_math as account_math_ops
from ..persistence import ledger as ledger_ops
from ..persistence import liquidation as liquidation_ops
from ..review import (
    ReviewRecorder,
)


class TrainingLiquidationRepository:
    """Own liquidations operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore, review: ReviewRecorder) -> None:
        self.base_store = base_store
        self._review = review

    async def commit_liquidation_cancellation(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
        canceled_orders: Sequence[Mapping[str, object]],
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "CANCEL_ORDERS":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "liquidation cancellation step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            now_ms = self.base_store._validated_now_ms()
            legs = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_liquidation_leg
                    WHERE run_id = ? AND case_id = ? ORDER BY leg_sequence
                    """,
                    (run_id, liquidation_id),
                ).fetchall()
            )
            if not legs:
                raise TypeError("liquidation cancellation has no legs")
            for index, raw in enumerate(canceled_orders, start=1):
                track_id = str(raw["track_id"])
                broker_order_id = str(raw["order_id"])
                order_id = f"{track_id}:{broker_order_id}"
                leg = next(
                    (item for item in legs if str(item["track_id"]) == track_id),
                    legs[0],
                )
                payload = {
                    "case_id": liquidation_id,
                    "step_sequence": step_sequence,
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "track_id": track_id,
                    "state": "CANCELED",
                }
                connection.execute(
                    """
                    INSERT OR IGNORE INTO replay_training_liquidation_order(
                        run_id, case_id, step_sequence, order_id,
                        liquidation_leg_id, order_sequence, side, order_type,
                        requested_quantity, filled_quantity, remaining_quantity,
                        average_price, state, order_hash, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 'BUY', 'LIMIT', '0', '0', '0',
                              NULL, 'CANCELED', ?, ?, ?)
                    """,
                    (
                        run_id,
                        liquidation_id,
                        step_sequence,
                        order_id,
                        leg["liquidation_leg_id"],
                        index,
                        canonical_sha256(payload),
                        now_ms,
                        now_ms,
                    ),
                )
            after_snapshot_id, _risk = (
                liquidation_ops.capture_liquidation_risk_snapshot(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    label="CANCELED",
                    account_status="CANCELING_ORDERS",
                    now_ms=now_ms,
                )
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = 'RISK_RECHECK', updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (now_ms, run_id, liquidation_id),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type="RISK_RECHECK",
                before_snapshot_id=after_snapshot_id,
                plan={"recompute_after_margin_release": True},
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_adl(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "ADL":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "ADL step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            reason = json.loads(str(step["reason"]))
            plan = cast(
                Mapping[str, object], cast(Mapping[str, object], reason)["plan"]
            )
            projection = connection.execute(
                """
                SELECT * FROM replay_hedge_input_projection
                WHERE run_id = ? AND source_kind = 'SIMULATION'
                """,
                (run_id,),
            ).fetchone()
            if projection is None:
                raise TrainingRunError(
                    "LIQUIDATION_ADL_INPUT_MISSING",
                    "materialized ADL simulation projection is unavailable",
                    status_code=409,
                )
            state = json.loads(str(projection["state_json"]))
            snapshots = (
                state.get("adl_snapshots") if isinstance(state, Mapping) else None
            )
            raw_snapshot = (
                snapshots.get(str(plan["symbol"]))
                if isinstance(snapshots, Mapping)
                else None
            )
            if not isinstance(raw_snapshot, Mapping):
                raise TrainingRunError(
                    "LIQUIDATION_ADL_INPUT_MISSING",
                    "materialized ADL cohort for the bankrupt symbol is unavailable",
                    status_code=409,
                )
            case = connection.execute(
                """
                SELECT trigger_virtual_time_ms, trigger_source_sequence
                FROM replay_training_liquidation_case
                WHERE run_id = ? AND case_id = ?
                """,
                (run_id, liquidation_id),
            ).fetchone()
            if case is None:
                raise TypeError("ADL liquidation case is missing")
            trigger_time = int(case["trigger_virtual_time_ms"])
            if not (
                int(raw_snapshot["effective_time_ms"])
                <= trigger_time
                <= int(raw_snapshot["valid_until_ms"])
            ):
                raise TrainingRunError(
                    "LIQUIDATION_ADL_INPUT_GAP",
                    "materialized ADL cohort does not cover the liquidation time",
                    status_code=409,
                )
            raw_candidates = raw_snapshot.get("candidates")
            if not isinstance(raw_candidates, list):
                raise TypeError("ADL candidate projection is invalid")
            ranked = rank_adl_candidates(
                raw_candidates,
                bankrupt_position_side=str(plan["bankrupt_position_side"]),
                quote_step=plan["quote_step"],
            )
            selection = select_adl_candidates(
                raw_candidates,
                bankrupt_position_side=str(plan["bankrupt_position_side"]),
                takeover_quantity=plan["takeover_quantity"],
                quote_step=plan["quote_step"],
            )
            if selection["status"] != "COMPLETED":
                raise TrainingRunError(
                    "LIQUIDATION_ADL_COHORT_EXHAUSTED",
                    "materialized ADL cohort cannot absorb the uncovered bankruptcy quantity",
                    status_code=409,
                    details={"remaining_quantity": selection["remaining_quantity"]},
                )
            now_ms = self.base_store._validated_now_ms()
            snapshot_id = f"adl-{liquidation_id}-{step_sequence:03d}"
            snapshot_payload = {
                "snapshot_id": snapshot_id,
                "case_id": liquidation_id,
                "step_sequence": step_sequence,
                "symbol": plan["symbol"],
                "model_version": ADL_MODEL_VERSION,
                "source_snapshot_hash": raw_snapshot["snapshot_hash"],
                "input_chain_hash": projection["input_chain_hash"],
                "ranked_candidate_ids": [item["candidate_id"] for item in ranked],
            }
            connection.execute(
                """
                INSERT INTO replay_training_adl_snapshot(
                    run_id, snapshot_id, case_id, step_sequence, symbol,
                    cohort_sequence, model_version, input_hash, snapshot_hash,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot_id,
                    liquidation_id,
                    step_sequence,
                    plan["symbol"],
                    ADL_MODEL_VERSION,
                    canonical_sha256(
                        {
                            "source_snapshot_hash": raw_snapshot["snapshot_hash"],
                            "input_chain_hash": projection["input_chain_hash"],
                        }
                    ),
                    canonical_sha256(snapshot_payload),
                    now_ms,
                ),
            )
            ranked_by_id = {str(item["candidate_id"]): item for item in ranked}
            for rank, candidate in enumerate(ranked, start=1):
                payload = {
                    "snapshot_id": snapshot_id,
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
                connection.execute(
                    """
                    INSERT INTO replay_training_adl_candidate(
                        run_id, snapshot_id, candidate_id, rank, position_side,
                        quantity, entry_price, mark_price, profit_ratio,
                        effective_leverage, score, candidate_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        snapshot_id,
                        candidate["candidate_id"],
                        rank,
                        candidate["position_side"],
                        candidate["quantity"],
                        candidate["entry_price"],
                        candidate["mark_price"],
                        candidate["profit_ratio"],
                        candidate["effective_leverage"],
                        candidate["score"],
                        canonical_sha256(payload),
                    ),
                )
            adl_event_id = f"adl-event-{liquidation_id}-{step_sequence:03d}"
            takeover_price = Decimal(str(plan["takeover_price"]))
            completed_notional = (
                Decimal(str(plan["takeover_quantity"]))
                * takeover_price
                * Decimal(str(plan["contract_size"]))
            )
            event_payload = {
                "adl_event_id": adl_event_id,
                "case_id": liquidation_id,
                "step_sequence": step_sequence,
                "snapshot_id": snapshot_id,
                "required_notional": plan["uncovered_deficit"],
                "completed_notional": decimal_to_string(
                    completed_notional, field_name="ADL completed notional"
                ),
            }
            connection.execute(
                """
                INSERT INTO replay_training_adl_event(
                    run_id, adl_event_id, case_id, step_sequence, snapshot_id,
                    required_notional, completed_notional, state, event_hash,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
                """,
                (
                    run_id,
                    adl_event_id,
                    liquidation_id,
                    step_sequence,
                    snapshot_id,
                    plan["uncovered_deficit"],
                    event_payload["completed_notional"],
                    canonical_sha256(event_payload),
                    now_ms,
                    now_ms,
                ),
            )
            previous_hash = "sha256:" + "0" * 64
            selected = cast(list[dict[str, str]], selection["selected"])
            for sequence, item in enumerate(selected, start=1):
                candidate = ranked_by_id[item["candidate_id"]]
                quantity = Decimal(str(item["quantity"]))
                entry = Decimal(str(candidate["entry_price"]))
                cash_delta = (
                    (takeover_price - entry) * quantity
                    if candidate["position_side"] == "LONG"
                    else (entry - takeover_price) * quantity
                ) * Decimal(str(plan["contract_size"]))
                notional = (
                    quantity * takeover_price * Decimal(str(plan["contract_size"]))
                )
                selection_payload = {
                    "adl_event_id": adl_event_id,
                    "selection_sequence": sequence,
                    "candidate_id": item["candidate_id"],
                    "quantity": item["quantity"],
                    "price": plan["takeover_price"],
                    "notional": decimal_to_string(
                        notional, field_name="ADL selection notional"
                    ),
                    "cash_delta": decimal_to_string(
                        cash_delta, field_name="ADL cash delta"
                    ),
                }
                connection.execute(
                    """
                    INSERT INTO replay_training_adl_selection(
                        run_id, adl_event_id, selection_sequence, candidate_id,
                        snapshot_id, quantity, price, notional, cash_delta,
                        selection_hash, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        adl_event_id,
                        sequence,
                        item["candidate_id"],
                        snapshot_id,
                        item["quantity"],
                        plan["takeover_price"],
                        selection_payload["notional"],
                        selection_payload["cash_delta"],
                        canonical_sha256(selection_payload),
                        now_ms,
                    ),
                )
                quantity_before = Decimal(str(candidate["quantity"]))
                quantity_after = quantity_before - quantity
                ledger_payload = {
                    "adl_event_id": adl_event_id,
                    "ledger_sequence": sequence,
                    "candidate_id": item["candidate_id"],
                    "position_side": candidate["position_side"],
                    "quantity_before": candidate["quantity"],
                    "quantity_delta": decimal_to_string(
                        -quantity, field_name="ADL quantity delta"
                    ),
                    "quantity_after": decimal_to_string(
                        quantity_after, field_name="ADL quantity after"
                    ),
                    "takeover_price": plan["takeover_price"],
                    "cash_delta": selection_payload["cash_delta"],
                }
                entry_hash = ledger_chain_hash(
                    previous_hash=previous_hash,
                    ledger_sequence=sequence,
                    posting=ledger_payload,
                )
                connection.execute(
                    """
                    INSERT INTO replay_training_adl_counterparty_ledger(
                        run_id, adl_event_id, ledger_sequence, candidate_id,
                        snapshot_id, position_side, quantity_before,
                        quantity_delta, quantity_after, takeover_price,
                        cash_delta, previous_hash, entry_hash, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        adl_event_id,
                        sequence,
                        item["candidate_id"],
                        snapshot_id,
                        candidate["position_side"],
                        ledger_payload["quantity_before"],
                        ledger_payload["quantity_delta"],
                        ledger_payload["quantity_after"],
                        plan["takeover_price"],
                        ledger_payload["cash_delta"],
                        previous_hash,
                        entry_hash,
                        now_ms,
                    ),
                )
                previous_hash = entry_hash
            after_snapshot_id, _risk = (
                liquidation_ops.capture_liquidation_risk_snapshot(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    label="ADL",
                    account_status="ADL",
                    now_ms=now_ms,
                )
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = 'ADL', updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (now_ms, run_id, liquidation_id),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type="COMPLETE",
                before_snapshot_id=after_snapshot_id,
                plan={
                    "terminal_state": "BANKRUPT",
                    "bankruptcy": True,
                    "adl_event_id": adl_event_id,
                },
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_complete(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "COMPLETE":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "liquidation completion step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            now_ms = self.base_store._validated_now_ms()
            reason = json.loads(str(step["reason"]))
            plan = cast(
                Mapping[str, object], cast(Mapping[str, object], reason)["plan"]
            )
            after_snapshot_id, risk = liquidation_ops.capture_liquidation_risk_snapshot(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_sequence=step_sequence,
                label="COMPLETE",
                account_status=str(plan["terminal_state"]),
                now_ms=now_ms,
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            terminal = str(plan["terminal_state"])
            case_state = (
                "RECOVERED_AFTER_CANCEL"
                if terminal == "RECOVERED_AFTER_CANCEL"
                else "COMPLETED"
            )
            steps = [
                {
                    "step_sequence": int(row["step_sequence"]),
                    "step_type": str(row["step_type"]),
                    "state": str(row["state"]),
                    "step_hash": str(row["step_hash"]),
                    "after_snapshot_id": row["after_snapshot_id"],
                }
                for row in connection.execute(
                    """
                    SELECT * FROM replay_training_liquidation_step
                    WHERE run_id = ? AND case_id = ? ORDER BY step_sequence
                    """,
                    (run_id, liquidation_id),
                ).fetchall()
            ]
            component_hash = canonical_sha256(
                {
                    "schema_version": "replay.liquidation-case.v2",
                    "case_id": liquidation_id,
                    "terminal_state": terminal,
                    "final_snapshot_id": after_snapshot_id,
                    "steps": steps,
                }
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = ?, final_snapshot_id = ?, component_hash = ?,
                    updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (
                    case_state,
                    after_snapshot_id,
                    component_hash,
                    now_ms,
                    run_id,
                    liquidation_id,
                ),
            )
            another = connection.execute(
                """
                SELECT 1 FROM replay_training_liquidation_case
                WHERE run_id = ? AND case_id != ?
                  AND state NOT IN ('COMPLETED', 'BANKRUPT', 'FAILED_CLOSED', 'RECOVERED_AFTER_CANCEL')
                LIMIT 1
                """,
                (run_id, liquidation_id),
            ).fetchone()
            account_status = (
                "LIQUIDATING"
                if another is not None
                else "BANKRUPT"
                if bool(plan.get("bankruptcy")) or cast(Decimal, risk["equity"]) < 0
                else "ACTIVE"
            )
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET status = ?, updated_at_ms = ? WHERE run_id = ?
                """,
                (account_status, now_ms, run_id),
            )
            adapter = connection.execute(
                """
                SELECT track.adapter_session_id
                FROM replay_training_liquidation_leg AS leg
                JOIN replay_training_market_track AS track
                  ON track.run_id = leg.run_id AND track.track_id = leg.track_id
                WHERE leg.run_id = ? AND leg.case_id = ?
                ORDER BY leg.leg_sequence LIMIT 1
                """,
                (run_id, liquidation_id),
            ).fetchone()
            if adapter is not None and isinstance(adapter["adapter_session_id"], str):
                self._review.append(
                    connection,
                    run_id=run_id,
                    session_id=str(adapter["adapter_session_id"]),
                    context={
                        "kind": "DIRECT",
                        "category": "LIQUIDATION",
                        "event_type": "LIQUIDATION",
                        "command_id": f"liquidation-complete:{liquidation_id}",
                    },
                    state=None,
                    checkpoint=None,
                    now_ms=now_ms,
                )

        await self.base_store.run_extension_write(write)

    async def fail_liquidation_case(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        failure_code: str,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            now_ms = self.base_store._validated_now_ms()
            pending = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND state = 'PENDING'
                ORDER BY step_sequence LIMIT 1
                """,
                (run_id, liquidation_id),
            ).fetchone()
            if pending is not None:
                connection.execute(
                    """
                    UPDATE replay_training_liquidation_step
                    SET state = 'FAILED_CLOSED', reason = ?, committed_at_ms = ?
                    WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                    """,
                    (
                        canonical_json(
                            {"cause": "FAILED_CLOSED", "failure_code": failure_code}
                        ),
                        now_ms,
                        run_id,
                        liquidation_id,
                        pending["step_sequence"],
                    ),
                )
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = 'FAILED_CLOSED', reason = ?, updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (failure_code, now_ms, run_id, liquidation_id),
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_leg
                SET state = 'FAILED_CLOSED'
                WHERE run_id = ? AND case_id = ? AND state NOT IN ('CLOSED', 'TRANSFERRED')
                """,
                (run_id, liquidation_id),
            )
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET status = 'FAILED_CLOSED', updated_at_ms = ? WHERE run_id = ?
                """,
                (now_ms, run_id),
            )
            connection.execute(
                """
                UPDATE replay_training_run
                SET state = 'PAUSED', compatibility = 'DEGRADED',
                    updated_at_ms = ?, saved_at_ms = ? WHERE run_id = ?
                """,
                (now_ms, now_ms, run_id),
            )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_bankruptcy(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "BANKRUPTCY_TRANSFER":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "bankruptcy transfer step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            now_ms = self.base_store._validated_now_ms()
            reason = json.loads(str(step["reason"]))
            plan = cast(
                Mapping[str, object], cast(Mapping[str, object], reason)["plan"]
            )
            deficit = Decimal(str(plan["bankruptcy_deficit"]))
            legs = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_liquidation_leg
                    WHERE run_id = ? AND case_id = ? ORDER BY leg_sequence
                    """,
                    (run_id, liquidation_id),
                ).fetchall()
            )
            if deficit <= 0 or not legs:
                raise TrainingRunError(
                    "LIQUIDATION_BANKRUPTCY_INVALID",
                    "bankruptcy transfer requires a positive deficit and durable legs",
                    status_code=409,
                )
            connection.execute(
                """
                UPDATE replay_training_liquidation_leg
                SET state = 'TRANSFERRED', takeover_price = bankruptcy_price
                WHERE run_id = ? AND case_id = ?
                """,
                (run_id, liquidation_id),
            )
            after_snapshot_id, _risk = (
                liquidation_ops.capture_liquidation_risk_snapshot(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    label="BANKRUPTCY",
                    account_status="BANKRUPTCY_TRANSFER",
                    now_ms=now_ms,
                )
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = 'INSURANCE_FUND_SETTLEMENT', updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (now_ms, run_id, liquidation_id),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type="INSURANCE_FUND_SETTLEMENT",
                before_snapshot_id=after_snapshot_id,
                plan={
                    "bankruptcy_deficit": str(plan["bankruptcy_deficit"]),
                    "recovered": False,
                },
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_insurance(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "INSURANCE_FUND_SETTLEMENT":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "insurance settlement step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            reason = json.loads(str(step["reason"]))
            plan = cast(
                Mapping[str, object], cast(Mapping[str, object], reason)["plan"]
            )
            deficit = Decimal(str(plan.get("bankruptcy_deficit", "0")))
            now_ms = self.base_store._validated_now_ms()
            run = connection.execute(
                "SELECT settlement_asset FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            fund = connection.execute(
                """
                SELECT * FROM replay_training_insurance_fund
                WHERE run_id = ? AND asset = ?
                """,
                (run_id, run["settlement_asset"] if run is not None else ""),
            ).fetchone()
            if run is None or fund is None:
                raise TrainingRunError(
                    "LIQUIDATION_SIMULATION_INPUT_MISSING",
                    "pinned insurance fund state is unavailable",
                    status_code=409,
                )
            asset = str(run["settlement_asset"])
            fee_rows = connection.execute(
                """
                SELECT liquidation_fee
                FROM replay_training_liquidation_fill
                WHERE run_id = ? AND case_id = ?
                """,
                (run_id, liquidation_id),
            ).fetchall()
            fee_inflow = sum(
                (Decimal(str(row["liquidation_fee"])) for row in fee_rows),
                Decimal(0),
            )
            settlement = settle_insurance_fund(
                balance=fund["current_balance"],
                deficit=decimal_to_string(deficit, field_name="insurance deficit"),
                liquidation_fee_inflow=decimal_to_string(
                    fee_inflow,
                    field_name="insurance liquidation fee inflow",
                ),
            )
            if fee_inflow > 0:
                liquidation_ops.append_insurance_posting(
                    connection,
                    run_id=run_id,
                    asset=asset,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    cash_delta=fee_inflow,
                    reason="LIQUIDATION_FEE_INFLOW",
                    now_ms=now_ms,
                )
            coverage = Decimal(str(settlement["coverage"]))
            if coverage > 0:
                liquidation_ops.append_insurance_posting(
                    connection,
                    run_id=run_id,
                    asset=asset,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    cash_delta=-coverage,
                    reason="BANKRUPTCY_DEFICIT_DEBIT",
                    now_ms=now_ms,
                )
            uncovered = Decimal(str(settlement["uncovered_deficit"]))
            after_snapshot_id, _risk = (
                liquidation_ops.capture_liquidation_risk_snapshot(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                    step_sequence=step_sequence,
                    label="INSURANCE",
                    account_status="INSURANCE_FUND_SETTLEMENT",
                    now_ms=now_ms,
                )
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            if uncovered > 0:
                adl_legs = connection.execute(
                    """
                SELECT leg.*, track.symbol, proof.takeover_price AS proof_takeover_price,
                       proof.price_tick, proof.rule_revision AS proof_rule_revision
                    FROM replay_training_liquidation_leg AS leg
                    JOIN replay_training_market_track AS track
                      ON track.run_id = leg.run_id AND track.track_id = leg.track_id
                    JOIN replay_training_liquidation_leg_price_proof AS proof
                     ON proof.run_id = leg.run_id AND proof.case_id = leg.case_id
                     AND proof.liquidation_leg_id = leg.liquidation_leg_id
                    WHERE leg.run_id = ? AND leg.case_id = ?
                    ORDER BY leg.leg_sequence
                    """,
                    (run_id, liquidation_id),
                ).fetchall()
                if not adl_legs:
                    raise TrainingRunError(
                        "LIQUIDATION_ADL_INPUT_MISSING",
                        "bankruptcy leg price proof is unavailable for ADL",
                        status_code=409,
                    )
                leg = max(
                    adl_legs,
                    key=lambda candidate: (
                        Decimal(str(candidate["trigger_notional"])),
                        -int(candidate["leg_sequence"]),
                    ),
                )
                takeover_price = Decimal(str(leg["proof_takeover_price"]))
                rule_row = connection.execute(
                    """
                    SELECT rule_json FROM replay_training_instrument_rule
                    WHERE run_id = ? AND track_id = ? AND revision = ?
                    """,
                    (run_id, leg["track_id"], leg["proof_rule_revision"]),
                ).fetchone()
                if rule_row is None or takeover_price <= 0:
                    raise TrainingRunError(
                        "LIQUIDATION_ADL_INPUT_MISSING",
                        "ADL quantity cannot be reconstructed from the pinned rule",
                        status_code=409,
                    )
                rule = InstrumentRule.from_mapping(
                    json.loads(str(rule_row["rule_json"]))
                )
                takeover_quantity = round_to_step(
                    uncovered / (takeover_price * Decimal(rule.contract_size)),
                    Decimal(rule.quantity_step),
                    upward=True,
                )
                next_type = "ADL"
                next_plan: dict[str, object] = {
                    "uncovered_deficit": decimal_to_string(
                        uncovered, field_name="ADL uncovered deficit"
                    ),
                    "symbol": str(leg["symbol"]),
                    "bankrupt_position_side": str(leg["position_side"]),
                    "takeover_price": decimal_to_string(
                        takeover_price, field_name="ADL takeover price"
                    ),
                    "takeover_quantity": decimal_to_string(
                        takeover_quantity, field_name="ADL takeover quantity"
                    ),
                    "quote_step": rule.quote_step,
                    "contract_size": rule.contract_size,
                    "rule_revision": int(leg["proof_rule_revision"]),
                    "track_id": str(leg["track_id"]),
                }
            else:
                next_type = "COMPLETE"
                next_plan = {
                    "terminal_state": "BANKRUPT" if deficit > 0 else "ACTIVE",
                    "bankruptcy": deficit > 0,
                }
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = ?, updated_at_ms = ? WHERE run_id = ? AND case_id = ?
                """,
                (
                    "INSURANCE_FUND_SETTLEMENT"
                    if next_type == "COMPLETE"
                    else next_type,
                    now_ms,
                    run_id,
                    liquidation_id,
                ),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type=next_type,
                before_snapshot_id=after_snapshot_id,
                plan=next_plan,
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_recheck(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) != "RISK_RECHECK":
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "liquidation risk recheck step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            now_ms = self.base_store._validated_now_ms()
            after_snapshot_id, risk = liquidation_ops.capture_liquidation_risk_snapshot(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_sequence=step_sequence,
                label="RECHECKED",
                account_status="RISK_RECHECK",
                now_ms=now_ms,
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            try:
                next_plan = liquidation_ops.next_liquidation_trade_plan(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                )
            except TrainingRunError as exc:
                next_plan = (
                    "FAILED_CLOSED",
                    {"failure_code": exc.code, "fallback_applied": False},
                )
            if next_plan is None:
                next_type = "COMPLETE"
                plan: dict[str, object] = {
                    "terminal_state": "RECOVERED_AFTER_CANCEL",
                    "bankruptcy": False,
                }
            else:
                next_type, plan = next_plan
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = ?, updated_at_ms = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (
                    (
                        "RISK_RECHECK"
                        if next_type in {"COMPLETE", "FAILED_CLOSED"}
                        else next_type
                    ),
                    now_ms,
                    run_id,
                    liquidation_id,
                ),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type=next_type,
                before_snapshot_id=after_snapshot_id,
                plan=plan,
                now_ms=now_ms,
            )
            if not bool(risk["breached"]):
                connection.execute(
                    """
                    UPDATE replay_training_contract_account
                    SET status = 'ACTIVE', updated_at_ms = ? WHERE run_id = ?
                    """,
                    (now_ms, run_id),
                )

        await self.base_store.run_extension_write(write)

    async def commit_liquidation_execution(
        self,
        *,
        run_id: str,
        liquidation_id: str,
        step_sequence: int,
        order_id: str,
    ) -> None:
        def write(connection: sqlite3.Connection) -> None:
            step = connection.execute(
                """
                SELECT * FROM replay_training_liquidation_step
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (run_id, liquidation_id, step_sequence),
            ).fetchone()
            if step is None or str(step["step_type"]) not in {
                "PARTIAL_LIQUIDATION",
                "FULL_LIQUIDATION",
            }:
                raise TrainingRunError(
                    "LIQUIDATION_STATE_CONFLICT",
                    "liquidation execution step is unavailable",
                    status_code=409,
                )
            if str(step["state"]) == "APPLIED":
                return
            reason = json.loads(str(step["reason"]))
            if not isinstance(reason, Mapping) or not isinstance(
                reason.get("plan"), Mapping
            ):
                raise TypeError("liquidation execution plan is invalid")
            plan = cast(Mapping[str, object], reason["plan"])
            track_id = str(plan["track_id"])
            hedge_execution = str(plan.get("position_mode")) == "HEDGE"
            execution_model = str(plan.get("execution_model", ""))
            book_execution_raw = plan.get("book_execution")
            book_execution = (
                cast(Mapping[str, object], book_execution_raw)
                if isinstance(book_execution_raw, Mapping)
                else None
            )
            historical_book_execution = (
                execution_model == HISTORICAL_L2_LIQUIDATION_FIDELITY
            )
            if historical_book_execution and book_execution is None:
                raise TrainingRunError(
                    "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                    "historical L2 liquidation has no frozen execution proof",
                    status_code=409,
                )
            if book_execution is not None and not historical_book_execution:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "non-L2 liquidation cannot carry a historical book execution proof",
                    status_code=409,
                )
            if hedge_execution and execution_model not in {
                HISTORICAL_L2_LIQUIDATION_FIDELITY,
                account_math_ops.TOUCH_OR_TAPE_LIQUIDATION_FIDELITY,
            }:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "HEDGE liquidation execution model is missing or unsupported",
                    status_code=409,
                )
            order_row = connection.execute(
                """
                SELECT * FROM replay_training_contract_order
                WHERE run_id = ? AND track_id = ? AND order_id = ?
                """,
                (run_id, track_id, order_id),
            ).fetchone()
            if order_row is None:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "liquidation broker order is not durable",
                    status_code=409,
                )
            raw_order = json.loads(str(order_row["order_json"]))
            if not isinstance(raw_order, Mapping):
                raise TypeError("liquidation broker order projection is invalid")
            if (
                str(raw_order.get("quantity")) != str(plan["quantity"])
                or str(raw_order.get("side")) != str(plan["side"])
                or str(raw_order.get("order_type")) != "MARKET"
                or raw_order.get("reduce_only") is not True
                or (
                    hedge_execution
                    and str(raw_order.get("position_side"))
                    != str(plan["position_side"])
                )
            ):
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "liquidation broker order differs from the durable plan",
                    status_code=409,
                )
            fill_rows = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_contract_fill
                    WHERE run_id = ? AND track_id = ?
                      AND json_extract(fill_json, '$.order_id') = ?
                    ORDER BY fill_id
                    """,
                    (run_id, track_id, order_id),
                ).fetchall()
            )
            if not fill_rows:
                raise TrainingRunError(
                    "LIQUIDATION_EXECUTION_FAILED",
                    "liquidation broker order has no durable fill",
                    status_code=409,
                )
            planned_levels: tuple[Mapping[str, object], ...] = ()
            if book_execution is not None:
                raw_planned_levels = book_execution.get("levels")
                if not isinstance(raw_planned_levels, list) or not all(
                    isinstance(level, Mapping) for level in raw_planned_levels
                ):
                    raise TrainingRunError(
                        "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                        "historical L2 liquidation levels are invalid",
                        status_code=409,
                    )
                planned_levels = tuple(
                    cast(Mapping[str, object], level) for level in raw_planned_levels
                )
                proof_payload = {
                    "archive_id": str(book_execution["archive_id"]),
                    "as_of_virtual_time_ms": int(
                        book_execution["as_of_virtual_time_ms"]
                    ),
                    "last_update_id": int(book_execution["last_update_id"]),
                    "side": str(book_execution["side"]),
                    "requested_quantity": str(book_execution["requested_quantity"]),
                    "visible_quantity": str(book_execution["visible_quantity"]),
                    "levels": [dict(level) for level in planned_levels],
                    "book_hash": str(book_execution["book_hash"]),
                    "execution_fidelity": str(book_execution["execution_fidelity"]),
                    "queue_exact": False,
                }
                if (
                    book_execution.get("queue_exact") is not False
                    or str(book_execution.get("execution_fidelity"))
                    != HISTORICAL_L2_LIQUIDATION_FIDELITY
                    or str(book_execution.get("execution_plan_hash"))
                    != canonical_sha256(proof_payload)
                    or str(book_execution.get("side")) != str(plan["side"])
                    or str(book_execution.get("requested_quantity"))
                    != str(plan["quantity"])
                    or len(planned_levels) != len(fill_rows)
                ):
                    raise TrainingRunError(
                        "HISTORICAL_BOOK_EXECUTION_UNAVAILABLE",
                        "historical L2 liquidation proof does not match the durable plan",
                        status_code=409,
                    )
                for level, row in zip(planned_levels, fill_rows, strict=True):
                    raw_fill = json.loads(str(row["fill_json"]))
                    if (
                        str(raw_fill.get("price")) != str(level["price"])
                        or str(raw_fill.get("quantity")) != str(level["quantity"])
                        or str(raw_fill.get("reason")) != "HISTORICAL_BOOK_LEVEL"
                        or raw_fill.get("historical_execution") is not True
                        or str(raw_fill.get("position_side"))
                        != str(plan["position_side"])
                    ):
                        raise TrainingRunError(
                            "LIQUIDATION_EXECUTION_FAILED",
                            "historical L2 broker fills differ from the frozen level plan",
                            status_code=409,
                        )
            elif hedge_execution:
                for row in fill_rows:
                    raw_fill = json.loads(str(row["fill_json"]))
                    if (
                        str(raw_fill.get("reason")) != "MARKET_REVEALED_REFERENCE"
                        or str(raw_fill.get("position_side"))
                        != str(plan["position_side"])
                        or str(raw_fill.get("price")) != str(plan["execution_price"])
                    ):
                        raise TrainingRunError(
                            "LIQUIDATION_EXECUTION_FAILED",
                            "no-book HEDGE liquidation fill differs from the pinned mark-slippage plan",
                            status_code=409,
                        )
            now_ms = self.base_store._validated_now_ms()
            requested = Decimal(str(plan["quantity"]))
            filled = sum(
                (
                    Decimal(str(json.loads(str(row["fill_json"]))["quantity"]))
                    for row in fill_rows
                ),
                Decimal(0),
            )
            remaining = max(Decimal(0), requested - filled)
            if hedge_execution and remaining != 0:
                raise TrainingRunError(
                    "HISTORICAL_BOOK_DEPTH_EXHAUSTED",
                    "historical L2 liquidation did not fully execute the frozen step",
                    status_code=409,
                )
            average = (
                sum(
                    (
                        Decimal(str(json.loads(str(row["fill_json"]))["price"]))
                        * Decimal(str(json.loads(str(row["fill_json"]))["quantity"]))
                        for row in fill_rows
                    ),
                    Decimal(0),
                )
                / filled
            )
            broker_order_id = order_id
            evidence_order_id = f"{track_id}:{broker_order_id}"
            order_payload = {
                "case_id": liquidation_id,
                "step_sequence": step_sequence,
                "order_id": evidence_order_id,
                "broker_order_id": broker_order_id,
                "track_id": track_id,
                "plan": dict(plan),
                "broker_order": dict(raw_order),
            }
            connection.execute(
                """
                INSERT INTO replay_training_liquidation_order(
                    run_id, case_id, step_sequence, order_id,
                    liquidation_leg_id, order_sequence, side, order_type,
                    requested_quantity, filled_quantity, remaining_quantity,
                    average_price, state, order_hash, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 'MARKET', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    liquidation_id,
                    step_sequence,
                    evidence_order_id,
                    plan["liquidation_leg_id"],
                    plan["side"],
                    plan["quantity"],
                    decimal_to_string(filled, field_name="liquidation filled quantity"),
                    decimal_to_string(
                        remaining, field_name="liquidation remaining quantity"
                    ),
                    decimal_to_string(average, field_name="liquidation average price"),
                    "FILLED" if remaining == 0 else "PARTIALLY_FILLED",
                    canonical_sha256(order_payload),
                    now_ms,
                    now_ms,
                ),
            )
            if book_execution is not None:
                connection.execute(
                    """
                    INSERT INTO replay_training_liquidation_book_execution(
                        run_id, case_id, step_sequence, track_id, archive_id,
                        as_of_virtual_time_ms, last_update_id, side,
                        requested_quantity, visible_quantity, levels_json,
                        book_hash, execution_fidelity, queue_exact,
                        execution_plan_hash, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        run_id,
                        liquidation_id,
                        step_sequence,
                        track_id,
                        book_execution["archive_id"],
                        book_execution["as_of_virtual_time_ms"],
                        book_execution["last_update_id"],
                        book_execution["side"],
                        book_execution["requested_quantity"],
                        book_execution["visible_quantity"],
                        canonical_json([dict(level) for level in planned_levels]),
                        book_execution["book_hash"],
                        book_execution["execution_fidelity"],
                        book_execution["execution_plan_hash"],
                        now_ms,
                    ),
                )
            total_liquidation_fee = Decimal(0)
            for fill_sequence, row in enumerate(fill_rows, start=1):
                raw = json.loads(str(row["fill_json"]))
                book_level = (
                    None
                    if not planned_levels
                    else int(planned_levels[fill_sequence - 1]["book_level"])
                )
                quantity = Decimal(str(raw["quantity"]))
                price = Decimal(str(raw["price"]))
                notional = quantity * price * Decimal(str(plan["contract_size"]))
                liquidation_fee = round_to_step(
                    notional
                    * Decimal(str(plan["liquidation_fee_bps"]))
                    / Decimal(10_000),
                    Decimal(str(plan["quote_step"])),
                    upward=True,
                )
                total_liquidation_fee += liquidation_fee
                evidence_fill_id = f"{track_id}:{raw['fill_id']}"
                fill_payload = {
                    "case_id": liquidation_id,
                    "order_id": evidence_order_id,
                    "broker_order_id": broker_order_id,
                    "track_id": track_id,
                    "fill_id": evidence_fill_id,
                    "broker_fill_id": str(raw["fill_id"]),
                    "price": str(raw["price"]),
                    "quantity": str(raw["quantity"]),
                    "notional": decimal_to_string(
                        notional, field_name="liquidation notional"
                    ),
                    "trading_fee": str(row["configured_fee"]),
                    "liquidation_fee": decimal_to_string(
                        liquidation_fee,
                        field_name="liquidation fee",
                    ),
                    "source_sequence": int(raw["source_sequence"]),
                    "event_time_ms": int(raw["event_time_ms"]),
                    "model_version": raw.get("model_version"),
                    "book_level": book_level,
                    "book_hash": (
                        None if book_execution is None else book_execution["book_hash"]
                    ),
                    "execution_plan_hash": (
                        None
                        if book_execution is None
                        else book_execution["execution_plan_hash"]
                    ),
                    "execution_fidelity": (
                        execution_model
                        if book_execution is None
                        else book_execution["execution_fidelity"]
                    ),
                    "queue_exact": False if hedge_execution else None,
                }
                connection.execute(
                    """
                    INSERT INTO replay_training_liquidation_fill(
                        run_id, case_id, order_id, fill_id, broker_fill_id,
                        fill_sequence,
                        price, quantity, notional, trading_fee, liquidation_fee,
                        book_level, virtual_time_ms, source_sequence, fill_hash,
                        created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        liquidation_id,
                        evidence_order_id,
                        evidence_fill_id,
                        raw["fill_id"],
                        fill_sequence,
                        raw["price"],
                        raw["quantity"],
                        fill_payload["notional"],
                        row["configured_fee"],
                        fill_payload["liquidation_fee"],
                        book_level,
                        raw["event_time_ms"],
                        raw["source_sequence"],
                        canonical_sha256(fill_payload),
                        now_ms,
                    ),
                )
            account = connection.execute(
                """
                SELECT account.overlay_cash, run.settlement_asset
                FROM replay_training_contract_account AS account
                JOIN replay_training_run AS run USING(run_id)
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if account is None:
                raise TypeError("liquidation account is missing")
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET overlay_cash = ?, updated_at_ms = ? WHERE run_id = ?
                """,
                (
                    decimal_to_string(
                        Decimal(str(account["overlay_cash"])) - total_liquidation_fee,
                        field_name="liquidation overlay cash",
                    ),
                    now_ms,
                    run_id,
                ),
            )
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=(f"liquidation-fee:{liquidation_id}:{evidence_order_id}"),
                track_id=track_id,
                kind="LIQUIDATION_FEE",
                cash_delta=-total_liquidation_fee,
                asset=str(account["settlement_asset"]),
                virtual_time_ms=max(
                    int(json.loads(str(row["fill_json"]))["event_time_ms"])
                    for row in fill_rows
                ),
                source_sequence=max(
                    int(json.loads(str(row["fill_json"]))["source_sequence"])
                    for row in fill_rows
                ),
                fidelity=(
                    HISTORICAL_L2_LIQUIDATION_FIDELITY
                    if book_execution is not None
                    else account_math_ops.TOUCH_OR_TAPE_LIQUIDATION_FIDELITY
                    if hedge_execution
                    else "PINNED_RULE_REAL_BROKER_FILL"
                ),
                rule_revision=int(plan["rule_revision"]),
                reference_type="LIQUIDATION_ORDER",
                reference_id=evidence_order_id,
                metadata={
                    "case_id": liquidation_id,
                    "broker_order_id": broker_order_id,
                    "position_side": plan["position_side"],
                    "liquidation_leg_id": plan["liquidation_leg_id"],
                    "step_sequence": step_sequence,
                    "book_hash": (
                        None if book_execution is None else book_execution["book_hash"]
                    ),
                    "execution_plan_hash": (
                        None
                        if book_execution is None
                        else book_execution["execution_plan_hash"]
                    ),
                },
                now_ms=now_ms,
            )
            leg = connection.execute(
                """
                SELECT completed_quantity, target_quantity
                FROM replay_training_liquidation_leg
                WHERE run_id = ? AND case_id = ? AND liquidation_leg_id = ?
                """,
                (run_id, liquidation_id, plan["liquidation_leg_id"]),
            ).fetchone()
            if leg is None:
                raise TypeError("liquidation execution leg is missing")
            completed = min(
                Decimal(str(leg["target_quantity"])),
                Decimal(str(leg["completed_quantity"])) + filled,
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_leg
                SET completed_quantity = ?, state = ?
                WHERE run_id = ? AND case_id = ? AND liquidation_leg_id = ?
                """,
                (
                    decimal_to_string(
                        completed, field_name="completed liquidation quantity"
                    ),
                    "CLOSED"
                    if completed >= Decimal(str(leg["target_quantity"]))
                    else "PARTIAL",
                    run_id,
                    liquidation_id,
                    plan["liquidation_leg_id"],
                ),
            )
            liquidation_ops.detect_contract_liquidations(
                connection, run_id=run_id, now_ms=now_ms
            )
            after_snapshot_id, risk = liquidation_ops.capture_liquidation_risk_snapshot(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_sequence=step_sequence,
                label="EXECUTED",
                account_status=str(step["step_type"]),
                now_ms=now_ms,
            )
            connection.execute(
                """
                UPDATE replay_training_liquidation_step
                SET state = 'APPLIED', after_snapshot_id = ?, committed_at_ms = ?
                WHERE run_id = ? AND case_id = ? AND step_sequence = ?
                """,
                (after_snapshot_id, now_ms, run_id, liquidation_id, step_sequence),
            )
            try:
                next_plan = liquidation_ops.next_liquidation_trade_plan(
                    connection,
                    run_id=run_id,
                    case_id=liquidation_id,
                    require_breach=str(step["step_type"]) != "FULL_LIQUIDATION",
                )
            except TrainingRunError as exc:
                next_plan = (
                    "FAILED_CLOSED",
                    {"failure_code": exc.code, "fallback_applied": False},
                )
            if next_plan is not None:
                next_type, next_payload = next_plan
            else:
                remaining_case_quantity = sum(
                    (
                        Decimal(str(row["absolute_quantity"]))
                        for row in cast(list[dict[str, object]], risk["active_legs"])
                        if connection.execute(
                            """
                            SELECT 1 FROM replay_training_liquidation_leg
                            WHERE run_id = ? AND case_id = ?
                              AND track_id = ? AND position_side = ?
                            """,
                            (
                                run_id,
                                liquidation_id,
                                row["track_id"],
                                row["position_side"],
                            ),
                        ).fetchone()
                        is not None
                    ),
                    Decimal(0),
                )
                run_contract = connection.execute(
                    """
                    SELECT position_mode, account_data_mode
                    FROM replay_training_run WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if remaining_case_quantity > 0:
                    next_type = "INSURANCE_FUND_SETTLEMENT"
                    next_payload = {"bankruptcy_deficit": "0", "recovered": True}
                elif (
                    run_contract is not None
                    and str(run_contract["position_mode"]) != "HEDGE"
                ):
                    deficit = max(Decimal(0), -cast(Decimal, risk["equity"]))
                    next_type = "COMPLETE"
                    next_payload = {
                        "terminal_state": "BANKRUPT" if deficit > 0 else "ACTIVE",
                        "bankruptcy": deficit > 0,
                    }
                else:
                    deficit = max(Decimal(0), -cast(Decimal, risk["equity"]))
                    next_type = (
                        "BANKRUPTCY_TRANSFER"
                        if deficit > 0
                        else "INSURANCE_FUND_SETTLEMENT"
                    )
                    next_payload = {
                        "bankruptcy_deficit": decimal_to_string(
                            deficit, field_name="bankruptcy deficit"
                        ),
                        "recovered": deficit == 0,
                    }
            connection.execute(
                """
                UPDATE replay_training_liquidation_case
                SET state = ?, updated_at_ms = ? WHERE run_id = ? AND case_id = ?
                """,
                (
                    (
                        str(step["step_type"])
                        if next_type in {"COMPLETE", "FAILED_CLOSED"}
                        else next_type
                    ),
                    now_ms,
                    run_id,
                    liquidation_id,
                ),
            )
            liquidation_ops.insert_liquidation_step(
                connection,
                run_id=run_id,
                case_id=liquidation_id,
                step_type=next_type,
                before_snapshot_id=after_snapshot_id,
                plan=next_payload,
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def pending_liquidations(self, run_id: str) -> tuple[dict[str, object], ...]:
        def read(connection: sqlite3.Connection) -> tuple[dict[str, object], ...]:
            cases = connection.execute(
                """
                SELECT case_row.*, snapshot.equity AS account_equity_before
                FROM replay_training_liquidation_case AS case_row
                JOIN replay_training_risk_snapshot AS snapshot
                  ON snapshot.run_id = case_row.run_id
                 AND snapshot.snapshot_id = case_row.trigger_snapshot_id
                WHERE case_row.run_id = ?
                  AND case_row.state NOT IN (
                      'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED',
                      'RECOVERED_AFTER_CANCEL'
                  )
                ORDER BY case_row.case_sequence
                """,
                (run_id,),
            ).fetchall()
            result: list[dict[str, object]] = []
            for case in cases:
                case_id = str(case["case_id"])
                legs = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT leg.*, position.mark_price,
                               track.adapter_session_id, track.symbol,
                               track.stable_ordinal
                        FROM replay_training_liquidation_leg AS leg
                        JOIN replay_training_market_track AS track
                          ON track.run_id = leg.run_id
                         AND track.track_id = leg.track_id
                        LEFT JOIN replay_training_position_leg AS position
                          ON position.run_id = leg.run_id
                         AND position.track_id = leg.track_id
                         AND position.position_side = leg.position_side
                        WHERE leg.run_id = ? AND leg.case_id = ?
                        ORDER BY leg.leg_sequence
                        """,
                        (run_id, case_id),
                    ).fetchall()
                ]
                tracks: list[dict[str, object]] = []
                seen_tracks: set[str] = set()
                for leg in legs:
                    track_id = str(leg["track_id"])
                    if track_id in seen_tracks:
                        continue
                    seen_tracks.add(track_id)
                    track = connection.execute(
                        """
                        SELECT track_id, adapter_session_id, open_orders_json,
                               stable_ordinal, symbol
                        FROM replay_training_market_track
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (run_id, track_id),
                    ).fetchone()
                    if track is None:
                        raise TypeError("liquidation market track is missing")
                    tracks.append(
                        {
                            "track_id": track_id,
                            "adapter_session_id": track["adapter_session_id"],
                            "open_orders": json.loads(str(track["open_orders_json"])),
                            "stable_ordinal": int(track["stable_ordinal"]),
                            "symbol": str(track["symbol"]),
                        }
                    )
                pending_step = connection.execute(
                    """
                    SELECT * FROM replay_training_liquidation_step
                    WHERE run_id = ? AND case_id = ? AND state = 'PENDING'
                    ORDER BY step_sequence LIMIT 1
                    """,
                    (run_id, case_id),
                ).fetchone()
                if pending_step is None:
                    raise TypeError(
                        "active liquidation case has no pending durable step"
                    )
                reason = json.loads(str(pending_step["reason"]))
                if not isinstance(reason, Mapping) or not isinstance(
                    reason.get("plan"), Mapping
                ):
                    raise TypeError("liquidation step plan is invalid")
                result.append(
                    {
                        "liquidation_id": case_id,
                        "state": str(case["state"]),
                        "trigger_virtual_time_ms": int(case["trigger_virtual_time_ms"]),
                        "trigger_source_sequence": int(case["trigger_source_sequence"]),
                        "account_equity_before": str(case["account_equity_before"]),
                        "fidelity": str(case["fidelity"]),
                        "reason": str(case["reason"]),
                        "legs": legs,
                        "tracks": tracks,
                        "pending_step": {
                            **dict(pending_step),
                            "plan": dict(cast(Mapping[str, object], reason["plan"])),
                        },
                    }
                )
            return tuple(result)

        return await self.base_store.run_extension_read(read)
