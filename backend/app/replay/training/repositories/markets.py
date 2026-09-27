"""TrainingMarketRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..account import (
    CONFIGURED_FEE_FIDELITY,
    CONTRACT_ACCOUNT_MODEL,
    isolated_margin_key,
)
from ..errors import TrainingRunError
from ..historical_book import (
    PreparedHistoricalBookBinding,
    bind_historical_book_archive,
)
from ..models import (
    REPLAY_V2_PROTOCOL,
    ViewerState,
)
from ..multitrack import (
    GLOBAL_ORDERING_VERSION,
)
from ..persistence import ledger as ledger_ops
from ..persistence import liquidation as liquidation_ops
from ..persistence import portfolio as portfolio_ops
from ..persistence import public_time as public_time_ops
from ..persistence import run_records as run_records_ops
from ..review import (
    ReviewRecorder,
)
from ..schema import (
    RUN_RULES_SCHEMA_VERSION,
)


class TrainingMarketRepository:
    """Own markets operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore, review: ReviewRecorder) -> None:
        self.base_store = base_store
        self._review = review

    async def get_market_tracks(
        self,
        run_id: str,
        *,
        live_portfolio: bool = False,
    ) -> dict[str, object]:
        def read(
            connection: sqlite3.Connection,
        ) -> (
            tuple[
                sqlite3.Row,
                list[dict[str, object]],
                dict[str, object],
                dict[str, object] | None,
            ]
            | None
        ):
            run = connection.execute(
                """
                SELECT r.run_id, r.state AS run_state, r.initial_equity,
                       r.source_kind, r.book_mode,
                       r.adapter_session_id AS primary_adapter_session_id,
                       r.time_disclosure_policy AS run_time_disclosure_policy,
                       COALESCE(integrity.revealed, 0) AS run_revealed,
                       dataset.actual_replay_start_ms AS run_actual_start_ms,
                       dataset.actual_replay_end_ms AS run_actual_end_ms,
                       dataset.synthetic_origin_ms AS run_synthetic_origin_ms,
                       launch.context_json AS launch_context_json,
                       launch.context_hash AS launch_context_hash,
                       viewer.*
                FROM replay_training_run AS r
                JOIN replay_training_viewer_state AS viewer USING(run_id)
                LEFT JOIN replay_training_launch_context AS launch USING(run_id)
                LEFT JOIN replay_training_integrity AS integrity USING(run_id)
                LEFT JOIN replay_dataset_ref AS dataset
                  ON dataset.session_id = r.adapter_session_id
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                return None
            rows = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_market_track
                    WHERE run_id = ?
                    ORDER BY stable_ordinal, track_id
                    """,
                    (run_id,),
                ).fetchall()
            )
            track_payloads = [portfolio_ops.market_track_from_row(row) for row in rows]
            book_rows = {
                str(row["track_id"]): row
                for row in connection.execute(
                    """
                    SELECT * FROM replay_historical_book_projection
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchall()
            }
            for track in track_payloads:
                track["historical_book"] = portfolio_ops.historical_book_projection(
                    book_rows.get(str(track["track_id"])),
                    book_mode=str(run["book_mode"]),
                    subscription_tier=str(track["subscription_tier"]),
                )
            portfolio = portfolio_ops.contract_portfolio_projection(
                connection,
                run_id=run_id,
                initial_equity=str(run["initial_equity"]),
                tracks=track_payloads,
                live=live_portfolio,
            )
            if portfolio.get("hedge_inputs") is not None:
                try:
                    portfolio = portfolio_ops.public_contract_portfolio_projection(
                        portfolio,
                        time_disclosure_policy=str(run["run_time_disclosure_policy"]),
                        revealed=bool(run["run_revealed"]),
                        actual_start_ms=int(run["run_actual_start_ms"]),
                        actual_end_ms=int(run["run_actual_end_ms"]),
                        synthetic_origin_ms=(
                            None
                            if run["run_synthetic_origin_ms"] is None
                            else int(run["run_synthetic_origin_ms"])
                        ),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise TrainingRunError(
                        "TRAINING_RUN_STORAGE_DEGRADED",
                        "public HEDGE input projection is invalid",
                        status_code=503,
                    ) from exc
            launch_context = run_records_ops.launch_context_projection(run)
            if launch_context is None and str(run["run_state"]) != "AWAITING_MARKET":
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "initialized training run is missing its replay launch context",
                    status_code=503,
                )
            return run, track_payloads, portfolio, launch_context

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        run, tracks, portfolio, launch_context = result
        viewer = run_records_ops.viewer_from_row(run)
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "run_id": run_id,
            "ordering_version": GLOBAL_ORDERING_VERSION,
            "launch_context": launch_context,
            "viewer_state": viewer.to_dict(),
            "tracks": tracks,
            "portfolio": portfolio,
        }

    async def get_market_track_heads(self, run_id: str) -> list[dict[str, object]]:
        """Read operational track state without materializing audit history."""

        def read(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...] | None:
            run = connection.execute(
                "SELECT 1 FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                return None
            return tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_market_track
                    WHERE run_id = ?
                    ORDER BY stable_ordinal, track_id
                    """,
                    (run_id,),
                ).fetchall()
            )

        rows = await self.base_store.run_extension_read(read)
        if rows is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        return [portfolio_ops.market_track_from_row(row) for row in rows]

    async def get_market_track(
        self,
        run_id: str,
        track_id: str,
    ) -> dict[str, object]:
        def read(
            connection: sqlite3.Connection,
        ) -> tuple[sqlite3.Row, sqlite3.Row | None, str] | None:
            row = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if row is None:
                return None
            projection = connection.execute(
                """
                SELECT * FROM replay_historical_book_projection
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            run = connection.execute(
                "SELECT book_mode FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            assert run is not None
            return row, projection, str(run["book_mode"])

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "MARKET_TRACK_NOT_FOUND",
                "training market track does not exist",
                status_code=404,
            )
        row, projection, book_mode = result
        track = portfolio_ops.market_track_from_row(row)
        track["historical_book"] = portfolio_ops.historical_book_projection(
            projection,
            book_mode=book_mode,
            subscription_tier=str(track["subscription_tier"]),
        )
        return track

    async def allocate_isolated_margin(
        self,
        *,
        run_id: str,
        track_id: str,
        position_side: str | None,
        amount: str,
        command_id: str,
        virtual_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        target = Decimal(amount)

        def write(connection: sqlite3.Connection) -> None:
            account = connection.execute(
                """
                SELECT account.*, run.settlement_asset, run.position_mode,
                       run.adapter_session_id
                FROM replay_training_contract_account AS account
                JOIN replay_training_run AS run USING(run_id)
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if (
                account is None
                or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL
            ):
                raise TrainingRunError(
                    "CONTRACT_ACCOUNT_UNAVAILABLE",
                    "isolated margin requires a current v2 contract account",
                    status_code=409,
                )
            if str(account["margin_mode"]) != "ISOLATED":
                raise TrainingRunError(
                    "MARGIN_MODE_MISMATCH",
                    "margin allocation requires an ISOLATED TrainingRun",
                    status_code=409,
                )
            if str(account["position_mode"]) == "HEDGE":
                if position_side not in {"LONG", "SHORT"}:
                    raise TrainingRunError(
                        "REPLAY_CONTROL_INVALID",
                        "HEDGE isolated margin requires position_side",
                        status_code=422,
                    )
            elif position_side is not None:
                raise TrainingRunError(
                    "REPLAY_CONTROL_INVALID",
                    "ONE_WAY isolated margin does not accept position_side",
                    status_code=422,
                )
            track = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if track is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_FOUND",
                    "training market track does not exist",
                    status_code=404,
                )
            if str(account["position_mode"]) == "HEDGE":
                leg = connection.execute(
                    """
                    SELECT initial_margin FROM replay_training_position_leg
                    WHERE run_id = ? AND track_id = ? AND position_side = ?
                    """,
                    (run_id, track_id, position_side),
                ).fetchone()
                position_margin = (
                    Decimal(0) if leg is None else Decimal(str(leg["initial_margin"]))
                )
                reserved_margin = sum(
                    (
                        Decimal(
                            str(json.loads(str(row["order_json"]))["reserved_margin"])
                        )
                        for row in connection.execute(
                            """
                            SELECT order_json
                            FROM replay_training_contract_order
                            WHERE run_id = ? AND track_id = ?
                              AND json_extract(order_json, '$.position_side') = ?
                              AND json_extract(order_json, '$.status')
                                  IN ('OPEN', 'PARTIALLY_FILLED')
                            """,
                            (run_id, track_id, position_side),
                        ).fetchall()
                    ),
                    Decimal(0),
                )
                required = position_margin + reserved_margin
            else:
                track_account = json.loads(str(track["account_json"]))
                if not isinstance(track_account, dict):
                    raise TypeError("track account projection is invalid")
                required = Decimal(
                    str(track_account.get("margin_used", "0"))
                ) + Decimal(str(track_account.get("reserved_margin", "0")))
            if target < required:
                raise TrainingRunError(
                    "ISOLATED_MARGIN_IN_USE",
                    "allocation cannot fall below active position and order margin",
                    status_code=409,
                    details={
                        "required_margin": decimal_to_string(
                            required,
                            field_name="required isolated margin",
                        )
                    },
                )
            allocations = json.loads(str(account["isolated_margin_json"]))
            if not isinstance(allocations, dict):
                raise TypeError("isolated margin allocation is invalid")
            allocation_key = isolated_margin_key(track_id, position_side)
            current = Decimal(str(allocations.get(allocation_key, "0")))
            delta = target - current
            rows = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_market_track
                    WHERE run_id = ? ORDER BY stable_ordinal, track_id
                    """,
                    (run_id,),
                ).fetchall()
            )
            tracks = [portfolio_ops.market_track_from_row(row) for row in rows]
            run = connection.execute(
                "SELECT initial_equity FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            portfolio = portfolio_ops.contract_portfolio_projection(
                connection,
                run_id=run_id,
                initial_equity=str(run["initial_equity"]),
                tracks=tracks,
            )
            if delta > Decimal(str(portfolio["available_equity"])):
                raise TrainingRunError(
                    "RUN_ACCOUNT_MARGIN_EXCEEDED",
                    "isolated allocation exceeds shared available equity",
                    status_code=409,
                )
            if target == 0:
                allocations.pop(allocation_key, None)
                kind = "MARGIN_RELEASE"
            else:
                allocations[allocation_key] = decimal_to_string(
                    target,
                    field_name="isolated margin allocation",
                )
                kind = "MARGIN_ALLOCATION" if delta >= 0 else "MARGIN_RELEASE"
            now_ms = self.base_store._validated_now_ms()
            connection.execute(
                """
                UPDATE replay_training_contract_account
                SET isolated_margin_json = ?, updated_at_ms = ? WHERE run_id = ?
                """,
                (canonical_json(allocations), now_ms, run_id),
            )
            rule = connection.execute(
                """
                SELECT revision FROM replay_training_instrument_rule
                WHERE run_id = ? AND track_id = ? ORDER BY revision DESC LIMIT 1
                """,
                (run_id, track_id),
            ).fetchone()
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=f"margin:{command_id}",
                track_id=track_id,
                kind=kind,
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=virtual_time_ms,
                source_sequence=source_sequence,
                fidelity="CONFIGURED_ISOLATED_MARGIN_EXACT",
                rule_revision=int(rule["revision"]),
                reference_type="COMMAND",
                reference_id=command_id,
                metadata={
                    "allocation_key": allocation_key,
                    "position_side": position_side,
                    "old_allocation": decimal_to_string(
                        current,
                        field_name="old isolated allocation",
                    ),
                    "new_allocation": decimal_to_string(
                        target,
                        field_name="new isolated allocation",
                    ),
                },
                now_ms=now_ms,
            )
            liquidation_ops.detect_contract_liquidations(
                connection,
                run_id=run_id,
                now_ms=now_ms,
                trigger_virtual_time_ms=virtual_time_ms,
            )
            self._review.append(
                connection,
                run_id=run_id,
                session_id=str(account["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "category": "POSITION",
                    "event_type": "ALLOCATE_ISOLATED_MARGIN",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)
        return (await self.get_market_tracks(run_id))["portfolio"]  # type: ignore[return-value]

    async def revise_contract_policy(
        self,
        *,
        run_id: str,
        command_id: str,
        command_type: str,
        payload: Mapping[str, object],
        virtual_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> dict[str, object]:
            account = connection.execute(
                """
                SELECT account.*, run.settlement_asset, run.integrity_mode,
                       run.adapter_session_id, run.time_disclosure_policy,
                       run.active_rule_revision,
                       COALESCE(integrity.revealed, 0) AS revealed,
                       COALESCE(history.account_data_mode, 'APPROX_PROXY')
                           AS account_data_mode
                FROM replay_training_contract_account AS account
                JOIN replay_training_run AS run USING(run_id)
                LEFT JOIN replay_training_integrity AS integrity USING(run_id)
                LEFT JOIN replay_training_account_history AS history USING(run_id)
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if (
                account is None
                or str(account["account_model"]) != CONTRACT_ACCOUNT_MODEL
            ):
                raise TrainingRunError(
                    "CONTRACT_ACCOUNT_UNAVAILABLE",
                    "policy revision requires a current v2 contract account",
                    status_code=409,
                )
            replayed = connection.execute(
                """
                SELECT event_type, new_value_json, reason, public_time_json
                FROM replay_run_action_event
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if replayed is not None:
                new_value = json.loads(str(replayed["new_value_json"]))
                if not isinstance(new_value, Mapping):
                    raise TypeError("stored policy command result is invalid")
                expected: dict[str, object]
                table: str
                if command_type == "change_fee_policy":
                    expected = {
                        "maker_fee_bps": str(payload["maker_fee_bps"]),
                        "taker_fee_bps": str(payload["taker_fee_bps"]),
                    }
                    table = "replay_training_fee_policy"
                elif command_type == "change_leverage_cap":
                    expected = {"max_leverage": str(payload["max_leverage"])}
                    table = "replay_training_leverage_policy"
                elif command_type == "change_funding_policy":
                    expected = {
                        "funding_mode": str(payload["funding_mode"]),
                        "fixed_funding_rate": payload.get("fixed_funding_rate"),
                        "funding_interval_ms": payload.get("funding_interval_ms"),
                    }
                    table = "replay_training_funding_policy"
                else:
                    raise ValueError("unsupported contract policy command")
                if (
                    str(replayed["event_type"]) != command_type.upper()
                    or str(replayed["reason"]) != str(payload["reason"])
                    or any(
                        new_value.get(key) != value for key, value in expected.items()
                    )
                ):
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id was reused with a different policy revision",
                        status_code=409,
                    )
                policy_hash = new_value.get("policy_hash")
                revision = new_value.get("revision")
                if not isinstance(policy_hash, str) or not isinstance(revision, int):
                    raise TypeError("stored policy command identity is incomplete")
                if table == "replay_training_fee_policy":
                    policy_row = connection.execute(
                        """
                        SELECT effective_virtual_time_ms
                        FROM replay_training_fee_policy
                        WHERE run_id = ? AND revision = ? AND policy_hash = ?
                        """,
                        (run_id, revision, policy_hash),
                    ).fetchone()
                    public_time = json.loads(str(replayed["public_time_json"]))
                    replay_source_sequence = (
                        int(public_time.get("sequence", 0))
                        if isinstance(public_time, Mapping)
                        else 0
                    )
                else:
                    policy_row = connection.execute(
                        f"""
                        SELECT effective_virtual_time_ms, source_sequence
                        FROM {table}
                        WHERE run_id = ? AND revision = ? AND policy_hash = ?
                        """,
                        (run_id, revision, policy_hash),
                    ).fetchone()
                    replay_source_sequence = (
                        0 if policy_row is None else int(policy_row["source_sequence"])
                    )
                if policy_row is None:
                    raise TypeError("stored policy command row is missing")
                return {
                    "revision": revision,
                    "policy_hash": policy_hash,
                    "effective_cursor": {
                        "virtual_time_ms": int(policy_row["effective_virtual_time_ms"]),
                        "source_sequence": replay_source_sequence,
                    },
                    "deduplicated": True,
                }
            now_ms = self.base_store._validated_now_ms()
            revision: int
            policy_hash: str
            old_value: dict[str, object]
            new_value: dict[str, object]
            if command_type == "change_fee_policy":
                old_policy = connection.execute(
                    """
                    SELECT * FROM replay_training_fee_policy
                    WHERE run_id = ?
                    ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if old_policy is None:
                    raise TypeError("active fee policy is missing")
                old_value = {
                    "maker_fee_bps": str(old_policy["maker_fee_bps"]),
                    "taker_fee_bps": str(old_policy["taker_fee_bps"]),
                    "revision": int(old_policy["revision"]),
                    "policy_hash": str(old_policy["policy_hash"]),
                }
                revision = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0) + 1
                        FROM replay_training_fee_policy WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()[0]
                )
                policy = {
                    "schema_version": "replay.training.fee-policy.v1",
                    "run_id": run_id,
                    "revision": revision,
                    "effective_virtual_time_ms": virtual_time_ms,
                    "maker_fee_bps": str(payload["maker_fee_bps"]),
                    "taker_fee_bps": str(payload["taker_fee_bps"]),
                    "fidelity": CONFIGURED_FEE_FIDELITY,
                }
                policy_hash = canonical_sha256(policy)
                connection.execute(
                    """
                    INSERT INTO replay_training_fee_policy(
                        run_id, revision, effective_virtual_time_ms,
                        maker_fee_bps, taker_fee_bps, policy_hash, fidelity,
                        reason, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        revision,
                        virtual_time_ms,
                        payload["maker_fee_bps"],
                        payload["taker_fee_bps"],
                        policy_hash,
                        CONFIGURED_FEE_FIDELITY,
                        payload["reason"],
                        now_ms,
                    ),
                )
                new_value = {
                    "maker_fee_bps": str(payload["maker_fee_bps"]),
                    "taker_fee_bps": str(payload["taker_fee_bps"]),
                    "revision": revision,
                    "policy_hash": policy_hash,
                }
            elif command_type == "change_leverage_cap":
                old_policy = connection.execute(
                    """
                    SELECT * FROM replay_training_leverage_policy
                    WHERE run_id = ?
                    ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if old_policy is None:
                    raise TypeError("active leverage policy is missing")
                old_value = {
                    "max_leverage": str(old_policy["max_leverage"]),
                    "revision": int(old_policy["revision"]),
                    "policy_hash": str(old_policy["policy_hash"]),
                }
                revision = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0) + 1
                        FROM replay_training_leverage_policy WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()[0]
                )
                leverage_policy = {
                    "schema_version": RUN_RULES_SCHEMA_VERSION,
                    "kind": "LEVERAGE_CAP",
                    "run_id": run_id,
                    "revision": revision,
                    "effective_virtual_time_ms": virtual_time_ms,
                    "source_sequence": source_sequence,
                    "max_leverage": str(payload["max_leverage"]),
                    "fidelity": "CONFIGURED_USER_CAP_EXACT",
                }
                policy_hash = canonical_sha256(leverage_policy)
                connection.execute(
                    """
                    INSERT INTO replay_training_leverage_policy(
                        run_id, revision, effective_virtual_time_ms,
                        source_sequence, max_leverage, policy_hash, fidelity,
                        reason, command_id, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 'CONFIGURED_USER_CAP_EXACT',
                              ?, ?, ?)
                    """,
                    (
                        run_id,
                        revision,
                        virtual_time_ms,
                        source_sequence,
                        payload["max_leverage"],
                        policy_hash,
                        payload["reason"],
                        command_id,
                        now_ms,
                    ),
                )
                new_value = {
                    "max_leverage": str(payload["max_leverage"]),
                    "revision": revision,
                    "policy_hash": policy_hash,
                }
            elif command_type == "change_funding_policy":
                if str(account["account_data_mode"]) == "HISTORICAL_EXACT":
                    raise TrainingRunError(
                        "HISTORICAL_FUNDING_POLICY_IMMUTABLE",
                        "exact account-history funding policy cannot be replaced",
                        status_code=409,
                        details={
                            "fallback_applied": False,
                            "archive_rule_mutated": False,
                        },
                    )
                old_policy = connection.execute(
                    """
                    SELECT * FROM replay_training_funding_policy
                    WHERE run_id = ?
                    ORDER BY effective_virtual_time_ms DESC, revision DESC LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if old_policy is None:
                    raise TypeError("active funding policy is missing")
                old_value = {
                    "funding_mode": str(old_policy["funding_mode"]),
                    "fixed_funding_rate": old_policy["fixed_funding_rate"],
                    "funding_interval_ms": old_policy["funding_interval_ms"],
                    "revision": int(old_policy["revision"]),
                    "policy_hash": str(old_policy["policy_hash"]),
                }
                revision = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0) + 1
                        FROM replay_training_funding_policy WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()[0]
                )
                mode = str(payload["funding_mode"])
                rate = payload.get("fixed_funding_rate")
                interval = payload.get("funding_interval_ms")
                next_time = (
                    None
                    if interval is None
                    else ((virtual_time_ms // int(interval)) + 1) * int(interval)
                )
                connection.execute(
                    """
                    UPDATE replay_training_contract_account
                    SET funding_mode = ?, fixed_funding_rate = ?,
                        funding_interval_ms = ?, next_funding_time_ms = ?,
                        updated_at_ms = ? WHERE run_id = ?
                    """,
                    (mode, rate, interval, next_time, now_ms, run_id),
                )
                funding_policy = {
                    "schema_version": RUN_RULES_SCHEMA_VERSION,
                    "kind": "FUNDING_POLICY",
                    "run_id": run_id,
                    "revision": revision,
                    "effective_virtual_time_ms": virtual_time_ms,
                    "source_sequence": source_sequence,
                    "funding_mode": mode,
                    "fixed_funding_rate": rate,
                    "funding_interval_ms": interval,
                    "fidelity": "CONFIGURED_FUNDING_POLICY_EXACT",
                }
                policy_hash = canonical_sha256(funding_policy)
                connection.execute(
                    """
                    INSERT INTO replay_training_funding_policy(
                        run_id, revision, effective_virtual_time_ms,
                        source_sequence, funding_mode, fixed_funding_rate,
                        funding_interval_ms, policy_hash, fidelity, reason,
                        command_id, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                              'CONFIGURED_FUNDING_POLICY_EXACT', ?, ?, ?)
                    """,
                    (
                        run_id,
                        revision,
                        virtual_time_ms,
                        source_sequence,
                        mode,
                        rate,
                        interval,
                        policy_hash,
                        payload["reason"],
                        command_id,
                        now_ms,
                    ),
                )
                new_value = {
                    "funding_mode": mode,
                    "fixed_funding_rate": rate,
                    "funding_interval_ms": interval,
                    "revision": revision,
                    "policy_hash": policy_hash,
                }
            else:
                raise ValueError("unsupported contract policy command")
            ledger_ops.append_contract_ledger(
                connection,
                run_id=run_id,
                posting_id=f"policy:{command_id}",
                track_id=None,
                kind="POLICY_REVISION",
                cash_delta=Decimal(0),
                asset=str(account["settlement_asset"]),
                virtual_time_ms=virtual_time_ms,
                source_sequence=source_sequence,
                fidelity="CONFIGURED_POLICY_EXACT",
                rule_revision=max(1, revision),
                reference_type="COMMAND",
                reference_id=command_id,
                metadata={
                    "command_type": command_type,
                    "policy_hash": policy_hash,
                    "reason": payload["reason"],
                    "policy": {
                        key: value for key, value in payload.items() if key != "reason"
                    },
                },
                now_ms=now_ms,
            )
            previous_action = connection.execute(
                """
                SELECT state_hash_after FROM replay_run_action_event
                WHERE run_id = ? ORDER BY action_sequence DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            action_sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(action_sequence), 0) + 1
                    FROM replay_run_action_event WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            session = connection.execute(
                "SELECT state_hash FROM replay_session WHERE session_id = ?",
                (account["adapter_session_id"],),
            ).fetchone()
            if session is None:
                raise TypeError("policy adapter session is missing")
            public_time = public_time_ops.public_time(
                connection,
                session_id=str(account["adapter_session_id"]),
                policy=str(account["time_disclosure_policy"]),
                revealed=bool(account["revealed"]),
                public_time_ms=virtual_time_ms,
                sequence=source_sequence,
            )
            connection.execute(
                """
                INSERT INTO replay_run_action_event(
                    run_id, action_sequence, event_id, command_id, event_type,
                    rule_revision, public_time_json, old_value_json,
                    new_value_json, reason, state_hash_before,
                    state_hash_after, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    action_sequence,
                    f"action-{action_sequence:08d}",
                    command_id,
                    command_type.upper(),
                    int(account["active_rule_revision"]),
                    canonical_json(public_time),
                    canonical_json(old_value),
                    canonical_json(new_value),
                    payload["reason"],
                    (
                        None
                        if previous_action is None
                        else str(previous_action["state_hash_after"])
                    ),
                    str(session["state_hash"]),
                    now_ms,
                ),
            )
            self._review.append(
                connection,
                run_id=run_id,
                session_id=str(account["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "event_type": command_type.upper(),
                    "category": "RULE",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
            return {
                "revision": revision,
                "policy_hash": policy_hash,
                "effective_cursor": {
                    "virtual_time_ms": virtual_time_ms,
                    "source_sequence": source_sequence,
                },
                "deduplicated": False,
            }

        result = await self.base_store.run_extension_write(write)
        result["portfolio"] = (await self.get_market_tracks(run_id))["portfolio"]
        return result

    async def reserve_market_track(
        self,
        *,
        run_id: str,
        exchange: str,
        market_type: str,
        symbol: str,
        settlement_asset: str,
        source_kind: str,
        subscription_tier: str,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> sqlite3.Row:
            run = connection.execute(
                "SELECT virtual_time_ms FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            duplicate = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND exchange = ? AND market_type = ? AND symbol = ?
                """,
                (run_id, exchange, market_type, symbol),
            ).fetchone()
            if duplicate is not None:
                raise TrainingRunError(
                    "MARKET_TRACK_CONFLICT",
                    "training market track already exists",
                    status_code=409,
                    details={"track_id": str(duplicate["track_id"])},
                )
            ordinal_row = connection.execute(
                """
                SELECT COALESCE(MAX(stable_ordinal), 0) + 1 AS ordinal
                FROM replay_training_market_track WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            ordinal = int(ordinal_row["ordinal"])
            track_id = f"track-{ordinal}"
            now_ms = self.base_store._validated_now_ms()
            state = "DORMANT" if subscription_tier == "NONE" else "PREPARING"
            connection.execute(
                """
                INSERT INTO replay_training_market_track(
                    run_id, track_id, stable_ordinal, adapter_session_id,
                    exchange, market_type, symbol, settlement_asset, source_kind,
                    state, subscription_tier, dataset_epoch, virtual_time_ms,
                    source_sequence, revision, forced_full_reasons_json,
                    capabilities_json, public_price, position_json, account_json,
                    open_orders_json, degraded_reason, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                          NULL, '[]', ?, NULL, '{}', '{}', '[]', NULL, ?, ?)
                """,
                (
                    run_id,
                    track_id,
                    ordinal,
                    exchange,
                    market_type,
                    symbol,
                    settlement_asset,
                    source_kind,
                    state,
                    subscription_tier,
                    canonical_json(run_records_ops._phase1_capabilities(source_kind)),
                    now_ms,
                    now_ms,
                ),
            )
            return connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()

        try:
            row = await self.base_store.run_extension_write(write)
        except sqlite3.IntegrityError as exc:
            raise TrainingRunError(
                "MARKET_TRACK_CONFLICT",
                "training market track identity conflicts with an existing track",
                status_code=409,
            ) from exc
        return portfolio_ops.market_track_from_row(row)

    async def mark_market_track_error(
        self,
        *,
        run_id: str,
        track_id: str,
        reason: str,
        degraded: bool = False,
    ) -> None:
        state = "DEGRADED" if degraded else "ERROR"

        def write(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                """
                SELECT forced_full_reasons_json
                FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if row is None:
                return
            reasons = json.loads(str(row["forced_full_reasons_json"]))
            if not isinstance(reasons, list):
                reasons = []
            if degraded and "REVIEW_REQUIRED" not in reasons:
                reasons.append("REVIEW_REQUIRED")
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET state = ?, degraded_reason = ?,
                    forced_full_reasons_json = ?, updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (
                    state,
                    reason[:500],
                    canonical_json(sorted(set(str(item) for item in reasons))),
                    self.base_store._validated_now_ms(),
                    run_id,
                    track_id,
                ),
            )

        await self.base_store.run_extension_write(write)

    async def set_market_track_tier(
        self,
        *,
        run_id: str,
        track_id: str,
        subscription_tier: str,
        historical_book_binding: PreparedHistoricalBookBinding | None = None,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> sqlite3.Row:
            row = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_FOUND",
                    "training market track does not exist",
                    status_code=404,
                )
            reasons = json.loads(str(row["forced_full_reasons_json"]))
            if not isinstance(reasons, list):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "market track force reasons are invalid",
                    status_code=503,
                )
            if reasons and subscription_tier != "FULL":
                raise TrainingRunError(
                    "MARKET_TRACK_FORCED_FULL",
                    "forced FULL market track cannot be downgraded",
                    status_code=409,
                    details={"forced_full_reasons": reasons},
                )
            if subscription_tier != "NONE" and row["adapter_session_id"] is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_PREPARED",
                    "market track must prepare a frozen adapter before activation",
                    status_code=409,
                )
            now_ms = self.base_store._validated_now_ms()
            run = connection.execute(
                """
                SELECT r.book_mode,
                       dataset.actual_replay_start_ms,
                       dataset.actual_replay_end_ms
                FROM replay_training_run AS r
                JOIN replay_dataset_ref AS dataset
                  ON dataset.session_id = r.adapter_session_id
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            history = connection.execute(
                """
                SELECT account_data_mode, status
                FROM replay_training_account_history WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if (
                history is not None
                and history["account_data_mode"] == "HISTORICAL_EXACT"
                and subscription_tier != "NONE"
            ):
                account_ref = connection.execute(
                    """
                    SELECT 1 FROM replay_account_history_ref
                    WHERE run_id = ? AND track_id = ? AND active = 1
                    LIMIT 1
                    """,
                    (run_id, track_id),
                ).fetchone()
                if history["status"] != "ACTIVE" or account_ref is None:
                    raise TrainingRunError(
                        "ACCOUNT_HISTORY_BINDING_MISSING",
                        "exact account WARM/FULL track requires a pinned archive",
                        status_code=409,
                        details={"fallback_applied": False},
                    )
            if run["book_mode"] == "BOOK_ASSISTED_REQUIRED":
                if subscription_tier == "FULL":
                    active = connection.execute(
                        """
                        SELECT 1 FROM replay_historical_book_ref
                        WHERE run_id = ? AND track_id = ? AND active = 1
                        LIMIT 1
                        """,
                        (run_id, track_id),
                    ).fetchone()
                    if historical_book_binding is not None:
                        bind_historical_book_archive(
                            connection,
                            run_id=run_id,
                            track_id=track_id,
                            binding=historical_book_binding,
                            bound_range_start_ms=int(run["actual_replay_start_ms"]),
                            bound_range_end_ms=int(run["actual_replay_end_ms"]),
                            now_ms=now_ms,
                        )
                    elif active is None:
                        raise TrainingRunError(
                            "HISTORICAL_BOOK_BINDING_MISSING",
                            "FULL book-assisted track requires a pinned L2 archive",
                            status_code=409,
                        )
                else:
                    connection.execute(
                        """
                        UPDATE replay_historical_book_ref
                        SET active = 0, released_at_ms = ?
                        WHERE run_id = ? AND track_id = ? AND active = 1
                        """,
                        (now_ms, run_id, track_id),
                    )
                    connection.execute(
                        """
                        DELETE FROM replay_historical_book_projection
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (run_id, track_id),
                    )
                    connection.execute(
                        """
                        UPDATE replay_training_market_track
                        SET capabilities_json = json_set(
                            capabilities_json,
                            '$.ORDER_BOOK',
                            'UNSUPPORTED_NO_HISTORY'
                        ), updated_at_ms = ?
                        WHERE run_id = ? AND track_id = ?
                        """,
                        (now_ms, run_id, track_id),
                    )
            state = "DORMANT" if subscription_tier == "NONE" else "READY"
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET subscription_tier = ?, state = ?, updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (
                    subscription_tier,
                    state,
                    now_ms,
                    run_id,
                    track_id,
                ),
            )
            return connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()

        return portfolio_ops.market_track_from_row(
            await self.base_store.run_extension_write(write)
        )

    async def clear_market_track_degradation(
        self,
        *,
        run_id: str,
        track_id: str,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> sqlite3.Row:
            row = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_FOUND",
                    "training market track does not exist",
                    status_code=404,
                )
            reasons = [
                reason
                for reason in portfolio_ops.reason_list(row)
                if reason != "REVIEW_REQUIRED"
            ]
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET state = 'READY', degraded_reason = NULL,
                    forced_full_reasons_json = ?, updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (
                    canonical_json(reasons),
                    self.base_store._validated_now_ms(),
                    run_id,
                    track_id,
                ),
            )
            return connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()

        return portfolio_ops.market_track_from_row(
            await self.base_store.run_extension_write(write)
        )

    async def select_market_track(
        self,
        *,
        run_id: str,
        track_id: str,
        expected_viewer_revision: int,
        command_id: str,
        command: Mapping[str, object],
    ) -> ViewerState:
        request_json = canonical_json(command)

        def write(connection: sqlite3.Connection) -> ViewerState:
            replayed = connection.execute(
                """
                SELECT request_json, viewer_state_json
                FROM replay_training_viewer_event
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if replayed is not None:
                if str(replayed["request_json"]) != request_json:
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id was reused with a different viewer command",
                        status_code=409,
                    )
                return ViewerState.from_dict(
                    json.loads(str(replayed["viewer_state_json"]))
                )
            viewer_row = connection.execute(
                "SELECT * FROM replay_training_viewer_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            target = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if viewer_row is None or target is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_FOUND",
                    "training market track does not exist",
                    status_code=404,
                )
            current = run_records_ops.viewer_from_row(viewer_row)
            if current.semantic_view_revision != expected_viewer_revision:
                raise TrainingRunError(
                    "VIEWER_REVISION_CONFLICT",
                    "viewer state revision does not match",
                    status_code=409,
                    details={
                        "expected": expected_viewer_revision,
                        "actual": current.semantic_view_revision,
                    },
                )
            if (
                target["adapter_session_id"] is None
                or target["state"] != "READY"
                or target["subscription_tier"] != "FULL"
            ):
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_READY",
                    "selected market track must be an aligned FULL track",
                    status_code=409,
                )
            current_track = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, current.selected_track_id),
            ).fetchone()
            if current_track is None or (
                int(current_track["virtual_time_ms"]) != int(target["virtual_time_ms"])
            ):
                raise TrainingRunError(
                    "GLOBAL_CLOCK_DIVERGED",
                    "market track is not aligned to the TrainingRun clock",
                    status_code=409,
                )
            if current.selected_track_id != track_id:
                old_reasons = portfolio_ops.reason_list(current_track)
                old_reasons = [reason for reason in old_reasons if reason != "VIEWED"]
                old_tier = str(current_track["subscription_tier"])
                if not old_reasons and old_tier == "FULL":
                    old_tier = "WARM"
                connection.execute(
                    """
                    UPDATE replay_training_market_track
                    SET subscription_tier = ?, forced_full_reasons_json = ?,
                        updated_at_ms = ?
                    WHERE run_id = ? AND track_id = ?
                    """,
                    (
                        old_tier,
                        canonical_json(old_reasons),
                        self.base_store._validated_now_ms(),
                        run_id,
                        current.selected_track_id,
                    ),
                )
            target_reasons = portfolio_ops.reason_list(target)
            if "VIEWED" not in target_reasons:
                target_reasons.append("VIEWED")
            now_ms = self.base_store._validated_now_ms()
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET subscription_tier = 'FULL', forced_full_reasons_json = ?,
                    updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (canonical_json(sorted(target_reasons)), now_ms, run_id, track_id),
            )
            updated = ViewerState(
                run_id=current.run_id,
                selected_track_id=track_id,
                display_interval=current.display_interval,
                chart_type=current.chart_type,
                visible_range=current.visible_range,
                pane_layout=current.pane_layout,
                rail_layout=current.rail_layout,
                semantic_view_revision=current.semantic_view_revision + 1,
            )
            payload_json = canonical_json(updated.to_dict())
            connection.execute(
                """
                UPDATE replay_training_viewer_state
                SET selected_track_id = ?, semantic_view_revision = ?,
                    updated_at_ms = ?
                WHERE run_id = ?
                """,
                (track_id, updated.semantic_view_revision, now_ms, run_id),
            )
            connection.execute(
                """
                UPDATE replay_training_run
                SET last_symbol = ?, current_equity = json_extract(?, '$.equity'),
                    summary_revision = ?, revision = ?, source_sequence = ?,
                    virtual_time_ms = ?, updated_at_ms = ?
                WHERE run_id = ?
                """,
                (
                    target["symbol"],
                    target["account_json"],
                    target["revision"],
                    target["revision"],
                    target["source_sequence"],
                    target["virtual_time_ms"],
                    now_ms,
                    run_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_training_viewer_event(
                    run_id, semantic_view_revision, command_id, event_type,
                    request_json, viewer_state_json, created_at_ms
                ) VALUES (?, ?, ?, 'SELECT_TRACK', ?, ?, ?)
                """,
                (
                    run_id,
                    updated.semantic_view_revision,
                    command_id,
                    request_json,
                    payload_json,
                    now_ms,
                ),
            )
            self._review.append(
                connection,
                run_id=run_id,
                session_id=str(target["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "category": "VIEWER",
                    "event_type": "SELECT_TRACK",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
            return updated

        return await self.base_store.run_extension_write(write)

    async def set_actor_segment_refs(self, run_id: str, *, active: bool) -> None:
        if active:

            def already_active(connection: sqlite3.Connection) -> bool:
                portfolio_ops.assert_run_segments_ready(
                    connection, run_id=run_id, operation="actor activation"
                )
                return (
                    connection.execute(
                        "SELECT 1 FROM replay_data_segment_ref WHERE run_id=? AND owner_kind='ACTOR' "
                        "AND (active != 1 OR released_at_ms IS NOT NULL) LIMIT 1",
                        (run_id,),
                    ).fetchone()
                    is None
                )

            # Most controls use already-pinned immutable segments. Keep the
            # readiness check, but don't acquire the writer for a no-op UPDATE.
            if await self.base_store.run_extension_read(already_active):
                return
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> None:
            if active:
                portfolio_ops.assert_run_segments_ready(
                    connection,
                    run_id=run_id,
                    operation="actor activation",
                )
                connection.execute(
                    """
                    UPDATE replay_data_segment_ref
                    SET active = 1, released_at_ms = NULL
                    WHERE run_id = ? AND owner_kind = 'ACTOR'
                      AND (active != 1 OR released_at_ms IS NOT NULL)
                    """,
                    (run_id,),
                )
            else:
                connection.execute(
                    """
                    UPDATE replay_data_segment_ref
                    SET active = 0, released_at_ms = ?
                    WHERE run_id = ? AND owner_kind = 'ACTOR'
                      AND (active != 0 OR released_at_ms IS NULL)
                    """,
                    (now_ms, run_id),
                )

        await self.base_store.run_extension_write(write)

    async def global_events(self, run_id: str) -> list[dict[str, object]]:
        def read(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
            return tuple(
                connection.execute(
                    """
                    SELECT global_sequence, ordering_version,
                           actual_event_time_ms, event_phase, track_id,
                           source_sequence, ordering_hash
                    FROM replay_training_global_event
                    WHERE run_id = ? ORDER BY global_sequence
                    """,
                    (run_id,),
                ).fetchall()
            )

        rows = await self.base_store.run_extension_read(read)
        return [dict(row) for row in rows]

    async def remove_market_track(self, run_id: str, track_id: str) -> str | None:
        def write(connection: sqlite3.Connection) -> str | None:
            viewer = connection.execute(
                "SELECT selected_track_id FROM replay_training_viewer_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            row = connection.execute(
                """
                SELECT * FROM replay_training_market_track
                WHERE run_id = ? AND track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "MARKET_TRACK_NOT_FOUND",
                    "training market track does not exist",
                    status_code=404,
                )
            reasons = portfolio_ops.reason_list(row)
            if (
                viewer is not None
                and viewer["selected_track_id"] == track_id
                or reasons
            ):
                raise TrainingRunError(
                    "MARKET_TRACK_FORCED_FULL",
                    "owned market track cannot be removed",
                    status_code=409,
                    details={"forced_full_reasons": reasons},
                )
            session_id = row["adapter_session_id"]
            connection.execute(
                "DELETE FROM replay_training_market_track WHERE run_id = ? AND track_id = ?",
                (run_id, track_id),
            )
            connection.execute(
                "DELETE FROM replay_training_pin WHERE run_id = ? AND pin_id = ?",
                (run_id, f"{track_id}-dataset"),
            )
            connection.execute(
                "DELETE FROM replay_archive_pin WHERE run_id = ? AND track_id = ?",
                (run_id, track_id),
            )
            connection.execute(
                "DELETE FROM replay_data_segment_ref WHERE run_id = ? AND track_id = ?",
                (run_id, track_id),
            )
            connection.execute(
                """
                DELETE FROM replay_data_segment
                WHERE storage_kind = 'EMBEDDED_ARCHIVE'
                  AND NOT EXISTS(
                      SELECT 1 FROM replay_data_segment_ref AS ref
                      WHERE ref.segment_id = replay_data_segment.segment_id
                  )
                """
            )
            return None if session_id is None else str(session_id)

        return await self.base_store.run_extension_write(write)

    async def history_archive_pin(
        self,
        *,
        run_id: str,
        track_id: str,
        interval: str,
    ) -> dict[str, object] | None:
        """Return the immutable archive revision bound to one chart interval."""

        def read(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return list(
                connection.execute(
                    """
                    SELECT source_revision, exchange, market_type, symbol,
                           base_interval, range_start_ms, range_end_ms,
                           dataset_epoch, created_at_ms
                    FROM replay_archive_pin
                    WHERE run_id = ? AND track_id = ? AND base_interval = ?
                    ORDER BY created_at_ms, source_revision
                    """,
                    (run_id, track_id, interval),
                ).fetchall()
            )

        rows = await self.base_store.run_extension_read(read)
        if not rows:
            return None
        if len(rows) != 1:
            raise TrainingRunError(
                "HISTORY_SOURCE_INCOMPLETE",
                "training history interval has conflicting archive pins",
                status_code=503,
            )
        return dict(rows[0])

    async def pin_history_archive_interval(
        self,
        *,
        run_id: str,
        track_id: str,
        source_revision: str,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        range_start_ms: int,
        range_end_ms: int,
    ) -> dict[str, object]:
        """Pin a native display catalog once, preserving later page stability."""

        if (
            len(source_revision) != 71
            or not source_revision.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in source_revision[7:]
            )
            or not exchange
            or not market_type
            or not symbol
            or not interval
            or isinstance(range_start_ms, bool)
            or not isinstance(range_start_ms, int)
            or isinstance(range_end_ms, bool)
            or not isinstance(range_end_ms, int)
            or range_start_ms < 0
            or range_end_ms < range_start_ms
        ):
            raise TrainingRunError(
                "HISTORY_SOURCE_INCOMPLETE",
                "native display archive pin is invalid",
                status_code=503,
            )
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            track = connection.execute(
                """
                SELECT t.exchange, t.market_type, t.symbol, t.dataset_epoch
                FROM replay_training_market_track AS t
                WHERE t.run_id = ? AND t.track_id = ?
                """,
                (run_id, track_id),
            ).fetchone()
            if track is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training history track does not exist",
                    status_code=404,
                )
            if (
                str(track["exchange"]) != exchange
                or str(track["market_type"]) != market_type
                or str(track["symbol"]) != symbol
            ):
                raise TrainingRunError(
                    "HISTORY_SOURCE_IDENTITY_DRIFT",
                    "native display archive identity changed",
                )
            existing = connection.execute(
                """
                SELECT source_revision, exchange, market_type, symbol,
                       base_interval, range_start_ms, range_end_ms,
                       dataset_epoch, created_at_ms
                FROM replay_archive_pin
                WHERE run_id = ? AND track_id = ? AND base_interval = ?
                ORDER BY created_at_ms, source_revision
                """,
                (run_id, track_id, interval),
            ).fetchall()
            if len(existing) > 1:
                raise TrainingRunError(
                    "HISTORY_SOURCE_INCOMPLETE",
                    "training history interval has conflicting archive pins",
                    status_code=503,
                )
            if existing:
                return dict(existing[0])
            connection.execute(
                """
                INSERT INTO replay_archive_pin(
                    run_id, track_id, source_revision,
                    exchange, market_type, symbol, base_interval,
                    range_start_ms, range_end_ms, dataset_epoch, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    track_id,
                    source_revision,
                    exchange,
                    market_type,
                    symbol,
                    interval,
                    range_start_ms,
                    range_end_ms,
                    str(track["dataset_epoch"]),
                    now_ms,
                ),
            )
            return {
                "source_revision": source_revision,
                "exchange": exchange,
                "market_type": market_type,
                "symbol": symbol,
                "base_interval": interval,
                "range_start_ms": range_start_ms,
                "range_end_ms": range_end_ms,
                "dataset_epoch": str(track["dataset_epoch"]),
                "created_at_ms": now_ms,
            }

        return await self.base_store.run_extension_write(write)

    async def history_binding(
        self,
        *,
        session_id: str,
        track_id: str,
    ) -> dict[str, object]:
        """Read the immutable source binding and latest durable public cursor.

        This query deliberately reads only replay-owned SQLite tables. The
        service may subsequently page pre-start chart history through its
        read-only replay repository when the bound policy is ALL_AVAILABLE.
        """

        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT
                    r.run_id,
                    r.adapter_session_id AS primary_adapter_session_id,
                    t.adapter_session_id,
                    r.base_interval,
                    r.display_interval,
                    r.time_disclosure_policy,
                    r.dataset_epoch AS run_dataset_epoch,
                    t.track_id,
                    t.exchange,
                    t.market_type,
                    t.symbol,
                    t.source_kind,
                    t.subscription_tier,
                    t.dataset_epoch AS track_dataset_epoch,
                    t.virtual_time_ms,
                    t.source_sequence,
                    t.revision,
                    s.config_json,
                    s.data_epoch AS session_data_epoch,
                    s.degraded_reason,
                    policy.schema_version,
                    policy.indicator_warmup_bars,
                    policy.visible_history_mode,
                    policy.visible_history_lookback_ms,
                    policy.visible_history_rows,
                    policy.actual_visible_history_start_ms,
                    policy.actual_replay_start_ms,
                    policy.effective_warmup_bars,
                    policy.forward_cache_ms,
                    policy.interval_ms,
                    policy.policy_hash
                FROM replay_training_run AS r
                JOIN replay_training_market_track AS t ON t.run_id = r.run_id
                JOIN replay_session AS s ON s.session_id = t.adapter_session_id
                JOIN replay_training_data_policy AS policy USING(run_id)
                WHERE t.adapter_session_id = ? AND t.track_id = ?
                """,
                (session_id, track_id),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training history track does not exist",
                status_code=404,
            )
        adapter_config = json.loads(str(row["config_json"]))
        if not isinstance(adapter_config, dict):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training adapter config is invalid",
                status_code=503,
            )
        adapter_display_interval = adapter_config.get("display_interval")
        if not isinstance(adapter_display_interval, str):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training adapter display interval is invalid",
                status_code=503,
            )
        history_policy = run_records_ops.data_policy_from_row(row)
        return {
            "run_id": str(row["run_id"]),
            "primary_adapter_session_id": str(row["primary_adapter_session_id"]),
            "session_id": str(row["adapter_session_id"]),
            "track_id": str(row["track_id"]),
            "exchange": str(row["exchange"]),
            "market_type": str(row["market_type"]),
            "symbol": str(row["symbol"]),
            "source_kind": str(row["source_kind"]),
            "subscription_tier": str(row["subscription_tier"]),
            "base_interval": str(row["base_interval"]),
            # Phase 3 keeps the adapter and frozen history at the base interval.
            # Mutable display selection belongs exclusively to ViewerState.
            "display_interval": adapter_display_interval,
            "time_disclosure_policy": str(row["time_disclosure_policy"]),
            "run_dataset_epoch": str(row["run_dataset_epoch"]),
            "track_dataset_epoch": str(row["track_dataset_epoch"]),
            "session_data_epoch": str(row["session_data_epoch"]),
            "virtual_time_ms": int(row["virtual_time_ms"]),
            "source_sequence": int(row["source_sequence"]),
            "revision": int(row["revision"]),
            "config": adapter_config,
            "degraded_reason": row["degraded_reason"],
            "history_policy": {
                **history_policy.to_dict(include_actual=True),
                "policy_hash": history_policy.policy_hash,
            },
        }
