"""Result records operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json


def sync_trade_results_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    component_state: Mapping[str, object],
    revealed_event_low: Decimal | None,
    revealed_event_high: Decimal | None,
    now_ms: int,
) -> None:
    """Incrementally project fills into immutable, reviewable trade results."""

    position = component_state.get("position")
    if isinstance(position, Mapping) and position.get("position_mode") == "HEDGE":
        for leg in ("LONG", "SHORT"):
            leg_component_state = dict(component_state)
            leg_component_state["position"] = position.get(leg.lower())
            sync_trade_results_projection_leg(
                connection,
                run_id=run_id,
                track_id=track_id,
                projection_track_id=f"{track_id}#{leg}",
                required_position_side=leg,
                component_state=leg_component_state,
                revealed_event_low=revealed_event_low,
                revealed_event_high=revealed_event_high,
                now_ms=now_ms,
            )
        return
    sync_trade_results_projection_leg(
        connection,
        run_id=run_id,
        track_id=track_id,
        projection_track_id=track_id,
        required_position_side=None,
        component_state=component_state,
        revealed_event_low=revealed_event_low,
        revealed_event_high=revealed_event_high,
        now_ms=now_ms,
    )


def sync_trade_results_projection_leg(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    projection_track_id: str,
    required_position_side: str | None,
    component_state: Mapping[str, object],
    revealed_event_low: Decimal | None,
    revealed_event_high: Decimal | None,
    now_ms: int,
) -> None:
    """Project one netted position stream or one independent hedge leg."""

    row = connection.execute(
        """
        SELECT * FROM replay_training_trade_projection
        WHERE run_id = ? AND track_id = ?
        """,
        (run_id, projection_track_id),
    ).fetchone()
    if row is None:
        last_fill_ordinal = 0
        episode_sequence = 0
        episode_id: str | None = None
        position_side: str | None = None
        net_quantity = Decimal(0)
        entry_price: Decimal | None = None
        entry_time_ms: int | None = None
        entry_source_sequence: int | None = None
        highest_mark: Decimal | None = None
        lowest_mark: Decimal | None = None
        allocations: dict[str, Decimal] = {}
    else:
        last_fill_ordinal = int(row["last_fill_ordinal"])
        episode_sequence = int(row["episode_sequence"])
        episode_id = None if row["episode_id"] is None else str(row["episode_id"])
        position_side = (
            None if row["position_side"] is None else str(row["position_side"])
        )
        net_quantity = Decimal(str(row["net_quantity"]))
        entry_price = (
            None if row["entry_price"] is None else Decimal(str(row["entry_price"]))
        )
        entry_time_ms = (
            None if row["entry_time_ms"] is None else int(row["entry_time_ms"])
        )
        entry_source_sequence = (
            None
            if row["entry_source_sequence"] is None
            else int(row["entry_source_sequence"])
        )
        highest_mark = (
            None if row["highest_mark"] is None else Decimal(str(row["highest_mark"]))
        )
        lowest_mark = (
            None if row["lowest_mark"] is None else Decimal(str(row["lowest_mark"]))
        )
        decoded_allocations = json.loads(str(row["plan_allocations_json"]))
        if not isinstance(decoded_allocations, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in decoded_allocations.items()
        ):
            raise TypeError("trade projection plan allocations are invalid")
        allocations = {
            key: Decimal(value) for key, value in decoded_allocations.items()
        }

    position = component_state.get("position")
    current_mark: Decimal | None = None
    if isinstance(position, Mapping) and position.get("mark_price") is not None:
        current_mark = Decimal(str(position["mark_price"]))
    if episode_id is not None and current_mark is not None:
        highest_mark = (
            current_mark if highest_mark is None else max(highest_mark, current_mark)
        )
        lowest_mark = (
            current_mark if lowest_mark is None else min(lowest_mark, current_mark)
        )
    if episode_id is not None and revealed_event_high is not None:
        highest_mark = (
            revealed_event_high
            if highest_mark is None
            else max(highest_mark, revealed_event_high)
        )
    if episode_id is not None and revealed_event_low is not None:
        lowest_mark = (
            revealed_event_low
            if lowest_mark is None
            else min(lowest_mark, revealed_event_low)
        )

    fill_rows = connection.execute(
        """
        SELECT fill_id, fill_json FROM replay_training_contract_fill
        WHERE run_id = ? AND track_id = ? AND fill_id > ?
        ORDER BY fill_id
        """,
        (run_id, track_id, f"fill-{last_fill_ordinal:010d}"),
    ).fetchall()
    raw_closed = component_state.get("closed_trades")
    closed_by_fill = (
        {
            str(item["fill_id"]): item
            for item in raw_closed
            if isinstance(item, Mapping)
            and isinstance(item.get("fill_id"), str)
            and (
                required_position_side is None
                or item.get("position_side") == required_position_side
            )
        }
        if fill_rows and isinstance(raw_closed, (list, tuple))
        else {}
    )

    def bind_plan(order_id: str, opening_quantity: Decimal) -> None:
        plan = connection.execute(
            """
            SELECT plan_id, risk_per_unit, quantity
            FROM replay_training_trade_plan
            WHERE run_id = ? AND track_id = ? AND order_id = ?
            """,
            (run_id, track_id, order_id),
        ).fetchone()
        if plan is None or opening_quantity <= 0:
            return
        planned_quantity = Decimal(str(plan["quantity"]))
        if planned_quantity <= 0:
            raise TypeError("trade plan quantity is invalid")
        allocation = Decimal(str(plan["risk_per_unit"])) * opening_quantity
        plan_id = str(plan["plan_id"])
        allocations[plan_id] = allocations.get(plan_id, Decimal(0)) + allocation

    for fill_row in fill_rows:
        raw = json.loads(str(fill_row["fill_json"]))
        if not isinstance(raw, Mapping):
            raise TypeError("contract fill projection is invalid")
        fill_id = str(raw["fill_id"])
        try:
            fill_ordinal = int(fill_id.rsplit("-", 1)[1])
        except (IndexError, ValueError) as exc:
            raise TypeError("contract fill identifier is invalid") from exc
        if (
            required_position_side is not None
            and raw.get("position_side") != required_position_side
        ):
            last_fill_ordinal = fill_ordinal
            continue
        fill_side = str(raw["side"])
        side_sign = Decimal(1) if fill_side == "BUY" else Decimal(-1)
        fill_quantity = Decimal(str(raw["quantity"]))
        fill_price = Decimal(str(raw["price"]))
        fill_time_ms = int(raw["event_time_ms"])
        fill_source_sequence = int(raw["source_sequence"])
        contract_size = Decimal(str(raw.get("contract_size", "1")))

        if episode_id is not None:
            highest_mark = (
                fill_price if highest_mark is None else max(highest_mark, fill_price)
            )
            lowest_mark = (
                fill_price if lowest_mark is None else min(lowest_mark, fill_price)
            )

        same_direction = net_quantity == 0 or (net_quantity > 0) == (side_sign > 0)
        if same_direction:
            if net_quantity == 0:
                episode_sequence += 1
                episode_id = f"trade-episode-{episode_sequence:08d}"
                position_side = fill_side
                net_quantity = side_sign * fill_quantity
                entry_price = fill_price
                entry_time_ms = fill_time_ms
                entry_source_sequence = fill_source_sequence
                highest_mark = fill_price
                lowest_mark = fill_price
                allocations = {}
                if revealed_event_high is not None:
                    highest_mark = max(highest_mark, revealed_event_high)
                if revealed_event_low is not None:
                    lowest_mark = min(lowest_mark, revealed_event_low)
            else:
                assert entry_price is not None
                combined = abs(net_quantity) + fill_quantity
                entry_price = (
                    abs(net_quantity) * entry_price + fill_quantity * fill_price
                ) / combined
                net_quantity += side_sign * fill_quantity
            bind_plan(str(raw["order_id"]), fill_quantity)
            last_fill_ordinal = fill_ordinal
            continue

        assert episode_id is not None
        assert position_side is not None
        assert entry_price is not None
        assert entry_time_ms is not None
        assert entry_source_sequence is not None
        assert highest_mark is not None
        assert lowest_mark is not None
        absolute_position = abs(net_quantity)
        closing_quantity = min(absolute_position, fill_quantity)
        position_sign = Decimal(1) if net_quantity > 0 else Decimal(-1)
        gross_pnl = (
            (fill_price - entry_price)
            * closing_quantity
            * position_sign
            * contract_size
        )
        if net_quantity > 0:
            mae = (lowest_mark - entry_price) * closing_quantity * contract_size
            mfe = (highest_mark - entry_price) * closing_quantity * contract_size
        else:
            mae = (entry_price - highest_mark) * closing_quantity * contract_size
            mfe = (entry_price - lowest_mark) * closing_quantity * contract_size
        mae = min(Decimal(0), mae)
        mfe = max(Decimal(0), mfe)
        risk_total = sum(allocations.values(), Decimal(0))
        close_fraction = closing_quantity / absolute_position
        allocated_risk = risk_total * close_fraction
        result_allocations = {
            plan_id: amount * close_fraction
            for plan_id, amount in allocations.items()
            if amount * close_fraction > 0
        }
        remaining_allocations = {
            plan_id: amount - result_allocations.get(plan_id, Decimal(0))
            for plan_id, amount in allocations.items()
            if amount - result_allocations.get(plan_id, Decimal(0)) > 0
        }
        r_multiple = None if allocated_risk <= 0 else gross_pnl / allocated_risk
        closed = closed_by_fill.get(fill_id)
        trade_id = (
            str(closed["trade_id"])
            if isinstance(closed, Mapping) and isinstance(closed.get("trade_id"), str)
            else f"trade-{fill_ordinal:010d}"
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO replay_training_trade_result(
                run_id, track_id, trade_id, episode_id, fill_id,
                closing_order_id, position_side, quantity, entry_price,
                exit_price, gross_realized_pnl, mae, mfe,
                initial_risk_amount, r_multiple, holding_duration_ms,
                entry_time_ms, exit_time_ms, entry_source_sequence,
                exit_source_sequence, plan_ids_json, excursion_fidelity,
                pnl_basis, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                track_id,
                trade_id,
                episode_id,
                fill_id,
                raw["order_id"],
                position_side,
                decimal_to_string(closing_quantity, field_name="closing quantity"),
                decimal_to_string(entry_price, field_name="trade entry price"),
                decimal_to_string(fill_price, field_name="trade exit price"),
                decimal_to_string(gross_pnl, field_name="trade gross pnl"),
                decimal_to_string(mae, field_name="trade mae"),
                decimal_to_string(mfe, field_name="trade mfe"),
                (
                    None
                    if allocated_risk <= 0
                    else decimal_to_string(allocated_risk, field_name="trade risk")
                ),
                (
                    None
                    if r_multiple is None
                    else decimal_to_string(r_multiple, field_name="trade r multiple")
                ),
                max(0, fill_time_ms - entry_time_ms),
                entry_time_ms,
                fill_time_ms,
                entry_source_sequence,
                fill_source_sequence,
                canonical_json(sorted(result_allocations)),
                "REVEALED_MARK_PATH_CONSERVATIVE",
                "REALIZED_GROSS_EX_FEES",
                now_ms,
            ),
        )

        residual_close_quantity = fill_quantity - closing_quantity
        if residual_close_quantity > 0:
            episode_sequence += 1
            episode_id = f"trade-episode-{episode_sequence:08d}"
            position_side = fill_side
            net_quantity = side_sign * residual_close_quantity
            entry_price = fill_price
            entry_time_ms = fill_time_ms
            entry_source_sequence = fill_source_sequence
            highest_mark = fill_price
            lowest_mark = fill_price
            allocations = {}
            if revealed_event_high is not None:
                highest_mark = max(highest_mark, revealed_event_high)
            if revealed_event_low is not None:
                lowest_mark = min(lowest_mark, revealed_event_low)
            bind_plan(str(raw["order_id"]), residual_close_quantity)
        elif closing_quantity == absolute_position:
            episode_id = None
            position_side = None
            net_quantity = Decimal(0)
            entry_price = None
            entry_time_ms = None
            entry_source_sequence = None
            highest_mark = None
            lowest_mark = None
            allocations = {}
        else:
            net_quantity = position_sign * (absolute_position - closing_quantity)
            allocations = remaining_allocations
        last_fill_ordinal = fill_ordinal

    if episode_id is not None and current_mark is not None:
        highest_mark = (
            current_mark if highest_mark is None else max(highest_mark, current_mark)
        )
        lowest_mark = (
            current_mark if lowest_mark is None else min(lowest_mark, current_mark)
        )
    if episode_id is not None and revealed_event_high is not None:
        highest_mark = (
            revealed_event_high
            if highest_mark is None
            else max(highest_mark, revealed_event_high)
        )
    if episode_id is not None and revealed_event_low is not None:
        lowest_mark = (
            revealed_event_low
            if lowest_mark is None
            else min(lowest_mark, revealed_event_low)
        )
    connection.execute(
        """
        INSERT INTO replay_training_trade_projection(
            run_id, track_id, last_fill_ordinal, episode_sequence,
            episode_id, position_side, net_quantity, entry_price,
            entry_time_ms, entry_source_sequence, highest_mark, lowest_mark,
            plan_allocations_json, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, track_id) DO UPDATE SET
            last_fill_ordinal = excluded.last_fill_ordinal,
            episode_sequence = excluded.episode_sequence,
            episode_id = excluded.episode_id,
            position_side = excluded.position_side,
            net_quantity = excluded.net_quantity,
            entry_price = excluded.entry_price,
            entry_time_ms = excluded.entry_time_ms,
            entry_source_sequence = excluded.entry_source_sequence,
            highest_mark = excluded.highest_mark,
            lowest_mark = excluded.lowest_mark,
            plan_allocations_json = excluded.plan_allocations_json,
            updated_at_ms = excluded.updated_at_ms
        """,
        (
            run_id,
            projection_track_id,
            last_fill_ordinal,
            episode_sequence,
            episode_id,
            position_side,
            decimal_to_string(net_quantity, field_name="projected net quantity"),
            (
                None
                if entry_price is None
                else decimal_to_string(entry_price, field_name="projected entry price")
            ),
            entry_time_ms,
            entry_source_sequence,
            (
                None
                if highest_mark is None
                else decimal_to_string(highest_mark, field_name="projected high mark")
            ),
            (
                None
                if lowest_mark is None
                else decimal_to_string(lowest_mark, field_name="projected low mark")
            ),
            canonical_json(
                {
                    plan_id: decimal_to_string(amount, field_name="plan allocation")
                    for plan_id, amount in sorted(allocations.items())
                }
            ),
            now_ms,
        ),
    )
