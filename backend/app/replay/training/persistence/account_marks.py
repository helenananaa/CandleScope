"""Account marks operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    CONTRACT_ACCOUNT_MODEL,
    SANDBOX_FUNDING_FIDELITY,
    fee_for_notional,
    isolated_margin_key,
    round_to_step,
)
from ..account_history import (
    AccountHistoryEvent,
)
from ..errors import TrainingRunError
from ..hedge_inputs import (
    HedgeInputEvent,
)
from ..multitrack import (
    StableMarketEvent,
    stable_market_event_order,
)
from ..phase_projection import load_track_rules
from . import account_math as account_math_ops
from . import ledger as ledger_ops

_HEDGE_RISK_FINGERPRINT_CACHE_MAX_RUNS = 128


def apply_exact_mark_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    now_ms: int,
) -> None:
    """Overlay the pinned mark without mutating the replay.v1 broker kernel."""

    projection = connection.execute(
        """
        SELECT projection.*, history.status AS history_status,
               history.account_data_mode
        FROM replay_account_history_projection AS projection
        JOIN replay_training_account_history AS history USING(run_id)
        WHERE projection.run_id = ? AND projection.track_id = ?
        """,
        (run_id, track_id),
    ).fetchone()
    if projection is None or projection["account_data_mode"] != "HISTORICAL_EXACT":
        return
    if (
        projection["history_status"] != "ACTIVE"
        or projection["status"] != "READY"
        or projection["mark_price"] is None
    ):
        raise TrainingRunError(
            "ACCOUNT_HISTORY_ARCHIVE_DEGRADED",
            "authoritative account mark is unavailable",
            status_code=409,
            details={"track_id": track_id, "fallback_applied": False},
        )
    track = connection.execute(
        """
        SELECT * FROM replay_training_market_track
        WHERE run_id = ? AND track_id = ?
        """,
        (run_id, track_id),
    ).fetchone()
    if track is None:
        raise TypeError("exact account market track is missing")
    rule_row = connection.execute(
        """
        SELECT revision, rule_json FROM replay_training_instrument_rule
        WHERE run_id = ? AND track_id = ?
          AND effective_virtual_time_ms <= COALESCE(?, 0)
        ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
        """,
        (run_id, track_id, track["virtual_time_ms"]),
    ).fetchone()
    if rule_row is None:
        raise TypeError("exact account instrument rule is missing")
    rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
    try:
        position = json.loads(str(track["position_json"]))
        account = json.loads(str(track["account_json"]))
        open_orders = json.loads(str(track["open_orders_json"]))
    except json.JSONDecodeError as exc:
        raise TypeError("exact account track projection JSON is invalid") from exc
    if (
        not isinstance(position, dict)
        or not isinstance(account, dict)
        or not isinstance(open_orders, list)
    ):
        raise TypeError("exact account track projection is invalid")
    try:
        mark = Decimal(str(projection["mark_price"]))
        quantity = Decimal(str(position.get("quantity", "0")))
        contract_size = Decimal(rule.contract_size)
        run_row = connection.execute(
            """
            SELECT initial_equity FROM replay_training_run WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise TypeError("exact account training run is missing")
        exact_realized = sum(
            (
                Decimal(str(row["cash_delta"]))
                for row in connection.execute(
                    """
                    SELECT cash_delta
                    FROM replay_training_contract_ledger
                    WHERE run_id = ? AND track_id = ?
                      AND kind = 'BROKER_REALIZED_PNL'
                    """,
                    (run_id, track_id),
                ).fetchall()
            ),
            Decimal(0),
        )
        broker_fees = Decimal(0)
        for fill_row in connection.execute(
            """
            SELECT fill_json FROM replay_training_contract_fill
            WHERE run_id = ? AND track_id = ?
            """,
            (run_id, track_id),
        ).fetchall():
            fill = json.loads(str(fill_row["fill_json"]))
            if not isinstance(fill, Mapping):
                raise TypeError("exact account fill projection is invalid")
            broker_fees += Decimal(str(fill["fee"]))
        entry_raw = position.get("entry_price")
        entry = None if entry_raw is None else Decimal(str(entry_raw))
        notional = abs(quantity) * mark * contract_size
        unrealized = (
            Decimal(0)
            if quantity == 0 or entry is None
            else (mark - entry) * quantity * contract_size
        )
        policy_row = connection.execute(
            """
            SELECT max_leverage
            FROM replay_training_leverage_policy
            WHERE run_id = ? AND effective_virtual_time_ms <= ?
            ORDER BY effective_virtual_time_ms DESC, source_sequence DESC,
                     revision DESC LIMIT 1
            """,
            (run_id, int(track["virtual_time_ms"] or 0)),
        ).fetchone()
        if policy_row is None:
            raise TypeError("training leverage policy is missing")
        configured_max = Decimal(str(policy_row["max_leverage"]))
        leverage = min(configured_max, Decimal(rule.max_leverage))
        if leverage <= 0:
            raise ValueError("effective leverage must be positive")
        margin_used = notional / leverage
        reserved = Decimal(0)
        terminal = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
        for raw in open_orders:
            if not isinstance(raw, Mapping) or raw.get("status") in terminal:
                continue
            order_quantity = Decimal(
                str(raw.get("remaining_quantity") or raw.get("quantity") or "0")
            )
            reference = raw.get("limit_price") or raw.get("stop_price") or mark
            reserved += (
                abs(order_quantity) * Decimal(str(reference)) * contract_size / leverage
            )
        cash = Decimal(str(run_row["initial_equity"])) + exact_realized - broker_fees
        equity = cash + unrealized
        available = equity - margin_used - reserved
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise TrainingRunError(
            "ACCOUNT_HISTORY_PROJECTION_INVALID",
            "authoritative mark could not reconcile the modelled account",
            status_code=409,
            details={"track_id": track_id, "fallback_applied": False},
        ) from exc
    position.update(
        {
            "mark_price": decimal_to_string(mark, field_name="exact mark"),
            "notional": decimal_to_string(
                notional, field_name="exact position notional"
            ),
            "realized_pnl": decimal_to_string(
                exact_realized, field_name="exact realized pnl"
            ),
            "unrealized_pnl": decimal_to_string(
                unrealized, field_name="exact unrealized pnl"
            ),
        }
    )
    account.update(
        {
            "cash_balance": decimal_to_string(cash, field_name="exact account cash"),
            "equity": decimal_to_string(equity, field_name="exact account equity"),
            "available_equity": decimal_to_string(
                available, field_name="exact account available"
            ),
            "margin_used": decimal_to_string(
                margin_used, field_name="exact margin used"
            ),
            "reserved_margin": decimal_to_string(
                reserved, field_name="exact reserved margin"
            ),
            "realized_pnl": decimal_to_string(
                exact_realized, field_name="exact account realized pnl"
            ),
            "unrealized_pnl": decimal_to_string(
                unrealized, field_name="exact account unrealized pnl"
            ),
            "fees_paid": decimal_to_string(broker_fees, field_name="exact broker fees"),
        }
    )
    capabilities = json.loads(str(track["capabilities_json"]))
    if not isinstance(capabilities, dict):
        raise TypeError("exact account capabilities are invalid")
    capabilities.update(
        {
            "HISTORICAL_MARK_INDEX": "AVAILABLE_EXACT",
            "HISTORICAL_INSTRUMENT_RULE": "AVAILABLE_EXACT",
            "SIMULATED_LIQUIDATION": "AVAILABLE_EXACT_INPUTS_MODELLED_ACCOUNT",
        }
    )
    connection.execute(
        """
        UPDATE replay_training_market_track
        SET position_json = ?, account_json = ?, capabilities_json = ?,
            updated_at_ms = ?
        WHERE run_id = ? AND track_id = ?
        """,
        (
            canonical_json(position),
            canonical_json(account),
            canonical_json(capabilities),
            now_ms,
            run_id,
            track_id,
        ),
    )


