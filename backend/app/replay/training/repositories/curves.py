"""TrainingCurveRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3

from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..errors import TrainingRunError
from ..models import (
    REPLAY_V2_PROTOCOL,
)
from ..persistence import curve_records as curve_records_ops


class TrainingCurveRepository:
    """Own curves operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore) -> None:
        self.base_store = base_store

    async def equity(
        self,
        run_id: str,
        *,
        resolution: str,
        limit: int,
    ) -> dict[str, object]:
        if resolution not in {"AUTO", "EVENT", "1M", "15M", "1H"}:
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "equity resolution is unsupported",
                status_code=422,
            )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 5_000
        ):
            raise TrainingRunError(
                "TRAINING_RUN_INVALID",
                "equity limit must be between 1 and 5000",
                status_code=422,
            )

        def load(connection: sqlite3.Connection) -> dict[str, object] | None:
            run = connection.execute(
                "SELECT run_id FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                return None
            cached = {}
            for row in connection.execute(
                "SELECT resolution, bucket_id, source_sequence, revision "
                "FROM replay_equity_sample WHERE run_id=?",
                (run_id,),
            ):
                cached[(str(row[0]), int(row[1]))] = (int(row[2]), int(row[3]))
            window = sorted(
                (bucket for name, bucket in cached if name == resolution), reverse=True
            )
            cutoff = window[limit - 1] if len(window) >= limit else None
            pending = curve_records_ops.load_pending_interval_curves(
                connection, run_id=run_id, resolution=resolution, cutoff=cutoff
            )
            bases = {}
            selected = resolution
            if selected == "AUTO":
                selected = "1H"
                for candidate in ("EVENT", "1M", "15M", "1H"):
                    size = curve_records_ops.attach_needed_curve_bodies(
                        connection,
                        pending,
                        run_id=run_id,
                        cached=cached,
                        resolution=candidate,
                        limit=limit + 1,
                        bases=bases,
                    )
                    if size <= limit:
                        selected = candidate
                        break
            else:
                curve_records_ops.attach_needed_curve_bodies(
                    connection,
                    pending,
                    run_id=run_id,
                    cached=cached,
                    resolution=selected,
                    limit=limit,
                    bases=bases,
                )
            return {
                "pending": pending,
                "origins": curve_records_ops.interval_curve_origins(
                    connection, pending
                ),
                "cached": cached,
                "selected": selected,
                "bases": bases,
            }

        loaded = await self.base_store.run_extension_read(load)
        if loaded is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )

        def prepare():
            bases = loaded["bases"]
            selected = loaded.get("selected", resolution)
            rows, completed = curve_records_ops.expand_pending_interval_curves(
                loaded["pending"],
                loaded["origins"],
                run_id=run_id,
                resolution=selected,
                limit=limit,
                cached=loaded["cached"],
                bases=bases,
            )
            return selected, rows, completed

        selected, prepared_rows, materialized_ids = await self.base_store.run_worker(
            "equity_curve_prepare", prepare
        )

        def write(connection: sqlite3.Connection) -> dict[str, object] | None:
            run = connection.execute(
                "SELECT run_id FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                return None
            curve_records_ops.persist_interval_curve_samples(
                connection,
                run_id=run_id,
                rows=prepared_rows,
                materialized_ids=materialized_ids,
                resolution=selected,
            )
            rows = connection.execute(
                """
                SELECT * FROM replay_equity_sample
                WHERE run_id = ? AND resolution = ?
                ORDER BY bucket_id DESC LIMIT ?
                """,
                (run_id, selected, limit),
            ).fetchall()
            from ..tape_interval import sample_reference

            samples = [
                {
                    "source_sequence": int(row["source_sequence"]),
                    "revision": int(row["revision"]),
                    "public_time": json.loads(str(row["public_time_json"])),
                    "equity": str(row["equity"]),
                    "cash_balance": str(row["cash_balance"]),
                    "unrealized_pnl": str(row["unrealized_pnl"]),
                    "ledger_tail_hash": str(row["ledger_tail_hash"]),
                    **sample_reference(str(row["state_hash"])),
                }
                for row in reversed(rows)
            ]
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "run_id": run_id,
                "resolution": selected,
                "samples": samples,
                "bounded": True,
                "limits": {
                    item[0]: item[2] for item in curve_records_ops._EQUITY_RESOLUTIONS
                },
            }

        operation = (
            self.base_store.run_extension_write
            if prepared_rows or materialized_ids
            else self.base_store.run_extension_read
        )
        result = await operation(write)
        if result is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training run does not exist",
                status_code=404,
            )
        return result

    async def prepare_indexed_curve(self, run_id, index):
        value = index.valuation
        curve_id = canonical_sha256(
            {
                "run": run_id,
                "value": value["key"],
                "source": index.chains[-1]
                if getattr(index, "shared", False)
                else index.curve_market_key(),
                "start": index.start,
            }
        )

        def write(connection):
            if connection.execute(
                "SELECT 1 FROM replay_prepared_curve WHERE curve_id=?", (curve_id,)
            ).fetchone():
                return curve_id
            data = index.curve_basis()
            connection.execute(
                "INSERT INTO replay_prepared_curve VALUES (?, ?, ?)",
                (curve_id, run_id, canonical_json(data)),
            )
            return curve_id

        return await self.base_store.run_extension_write(write)
