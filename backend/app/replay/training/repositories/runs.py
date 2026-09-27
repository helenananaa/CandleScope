"""TrainingRunRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.data_engine.interval_policy import parse_interval_ms
from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..errors import TrainingRunError
from ..models import (
    REPLAY_V2_PROTOCOL,
    TrainingRunCreateRequest,
    TrainingRunSetupRequest,
    ViewerState,
    validate_v2_counter,
)
from ..persistence import public_time as public_time_ops
from ..persistence import run_records as run_records_ops
from ..schema import (
    SELECTION_PREPARATION_SCHEMA_VERSION,
    TIME_COMMITMENT_SCHEMA_VERSION,
    TRAINING_SCHEMA_ID,
    selection_preparation_hash,
    start_selection_hash,
    time_commitment_hash,
)


class TrainingRunRepository:
    """Own runs operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore) -> None:
        self.base_store = base_store

    async def create_selection_preparation(
        self,
        *,
        preparation_id: str,
        start_mode: str,
        random_seed: int | None,
        catalog_epoch: str,
        source_fingerprint: str,
        selected_start_ms: int,
        required_start_ms: int,
        required_end_ms: int,
        interval_ms: int,
        request: TrainingRunCreateRequest,
        selection: Mapping[str, object],
    ) -> dict[str, object]:
        seed_source = "SERVER" if start_mode == "RANDOM" else "MANUAL"
        digest = selection_preparation_hash(
            preparation_id=preparation_id,
            start_mode=start_mode,
            seed_source=seed_source,
            random_seed=random_seed,
            catalog_epoch=catalog_epoch,
            source_fingerprint=source_fingerprint,
            selected_start_ms=selected_start_ms,
            required_start_ms=required_start_ms,
            required_end_ms=required_end_ms,
            interval_ms=interval_ms,
        )
        request_payload = request.to_dict(redact_hidden_start=False)
        if request.launch_context is not None:
            request_payload["launch_context"] = request.launch_context.to_dict()
        request_json = canonical_json(request_payload)
        request_hash = canonical_sha256(request_payload)
        selection_payload = dict(selection)
        selection_json = canonical_json(selection_payload)
        selection_json_hash = canonical_sha256(selection_payload)
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO replay_training_selection_preparation(
                    preparation_id, schema_version, status, start_mode,
                    seed_source, random_seed, catalog_epoch, source_fingerprint,
                    selected_start_ms, required_start_ms, required_end_ms,
                    interval_ms, selection_hash, request_json, request_hash,
                    selection_json, selection_json_hash, retry_count, dataset_epoch,
                    error_code, error_message, created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'PREPARING_DATA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, 0, NULL, NULL, NULL, ?, ?)
                """,
                (
                    preparation_id,
                    SELECTION_PREPARATION_SCHEMA_VERSION,
                    start_mode,
                    seed_source,
                    random_seed,
                    catalog_epoch,
                    source_fingerprint,
                    selected_start_ms,
                    required_start_ms,
                    required_end_ms,
                    interval_ms,
                    digest,
                    request_json,
                    request_hash,
                    selection_json,
                    selection_json_hash,
                    now_ms,
                    now_ms,
                ),
            )

        await self.base_store.run_extension_write(write)
        return {
            "preparation_id": preparation_id,
            "status": "PREPARING_DATA",
            "selection_hash": digest,
        }

    async def fail_selection_preparation(
        self,
        preparation_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        now_ms = self.base_store._validated_now_ms()
        bounded_code = str(error_code).strip()[:128] or "PREPARATION_FAILED"
        bounded_message = str(error_message).strip()[:500] or "data preparation failed"

        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                UPDATE replay_training_selection_preparation
                SET status = 'FAILED', error_code = ?, error_message = ?,
                    updated_at_ms = ?
                WHERE preparation_id = ? AND status = 'PREPARING_DATA'
                """,
                (bounded_code, bounded_message, now_ms, preparation_id),
            )

        await self.base_store.run_extension_write(write, allow_degraded=True)

    async def claim_selection_preparation_retry(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            row = connection.execute(
                """
                SELECT * FROM replay_training_selection_preparation
                WHERE preparation_id = ?
                """,
                (preparation_id,),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "TRAINING_PREPARATION_NOT_FOUND",
                    "training data preparation does not exist",
                    status_code=404,
                )
            if str(row["status"]) != "FAILED":
                raise TrainingRunError(
                    "TRAINING_PREPARATION_NOT_RETRYABLE",
                    "training data preparation is not in a retryable state",
                    status_code=409,
                    details={"status": str(row["status"])},
                )
            try:
                request_payload = json.loads(str(row["request_json"]))
                selection_payload = json.loads(str(row["selection_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training preparation retry payload is unreadable",
                    status_code=503,
                ) from exc
            if (
                not isinstance(request_payload, Mapping)
                or not isinstance(selection_payload, Mapping)
                or canonical_sha256(request_payload) != str(row["request_hash"])
                or canonical_sha256(selection_payload)
                != str(row["selection_json_hash"])
                or str(selection_payload.get("catalog_epoch"))
                != str(row["catalog_epoch"])
                or str(selection_payload.get("source_fingerprint"))
                != str(row["source_fingerprint"])
                or int(selection_payload.get("selected_start_ms", -1))
                != int(row["selected_start_ms"])
                or int(selection_payload.get("interval_ms", -1))
                != int(row["interval_ms"])
            ):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training preparation retry payload failed validation",
                    status_code=503,
                )
            updated = connection.execute(
                """
                UPDATE replay_training_selection_preparation
                SET status = 'PREPARING_DATA', error_code = NULL,
                    error_message = NULL, retry_count = retry_count + 1,
                    updated_at_ms = ?
                WHERE preparation_id = ? AND status = 'FAILED'
                """,
                (now_ms, preparation_id),
            )
            if updated.rowcount != 1:
                raise TrainingRunError(
                    "TRAINING_PREPARATION_NOT_RETRYABLE",
                    "training data preparation retry was claimed concurrently",
                    status_code=409,
                )
            return {
                "preparation_id": preparation_id,
                "request": dict(request_payload),
                "selection": dict(selection_payload),
            }

        return await self.base_store.run_extension_write(write)

    async def selection_preparation(
        self,
        preparation_id: str,
    ) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> dict[str, object] | None:
            row = connection.execute(
                """
                SELECT preparation_id, status, catalog_epoch, selection_hash,
                       dataset_epoch, error_code, error_message, retry_count,
                       created_at_ms, updated_at_ms
                FROM replay_training_selection_preparation
                WHERE preparation_id = ?
                """,
                (preparation_id,),
            ).fetchone()
            return None if row is None else dict(row)

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "TRAINING_PREPARATION_NOT_FOUND",
                "training data preparation does not exist",
                status_code=404,
            )
        return result

    async def create_empty_run(
        self,
        *,
        run_id: str,
        request: TrainingRunSetupRequest,
        committed_start_ms: int,
        random_seed: int | None,
    ) -> None:
        """Persist a run identity and immutable T0 before any market exists."""

        if not isinstance(request, TrainingRunSetupRequest):
            raise TypeError("request must be TrainingRunSetupRequest")
        setup = request.to_dict()
        committed_start = validate_v2_counter(
            committed_start_ms,
            field_name="committed_start_ms",
        )
        start_mode = str(setup["start_mode"])
        range_start = setup["random_range_start_ms"]
        range_end = setup["random_range_end_ms"]
        seed_source = "SERVER" if start_mode == "RANDOM" else "MANUAL"
        if start_mode == "MANUAL":
            if (
                committed_start != setup["requested_start_ms"]
                or random_seed is not None
            ):
                raise ValueError("manual time commitment does not match the setup")
        else:
            random_seed = validate_v2_counter(
                random_seed,
                field_name="random_seed",
            )
            if (
                not isinstance(range_start, int)
                or isinstance(range_start, bool)
                or not isinstance(range_end, int)
                or isinstance(range_end, bool)
                or committed_start < range_start
                or committed_start > range_end
            ):
                raise ValueError("random time commitment is outside the setup range")
        commitment_hash = time_commitment_hash(
            run_id=run_id,
            start_mode=start_mode,
            seed_source=seed_source,
            random_seed=random_seed,
            random_range_start_ms=range_start if isinstance(range_start, int) else None,
            random_range_end_ms=range_end if isinstance(range_end, int) else None,
            committed_start_ms=committed_start,
        )
        now_ms = self.base_store._validated_now_ms()
        name = run_records_ops._safe_name(
            setup.get("name") if isinstance(setup.get("name"), str) else None,
            fallback=f"回放训练 {run_id[-8:]}",
        )

        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO replay_training_run(
                    run_id, adapter_session_id, protocol, schema_version,
                    name, state, source_kind, start_mode, integrity_mode,
                    time_disclosure_policy, book_mode, margin_mode,
                    position_mode, funding_mode, account_data_mode,
                    hedge_public_history_ref_json, simulation_manifest_ref_json,
                    simulation_contract_hash, simulation_model_version,
                    account_fidelity, insurance_adl_fidelity,
                    execution_model, allow_rule_changes,
                    exchange, market_type, last_symbol, settlement_asset,
                    base_interval, display_interval, initial_equity,
                    current_equity, summary_revision, revision,
                    source_sequence, virtual_time_ms, active_rule_revision,
                    catalog_epoch, dataset_epoch, compatibility,
                    created_at_ms, updated_at_ms, saved_at_ms
                ) VALUES (
                    ?, NULL, 'replay.v3', 'replay.training.v2',
                    ?, 'AWAITING_MARKET', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    NULL, NULL, NULL, NULL, ?, ?,
                    'TOUCH_OR_TAPE_V2', ?, NULL, NULL, NULL, ?,
                    NULL, NULL, ?, ?, 0, 0, 0, ?, 0,
                    NULL, NULL, 'READY', ?, ?, ?
                )
                """,
                (
                    run_id,
                    name,
                    setup["source_kind"],
                    setup["start_mode"],
                    setup["integrity_mode"],
                    setup["time_disclosure_policy"],
                    setup["book_mode"],
                    setup["margin_mode"],
                    setup["position_mode"],
                    setup["funding_mode"],
                    setup["account_data_mode"],
                    setup["account_fidelity"],
                    setup["insurance_adl_fidelity"],
                    int(bool(setup["allow_rule_changes"])),
                    setup["settlement_asset"],
                    setup["initial_equity"],
                    setup["initial_equity"],
                    committed_start,
                    now_ms,
                    now_ms,
                    now_ms,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_training_time_commitment(
                    run_id, schema_version, start_mode, seed_source,
                    random_seed, random_range_start_ms, random_range_end_ms,
                    committed_start_ms, commitment_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    TIME_COMMITMENT_SCHEMA_VERSION,
                    start_mode,
                    seed_source,
                    random_seed,
                    range_start,
                    range_end,
                    committed_start,
                    commitment_hash,
                    now_ms,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_training_run_setup(
                    run_id, setup_json, setup_hash, created_at_ms
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    canonical_json(setup),
                    canonical_sha256(setup),
                    now_ms,
                ),
            )
            run_records_ops.insert_viewer_state(
                connection,
                ViewerState(
                    run_id=run_id,
                    selected_track_id=None,
                    display_interval="1m",
                    chart_type="candles",
                    visible_range=None,
                    pane_layout={},
                    rail_layout={},
                    semantic_view_revision=0,
                ),
                now_ms=now_ms,
            )
            run_records_ops.insert_initial_action(
                connection,
                run_id=run_id,
                action_type="CREATE_RUN",
                action={
                    "schema": "replay.training.action.v2",
                    "state": "AWAITING_MARKET",
                    "setup_hash": canonical_sha256(setup),
                    "time_commitment_hash": commitment_hash,
                },
                now_ms=now_ms,
            )

        await self.base_store.run_extension_write(write)

    async def get_time_commitment(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT * FROM replay_training_time_commitment WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training run has no immutable time commitment",
                status_code=503,
            )
        payload = {
            "schema_version": str(row["schema_version"]),
            "run_id": str(row["run_id"]),
            "start_mode": str(row["start_mode"]),
            "seed_source": str(row["seed_source"]),
            "random_seed": row["random_seed"],
            "random_range_start_ms": row["random_range_start_ms"],
            "random_range_end_ms": row["random_range_end_ms"],
            "committed_start_ms": int(row["committed_start_ms"]),
            "commitment_hash": str(row["commitment_hash"]),
        }
        expected = time_commitment_hash(
            run_id=str(payload["run_id"]),
            start_mode=str(payload["start_mode"]),
            seed_source=str(payload["seed_source"]),
            random_seed=(
                None if payload["random_seed"] is None else int(payload["random_seed"])
            ),
            random_range_start_ms=(
                None
                if payload["random_range_start_ms"] is None
                else int(payload["random_range_start_ms"])
            ),
            random_range_end_ms=(
                None
                if payload["random_range_end_ms"] is None
                else int(payload["random_range_end_ms"])
            ),
            committed_start_ms=int(payload["committed_start_ms"]),
        )
        if expected != payload["commitment_hash"]:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training time commitment hash does not match",
                status_code=503,
            )
        return payload

    async def get_run_setup(
        self,
        run_id: str,
        *,
        require_awaiting_market: bool = True,
    ) -> TrainingRunSetupRequest:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT run.state, setup.setup_json, setup.setup_hash
                FROM replay_training_run AS run
                JOIN replay_training_run_setup AS setup USING(run_id)
                WHERE run.run_id = ?
                """,
                (run_id,),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist or has no setup",
                status_code=404,
            )
        if require_awaiting_market and str(row["state"]) != "AWAITING_MARKET":
            raise TrainingRunError(
                "TRAINING_RUN_ALREADY_INITIALIZED",
                "training run already has a market clock",
                status_code=409,
            )
        try:
            payload = json.loads(str(row["setup_json"]))
            request = TrainingRunSetupRequest.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training run setup is invalid",
                status_code=503,
            ) from exc
        if canonical_sha256(request.to_dict()) != str(row["setup_hash"]):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training run setup failed its integrity check",
                status_code=503,
            )
        return request

    async def list_runs(
        self,
        *,
        limit: int,
        cursor: str | None,
        state: str | None,
        source_kind: str | None,
        compatibility: str | None,
    ) -> dict[str, object]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= run_records_ops._LIST_LIMIT_MAX
        ):
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                f"limit must be between 1 and {run_records_ops._LIST_LIMIT_MAX}",
                status_code=422,
            )
        if state is not None and state not in run_records_ops._STATES:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID", "state filter is invalid", status_code=422
            )
        if source_kind is not None and source_kind not in run_records_ops._SOURCES:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID", "source filter is invalid", status_code=422
            )
        if (
            compatibility is not None
            and compatibility not in run_records_ops._COMPATIBILITY_FILTERS
        ):
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "compatibility filter is invalid",
                status_code=422,
            )
        decoded_cursor = run_records_ops._cursor_payload(cursor)

        def read(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
            sql = (
                run_records_ops._CARD_CTE
                + """
            SELECT * FROM cards
            WHERE (:state IS NULL OR state = :state)
              AND (:source_kind IS NULL OR source_kind = :source_kind)
              AND (:compatibility IS NULL OR compatibility = :compatibility)
              AND (
                    :cursor_updated IS NULL
                    OR updated_at_ms < :cursor_updated
                    OR (
                        updated_at_ms = :cursor_updated
                        AND (
                            run_id < :cursor_run
                            OR (run_id = :cursor_run AND kind < :cursor_kind)
                        )
                    )
              )
            ORDER BY updated_at_ms DESC, run_id DESC, kind DESC
            LIMIT :row_limit
            """
            )
            params = {
                "state": state,
                "source_kind": source_kind,
                "compatibility": compatibility,
                "cursor_updated": None if decoded_cursor is None else decoded_cursor[0],
                "cursor_run": None if decoded_cursor is None else decoded_cursor[1],
                "cursor_kind": None if decoded_cursor is None else decoded_cursor[2],
                "row_limit": limit + 1,
            }
            return tuple(connection.execute(sql, params).fetchall())

        rows = await self.base_store.run_extension_read(read)
        visible = rows[:limit]
        items = [run_records_ops.card_from_row(row) for row in visible]
        next_cursor = (
            run_records_ops._encode_cursor(visible[-1])
            if len(rows) > limit and visible
            else None
        )
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "schema_version": TRAINING_SCHEMA_ID,
            "items": items,
            "next_cursor": next_cursor,
        }

    async def get_run(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                run_records_ops._CARD_CTE
                + "SELECT * FROM cards WHERE run_id = ? AND kind = 'V2'",
                (run_id,),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        return run_records_ops.card_from_row(row)

    async def account_record_page(
        self,
        run_id: str,
        *,
        record_type: str,
        order_scope: str,
        track_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, object]:
        if record_type not in run_records_ops._ACCOUNT_RECORD_TYPES:
            raise TrainingRunError(
                "REPLAY_ACCOUNT_RECORD_INVALID",
                "record_type must be ORDERS, FILLS, or LEDGER",
                status_code=422,
            )
        if order_scope not in run_records_ops._ACCOUNT_ORDER_SCOPES:
            raise TrainingRunError(
                "REPLAY_ACCOUNT_RECORD_INVALID",
                "order_scope must be ACTIVE, HISTORY, or ALL",
                status_code=422,
            )
        if record_type != "ORDERS" and order_scope != "ALL":
            raise TrainingRunError(
                "REPLAY_ACCOUNT_RECORD_INVALID",
                "order_scope is only supported for order pages",
                status_code=422,
            )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= run_records_ops._ACCOUNT_RECORD_LIMIT_MAX
        ):
            raise TrainingRunError(
                "REPLAY_ACCOUNT_RECORD_INVALID",
                f"limit must be between 1 and {run_records_ops._ACCOUNT_RECORD_LIMIT_MAX}",
                status_code=422,
            )
        decoded_cursor = run_records_ops._account_record_cursor_payload(
            cursor,
            record_type=record_type,
            order_scope=order_scope,
            track_id=track_id,
        )

        def read(
            connection: sqlite3.Connection,
        ) -> tuple[tuple[sqlite3.Row, ...], int]:
            exists = connection.execute(
                "SELECT 1 FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if exists is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            cursor_value = None if decoded_cursor is None else decoded_cursor[0]
            cursor_track = None if decoded_cursor is None else decoded_cursor[1]
            cursor_record = None if decoded_cursor is None else decoded_cursor[2]
            params: dict[str, object] = {
                "run_id": run_id,
                "track_id": track_id,
                "order_scope": order_scope,
                "cursor_value": cursor_value,
                "cursor_track": cursor_track,
                "cursor_record": cursor_record,
                "row_limit": limit + 1,
            }
            if record_type == "ORDERS":
                filters = """
                    run_id = :run_id
                    AND (:track_id IS NULL OR track_id = :track_id)
                    AND (
                        :order_scope = 'ALL'
                        OR (
                            :order_scope = 'ACTIVE'
                            AND json_extract(order_json, '$.status')
                                IN ('OPEN', 'PARTIALLY_FILLED')
                        )
                        OR (
                            :order_scope = 'HISTORY'
                            AND json_extract(order_json, '$.status')
                                NOT IN ('OPEN', 'PARTIALLY_FILLED')
                        )
                    )
                """
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM replay_training_contract_order WHERE {filters}",
                        params,
                    ).fetchone()[0]
                )
                rows = tuple(
                    connection.execute(
                        f"""
                        SELECT *, updated_at_ms AS sort_value,
                               track_id AS sort_track_id, order_id AS record_id
                        FROM replay_training_contract_order
                        WHERE {filters}
                          AND (
                              :cursor_value IS NULL
                              OR updated_at_ms < :cursor_value
                              OR (
                                  updated_at_ms = :cursor_value
                                  AND (
                                      track_id < :cursor_track
                                      OR (
                                          track_id = :cursor_track
                                          AND order_id < :cursor_record
                                      )
                                  )
                              )
                          )
                        ORDER BY updated_at_ms DESC, track_id DESC, order_id DESC
                        LIMIT :row_limit
                        """,
                        params,
                    ).fetchall()
                )
                return rows, total
            if record_type == "FILLS":
                filters = """
                    run_id = :run_id
                    AND (:track_id IS NULL OR track_id = :track_id)
                """
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM replay_training_contract_fill WHERE {filters}",
                        params,
                    ).fetchone()[0]
                )
                rows = tuple(
                    connection.execute(
                        f"""
                        SELECT *, created_at_ms AS sort_value,
                               track_id AS sort_track_id, fill_id AS record_id
                        FROM replay_training_contract_fill
                        WHERE {filters}
                          AND (
                              :cursor_value IS NULL
                              OR created_at_ms < :cursor_value
                              OR (
                                  created_at_ms = :cursor_value
                                  AND (
                                      track_id < :cursor_track
                                      OR (
                                          track_id = :cursor_track
                                          AND fill_id < :cursor_record
                                      )
                                  )
                              )
                          )
                        ORDER BY created_at_ms DESC, track_id DESC, fill_id DESC
                        LIMIT :row_limit
                        """,
                        params,
                    ).fetchall()
                )
                return rows, total
            filters = """
                run_id = :run_id
                AND (:track_id IS NULL OR track_id = :track_id)
            """
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM replay_training_contract_ledger WHERE {filters}",
                    params,
                ).fetchone()[0]
            )
            rows = tuple(
                connection.execute(
                    f"""
                    SELECT *, ledger_sequence AS sort_value,
                           COALESCE(track_id, '') AS sort_track_id,
                           posting_id AS record_id
                    FROM replay_training_contract_ledger
                    WHERE {filters}
                      AND (
                          :cursor_value IS NULL
                          OR ledger_sequence < :cursor_value
                          OR (
                              ledger_sequence = :cursor_value
                              AND posting_id < :cursor_record
                          )
                      )
                    ORDER BY ledger_sequence DESC, posting_id DESC
                    LIMIT :row_limit
                    """,
                    params,
                ).fetchall()
            )
            return rows, total

        rows, total_count = await self.base_store.run_extension_read(read)
        visible = rows[:limit]
        items: list[dict[str, object]] = []
        for row in visible:
            if record_type == "ORDERS":
                items.append(
                    {
                        **json.loads(str(row["order_json"])),
                        "track_id": str(row["track_id"]),
                        "rule_revision": int(row["rule_revision"]),
                        "updated_at_ms": int(row["updated_at_ms"]),
                    }
                )
            elif record_type == "FILLS":
                items.append(
                    {
                        **json.loads(str(row["fill_json"])),
                        "track_id": str(row["track_id"]),
                        "configured_fee": str(row["configured_fee"]),
                        "fee_policy_revision": int(row["fee_policy_revision"]),
                        "fee_fidelity": str(row["fee_fidelity"]),
                    }
                )
            else:
                items.append(
                    {
                        "ledger_sequence": int(row["ledger_sequence"]),
                        "posting_id": str(row["posting_id"]),
                        "track_id": row["track_id"],
                        "kind": str(row["kind"]),
                        "cash_delta": str(row["cash_delta"]),
                        "asset": str(row["asset"]),
                        "virtual_time_ms": int(row["virtual_time_ms"]),
                        "source_sequence": int(row["source_sequence"]),
                        "fidelity": str(row["fidelity"]),
                        "rule_revision": int(row["rule_revision"]),
                        "reference_type": str(row["reference_type"]),
                        "reference_id": str(row["reference_id"]),
                        "metadata": json.loads(str(row["metadata_json"])),
                        "previous_hash": str(row["previous_hash"]),
                        "entry_hash": str(row["entry_hash"]),
                    }
                )
        next_cursor = None
        if len(rows) > limit and visible:
            last = visible[-1]
            next_cursor = run_records_ops._encode_account_record_cursor(
                record_type=record_type,
                order_scope=order_scope,
                track_id=track_id,
                sort_value=int(last["sort_value"]),
                sort_track_id=str(last["sort_track_id"]),
                record_id=str(last["record_id"]),
            )
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "schema_version": "replay.training.account-record-page.v1",
            "run_id": run_id,
            "record_type": record_type,
            "order_scope": order_scope,
            "track_id": track_id,
            "items": items,
            "total_count": total_count,
            "next_cursor": next_cursor,
        }

    async def training_results(self, run_id: str, *, limit: int) -> dict[str, object]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 2_000
        ):
            raise TrainingRunError(
                "TRAINING_RESULTS_INVALID",
                "training-results limit must be between 1 and 2000",
                status_code=422,
            )

        def read(
            connection: sqlite3.Connection,
        ) -> tuple[
            sqlite3.Row,
            tuple[sqlite3.Row, ...],
            tuple[sqlite3.Row, ...],
            tuple[sqlite3.Row, ...],
        ]:
            run = connection.execute(
                """
                SELECT r.run_id, r.time_disclosure_policy,
                       COALESCE(i.revealed, 0) AS revealed
                FROM replay_training_run AS r
                LEFT JOIN replay_training_integrity AS i USING(run_id)
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
            rows = tuple(
                connection.execute(
                    """
                    SELECT result.*, track.symbol, track.settlement_asset,
                           track.adapter_session_id,
                           (
                               SELECT event.event_id
                               FROM replay_review_timeline_event AS event
                               WHERE event.run_id = result.run_id
                                 AND event.track_id = result.track_id
                                 AND event.source_sequence = result.exit_source_sequence
                                 AND event.category = 'FILL'
                               ORDER BY event.timeline_sequence DESC LIMIT 1
                           ) AS review_event_id
                    FROM replay_training_trade_result AS result
                    JOIN replay_training_market_track AS track
                      ON track.run_id = result.run_id
                     AND track.track_id = result.track_id
                    WHERE result.run_id = ?
                    ORDER BY result.exit_time_ms DESC, result.track_id, result.trade_id
                    LIMIT ?
                    """,
                    (run_id, limit),
                ).fetchall()
            )
            plans = tuple(
                connection.execute(
                    """
                    SELECT * FROM replay_training_trade_plan
                    WHERE run_id = ? ORDER BY plan_sequence
                    """,
                    (run_id,),
                ).fetchall()
            )
            metrics = tuple(
                connection.execute(
                    """
                    SELECT gross_realized_pnl, mae, mfe, r_multiple,
                           holding_duration_ms, initial_risk_amount
                    FROM replay_training_trade_result WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchall()
            )
            return run, rows, plans, metrics

        run, rows, plan_rows, metric_rows = await self.base_store.run_extension_read(
            read
        )
        previous_plan_hash = "sha256:" + ("0" * 64)
        for expected_sequence, plan_row in enumerate(plan_rows, start=1):
            try:
                persisted_plan = json.loads(str(plan_row["plan_json"]))
            except json.JSONDecodeError as exc:
                raise TrainingRunError(
                    "TRAINING_RESULTS_INTEGRITY_FAILED",
                    "trade-plan log contains invalid canonical JSON",
                    status_code=503,
                ) from exc
            if not isinstance(persisted_plan, dict):
                raise TrainingRunError(
                    "TRAINING_RESULTS_INTEGRITY_FAILED",
                    "trade-plan log entry is invalid",
                    status_code=503,
                )
            logged_hash = persisted_plan.pop("plan_hash", None)
            plan_snapshot = {
                "schema_version": "replay.trade-plan.snapshot.v1",
                "track_id": str(plan_row["track_id"]),
                "client_order_id": str(plan_row["client_order_id"]),
                "side": str(plan_row["side"]),
                "order_type": str(plan_row["order_type"]),
                "sizing_mode": str(plan_row["sizing_mode"]),
                "risk_amount": str(plan_row["risk_amount"]),
                "risk_percent": plan_row["risk_percent"],
                "account_equity": str(plan_row["account_equity"]),
                "entry_price": str(plan_row["entry_price"]),
                "invalidation_price": str(plan_row["invalidation_price"]),
                "target_price": str(plan_row["target_price"]),
                "risk_per_unit": str(plan_row["risk_per_unit"]),
                "reward_risk_ratio": str(plan_row["reward_risk_ratio"]),
                "quantity": str(plan_row["quantity"]),
                "reason": str(plan_row["reason"]),
            }
            expected_material = {
                "schema_version": "replay.trade-plan.log.v1",
                "run_id": run_id,
                "plan_sequence": expected_sequence,
                "plan_id": str(plan_row["plan_id"]),
                "command_id": str(plan_row["command_id"]),
                "track_id": str(plan_row["track_id"]),
                "order_id": str(plan_row["order_id"]),
                "virtual_time_ms": int(plan_row["virtual_time_ms"]),
                "source_sequence": int(plan_row["source_sequence"]),
                "state_hash": str(plan_row["state_hash"]),
                "plan": plan_snapshot,
                "previous_plan_hash": previous_plan_hash,
            }
            expected_hash = canonical_sha256(expected_material)
            if (
                int(plan_row["plan_sequence"]) != expected_sequence
                or str(plan_row["previous_plan_hash"]) != previous_plan_hash
                or persisted_plan != expected_material
                or logged_hash != expected_hash
                or str(plan_row["plan_hash"]) != expected_hash
            ):
                raise TrainingRunError(
                    "TRAINING_RESULTS_INTEGRITY_FAILED",
                    "trade-plan log hash chain verification failed",
                    status_code=503,
                    details={"plan_sequence": expected_sequence},
                )
            previous_plan_hash = expected_hash
        timeline_values = tuple(
            sorted(
                {
                    int(row[field_name])
                    for row in rows
                    for field_name in ("entry_time_ms", "exit_time_ms")
                }
            )
        )
        if timeline_values:
            public_projection = await self.public_times(
                run_id,
                timeline_ms=timeline_values,
                max_items=4_000,
            )
            public_time_index = {
                int(item["input_timeline_ms"]): item["public_time"]
                for item in public_projection["items"]
                if isinstance(item, Mapping)
            }
        else:
            public_time_index = {}
        plan_index = {str(row["plan_id"]): row for row in plan_rows}
        items: list[dict[str, object]] = []
        pnls = [Decimal(str(row["gross_realized_pnl"])) for row in metric_rows]
        maes = [Decimal(str(row["mae"])) for row in metric_rows]
        mfes = [Decimal(str(row["mfe"])) for row in metric_rows]
        r_values = [
            Decimal(str(row["r_multiple"]))
            for row in metric_rows
            if row["r_multiple"] is not None
        ]
        holding_values = [int(row["holding_duration_ms"]) for row in metric_rows]
        for row in rows:
            plan_ids = json.loads(str(row["plan_ids_json"]))
            if not isinstance(plan_ids, list) or any(
                not isinstance(plan_id, str) for plan_id in plan_ids
            ):
                raise TypeError("training result plan_ids are invalid")
            plans: list[dict[str, object]] = []
            for plan_id in plan_ids:
                plan = plan_index.get(plan_id)
                if plan is None:
                    raise TypeError("training result references a missing trade plan")
                plans.append(
                    {
                        "plan_id": plan_id,
                        "plan_hash": str(plan["plan_hash"]),
                        "sizing_mode": str(plan["sizing_mode"]),
                        "risk_amount": str(plan["risk_amount"]),
                        "risk_percent": plan["risk_percent"],
                        "entry_price": str(plan["entry_price"]),
                        "invalidation_price": str(plan["invalidation_price"]),
                        "target_price": str(plan["target_price"]),
                        "reward_risk_ratio": str(plan["reward_risk_ratio"]),
                        "quantity": str(plan["quantity"]),
                        "reason": str(plan["reason"]),
                    }
                )
            entry_public_time = public_time_index[int(row["entry_time_ms"])]
            exit_public_time = public_time_index[int(row["exit_time_ms"])]
            items.append(
                {
                    "trade_id": str(row["trade_id"]),
                    "episode_id": str(row["episode_id"]),
                    "track_id": str(row["track_id"]),
                    "symbol": str(row["symbol"]),
                    "settlement_asset": str(row["settlement_asset"]),
                    "fill_id": str(row["fill_id"]),
                    "position_side": str(row["position_side"]),
                    "quantity": str(row["quantity"]),
                    "entry_price": str(row["entry_price"]),
                    "exit_price": str(row["exit_price"]),
                    "gross_realized_pnl": str(row["gross_realized_pnl"]),
                    "mae": str(row["mae"]),
                    "mfe": str(row["mfe"]),
                    "initial_risk_amount": row["initial_risk_amount"],
                    "r_multiple": row["r_multiple"],
                    "holding_duration_ms": int(row["holding_duration_ms"]),
                    "entry_source_sequence": int(row["entry_source_sequence"]),
                    "exit_source_sequence": int(row["exit_source_sequence"]),
                    "entry_public_time": entry_public_time,
                    "exit_public_time": exit_public_time,
                    "plans": plans,
                    "review_event_id": row["review_event_id"],
                    "excursion_fidelity": str(row["excursion_fidelity"]),
                    "pnl_basis": str(row["pnl_basis"]),
                }
            )

        winners = [value for value in pnls if value > 0]
        losers = [value for value in pnls if value < 0]
        count = len(pnls)
        average_win = (
            Decimal(0) if not winners else sum(winners, Decimal(0)) / len(winners)
        )
        average_loss = (
            Decimal(0) if not losers else sum(losers, Decimal(0)) / len(losers)
        )
        payoff_ratio = (
            None
            if average_win <= 0 or average_loss >= 0
            else average_win / abs(average_loss)
        )
        return {
            "protocol": REPLAY_V2_PROTOCOL,
            "schema_version": "replay.training-results.v1",
            "run_id": run_id,
            "summary": {
                "trade_count": count,
                "win_count": len(winners),
                "loss_count": len(losers),
                "win_rate": decimal_to_string(
                    Decimal(0) if count == 0 else Decimal(len(winners)) / count,
                    field_name="training win rate",
                ),
                "gross_realized_pnl": decimal_to_string(
                    sum(pnls, Decimal(0)),
                    field_name="training gross realized pnl",
                ),
                "average_win": decimal_to_string(average_win, field_name="average win"),
                "average_loss": decimal_to_string(
                    average_loss,
                    field_name="average loss",
                ),
                "payoff_ratio": (
                    None
                    if payoff_ratio is None
                    else decimal_to_string(payoff_ratio, field_name="payoff ratio")
                ),
                "average_mae": decimal_to_string(
                    Decimal(0) if not maes else sum(maes, Decimal(0)) / len(maes),
                    field_name="average mae",
                ),
                "average_mfe": decimal_to_string(
                    Decimal(0) if not mfes else sum(mfes, Decimal(0)) / len(mfes),
                    field_name="average mfe",
                ),
                "average_r_multiple": (
                    None
                    if not r_values
                    else decimal_to_string(
                        sum(r_values, Decimal(0)) / len(r_values),
                        field_name="average r multiple",
                    )
                ),
                "average_holding_duration_ms": (
                    0
                    if not holding_values
                    else sum(holding_values) // len(holding_values)
                ),
                "planned_trade_count": sum(
                    1 for row in metric_rows if row["initial_risk_amount"] is not None
                ),
            },
            "items": items,
            "returned_count": len(items),
            "truncated": len(items) < len(metric_rows),
        }

    async def deletion_target(self, run_id: str) -> tuple[str, tuple[str, ...]]:
        """Return the archive kind and replay sessions that a delete would remove."""

        def read(connection: sqlite3.Connection) -> tuple[str, tuple[str, ...]]:
            run = connection.execute(
                "SELECT adapter_session_id FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            child = connection.execute(
                """
                SELECT child_run_id FROM replay_run_lineage
                WHERE parent_run_id = ?
                UNION ALL
                SELECT child_run_id FROM replay_review_fork_lineage
                WHERE parent_run_id = ?
                LIMIT 1
                """,
                (run_id, run_id),
            ).fetchone()
            if child is not None:
                raise TrainingRunError(
                    "TRAINING_RUN_HAS_CHILDREN",
                    "delete child archives before deleting this training run",
                    status_code=409,
                    details={"child_run_id": str(child["child_run_id"])},
                )
            sessions = connection.execute(
                """
                SELECT adapter_session_id
                FROM replay_training_market_track
                WHERE run_id = ? AND adapter_session_id IS NOT NULL
                UNION
                SELECT adapter_session_id
                FROM replay_training_run
                WHERE run_id = ? AND adapter_session_id IS NOT NULL
                """,
                (run_id, run_id),
            ).fetchall()
            return "V2", tuple(sorted(str(row[0]) for row in sessions))

        return await self.base_store.run_extension_read(read)

    async def delete_run(
        self,
        run_id: str,
        *,
        expected_session_ids: Sequence[str],
    ) -> tuple[str, ...]:
        """Delete one Hub archive and its replay sessions in one SQLite transaction."""

        expected = tuple(sorted(dict.fromkeys(expected_session_ids)))

        def write(connection: sqlite3.Connection) -> tuple[str, ...]:
            run = connection.execute(
                "SELECT adapter_session_id FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is not None:
                child = connection.execute(
                    """
                    SELECT child_run_id FROM replay_run_lineage
                    WHERE parent_run_id = ?
                    UNION ALL
                    SELECT child_run_id FROM replay_review_fork_lineage
                    WHERE parent_run_id = ?
                    LIMIT 1
                    """,
                    (run_id, run_id),
                ).fetchone()
                if child is not None:
                    raise TrainingRunError(
                        "TRAINING_RUN_HAS_CHILDREN",
                        "delete child archives before deleting this training run",
                        status_code=409,
                        details={"child_run_id": str(child["child_run_id"])},
                    )
                sessions = connection.execute(
                    """
                    SELECT adapter_session_id
                    FROM replay_training_market_track
                    WHERE run_id = ? AND adapter_session_id IS NOT NULL
                    UNION
                    SELECT adapter_session_id
                    FROM replay_training_run
                    WHERE run_id = ? AND adapter_session_id IS NOT NULL
                    """,
                    (run_id, run_id),
                ).fetchall()
                session_ids = tuple(sorted(str(row[0]) for row in sessions))
                if session_ids != expected:
                    raise TrainingRunError(
                        "TRAINING_RUN_CHANGED",
                        "training run sessions changed while deletion was being prepared",
                        status_code=409,
                        details={
                            "expected_session_ids": expected,
                            "actual_session_ids": session_ids,
                        },
                    )
                # Funding receipts reference position legs without an ON DELETE
                # cascade. Remove owned receipts before deleting those legs.
                connection.execute(
                    "DELETE FROM replay_training_hedge_funding_settlement WHERE run_id=?",
                    (run_id,),
                )
                deleted = connection.execute(
                    "DELETE FROM replay_training_run WHERE run_id = ?",
                    (run_id,),
                )
                if deleted.rowcount != 1:
                    raise TrainingRunError(
                        "TRAINING_RUN_NOT_FOUND",
                        "training run does not exist",
                        status_code=404,
                    )
                for session_id in session_ids:
                    session_deleted = connection.execute(
                        "DELETE FROM replay_session WHERE session_id = ?",
                        (session_id,),
                    )
                    if session_deleted.rowcount != 1:
                        raise TrainingRunError(
                            "TRAINING_RUN_STORAGE_DEGRADED",
                            "training adapter session is missing during archive deletion",
                            status_code=503,
                            details={"session_id": session_id},
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
                return session_ids

            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )

        deleted_sessions = await self.base_store.run_extension_write(
            write,
            allow_degraded=True,
        )
        await self.base_store.collect_dataset_objects()
        return deleted_sessions

    async def run_id_for_session(self, session_id: str) -> str:
        def read(connection: sqlite3.Connection) -> str | None:
            row = connection.execute(
                """
                SELECT run_id FROM replay_training_market_track
                WHERE adapter_session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT run_id FROM replay_training_run WHERE adapter_session_id = ?",
                    (session_id,),
                ).fetchone()
            return str(row["run_id"]) if row is not None else None

        run_id = await self.base_store.run_extension_read(read)
        if run_id is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training adapter session does not exist",
                status_code=404,
            )
        return run_id

    async def run_binding(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT r.run_id, selected.adapter_session_id, r.source_kind,
                       r.book_mode, r.position_mode,
                       r.account_data_mode AS run_account_data_mode,
                       r.hedge_public_history_ref_json,
                       r.simulation_manifest_ref_json,
                       r.simulation_contract_hash,
                       r.simulation_model_version,
                       r.account_fidelity, r.insurance_adl_fidelity,
                       r.base_interval, r.display_interval, r.compatibility,
                       r.exchange, r.market_type, r.settlement_asset,
                       r.catalog_epoch, r.dataset_epoch, r.initial_equity,
                       selected.track_id AS selected_track_id,
                       selected.stable_ordinal AS selected_track_ordinal,
                       s.config_json,
                       r.integrity_mode, r.time_disclosure_policy,
                        r.allow_rule_changes, r.active_rule_revision,
                        account.account_model, account.margin_mode,
                        account.funding_mode, account.status AS account_status,
                       history.account_data_mode,
                       history.status AS account_history_status,
                       history.archive_proof_hash,
                       i.allowed_mutations_json, i.revealed,
                       i.strict_eligible, i.start_time_known, i.result_label,
                       dataset.actual_replay_start_ms,
                       dataset.actual_replay_end_ms,
                       dataset.synthetic_origin_ms
                FROM replay_training_run AS r
                JOIN replay_training_viewer_state AS viewer USING(run_id)
                JOIN replay_training_market_track AS selected
                  ON selected.run_id = r.run_id
                 AND selected.track_id = viewer.selected_track_id
                 AND selected.adapter_session_id IS NOT NULL
                JOIN replay_session AS s ON s.session_id = r.adapter_session_id
                JOIN replay_dataset_ref AS dataset
                  ON dataset.session_id = r.adapter_session_id
                JOIN replay_training_integrity AS i USING(run_id)
                JOIN replay_training_contract_account AS account USING(run_id)
                JOIN replay_training_account_history AS history USING(run_id)
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        adapter_config = json.loads(str(row["config_json"]))
        return {
            "run_id": str(row["run_id"]),
            "adapter_session_id": str(row["adapter_session_id"]),
            "source_kind": str(row["source_kind"]),
            "book_mode": str(row["book_mode"]),
            "base_interval": str(row["base_interval"]),
            "display_interval": str(row["display_interval"]),
            "compatibility": str(row["compatibility"]),
            "adapter_config": adapter_config,
            "position_mode": str(row["position_mode"]),
            "exchange": str(row["exchange"]),
            "market_type": str(row["market_type"]),
            "settlement_asset": str(row["settlement_asset"]),
            "catalog_epoch": str(row["catalog_epoch"]),
            "dataset_epoch": str(row["dataset_epoch"]),
            "initial_equity": str(row["initial_equity"]),
            "selected_track_id": str(row["selected_track_id"]),
            "selected_track_ordinal": int(row["selected_track_ordinal"]),
            "actual_replay_start_ms": int(row["actual_replay_start_ms"]),
            "actual_replay_end_ms": int(row["actual_replay_end_ms"]),
            "synthetic_origin_ms": row["synthetic_origin_ms"],
            "integrity_mode": str(row["integrity_mode"]),
            "time_disclosure_policy": str(row["time_disclosure_policy"]),
            "allow_rule_changes": bool(row["allow_rule_changes"]),
            "allowed_mutations": tuple(json.loads(str(row["allowed_mutations_json"]))),
            "revealed": bool(row["revealed"]),
            "strict_eligible": bool(row["strict_eligible"]),
            "start_time_known": bool(row["start_time_known"]),
            "result_label": str(row["result_label"]),
            "active_rule_revision": int(row["active_rule_revision"]),
            "account_model": str(row["account_model"]),
            "margin_mode": str(row["margin_mode"]),
            "funding_mode": str(row["funding_mode"]),
            "account_status": str(row["account_status"]),
            "account_data_mode": str(row["run_account_data_mode"]),
            "account_history_status": str(row["account_history_status"]),
            "account_archive_proof_hash": row["archive_proof_hash"],
            "hedge_public_history_ref": (
                None
                if row["hedge_public_history_ref_json"] is None
                else json.loads(str(row["hedge_public_history_ref_json"]))
            ),
            "simulation_manifest_ref": (
                None
                if row["simulation_manifest_ref_json"] is None
                else json.loads(str(row["simulation_manifest_ref_json"]))
            ),
            "simulation_contract_hash": row["simulation_contract_hash"],
            "simulation_model_version": row["simulation_model_version"],
            "account_fidelity": row["account_fidelity"],
            "insurance_adl_fidelity": row["insurance_adl_fidelity"],
        }

    async def integrity(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> dict[str, object] | None:
            row = connection.execute(
                """
                SELECT r.run_id, r.adapter_session_id, r.integrity_mode,
                       r.time_disclosure_policy, r.active_rule_revision,
                       r.virtual_time_ms, r.source_sequence,
                       i.strict_eligible, i.start_time_known, i.revealed,
                       i.allowed_mutations_json, i.result_label,
                       rule.rule_hash, rule.rule_json,
                       selection.schema_version AS selection_schema_version,
                       selection.start_mode AS selection_start_mode,
                       selection.seed_source AS selection_seed_source,
                       selection.random_seed AS selection_random_seed,
                       selection.actual_start_ms AS selection_actual_start_ms,
                       selection.actual_end_ms AS selection_actual_end_ms,
                       selection.dataset_epoch AS selection_dataset_epoch,
                       selection.parent_selection_hash,
                       selection.selection_hash
                FROM replay_training_run AS r
                JOIN replay_training_integrity AS i USING(run_id)
                JOIN replay_training_rule AS rule
                  ON rule.run_id = r.run_id
                 AND rule.revision = r.active_rule_revision
                JOIN replay_training_start_selection AS selection USING(run_id)
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            expected_selection_hash = start_selection_hash(
                run_id=str(row["run_id"]),
                start_mode=str(row["selection_start_mode"]),
                seed_source=str(row["selection_seed_source"]),
                random_seed=(
                    None
                    if row["selection_random_seed"] is None
                    else int(row["selection_random_seed"])
                ),
                actual_start_ms=int(row["selection_actual_start_ms"]),
                actual_end_ms=int(row["selection_actual_end_ms"]),
                dataset_epoch=str(row["selection_dataset_epoch"]),
                parent_selection_hash=(
                    None
                    if row["parent_selection_hash"] is None
                    else str(row["parent_selection_hash"])
                ),
            )
            if expected_selection_hash != str(row["selection_hash"]):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training start selection commitment failed validation",
                    status_code=503,
                )
            actions = connection.execute(
                """
                SELECT * FROM replay_run_action_event
                WHERE run_id = ? AND event_type != 'CREATE_RUN'
                ORDER BY action_sequence
                """,
                (run_id,),
            ).fetchall()
            public_time = public_time_ops.public_time(
                connection,
                session_id=str(row["adapter_session_id"]),
                policy=str(row["time_disclosure_policy"]),
                revealed=bool(row["revealed"]),
                public_time_ms=int(row["virtual_time_ms"]),
                sequence=int(row["source_sequence"]),
            )
            revealed = bool(row["revealed"])
            configured_policy = str(row["time_disclosure_policy"])
            active_rule = public_time_ops.redact_active_rule(
                json.loads(str(row["rule_json"])),
                hidden=configured_policy != "NONE" and not revealed,
            )
            start_public_time, end_public_time = (
                public_time_ops.selection_public_bounds(
                    connection,
                    session_id=str(row["adapter_session_id"]),
                    policy=configured_policy,
                    revealed=revealed,
                    actual_start_ms=int(row["selection_actual_start_ms"]),
                    actual_end_ms=int(row["selection_actual_end_ms"]),
                )
            )
            disclose_seed = row["selection_random_seed"] is not None and (
                configured_policy == "NONE" or revealed
            )
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": str(row["run_id"]),
                "integrity_mode": str(row["integrity_mode"]),
                "configured_time_disclosure_policy": str(row["time_disclosure_policy"]),
                "effective_time_disclosure_policy": (
                    "NONE"
                    if bool(row["revealed"])
                    else str(row["time_disclosure_policy"])
                ),
                "strict_eligible": bool(row["strict_eligible"]),
                "start_time_known": bool(row["start_time_known"]),
                "revealed": bool(row["revealed"]),
                "allowed_mutations": json.loads(str(row["allowed_mutations_json"])),
                "result_label": str(row["result_label"]),
                "active_rule_revision": int(row["active_rule_revision"]),
                "active_rule_hash": str(row["rule_hash"]),
                "active_rule": active_rule,
                "start_selection": {
                    "schema_version": str(row["selection_schema_version"]),
                    "start_mode": str(row["selection_start_mode"]),
                    "seed_source": str(row["selection_seed_source"]),
                    "seed_disclosed": disclose_seed,
                    "random_seed": (
                        int(row["selection_random_seed"]) if disclose_seed else None
                    ),
                    "dataset_epoch": str(row["selection_dataset_epoch"]),
                    "parent_selection_hash": row["parent_selection_hash"],
                    "selection_hash": str(row["selection_hash"]),
                    "public_start": start_public_time,
                    "public_end": end_public_time,
                },
                "public_time": public_time,
                "mutations": [
                    run_records_ops.action_from_row(action) for action in actions
                ],
            }

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training integrity record does not exist",
                status_code=404,
            )
        return result

    async def public_times(
        self,
        run_id: str,
        *,
        timeline_ms: tuple[int, ...],
        max_items: int,
    ) -> dict[str, object]:
        if (
            isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or not 1 <= max_items <= public_time_ops._PUBLIC_TIME_BATCH_LIMIT
        ):
            raise TypeError("max_items is outside the public-time storage bound")
        if not isinstance(timeline_ms, tuple) or not 1 <= len(timeline_ms) <= max_items:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                f"public time batch must contain between 1 and {max_items} values",
                status_code=422,
            )
        normalized: list[int] = []
        for index, value in enumerate(timeline_ms):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 253_402_300_799_999
            ):
                raise TrainingRunError(
                    "TRAINING_RUN_INVALID",
                    f"timeline_ms[{index}] is not a valid timestamp",
                    status_code=422,
                )
            normalized.append(value)

        def read(connection: sqlite3.Connection) -> dict[str, object] | None:
            row = connection.execute(
                """
                SELECT r.adapter_session_id, r.time_disclosure_policy,
                       r.base_interval, r.display_interval, r.virtual_time_ms,
                       i.revealed,
                       d.actual_replay_start_ms, d.actual_replay_end_ms,
                       d.synthetic_origin_ms,
                       policy.effective_warmup_bars,
                       policy.actual_visible_history_start_ms,
                       policy.interval_ms AS policy_interval_ms
                FROM replay_training_run AS r
                JOIN replay_training_integrity AS i USING(run_id)
                JOIN replay_dataset_ref AS d
                  ON d.session_id = r.adapter_session_id
                JOIN replay_training_data_policy AS policy USING(run_id)
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            policy = str(row["time_disclosure_policy"])
            revealed = bool(row["revealed"])
            actual_origin = int(row["actual_replay_start_ms"])
            public_origin = (
                actual_origin
                if policy == "NONE"
                else public_time_ops.required_synthetic_origin(
                    row["synthetic_origin_ms"]
                )
            )
            warmup = int(row["effective_warmup_bars"])
            interval_ms = parse_interval_ms(str(row["base_interval"]))
            display_interval_ms = parse_interval_ms(str(row["display_interval"]))
            if (
                warmup < 1
                or interval_ms is None
                or interval_ms != int(row["policy_interval_ms"])
                or display_interval_ms is None
                or display_interval_ms < interval_ms
            ):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training time bounds are invalid",
                    status_code=503,
                )
            execution_lower = (
                public_origin
                - warmup * interval_ms
                - (display_interval_ms - interval_ms)
            )
            history_lower = (
                public_origin
                + int(row["actual_visible_history_start_ms"])
                - actual_origin
            )
            # The execution warmup and lazy visible-history prefix have
            # independent frozen bounds; either may reach farther left.
            lower = min(execution_lower, history_lower)
            # Dataset refs pin BAR replay bounds by base-bar open time.  Public
            # chart timestamps also include the final bar's close time, so the
            # valid closed interval ends one base interval after the last open
            # (exclusive) rather than at the last open itself.
            initial_forward_upper = (
                public_origin
                + int(row["actual_replay_end_ms"])
                - actual_origin
                + interval_ms
                - 1
            )
            current_public_cursor = int(row["virtual_time_ms"])
            if current_public_cursor < 0 or current_public_cursor > 253_402_300_799_999:
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "training public cursor is invalid",
                    status_code=503,
                )
            # Paged BAR runs may continue beyond the eagerly persisted forward
            # cache.  The Run cursor is the server-authoritative, already-public
            # frontier, so extending to it admits revealed pages without exposing
            # the private terminal committed by the paging manifest.  Preserve
            # the initial cache allowance for fixed datasets and display-bucket
            # alignment established by the Phase 12 public-time contract.
            upper = max(initial_forward_upper, current_public_cursor)
            if lower < 0 or any(value < lower or value > upper for value in normalized):
                raise TrainingRunError(
                    "TRAINING_RUN_INVALID",
                    "public time request is outside the pinned training dataset",
                    status_code=422,
                )
            items = [
                {
                    "input_timeline_ms": value,
                    "public_time": public_time_ops.project_public_time(
                        actual_origin_ms=actual_origin,
                        public_origin_ms=public_origin,
                        policy=policy,
                        revealed=revealed,
                        public_time_ms=value,
                        sequence=index,
                    ),
                }
                for index, value in enumerate(normalized)
            ]
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": run_id,
                "policy": "NONE" if revealed else policy,
                "items": items,
            }

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        return result