def apply_hedge_mark_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
) -> None:
    """Overlay the pinned HEDGE mark on every leg before risk evaluation."""

    binding = connection.execute(
        """
        SELECT status FROM replay_hedge_input_binding WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if binding is None or binding["status"] != "ACTIVE":
        raise TrainingRunError(
            "HEDGE_INPUT_PAUSED",
            "pinned HEDGE public input is not active",
            status_code=409,
            details={"fallback_applied": False},
        )
    run = connection.execute(
        """
        SELECT initial_equity FROM replay_training_run WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    contract_account = connection.execute(
        """
        SELECT overlay_cash FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if run is None or contract_account is None:
        raise TypeError("HEDGE contract account is missing")
    tracks = connection.execute(
        """
        SELECT * FROM replay_training_market_track
        WHERE run_id = ? AND subscription_tier = 'FULL'
        ORDER BY stable_ordinal, track_id
        """,
        (run_id,),
    ).fetchall()
    projections = {
        row["track_id"]: row
        for row in connection.execute(
            """
            SELECT projection.*
            FROM replay_hedge_track_public_binding AS binding
            JOIN replay_hedge_track_public_projection AS projection
              ON projection.run_id=binding.run_id AND projection.track_id=binding.track_id
            WHERE binding.run_id=? AND binding.status='ACTIVE'
            """,
            (run_id,),
        ).fetchall()
    }
    rules = load_track_rules(connection, run_id, effective=True)
    for track in tracks:
        try:
            projection = projections.get(track["track_id"])
            if projection is None:
                raise ValueError("track public projection is missing")
            state = json.loads(str(projection["state_json"]))
            projection_payload = {
                "schema_version": "replay.hedge-track-public-projection.v1",
                "run_id": run_id,
                "track_id": str(track["track_id"]),
                "last_event_sequence": int(projection["last_event_sequence"]),
                "as_of_actual_time_ms": int(projection["as_of_actual_time_ms"]),
                "as_of_virtual_time_ms": int(projection["as_of_virtual_time_ms"]),
                "state": state,
                "input_chain_hash": str(projection["input_chain_hash"]),
            }
            if canonical_sha256(projection_payload) != projection["component_hash"]:
                raise ValueError("track public projection hash is invalid")
            mark_state = state["mark_index"]
            mark = Decimal(str(mark_state["mark_price"]))
            if mark <= 0:
                raise ValueError("mark must be positive")
            position = json.loads(str(track["position_json"]))
            account = json.loads(str(track["account_json"]))
            orders = json.loads(str(track["open_orders_json"]))
        except (
            InvalidOperation,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise TrainingRunError(
                "HEDGE_PINNED_MARK_UNAVAILABLE",
                "the track-specific pinned HEDGE mark is unavailable",
                status_code=409,
                details={
                    "track_id": str(track["track_id"]),
                    "fallback_applied": False,
                },
            ) from exc
        if (
            not isinstance(position, dict)
            or position.get("position_mode") != "HEDGE"
            or not isinstance(account, dict)
            or not isinstance(orders, list)
        ):
            raise TypeError("HEDGE track projection is invalid")
        rule_row = rules.get(track["track_id"])
        if rule_row is None:
            raise TypeError("HEDGE pinned instrument rule is missing")
        rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
        total_unrealized = Decimal(0)
        total_initial = Decimal(0)
        for leg_name, side in (("long", "LONG"), ("short", "SHORT")):
            leg = position.get(leg_name)
            if not isinstance(leg, dict):
                raise TypeError("HEDGE position leg is missing")
            quantity = abs(Decimal(str(leg.get("quantity", "0"))))
            entry_raw = leg.get("entry_price")
            entry = None if entry_raw is None else Decimal(str(entry_raw))
            contract_size = Decimal(rule.contract_size)
            notional = quantity * mark * contract_size
            unrealized = (
                Decimal(0)
                if quantity == 0 or entry is None
                else (
                    (mark - entry) * quantity * contract_size
                    if side == "LONG"
                    else (entry - mark) * quantity * contract_size
                )
            )
            leverage = Decimal(str(leg.get("leverage", rule.max_leverage)))
            initial = rule.initial_margin(notional, leverage)
            total_unrealized += unrealized
            total_initial += initial
            leg.update(
                {
                    "mark_price": decimal_to_string(
                        mark, field_name="pinned hedge mark"
                    ),
                    "notional": decimal_to_string(
                        notional, field_name="pinned hedge notional"
                    ),
                    "unrealized_pnl": decimal_to_string(
                        unrealized, field_name="pinned hedge unrealized pnl"
                    ),
                }
            )
        reserved = sum(
            (
                Decimal(str(order.get("reserved_margin", "0")))
                for order in orders
                if isinstance(order, Mapping)
                and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                and order.get("reduce_only") is not True
            ),
            Decimal(0),
        )
        cash = Decimal(str(account.get("cash_balance", run["initial_equity"])))
        equity = (
            cash + total_unrealized + Decimal(str(contract_account["overlay_cash"]))
        )
        account.update(
            {
                "equity": decimal_to_string(equity, field_name="pinned hedge equity"),
                "available_equity": decimal_to_string(
                    equity - total_initial - reserved,
                    field_name="pinned hedge available equity",
                ),
                "margin_used": decimal_to_string(
                    total_initial, field_name="pinned hedge initial margin"
                ),
                "reserved_margin": decimal_to_string(
                    reserved, field_name="pinned hedge reserved margin"
                ),
                "unrealized_pnl": decimal_to_string(
                    total_unrealized,
                    field_name="pinned hedge account unrealized pnl",
                ),
            }
        )
        position_json = canonical_json(position)
        account_json = canonical_json(account)
        public_price = decimal_to_string(mark, field_name="pinned public price")
        if (
            position_json == track["position_json"]
            and account_json == track["account_json"]
            and public_price == track["public_price"]
        ):
            # Validation above still runs. Reapplying an identical overlay
            # must not dirty a WAL page just to refresh its write timestamp.
            continue
        connection.execute(
            """
            UPDATE replay_training_market_track
            SET position_json = ?, account_json = ?, public_price = ?,
                updated_at_ms = ?
            WHERE run_id = ? AND track_id = ?
            """,
            (
                position_json,
                account_json,
                public_price,
                now_ms,
                run_id,
                track["track_id"],
            ),
        )


def apply_hedge_public_mark_batch(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    events: Sequence[HedgeInputEvent],
    virtual_times_ms: Sequence[int],
    track_id: str,
    now_ms: int,
) -> tuple[StableMarketEvent, ...]:
    """Apply a contiguous MARK batch; only track-1 owns v1 compatibility rows."""

    projection = connection.execute(
        """
        SELECT * FROM replay_hedge_track_public_projection
        WHERE run_id = ? AND track_id = ?
        """,
        (run_id, track_id),
    ).fetchone()
    if projection is None:
        raise TrainingRunError(
            "HEDGE_INPUT_PROJECTION_MISSING",
            "HEDGE input projection is missing",
            status_code=409,
            details={"fallback_applied": False},
        )
    state = json.loads(str(projection["state_json"]))
    if not isinstance(state, dict):
        raise TypeError("HEDGE input projection state is invalid")
    first_sequence = min(event.event_sequence for event in events)
    last_sequence = max(event.event_sequence for event in events)
    existing_sequences = {
        int(row["event_sequence"])
        for row in connection.execute(
            """
            SELECT event_sequence
            FROM replay_hedge_track_public_applied_event
            WHERE run_id = ? AND track_id = ?
              AND event_sequence BETWEEN ? AND ?
            """,
            (run_id, track_id, first_sequence, last_sequence),
        ).fetchall()
    }
    projection_sequence = int(projection["last_event_sequence"])
    projection_chain_hash = str(projection["input_chain_hash"])
    track_applied_rows: list[tuple[object, ...]] = []
    compatibility_applied_rows: list[tuple[object, ...]] = []
    stable: list[StableMarketEvent] = []
    final_event: HedgeInputEvent | None = None
    final_virtual_time_ms: int | None = None

    for event, virtual_time_ms in zip(events, virtual_times_ms, strict=True):
        stable.append(
            StableMarketEvent(
                actual_event_time_ms=event.event_time_ms,
                event_phase=event.event_phase,
                market_track_stable_id=event.stable_track_id,
                source_sequence=event.event_sequence,
            )
        )
        if event.event_sequence <= projection_sequence:
            if event.event_sequence in existing_sequences:
                continue
            raise TrainingRunError(
                "HEDGE_INPUT_EVENT_GAP",
                "HEDGE input event sequence is not contiguous",
                status_code=409,
                details={
                    "expected_sequence": projection_sequence + 1,
                    "actual_sequence": event.event_sequence,
                    "fallback_applied": False,
                },
            )
        expected = projection_sequence + 1
        if event.event_sequence != expected:
            raise TrainingRunError(
                "HEDGE_INPUT_EVENT_GAP",
                "HEDGE input event sequence is not contiguous",
                status_code=409,
                details={
                    "expected_sequence": expected,
                    "actual_sequence": event.event_sequence,
                    "fallback_applied": False,
                },
            )
        if event.previous_hash != projection_chain_hash:
            raise TrainingRunError(
                "HEDGE_INPUT_EVENT_CHAIN_MISMATCH",
                "HEDGE input event no longer follows the pinned chain",
                status_code=409,
                details={"fallback_applied": False},
            )
        state["mark_index"] = dict(event.payload)
        applied_hash = canonical_sha256(
            {
                "run_id": run_id,
                "track_id": track_id,
                "virtual_time_ms": virtual_time_ms,
                "source_kind": event.source_kind,
                "source_id": event.source_id,
                "event_sequence": event.event_sequence,
                "event_hash": event.event_hash,
                "payload": dict(event.payload),
            }
        )
        track_applied_rows.append(
            (
                run_id,
                track_id,
                event.event_sequence,
                event.event_time_ms,
                event.event_phase,
                event.event_kind,
                event.component_sequence,
                virtual_time_ms,
                event.event_hash,
                canonical_json(event.payload),
                applied_hash,
                now_ms,
            )
        )
        compatibility_hash = canonical_sha256(
            {
                "run_id": run_id,
                "virtual_time_ms": virtual_time_ms,
                "source_kind": "PUBLIC",
                "source_id": event.source_id,
                "event_sequence": event.event_sequence,
                "event_hash": event.event_hash,
                "payload": dict(event.payload),
            }
        )
        compatibility_applied_rows.append(
            (
                run_id,
                event.event_sequence,
                event.event_time_ms,
                event.event_phase,
                event.event_kind,
                event.component_sequence,
                virtual_time_ms,
                event.event_hash,
                canonical_json(event.payload),
                compatibility_hash,
                now_ms,
            )
        )
        projection_sequence = event.event_sequence
        projection_chain_hash = event.event_hash
        existing_sequences.add(event.event_sequence)
        final_event = event
        final_virtual_time_ms = virtual_time_ms

    if final_event is not None and final_virtual_time_ms is not None:
        projection_payload = {
            "schema_version": "replay.hedge-track-public-projection.v1",
            "run_id": run_id,
            "track_id": track_id,
            "last_event_sequence": final_event.event_sequence,
            "as_of_actual_time_ms": final_event.event_time_ms,
            "as_of_virtual_time_ms": final_virtual_time_ms,
            "state": state,
            "input_chain_hash": final_event.event_hash,
        }
        connection.execute(
            """
            UPDATE replay_hedge_track_public_projection
            SET last_event_sequence = ?, as_of_actual_time_ms = ?,
                as_of_virtual_time_ms = ?, state_json = ?,
                input_chain_hash = ?, component_hash = ?, updated_at_ms = ?
            WHERE run_id = ? AND track_id = ?
            """,
            (
                final_event.event_sequence,
                final_event.event_time_ms,
                final_virtual_time_ms,
                canonical_json(state),
                final_event.event_hash,
                canonical_sha256(projection_payload),
                now_ms,
                run_id,
                track_id,
            ),
        )
        if track_id == "track-1":
            compatibility_payload = {
                "schema_version": "replay.hedge-input-projection.v1",
                "source_kind": "PUBLIC",
                "last_event_sequence": final_event.event_sequence,
                "as_of_actual_time_ms": final_event.event_time_ms,
                "as_of_virtual_time_ms": final_virtual_time_ms,
                "state": state,
                "input_chain_hash": final_event.event_hash,
            }
            connection.execute(
                """
                UPDATE replay_hedge_input_projection
                SET last_event_sequence = ?, as_of_actual_time_ms = ?,
                    as_of_virtual_time_ms = ?, state_json = ?,
                    input_chain_hash = ?, component_hash = ?, updated_at_ms = ?
                WHERE run_id = ? AND source_kind = 'PUBLIC'
                """,
                (
                    final_event.event_sequence,
                    final_event.event_time_ms,
                    final_virtual_time_ms,
                    canonical_json(state),
                    final_event.event_hash,
                    canonical_sha256(compatibility_payload),
                    now_ms,
                    run_id,
                ),
            )
    connection.executemany(
        """
        INSERT INTO replay_hedge_track_public_applied_event(
            run_id, track_id, event_sequence, event_time_ms,
            event_phase, event_kind, component_sequence,
            applied_virtual_time_ms, source_event_hash,
            payload_json, applied_payload_hash, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        track_applied_rows,
    )
    connection.executemany(
        """
        INSERT INTO replay_hedge_input_applied_event(
            run_id, source_kind, event_sequence,
            event_time_ms, event_phase, event_kind,
            component_sequence, applied_virtual_time_ms,
            source_event_hash, payload_json,
            applied_payload_hash, created_at_ms
        ) VALUES (?, 'PUBLIC', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        compatibility_applied_rows if track_id == "track-1" else (),
    )
    return stable_market_event_order(stable)


def settle_hedge_funding_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    event: HedgeInputEvent,
    virtual_time_ms: int,
    now_ms: int,
    accounting_totals: dict[tuple[str, str], tuple[Decimal, Decimal, Decimal]]
    | None = None,
) -> None:
    """Settle both HEDGE legs from one immutable pre-settlement snapshot."""

    if event.source_kind != "PUBLIC":
        raise TypeError("HEDGE funding must originate from the public archive")
    if event.track_id is None:
        raise TypeError("HEDGE funding event lacks a track identity")
    run = connection.execute(
        """
        SELECT run.position_mode, run.settlement_asset,
               account.account_model, account.funding_mode
        FROM replay_training_run AS run
        JOIN replay_training_contract_account AS account USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if run is None or str(run["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        raise TypeError("HEDGE funding contract account is missing")
    if str(run["position_mode"]) != "HEDGE":
        raise TypeError("HEDGE funding cannot settle a one-way run")
    if str(run["funding_mode"]) != "HISTORICAL_EXACT":
        raise TrainingRunError(
            "HEDGE_FUNDING_MODE_MISMATCH",
            "HEDGE public funding requires HISTORICAL_EXACT mode",
            status_code=409,
        )
    track = connection.execute(
        """
        SELECT track_id, source_sequence
        FROM replay_training_market_track
        WHERE run_id = ? AND track_id = ? AND subscription_tier = 'FULL'
        """,
        (run_id, event.track_id),
    ).fetchone()
    if track is None:
        raise TypeError("HEDGE funding FULL track is missing")
    track_id = str(track["track_id"])
    existing = tuple(
        connection.execute(
            """
            SELECT position_side
            FROM replay_training_hedge_funding_settlement
            WHERE run_id = ? AND track_id = ? AND settlement_time_ms = ?
            ORDER BY position_side
            """,
            (run_id, track_id, virtual_time_ms),
        ).fetchall()
    )
    if len(existing) == 2:
        return
    if existing:
        raise TrainingRunError(
            "HEDGE_FUNDING_PARTIAL_SETTLEMENT",
            "HEDGE funding has only one durable leg settlement",
            status_code=409,
            details={"fallback_applied": False},
        )
    legs = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_position_leg
            WHERE run_id = ? AND track_id = ?
            ORDER BY CASE position_side WHEN 'LONG' THEN 0 ELSE 1 END
            """,
            (run_id, track_id),
        ).fetchall()
    )
    if tuple(str(row["position_side"]) for row in legs) != (
        "LONG",
        "SHORT",
    ):
        raise TrainingRunError(
            "HEDGE_FUNDING_POSITION_SNAPSHOT_MISSING",
            "both HEDGE position legs must exist before funding settlement",
            status_code=409,
            details={"fallback_applied": False},
        )
    rule_row = connection.execute(
        """
        SELECT revision, rule_json
        FROM replay_training_instrument_rule
        WHERE run_id = ? AND track_id = ?
          AND effective_virtual_time_ms <= ?
        ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
        """,
        (run_id, track_id, virtual_time_ms),
    ).fetchone()
    if rule_row is None:
        raise TypeError("HEDGE funding effective instrument rule is missing")
    rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
    mark = Decimal(str(event.payload["mark_price"]))
    rate = Decimal(str(event.payload["funding_rate"]))
    overlay_delta = Decimal(0)
    for leg in legs:
        position_side = str(leg["position_side"])
        signed_quantity = Decimal(str(leg["signed_quantity"]))
        absolute_quantity = Decimal(str(leg["absolute_quantity"]))
        raw = -(signed_quantity * mark * Decimal(rule.contract_size) * rate)
        rounded = round_to_step(
            abs(raw),
            Decimal(rule.quote_step),
            upward=True,
        )
        cash_delta = rounded.copy_sign(raw) if raw else Decimal(0)
        component = {
            "schema_version": "replay.training.hedge-funding-settlement.v1",
            "run_id": run_id,
            "track_id": track_id,
            "position_side": position_side,
            "settlement_time_ms": virtual_time_ms,
            "actual_settlement_time_ms": event.event_time_ms,
            "source_kind": event.source_kind,
            "source_id": event.source_id,
            "source_event_sequence": event.event_sequence,
            "source_event_hash": event.event_hash,
            "pre_settlement_signed_quantity": decimal_to_string(
                signed_quantity,
                field_name="funding signed quantity",
            ),
            "pre_settlement_absolute_quantity": decimal_to_string(
                absolute_quantity,
                field_name="funding absolute quantity",
            ),
            "mark_price": decimal_to_string(mark, field_name="funding mark"),
            "funding_rate": decimal_to_string(
                rate,
                field_name="funding rate",
            ),
            "contract_size": rule.contract_size,
            "cash_delta": decimal_to_string(
                cash_delta,
                field_name="funding cash delta",
            ),
            "rounding": "ABS_CEILING_QUOTE_STEP_THEN_SIGN",
            "fidelity": "PINNED_HISTORICAL_HEDGE_FUNDING",
            "rule_revision": int(rule_row["revision"]),
        }
        ledger_sequence = ledger_ops.append_contract_ledger(
            connection,
            run_id=run_id,
            posting_id=(
                f"hedge-funding:{event.source_id}:"
                f"{event.event_sequence}:{track_id}:{position_side}"
            ),
            track_id=track_id,
            kind="FUNDING_SETTLEMENT",
            cash_delta=cash_delta,
            asset=str(run["settlement_asset"]),
            virtual_time_ms=virtual_time_ms,
            source_sequence=int(track["source_sequence"] or 0),
            fidelity="PINNED_HISTORICAL_HEDGE_FUNDING",
            rule_revision=int(rule_row["revision"]),
            reference_type="HEDGE_PUBLIC_EVENT",
            reference_id=f"{event.source_id}:{event.event_sequence}",
            metadata={
                "position_side": position_side,
                "actual_settlement_time_ms": event.event_time_ms,
                "source_event_hash": event.event_hash,
                "pre_settlement_signed_quantity": component[
                    "pre_settlement_signed_quantity"
                ],
                "pre_settlement_absolute_quantity": component[
                    "pre_settlement_absolute_quantity"
                ],
                "rate": component["funding_rate"],
                "mark_price": component["mark_price"],
                "contract_size": rule.contract_size,
                "rounding": component["rounding"],
            },
            now_ms=now_ms,
        )
        connection.execute(
            """
            INSERT INTO replay_training_hedge_funding_settlement(
                run_id, track_id, position_side, settlement_time_ms,
                actual_settlement_time_ms, source_kind, source_id,
                source_event_sequence, source_event_hash,
                pre_settlement_signed_quantity,
                pre_settlement_absolute_quantity, mark_price, funding_rate,
                contract_size, cash_delta, rounding, fidelity,
                rule_revision, ledger_sequence, component_hash, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, 'PUBLIC', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'ABS_CEILING_QUOTE_STEP_THEN_SIGN',
                      'PINNED_HISTORICAL_HEDGE_FUNDING', ?, ?, ?, ?)
            """,
            (
                run_id,
                track_id,
                position_side,
                virtual_time_ms,
                event.event_time_ms,
                event.source_id,
                event.event_sequence,
                event.event_hash,
                component["pre_settlement_signed_quantity"],
                component["pre_settlement_absolute_quantity"],
                component["mark_price"],
                component["funding_rate"],
                rule.contract_size,
                component["cash_delta"],
                int(rule_row["revision"]),
                ledger_sequence,
                canonical_sha256(component),
                now_ms,
            ),
        )
        if accounting_totals is not None:
            accounting_key = (track_id, position_side)
            funding, trading_fees, liquidation_fees = accounting_totals.get(
                accounting_key,
                (Decimal(0), Decimal(0), Decimal(0)),
            )
            accounting_totals[accounting_key] = (
                funding + cash_delta,
                trading_fees,
                liquidation_fees,
            )
        overlay_delta += cash_delta
    account = connection.execute(
        """
        SELECT overlay_cash FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None:
        raise TypeError("HEDGE funding account disappeared")
    overlay = Decimal(str(account["overlay_cash"])) + overlay_delta
    connection.execute(
        """
        UPDATE replay_training_contract_account
        SET overlay_cash = ?, updated_at_ms = ? WHERE run_id = ?
        """,
        (
            decimal_to_string(overlay, field_name="HEDGE funding overlay cash"),
            now_ms,
            run_id,
        ),
    )
    refresh_hedge_leg_accounting(
        connection,
        run_id=run_id,
        track_id=track_id,
        virtual_time_ms=virtual_time_ms,
        source_sequence=int(track["source_sequence"] or 0),
        now_ms=now_ms,
        reason="FUNDING_SETTLEMENT",
        accounting_totals=accounting_totals,
    )


def hedge_accounting_totals_by_leg(
    connection: sqlite3.Connection,
    *,
    run_id: str,
) -> dict[tuple[str, str], tuple[Decimal, Decimal, Decimal]]:
    """Aggregate exact leg accounting once per risk pass without float math."""

    totals: dict[tuple[str, str], list[Decimal]] = {}

    def bucket(track_id: object, position_side: object) -> list[Decimal]:
        key = (str(track_id), str(position_side))
        return totals.setdefault(key, [Decimal(0), Decimal(0), Decimal(0)])

    for row in connection.execute(
        """
        SELECT track_id, position_side, cash_delta
        FROM replay_training_hedge_funding_settlement
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall():
        bucket(row["track_id"], row["position_side"])[0] += Decimal(
            str(row["cash_delta"])
        )
    for row in connection.execute(
        """
        SELECT track_id, fill_json, configured_fee
        FROM replay_training_contract_fill
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall():
        fill = json.loads(str(row["fill_json"]))
        if not isinstance(fill, Mapping):
            raise TypeError("contract fill accounting payload is invalid")
        position_side = fill.get("position_side")
        if position_side in {"LONG", "SHORT"}:
            bucket(row["track_id"], position_side)[1] += Decimal(
                str(row["configured_fee"])
            )
    for row in connection.execute(
        """
        SELECT track_id, cash_delta, metadata_json
        FROM replay_training_contract_ledger
        WHERE run_id = ? AND kind = 'LIQUIDATION_FEE'
        """,
        (run_id,),
    ).fetchall():
        metadata = json.loads(str(row["metadata_json"]))
        if not isinstance(metadata, Mapping):
            raise TypeError("liquidation fee ledger metadata is invalid")
        position_side = metadata.get("position_side")
        if position_side in {"LONG", "SHORT"}:
            bucket(row["track_id"], position_side)[2] -= Decimal(str(row["cash_delta"]))
    return {key: tuple(values) for key, values in totals.items()}


def position_leg_component(
    row: Mapping[str, object],
    *,
    accumulated_funding: str,
    trading_fees: str,
    liquidation_fees: str,
) -> dict[str, object]:
    protection = json.loads(str(row["protection_json"]))
    if not isinstance(protection, Mapping):
        raise TypeError("position leg protection is invalid")
    return {
        "schema_version": "replay.position-leg.v1",
        "track_id": str(row["track_id"]),
        "position_side": str(row["position_side"]),
        "signed_quantity": str(row["signed_quantity"]),
        "absolute_quantity": str(row["absolute_quantity"]),
        "entry_price": row["entry_price"],
        "mark_price": row["mark_price"],
        "notional": str(row["notional"]),
        "realized_pnl": str(row["realized_pnl"]),
        "unrealized_pnl": str(row["unrealized_pnl"]),
        "initial_margin": str(row["initial_margin"]),
        "maintenance_margin": str(row["maintenance_margin"]),
        "leverage": str(row["leverage"]),
        "margin_mode": str(row["margin_mode"]),
        "isolated_wallet": str(row["isolated_wallet"]),
        "liquidation_price": row["liquidation_price"],
        "bankruptcy_price": row["bankruptcy_price"],
        "accumulated_funding": accumulated_funding,
        "trading_fees": trading_fees,
        "liquidation_fees": liquidation_fees,
        "risk_tier": int(row["risk_tier"]),
        "rule_revision": int(row["rule_revision"]),
        "protection": dict(protection),
    }


def refresh_hedge_leg_accounting(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    virtual_time_ms: int,
    source_sequence: int,
    now_ms: int,
    reason: str,
    accounting_totals: Mapping[tuple[str, str], tuple[Decimal, Decimal, Decimal]]
    | None = None,
) -> None:
    run = connection.execute(
        "SELECT position_mode, settlement_asset FROM replay_training_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None or str(run["position_mode"]) != "HEDGE":
        return
    rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_position_leg
            WHERE run_id = ? AND track_id = ?
            ORDER BY CASE position_side WHEN 'LONG' THEN 0 ELSE 1 END
            """,
            (run_id, track_id),
        ).fetchall()
    )
    if not rows:
        # Review forks synchronize fills before rebuilding their selected
        # checkpoint position projection.  The subsequent detector derives
        # the same accounting totals once both legs exist.
        return
    if tuple(str(row["position_side"]) for row in rows) != ("LONG", "SHORT"):
        raise TrainingRunError(
            "HEDGE_POSITION_ACCOUNTING_INCOMPLETE",
            "both HEDGE legs are required for accounting refresh",
            status_code=409,
            details={"fallback_applied": False},
        )
    totals = (
        hedge_accounting_totals_by_leg(connection, run_id=run_id)
        if accounting_totals is None
        else accounting_totals
    )
    for row in rows:
        position_side = str(row["position_side"])
        funding, trading_fees, liquidation_fees = totals.get(
            (track_id, position_side),
            (Decimal(0), Decimal(0), Decimal(0)),
        )
        funding_value = decimal_to_string(
            funding,
            field_name="leg accumulated funding",
        )
        trading_value = decimal_to_string(
            trading_fees,
            field_name="leg trading fees",
        )
        liquidation_value = decimal_to_string(
            liquidation_fees,
            field_name="leg liquidation fees",
        )
        component = position_leg_component(
            row,
            accumulated_funding=funding_value,
            trading_fees=trading_value,
            liquidation_fees=liquidation_value,
        )
        component_hash = canonical_sha256(component)
        if (
            str(row["component_hash"]) == component_hash
            and str(row["accumulated_funding"]) == funding_value
            and str(row["trading_fees"]) == trading_value
            and str(row["liquidation_fees"]) == liquidation_value
        ):
            continue
        next_revision = int(row["component_revision"]) + 1
        connection.execute(
            """
            UPDATE replay_training_position_leg
            SET accumulated_funding = ?, trading_fees = ?,
                liquidation_fees = ?, component_revision = ?,
                component_hash = ?, updated_at_ms = ?
            WHERE run_id = ? AND track_id = ? AND position_side = ?
            """,
            (
                funding_value,
                trading_value,
                liquidation_value,
                next_revision,
                component_hash,
                now_ms,
                run_id,
                track_id,
                position_side,
            ),
        )
        ledger_ops.append_contract_ledger(
            connection,
            run_id=run_id,
            posting_id=(
                f"position-accounting:{track_id}:{position_side}:"
                f"{next_revision}:{component_hash}"
            ),
            track_id=track_id,
            kind="POSITION_ACCOUNTING_MUTATION",
            cash_delta=Decimal(0),
            asset=str(run["settlement_asset"]),
            virtual_time_ms=virtual_time_ms,
            source_sequence=source_sequence,
            fidelity="DERIVED_FROM_HASH_CHAINED_LEDGER",
            rule_revision=int(row["rule_revision"]),
            reference_type="POSITION_LEG",
            reference_id=f"{track_id}:{position_side}",
            metadata={
                "position_side": position_side,
                "reason": reason,
                "previous_component_hash": str(row["component_hash"]),
                "component_hash": component_hash,
                "component_revision": next_revision,
                "accumulated_funding": funding_value,
                "trading_fees": trading_value,
                "liquidation_fees": liquidation_value,
            },
            now_ms=now_ms,
        )


def hedge_risk_fingerprint(
    connection: sqlite3.Connection,
    *,
    run_id: str,
) -> str:
    account = connection.execute(
        """
        SELECT account.margin_mode, run.position_mode, account.overlay_cash,
               account.isolated_margin_json, account.status,
               run.current_equity
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE account.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None:
        raise TypeError("HEDGE risk account is missing")
    tracks = tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT track_id, position_json, account_json, open_orders_json,
                   public_price
            FROM replay_training_market_track
            WHERE run_id = ? AND subscription_tier = 'FULL'
            ORDER BY stable_ordinal, track_id
            """,
            (run_id,),
        ).fetchall()
    )
    rules = tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT track_id, revision, rule_hash
            FROM replay_training_instrument_rule
            WHERE run_id = ? ORDER BY track_id, revision
            """,
            (run_id,),
        ).fetchall()
    )
    active_cases = tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT case_id, state, trigger_snapshot_id
            FROM replay_training_liquidation_case
            WHERE run_id = ?
              AND state NOT IN (
                  'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED',
                  'RECOVERED_AFTER_CANCEL'
              )
            ORDER BY case_sequence, case_id
            """,
            (run_id,),
        ).fetchall()
    )
    return canonical_sha256(
        {
            "account": tuple(account),
            "tracks": tracks,
            "rules": rules,
            "active_cases": active_cases,
        }
    )


def settle_exact_funding_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    event: AccountHistoryEvent,
    virtual_time_ms: int,
    source_sequence: int,
    settlement_asset: str,
    now_ms: int,
) -> None:
    existing = connection.execute(
        """
        SELECT 1 FROM replay_training_funding_settlement
        WHERE run_id = ? AND track_id = ? AND settlement_time_ms = ?
        """,
        (run_id, track_id, virtual_time_ms),
    ).fetchone()
    if existing is not None:
        return
    track = connection.execute(
        """
        SELECT position_json FROM replay_training_market_track
        WHERE run_id = ? AND track_id = ?
        """,
        (run_id, track_id),
    ).fetchone()
    rule_row = connection.execute(
        """
        SELECT revision, rule_json FROM replay_training_instrument_rule
        WHERE run_id = ? AND track_id = ?
          AND effective_virtual_time_ms <= ?
        ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
        """,
        (run_id, track_id, virtual_time_ms),
    ).fetchone()
    if track is None or rule_row is None:
        raise TypeError("exact funding inputs are missing")
    position = json.loads(str(track["position_json"]))
    if not isinstance(position, dict):
        raise TypeError("exact funding position is invalid")
    rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
    quantity = Decimal(str(position.get("quantity", "0")))
    mark = Decimal(str(event.payload["mark_price"]))
    rate = Decimal(str(event.payload["funding_rate"]))
    raw = -(quantity * mark * Decimal(rule.contract_size) * rate)
    rounded = round_to_step(
        abs(raw),
        Decimal(rule.quote_step),
        upward=True,
    )
    cash_delta = rounded.copy_sign(raw) if raw else Decimal(0)
    ledger_sequence = ledger_ops.append_contract_ledger(
        connection,
        run_id=run_id,
        posting_id=f"exact-funding:{track_id}:{event.event_time_ms}",
        track_id=track_id,
        kind="FUNDING_SETTLEMENT",
        cash_delta=cash_delta,
        asset=settlement_asset,
        virtual_time_ms=virtual_time_ms,
        source_sequence=source_sequence,
        fidelity="HISTORICAL_EXACT_ARCHIVE_FUNDING",
        rule_revision=int(rule_row["revision"]),
        reference_type="ACCOUNT_ARCHIVE_EVENT",
        reference_id=f"{event.archive_id}:{event.event_sequence}",
        metadata={
            "archive_id": event.archive_id,
            "archive_event_sequence": event.event_sequence,
            "actual_settlement_time_ms": event.event_time_ms,
            "rate": str(event.payload["funding_rate"]),
            "mark_price": str(event.payload["mark_price"]),
            "contract_size": rule.contract_size,
            "rounding": "ABS_CEILING_QUOTE_STEP_THEN_SIGN",
        },
        now_ms=now_ms,
    )
    connection.execute(
        """
        INSERT INTO replay_training_funding_settlement(
            run_id, track_id, settlement_time_ms, position_quantity,
            mark_price, funding_rate, cash_delta, fidelity,
            ledger_sequence, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            track_id,
            virtual_time_ms,
            decimal_to_string(quantity, field_name="funding quantity"),
            str(event.payload["mark_price"]),
            str(event.payload["funding_rate"]),
            decimal_to_string(cash_delta, field_name="funding cash delta"),
            "HISTORICAL_EXACT_ARCHIVE_FUNDING",
            ledger_sequence,
            now_ms,
        ),
    )
    account = connection.execute(
        """
        SELECT overlay_cash FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    overlay = Decimal(str(account["overlay_cash"])) + cash_delta
    connection.execute(
        """
        UPDATE replay_training_contract_account
        SET overlay_cash = ?, updated_at_ms = ? WHERE run_id = ?
        """,
        (
            decimal_to_string(overlay, field_name="overlay cash"),
            now_ms,
            run_id,
        ),
    )


def append_only_projection_delta(
    current: object,
    previous: object,
) -> Sequence[object] | object:
    """Return only an immutable sequence tail, with a safe full fallback."""

    if not isinstance(current, (list, tuple)) or not isinstance(
        previous, (list, tuple)
    ):
        return current
    common_length = min(len(current), len(previous))
    if common_length and current[common_length - 1] != previous[common_length - 1]:
        return current
    if len(current) < len(previous):
        # Contract projections intentionally retain immutable historical rows.
        return ()
    return current[len(previous) :]


def sync_contract_components(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    track_id: str,
    virtual_time_ms: int,
    source_sequence: int,
    component_state: Mapping[str, object],
    now_ms: int,
    previous_component_state: Mapping[str, object] | None = None,
    fork_parent_run_id: str | None = None,
    fork_parent_track_id: str | None = None,
) -> None:
    if (fork_parent_run_id is None) != (fork_parent_track_id is None):
        raise TypeError("fork parent ledger identity must be complete")
    account = connection.execute(
        """
        SELECT account.*, run.settlement_asset, run.position_mode
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if account is None or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        return
    rule_row = connection.execute(
        """
        SELECT revision, rule_json FROM replay_training_instrument_rule
        WHERE run_id = ? AND track_id = ?
          AND effective_virtual_time_ms <= ?
        ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
        """,
        (run_id, track_id, virtual_time_ms),
    ).fetchone()
    if rule_row is None:
        raise TypeError("versioned instrument rule is missing")
    rule = account_math_ops._stored_instrument_rule(str(rule_row["rule_json"]))
    rule_revision = int(rule_row["revision"])
    raw_orders = component_state.get("orders")
    previous_orders = (
        previous_component_state.get("orders")
        if previous_component_state is not None
        else None
    )
    if isinstance(raw_orders, (list, tuple)) and isinstance(
        previous_orders, (list, tuple)
    ):
        if raw_orders == previous_orders:
            raw_orders = ()
        else:
            previous_orders_by_id = {
                str(raw["order_id"]): raw
                for raw in previous_orders
                if isinstance(raw, Mapping) and isinstance(raw.get("order_id"), str)
            }
            raw_orders = tuple(
                raw
                for raw in raw_orders
                if not isinstance(raw, Mapping)
                or previous_orders_by_id.get(str(raw.get("order_id"))) != raw
            )
    if isinstance(raw_orders, (list, tuple)):
        for raw in raw_orders:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("order_id"), str):
                raise TypeError("contract order projection is invalid")
            connection.execute(
                """
                INSERT INTO replay_training_contract_order(
                    run_id, track_id, order_id, order_json,
                    rule_revision, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, track_id, order_id) DO UPDATE SET
                    order_json = excluded.order_json,
                    rule_revision = excluded.rule_revision,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    run_id,
                    track_id,
                    raw["order_id"],
                    canonical_json(raw),
                    rule_revision,
                    now_ms,
                ),
            )

    raw_fills = component_state.get("fills")
    if previous_component_state is not None:
        raw_fills = append_only_projection_delta(
            raw_fills,
            previous_component_state.get("fills"),
        )
    overlay_delta = Decimal(0)
    hedge_fee_changed = False
    if isinstance(raw_fills, (list, tuple)):
        for raw in raw_fills:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("fill_id"), str):
                raise TypeError("contract fill projection is invalid")
            fill_id = str(raw["fill_id"])
            exists = connection.execute(
                """
                SELECT 1 FROM replay_training_contract_fill
                WHERE run_id = ? AND track_id = ? AND fill_id = ?
                """,
                (run_id, track_id, fill_id),
            ).fetchone()
            if exists is not None:
                continue
            position_side = raw.get("position_side")
            if str(account["position_mode"]) == "HEDGE" and position_side not in {
                "LONG",
                "SHORT",
            }:
                raise TrainingRunError(
                    "HEDGE_FILL_POSITION_SIDE_REQUIRED",
                    "a HEDGE fill must identify LONG or SHORT",
                    status_code=409,
                    details={"fill_id": fill_id, "fallback_applied": False},
                )
            event_time_ms = int(raw.get("event_time_ms", virtual_time_ms))
            policy = connection.execute(
                """
                SELECT policy.*, extension.policy_version,
                       extension.account_tier,
                       extension.liquidation_fee_bps,
                       extension.source_kind AS policy_source_kind,
                       extension.source_id AS policy_source_id,
                       extension.source_event_sequence
                FROM replay_training_fee_policy AS policy
                LEFT JOIN replay_training_fee_policy_extension AS extension
                  ON extension.run_id = policy.run_id
                 AND extension.revision = policy.revision
                WHERE policy.run_id = ?
                  AND policy.effective_virtual_time_ms <= ?
                ORDER BY policy.effective_virtual_time_ms DESC,
                         policy.revision DESC LIMIT 1
                """,
                (run_id, event_time_ms),
            ).fetchone()
            if policy is None:
                raise TypeError("versioned fee policy is missing")
            if (
                str(account["position_mode"]) == "HEDGE"
                and policy["policy_version"] is None
            ):
                raise TrainingRunError(
                    "HEDGE_FEE_POLICY_EXTENSION_MISSING",
                    "the effective HEDGE fee policy is incomplete",
                    status_code=409,
                    details={"fallback_applied": False},
                )
            broker_notional = Decimal(str(raw["notional"]))
            notional = broker_notional * Decimal(rule.contract_size)
            configured_fee = fee_for_notional(
                notional=notional,
                liquidity=str(raw["liquidity"]),
                maker_bps=policy["maker_fee_bps"],
                taker_bps=policy["taker_fee_bps"],
                quote_step=rule.quote_step,
            )
            broker_fee = Decimal(str(raw["fee"]))
            connection.execute(
                """
                INSERT INTO replay_training_contract_fill(
                    run_id, track_id, fill_id, fill_json, rule_revision,
                    fee_policy_revision, configured_fee, fee_fidelity,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    track_id,
                    fill_id,
                    canonical_json(
                        {
                            **dict(raw),
                            "account_notional": decimal_to_string(
                                notional,
                                field_name="account fill notional",
                            ),
                            "contract_size": rule.contract_size,
                            "rule_fidelity": rule.rule_fidelity,
                        }
                    ),
                    rule_revision,
                    int(policy["revision"]),
                    decimal_to_string(configured_fee, field_name="configured fee"),
                    str(policy["fidelity"]),
                    now_ms,
                ),
            )
            fork_metadata: dict[str, object] = {}
            if fork_parent_run_id is not None and fork_parent_track_id is not None:
                parent_posting = connection.execute(
                    """
                    SELECT ledger_sequence
                    FROM replay_training_contract_ledger
                    WHERE run_id = ? AND posting_id = ?
                    """,
                    (
                        fork_parent_run_id,
                        f"fee:{fork_parent_track_id}:{fill_id}",
                    ),
                ).fetchone()
                if parent_posting is None:
                    raise TrainingRunError(
                        "REVIEW_FORK_ACCOUNT_LEDGER_MISSING",
                        "forked fill has no immutable parent fee posting",
                        status_code=409,
                        details={"fallback_applied": False},
                    )
                fork_metadata = {
                    "fork_parent_run_id": fork_parent_run_id,
                    "fork_parent_ledger_sequence": int(
                        parent_posting["ledger_sequence"]
                    ),
                }
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=f"fee:{track_id}:{fill_id}",
                track_id=track_id,
                kind="TRADING_FEE",
                cash_delta=-configured_fee,
                asset=str(raw["fee_asset"]),
                virtual_time_ms=event_time_ms,
                source_sequence=int(raw.get("source_sequence", source_sequence)),
                fidelity=str(policy["fidelity"]),
                rule_revision=rule_revision,
                reference_type="FILL",
                reference_id=fill_id,
                metadata={
                    "fee_policy_revision": int(policy["revision"]),
                    "fee_policy_version": policy["policy_version"],
                    "account_tier": policy["account_tier"],
                    "liquidation_fee_bps": policy["liquidation_fee_bps"],
                    "policy_source_kind": policy["policy_source_kind"],
                    "policy_source_id": policy["policy_source_id"],
                    "policy_source_event_sequence": policy["source_event_sequence"],
                    "position_side": position_side,
                    "broker_fee": str(raw["fee"]),
                    "liquidity": str(raw["liquidity"]),
                    **fork_metadata,
                },
                now_ms=now_ms,
            )
            overlay_delta += broker_fee - configured_fee
            hedge_fee_changed = (
                hedge_fee_changed or str(account["position_mode"]) == "HEDGE"
            )

    raw_ledger = component_state.get("ledger")
    entries = raw_ledger.get("entries") if isinstance(raw_ledger, Mapping) else None
    previous_ledger = (
        previous_component_state.get("ledger")
        if previous_component_state is not None
        else None
    )
    previous_entries = (
        previous_ledger.get("entries") if isinstance(previous_ledger, Mapping) else None
    )
    if previous_component_state is not None:
        entries = append_only_projection_delta(entries, previous_entries)
    if isinstance(entries, (list, tuple)):
        for raw in entries:
            if not isinstance(raw, Mapping) or raw.get("account") != "CASH":
                continue
            kind = str(raw.get("kind"))
            if kind in {"INITIAL_CAPITAL", "FEE"}:
                continue
            entry_id = str(raw.get("entry_id"))
            cash_delta = Decimal(str(raw["amount"]))
            if (
                kind == "REALIZED_PNL"
                and rule.rule_fidelity == "HISTORICAL_EXACT_VERSIONED_EXCHANGE_RULE"
            ):
                cash_delta *= Decimal(rule.contract_size)
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=f"broker:{track_id}:{entry_id}",
                track_id=track_id,
                kind=f"BROKER_{kind}",
                cash_delta=cash_delta,
                asset=str(raw["currency"]),
                virtual_time_ms=int(raw.get("event_time_ms", virtual_time_ms)),
                source_sequence=int(raw.get("source_sequence", source_sequence)),
                fidelity="PAPER_BROKER_LEDGER_EXACT",
                rule_revision=rule_revision,
                reference_type="BROKER_ENTRY",
                reference_id=entry_id,
                metadata={
                    "transaction_id": raw.get("transaction_id"),
                    "order_id": raw.get("order_id"),
                    "fill_id": raw.get("fill_id"),
                    "broker_amount": str(raw["amount"]),
                    "contract_size": rule.contract_size,
                },
                now_ms=now_ms,
            )
    if overlay_delta:
        current = connection.execute(
            """
            SELECT overlay_cash FROM replay_training_contract_account
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        adjusted = Decimal(str(current["overlay_cash"])) + overlay_delta
        connection.execute(
            """
            UPDATE replay_training_contract_account
            SET overlay_cash = ?, updated_at_ms = ? WHERE run_id = ?
            """,
            (
                decimal_to_string(adjusted, field_name="overlay_cash"),
                now_ms,
                run_id,
            ),
        )
    if hedge_fee_changed:
        refresh_hedge_leg_accounting(
            connection,
            run_id=run_id,
            track_id=track_id,
            virtual_time_ms=virtual_time_ms,
            source_sequence=source_sequence,
            now_ms=now_ms,
            reason="TRADING_FEE",
        )
    if str(account["margin_mode"]) == "ISOLATED":
        position = component_state.get("position")
        orders = component_state.get("orders")
        terminal = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
        allocations = json.loads(str(account["isolated_margin_json"]))
        if not isinstance(allocations, dict):
            raise TypeError("isolated margin allocation is invalid")
        scopes: tuple[tuple[str | None, Mapping[str, object]], ...]
        if isinstance(position, Mapping) and position.get("position_mode") == "HEDGE":
            scopes = tuple(
                (side, leg)
                for side, leg in (
                    ("LONG", position.get("long")),
                    ("SHORT", position.get("short")),
                )
                if isinstance(leg, Mapping)
            )
        elif isinstance(position, Mapping):
            scopes = ((None, position),)
        else:
            scopes = ()
        changed = False
        for position_side, leg in scopes:
            allocation_key = isolated_margin_key(track_id, position_side)
            prior_was_open = True
            if position_side is not None:
                prior_leg = connection.execute(
                    """
                    SELECT absolute_quantity
                    FROM replay_training_position_leg
                    WHERE run_id = ? AND track_id = ? AND position_side = ?
                    """,
                    (run_id, track_id, position_side),
                ).fetchone()
                prior_was_open = (
                    prior_leg is not None
                    and Decimal(str(prior_leg["absolute_quantity"])) > 0
                )
            has_open_order = isinstance(orders, (list, tuple)) and any(
                isinstance(order, Mapping)
                and order.get("status") not in terminal
                and (
                    position_side is None or order.get("position_side") == position_side
                )
                for order in orders
            )
            if (
                not prior_was_open
                or str(leg.get("quantity")) != "0"
                or has_open_order
                or allocation_key not in allocations
            ):
                continue
            released = Decimal(str(allocations.pop(allocation_key)))
            changed = True
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=(f"auto-margin-release:{allocation_key}:{source_sequence}"),
                track_id=track_id,
                kind="MARGIN_RELEASE",
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=virtual_time_ms,
                source_sequence=source_sequence,
                fidelity="CONFIGURED_ISOLATED_MARGIN_EXACT",
                rule_revision=rule_revision,
                reference_type="POSITION",
                reference_id=allocation_key,
                metadata={
                    "allocation_key": allocation_key,
                    "position_side": position_side,
                    "released_margin": decimal_to_string(
                        released,
                        field_name="released isolated margin",
                    ),
                },
                now_ms=now_ms,
            )
        if changed:
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET isolated_margin_json = ?, updated_at_ms = ? WHERE run_id = ?
                """,
                (canonical_json(allocations), now_ms, run_id),
            )


def settle_contract_funding(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    now_ms: int,
) -> None:
    account = connection.execute(
        """
        SELECT account.*, run.settlement_asset
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if (
        account is None
        or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL
        or str(account["funding_mode"]) != "SANDBOX_FIXED"
    ):
        return
    interval = account["funding_interval_ms"]
    next_time = account["next_funding_time_ms"]
    rate_value = account["fixed_funding_rate"]
    if interval is None or next_time is None or rate_value is None:
        raise TypeError("sandbox funding configuration is incomplete")
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
    if not tracks or any(track["virtual_time_ms"] is None for track in tracks):
        return
    global_time = min(int(track["virtual_time_ms"]) for track in tracks)
    settlement_time = int(next_time)
    interval_ms = int(interval)
    rate = Decimal(str(rate_value))
    iterations = 0
    while settlement_time <= global_time:
        iterations += 1
        if iterations > 4096:
            raise TrainingRunError(
                "FUNDING_SCAN_LIMIT_EXCEEDED",
                "funding settlement exceeded the bounded interval budget",
                status_code=409,
            )
        for track in tracks:
            position = json.loads(str(track["position_json"]))
            if not isinstance(position, dict):
                raise TypeError("funding position projection is invalid")
            quantity = Decimal(str(position.get("quantity", "0")))
            mark = Decimal(
                str(position.get("mark_price", track["public_price"] or "0"))
            )
            if quantity and mark <= 0:
                raise TrainingRunError(
                    "HISTORICAL_MARK_UNAVAILABLE",
                    "funding settlement has no revealed mark proxy",
                    status_code=409,
                )
            cash_delta = -(quantity * mark * rate)
            existing = connection.execute(
                """
                SELECT ledger_sequence FROM replay_training_funding_settlement
                WHERE run_id = ? AND track_id = ? AND settlement_time_ms = ?
                """,
                (run_id, track["track_id"], settlement_time),
            ).fetchone()
            if existing is not None:
                continue
            rule_row = connection.execute(
                """
                SELECT revision FROM replay_training_instrument_rule
                WHERE run_id = ? AND track_id = ?
                ORDER BY revision DESC LIMIT 1
                """,
                (run_id, track["track_id"]),
            ).fetchone()
            if rule_row is None:
                raise TypeError("funding instrument rule is missing")
            sequence = ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=f"funding:{track['track_id']}:{settlement_time}",
                track_id=str(track["track_id"]),
                kind="FUNDING_SETTLEMENT",
                cash_delta=cash_delta,
                asset=str(account["settlement_asset"]),
                virtual_time_ms=settlement_time,
                source_sequence=int(track["source_sequence"] or 0),
                fidelity=SANDBOX_FUNDING_FIDELITY,
                rule_revision=int(rule_row["revision"]),
                reference_type="FUNDING_BOUNDARY",
                reference_id=f"funding-{settlement_time}",
                metadata={"rate": str(rate_value), "mark_price": str(mark)},
                now_ms=now_ms,
            )
            connection.execute(
                """
                INSERT INTO replay_training_funding_settlement(
                    run_id, track_id, settlement_time_ms, position_quantity,
                    mark_price, funding_rate, cash_delta, fidelity,
                    ledger_sequence, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    track["track_id"],
                    settlement_time,
                    decimal_to_string(quantity, field_name="funding quantity"),
                    decimal_to_string(mark, field_name="funding mark"),
                    str(rate_value),
                    decimal_to_string(cash_delta, field_name="funding cash_delta"),
                    SANDBOX_FUNDING_FIDELITY,
                    sequence,
                    now_ms,
                ),
            )
            overlay = Decimal(str(account["overlay_cash"])) + cash_delta
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET overlay_cash = ?, updated_at_ms = ? WHERE run_id = ?
                """,
                (
                    decimal_to_string(overlay, field_name="overlay_cash"),
                    now_ms,
                    run_id,
                ),
            )
            account = connection.execute(
                """
                SELECT account.*, run.settlement_asset
                FROM replay_training_contract_account AS account
                JOIN replay_training_run AS run USING(run_id)
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        settlement_time += interval_ms
    connection.execute(
        """
        UPDATE replay_training_contract_account
        SET next_funding_time_ms = ?, updated_at_ms = ? WHERE run_id = ?
        """,
        (settlement_time, now_ms, run_id),
    )
