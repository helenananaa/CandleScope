from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.core.config import KLINES_DB_PATH
from app.data_engine.interval_policy import (
    compute_bucket_close_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.data_engine.kline_quality import repair_requires_trusted_finality
from app.data_engine.series_identity import (
    KlineSeriesIdentity,
    identity_from_metadata,
    resolve_kline_series_identity,
)


_DEFAULT_STALE_AFTER_MS = 15 * 60 * 1000
_MAX_FAILED_RETRY_MS = 24 * 60 * 60 * 1000
_MAX_REASON_PARTS = 8
_MAX_REASON_LENGTH = 256
_MAX_ERROR_LENGTH = 2_000


_LEGACY_TABLE = "kline_gap_ledger"
_SCOPED_TABLE = "kline_gap_ledger_scoped"
_ALL_ROWS = "kline_gap_ledger_all"
_RANGE_KEY = "exchange, market_type, symbol, interval, start_ms, end_ms"
_ROW_FIELDS = (
    _RANGE_KEY + ", expected_count, missing_count, status, priority, reason, repair_ticket, "
    "attempts, last_error, first_seen_at, last_seen_at, last_checked_at, resolved_at, "
    "next_retry_at, metadata_json"
)


def _partition(scope: str) -> tuple[str, str]:
    if scope:
        return _SCOPED_TABLE, "series_scope"
    return _LEGACY_TABLE, "gap_series_scope(exchange, metadata_json)"


def _row_table(row_id: int) -> str:
    # The combined read view negates scoped ids so old row ids keep their meaning.
    return _SCOPED_TABLE if row_id < 0 else _LEGACY_TABLE


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or KLINES_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.create_function("gap_series_scope", 2, _series_scope, deterministic=True)
    return conn


def _now_ms() -> int:
    return int(time.time() * 1000)


def _estimate_count(start_ms: int, end_ms: int, interval: str) -> int:
    interval_ms = parse_interval_ms(interval) or 60_000
    if end_ms < start_ms:
        return 0
    return int((end_ms - start_ms) // interval_ms) + 1


def _bounded_reason(value: Any) -> str:
    """Keep merged scheduler reasons stable, unique, and diagnostic-sized."""
    parts: list[str] = []
    for raw_part in str(value or "unknown").split("+"):
        part = raw_part.strip()
        if not part or part in parts:
            continue
        parts.append(part[:_MAX_REASON_LENGTH])
        if len(parts) >= _MAX_REASON_PARTS:
            break
    return "+".join(parts)[:_MAX_REASON_LENGTH] or "unknown"


def _bounded_error(value: Any | None) -> str | None:
    if value is None:
        return None
    return str(value)[:_MAX_ERROR_LENGTH]


def _metadata_object(value: Any) -> dict[str, Any]:
    """Decode ledger metadata without trusting legacy/corrupt JSON shapes."""
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _series_scope(exchange: str, metadata: Any) -> str:
    try:
        identity = identity_from_metadata(exchange, _metadata_object(metadata))
        return _identity_scope(exchange, identity)
    except (TypeError, ValueError):
        # Malformed legacy evidence cannot prove any current identity.
        return "invalid"


def _identity_scope(exchange: str, identity: KlineSeriesIdentity | None) -> str:
    resolved = resolve_kline_series_identity(exchange, identity)
    return "" if resolved.is_legacy_default_for(exchange) else json.dumps(resolved.storage_values)


def _request_scope(request: Any) -> str:
    return _identity_scope(request.exchange, identity_from_metadata(request.exchange, request.metadata))


def _request_range(request: Any) -> tuple[int, int]:
    """Resolve the durable parent range carried by scheduler chunks."""
    metadata = dict(getattr(request, "metadata", {}) or {})
    ledger_range = metadata.get("ledger_range")
    if isinstance(ledger_range, dict):
        try:
            start_ms = int(ledger_range["start_ms"])
            end_ms = int(ledger_range["end_ms"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if start_ms <= end_ms:
                return start_ms, end_ms
    return int(request.start_ms), int(request.end_ms)


class GapLedger:
    """Persistent ledger for detected and repaired K-line gaps."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path or KLINES_DB_PATH)
        self.init_storage()

    def init_storage(self) -> None:
        with _connect(self._db_path) as conn:
            # Keep the old writer's conflict target intact during rollback.
            # Schema creation and transfer share the same write transaction.
            conn.execute("BEGIN IMMEDIATE")
            for table, suffix in ((_LEGACY_TABLE, ""), (_SCOPED_TABLE, "_scoped")):
                scope_column = "series_scope TEXT NOT NULL," if suffix else ""
                scope_key = ", series_scope" if suffix else ""
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        {scope_column}
                        exchange TEXT NOT NULL,
                        market_type TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        interval TEXT NOT NULL,
                        start_ms INTEGER NOT NULL,
                        end_ms INTEGER NOT NULL,
                        expected_count INTEGER NOT NULL,
                        missing_count INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 100,
                        reason TEXT NOT NULL,
                        repair_ticket TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        first_seen_at INTEGER NOT NULL,
                        last_seen_at INTEGER NOT NULL,
                        last_checked_at INTEGER,
                        resolved_at INTEGER,
                        next_retry_at INTEGER,
                        metadata_json TEXT,
                        UNIQUE({_RANGE_KEY}{scope_key})
                    )
                """)
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_gap_ledger_status_priority{suffix}
                    ON {table}(status, priority, next_retry_at)
                """)
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_gap_ledger_series{suffix}
                    ON {table}(exchange, market_type, symbol, interval{scope_key}, start_ms, end_ms)
                """)
            conn.execute(f"""
                CREATE VIEW IF NOT EXISTS {_ALL_ROWS} AS
                SELECT id, {_ROW_FIELDS} FROM {_LEGACY_TABLE}
                UNION ALL
                SELECT -id, {_ROW_FIELDS} FROM {_SCOPED_TABLE}
            """)
            # Older revisions could persist an explicit identity in metadata.
            # Transfer those rows on every open, including after a rollback.
            assigned_fields = ", ".join(
                f"{name} = excluded.{name}"
                for name in _ROW_FIELDS.split(", ")[6:]
            )
            conn.execute(f"""
                INSERT INTO {_SCOPED_TABLE} ({_ROW_FIELDS}, series_scope)
                SELECT {_ROW_FIELDS}, gap_series_scope(exchange, metadata_json)
                FROM {_LEGACY_TABLE}
                WHERE gap_series_scope(exchange, metadata_json) NOT IN ('', 'invalid')
                ON CONFLICT({_RANGE_KEY}, series_scope) DO UPDATE SET {assigned_fields}
                WHERE max(excluded.last_seen_at, COALESCE(excluded.last_checked_at, 0)) >
                      max({_SCOPED_TABLE}.last_seen_at, COALESCE({_SCOPED_TABLE}.last_checked_at, 0))
            """)
            conn.execute(f"""
                DELETE FROM {_LEGACY_TABLE}
                WHERE gap_series_scope(exchange, metadata_json) NOT IN ('', 'invalid')
            """)

    def upsert_detected(self, request: Any, *, status: str = "queued") -> None:
        self.upsert_detected_many([request], status=status)

    def upsert_detected_many(
        self,
        requests: list[Any] | tuple[Any, ...],
        *,
        status: str = "queued",
    ) -> None:
        """Persist a scheduler batch in one SQLite transaction."""
        if not requests:
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for request in requests:
            start_ms, end_ms = _request_range(request)
            metadata = dict(request.metadata or {})
            scope = _request_scope(request)
            grouped.setdefault(scope, []).append({
                "exchange": request.exchange,
                "market_type": request.market_type,
                "symbol": request.symbol,
                "interval": request.interval,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "expected": _estimate_count(start_ms, end_ms, request.interval),
                "status": status,
                "priority": int(request.priority or metadata.get("priority", 100)),
                "reason": _bounded_reason(request.reason),
                "ticket": request.request_id,
                "now": _now_ms(),
                "metadata": json.dumps(metadata, sort_keys=True),
                "scope": scope,
            })

        with _connect(self._db_path) as conn:
            for scope, rows in grouped.items():
                table, scope_column = _partition(scope)
                extra_column, extra_value = (", series_scope", ", :scope") if scope else ("", "")
                # Widening an existing scheduler ticket retires its old range.
                conn.executemany(f"""
                    UPDATE {table}
                    SET status = 'superseded',
                        last_error = 'superseded_by_merged_request',
                        last_checked_at = :now,
                        resolved_at = :now,
                        next_retry_at = NULL
                    WHERE repair_ticket = :ticket
                      AND {scope_column} = :scope
                      AND NOT (
                        exchange = :exchange AND market_type = :market_type AND symbol = :symbol
                        AND interval = :interval AND start_ms = :start_ms AND end_ms = :end_ms
                      )
                      AND status IN (
                        'queued', 'repairing', 'verifying', 'partial', 'retry_wait', 'unavailable'
                      )
                """, rows)
                conn.executemany(f"""
                    INSERT INTO {table} (
                        {_RANGE_KEY}, expected_count, missing_count, status, priority,
                        reason, repair_ticket, attempts, first_seen_at, last_seen_at,
                        metadata_json{extra_column}
                    ) VALUES (
                        :exchange, :market_type, :symbol, :interval, :start_ms, :end_ms,
                        :expected, :expected, :status, :priority, :reason,
                        :ticket, 0, :now, :now, :metadata{extra_value}
                    )
                    ON CONFLICT({_RANGE_KEY}{extra_column}) DO UPDATE SET
                        expected_count = excluded.expected_count,
                        missing_count = excluded.missing_count,
                        status = excluded.status,
                        priority = excluded.priority,
                        reason = excluded.reason,
                        repair_ticket = excluded.repair_ticket,
                        attempts = 0,
                        last_error = NULL,
                        last_seen_at = excluded.last_seen_at,
                        last_checked_at = NULL,
                        resolved_at = NULL,
                        next_retry_at = NULL,
                        metadata_json = excluded.metadata_json
                """, rows)

    def mark_started(self, request: Any, *, attempt: int) -> None:
        self._update(
            request,
            require_repair_ticket=True,
            status="repairing",
            attempts=attempt,
            last_error=None,
            next_retry_at=None,
        )

    def mark_retry_wait(
        self,
        request: Any,
        *,
        attempt: int,
        error: str | None,
        next_retry_at: int,
    ) -> None:
        self._update(
            request,
            require_repair_ticket=True,
            status="retry_wait",
            attempts=attempt,
            last_error=_bounded_error(error),
            next_retry_at=next_retry_at,
        )

    def mark_verifying(self, request: Any) -> None:
        self._update(
            request,
            require_repair_ticket=True,
            status="verifying",
            last_checked_at=_now_ms(),
        )

    def mark_attempts(self, request: Any, *, attempts: int) -> None:
        self._update(
            request,
            require_repair_ticket=True,
            attempts=max(0, int(attempts)),
        )

    def mark_resolved(
        self,
        request: Any,
        *,
        status: str,
        missing_count: int | None = None,
        error: str | None = None,
    ) -> None:
        now = _now_ms()
        next_retry_at: int | None = None
        if status == "source_empty":
            next_retry_at = now + 86_400_000
        elif status == "partial":
            # Partial verification is actionable, but giving it a lease keeps
            # repeated chart polls from immediately restarting the same repair.
            # Ledger reconciliation will make it eligible again after the
            # normal stale window.
            next_retry_at = now + _DEFAULT_STALE_AFTER_MS
        elif status == "failed":
            metadata = dict(getattr(request, "metadata", {}) or {})
            try:
                recovery_count = max(
                    0,
                    int(metadata.get("ledger_recovery_count", 0) or 0),
                )
            except (TypeError, ValueError):
                recovery_count = 0
            retry_delay_ms = min(
                _MAX_FAILED_RETRY_MS,
                _DEFAULT_STALE_AFTER_MS * (2 ** min(recovery_count, 8)),
            )
            next_retry_at = now + retry_delay_ms
        values: dict[str, Any] = {
            "status": status,
            "last_error": _bounded_error(error),
            "last_checked_at": now,
            "resolved_at": now if status in {"filled", "source_empty", "failed"} else None,
            "next_retry_at": next_retry_at,
        }
        if status == "filled" and missing_count is None:
            missing_count = 0
        if missing_count is not None:
            values["missing_count"] = max(0, int(missing_count))
        self._update(request, **values)
        if status == "source_empty":
            self._supersede_contained_source_empty(request)

    def mark_deferred(
        self,
        request: Any,
        *,
        status: str,
        reason: str | None = None,
        next_retry_at: int | None = None,
    ) -> None:
        """Record a non-fetchable history decision without fabricating emptiness.

        ``not_expected`` is used for forming/market-closed windows and is a
        resolved informational state.  ``unavailable`` keeps an auditable open
        record with an optional retry deadline.  Neither state is equivalent to
        an exchange-confirmed ``source_empty`` range.
        """
        now = _now_ms()
        self._update(
            request,
            status=status,
            last_error=_bounded_error(reason),
            last_checked_at=now,
            resolved_at=now if status == "not_expected" else None,
            next_retry_at=next_retry_at,
        )

    def finalize_parent(
        self,
        request: Any,
        *,
        status: str,
        missing_count: int | None = None,
        error: str | None = None,
        attempts: int = 0,
        coverage_start_ms: int | None = None,
        coverage_end_ms: int | None = None,
        next_retry_at: int | None = None,
    ) -> bool:
        """Finalize only the ledger ticket still owned by this scheduler parent.

        A stronger successor can be queued while an ordinary predecessor is
        still draining.  The natural range key is shared, so terminal writes
        must compare ``repair_ticket`` and broad coverage must not close a
        different in-flight ticket or a stronger trusted-finality contract.
        """
        now = _now_ms()
        normalized_status = str(status or "partial")
        if normalized_status == "filled":
            missing_count = 0
        if next_retry_at is None:
            if normalized_status == "source_empty":
                next_retry_at = now + 86_400_000
            elif normalized_status == "partial":
                next_retry_at = now + _DEFAULT_STALE_AFTER_MS
            elif normalized_status == "failed":
                metadata = dict(getattr(request, "metadata", {}) or {})
                try:
                    recovery_count = max(
                        0,
                        int(metadata.get("ledger_recovery_count", 0) or 0),
                    )
                except (TypeError, ValueError):
                    recovery_count = 0
                next_retry_at = now + min(
                    _MAX_FAILED_RETRY_MS,
                    _DEFAULT_STALE_AFTER_MS * (2 ** min(recovery_count, 8)),
                )
        resolved_at = (
            now
            if normalized_status in {"filled", "source_empty", "failed"}
            else None
        )
        start_ms, end_ms = _request_range(request)
        current_requires_trusted = repair_requires_trusted_finality(
            getattr(request, "metadata", None),
            reason=getattr(request, "reason", None),
        )

        scope = _request_scope(request)
        table, scope_column = _partition(scope)
        with _connect(self._db_path) as conn:
            cursor = conn.execute(
                f"""
                UPDATE {table}
                SET status = ?,
                    missing_count = COALESCE(?, missing_count),
                    attempts = ?,
                    last_error = ?,
                    last_checked_at = ?,
                    resolved_at = ?,
                    next_retry_at = ?
                WHERE exchange = ?
                  AND market_type = ?
                  AND symbol = ?
                  AND interval = ?
                  AND {scope_column} = ?
                  AND start_ms = ?
                  AND end_ms = ?
                  AND repair_ticket IS ?
                """,
                (
                    normalized_status,
                    (
                        max(0, int(missing_count))
                        if missing_count is not None
                        else None
                    ),
                    max(0, int(attempts)),
                    _bounded_error(error),
                    now,
                    resolved_at,
                    next_retry_at,
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    scope,
                    start_ms,
                    end_ms,
                    request.request_id,
                ),
            )
            if int(cursor.rowcount or 0) <= 0:
                conn.commit()
                return False

            if (
                normalized_status == "filled"
                and coverage_start_ms is not None
                and coverage_end_ms is not None
            ):
                candidates = conn.execute(
                    f"""
                    SELECT id, status, reason, repair_ticket, metadata_json
                    FROM {table}
                    WHERE exchange = ?
                      AND market_type = ?
                      AND symbol = ?
                      AND interval = ?
                      AND {scope_column} = ?
                      AND start_ms >= ?
                      AND end_ms <= ?
                      AND status IN (
                        'source_empty', 'failed', 'unavailable', 'not_expected',
                        'queued', 'repairing', 'verifying', 'partial', 'retry_wait'
                      )
                    """,
                    (
                        request.exchange,
                        request.market_type,
                        request.symbol,
                        request.interval,
                        scope,
                        int(coverage_start_ms),
                        int(coverage_end_ms),
                    ),
                ).fetchall()
                victim_ids: list[int] = []
                for row in candidates:
                    other_ticket = row["repair_ticket"]
                    if (
                        row["status"] in {"queued", "repairing", "verifying"}
                        and other_ticket != request.request_id
                    ):
                        continue
                    if (
                        not current_requires_trusted
                        and repair_requires_trusted_finality(
                            _metadata_object(row["metadata_json"]),
                            reason=row["reason"],
                        )
                    ):
                        continue
                    victim_ids.append(int(row["id"]))
                if victim_ids:
                    placeholders = ", ".join("?" for _ in victim_ids)
                    conn.execute(
                        f"""
                        UPDATE {table}
                        SET status = 'filled',
                            missing_count = 0,
                            last_error = NULL,
                            last_checked_at = ?,
                            resolved_at = ?,
                            next_retry_at = NULL
                        WHERE id IN ({placeholders})
                        """,
                        (now, now, *victim_ids),
                    )
            conn.commit()

        if normalized_status == "source_empty":
            self._supersede_contained_source_empty(request)
        return True

    def mark_covered_resolved(
        self,
        request: Any,
        *,
        coverage_start_ms: int | None = None,
        coverage_end_ms: int | None = None,
        row_snapshot: dict[str, Any] | None = None,
    ) -> int:
        """Close legacy ledger entries fully covered by verified continuity.

        Backfill requests are frequently merged or clipped to closed-bar
        boundaries, so an older ``source_empty``/``failed`` row may not have
        exactly the same natural key as the successful repair.  Only rows
        fully contained in the verified range are closed; partially covered
        rows remain actionable.
        """
        now = _now_ms()
        if coverage_start_ms is None or coverage_end_ms is None:
            interval_ms = parse_interval_ms(request.interval)
            if interval_ms is None or interval_ms <= 0:
                return 0
            coverage_start_ms = compute_bucket_start_ms(
                int(request.start_ms),
                interval_ms,
                interval=request.interval,
            )
            last_open_ms = compute_bucket_start_ms(
                int(request.end_ms),
                interval_ms,
                interval=request.interval,
            )
            # Repair requests are keyed by bar *open*, whereas older ledger
            # rows sometimes recorded a full bar close/wall-clock edge.
            coverage_end_ms = compute_bucket_close_ms(
                last_open_ms,
                interval_ms,
                interval=request.interval,
            )
        coverage_start_ms = int(coverage_start_ms)
        coverage_end_ms = int(coverage_end_ms)
        if coverage_end_ms < coverage_start_ms:
            return 0
        scope = _request_scope(request)
        table, scope_column = _partition(scope)
        with _connect(self._db_path) as conn:
            if row_snapshot is not None:
                try:
                    row_id = int(row_snapshot["id"])
                    if _row_table(row_id) != table:
                        return 0
                    expected_status = str(row_snapshot["status"])
                    expected_last_seen_at = int(row_snapshot["last_seen_at"])
                except (KeyError, TypeError, ValueError):
                    return 0
                expected_metadata_json = row_snapshot.get("metadata_json")
                expected_repair_ticket = row_snapshot.get("repair_ticket")
                metadata = _metadata_object(expected_metadata_json)
                metadata.pop("reconciliation_checkpoint", None)
                cursor = conn.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'filled',
                        missing_count = 0,
                        last_error = NULL,
                        last_checked_at = ?,
                        resolved_at = ?,
                        next_retry_at = NULL,
                        metadata_json = ?
                    WHERE id = ?
                      AND exchange = ?
                      AND market_type = ?
                      AND symbol = ?
                      AND interval = ?
                      AND {scope_column} = ?
                      AND start_ms >= ?
                      AND end_ms <= ?
                      AND status = ?
                      AND last_seen_at = ?
                      AND metadata_json IS ?
                      AND repair_ticket IS ?
                    """,
                    (
                        now,
                        now,
                        json.dumps(metadata, sort_keys=True),
                        abs(row_id),
                        request.exchange,
                        request.market_type,
                        request.symbol,
                        request.interval,
                        scope,
                        coverage_start_ms,
                        coverage_end_ms,
                        expected_status,
                        expected_last_seen_at,
                        expected_metadata_json,
                        expected_repair_ticket,
                    ),
                )
            else:
                cursor = conn.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'filled',
                        missing_count = 0,
                        last_error = NULL,
                        last_checked_at = ?,
                        resolved_at = ?,
                        next_retry_at = NULL
                    WHERE exchange = ?
                      AND market_type = ?
                      AND symbol = ?
                      AND interval = ?
                      AND {scope_column} = ?
                      AND start_ms >= ?
                      AND end_ms <= ?
                      AND status IN (
                        'source_empty', 'failed', 'unavailable', 'not_expected',
                        'queued', 'repairing', 'verifying', 'partial', 'retry_wait'
                      )
                    """,
                    (
                        now,
                        now,
                        request.exchange,
                        request.market_type,
                        request.symbol,
                        request.interval,
                        scope,
                        coverage_start_ms,
                        coverage_end_ms,
                    ),
                )
            conn.commit()
        return int(cursor.rowcount or 0)

    def get_status(self, request: Any) -> dict[str, Any] | None:
        scope = _request_scope(request)
        table, scope_column = _partition(scope)
        with _connect(self._db_path) as conn:
            row = conn.execute(
                f"""
                SELECT
                    status,
                    reason,
                    attempts,
                    missing_count,
                    last_error,
                    last_seen_at,
                    last_checked_at,
                    resolved_at,
                    next_retry_at,
                    metadata_json
                FROM {table}
                WHERE exchange = ?
                  AND market_type = ?
                  AND symbol = ?
                  AND interval = ?
                  AND {scope_column} = ?
                  AND start_ms = ?
                  AND end_ms = ?
                """,
                (
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    scope,
                    int(request.start_ms),
                    int(request.end_ms),
                ),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_covering_status(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        now_ms: int | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> dict[str, Any] | None:
        """Return the most relevant unresolved row covering an exact gap.

        Scheduler parents are often wider than the individual gap rediscovered
        by a later audit.  Natural-key-only lookup lets that child bypass the
        parent's active lease or retry deadline, so covering state is the
        durable unit used for suppression decisions.
        """
        now = int(_now_ms() if now_ms is None else now_ms)
        fresh_after = now - _DEFAULT_STALE_AFTER_MS
        scope = _identity_scope(exchange, series_identity)
        table, scope_column = _partition(scope)
        row_id = "-id" if scope else "id"
        with _connect(self._db_path) as conn:
            row = conn.execute(
                f"""
                SELECT {row_id} AS id, {_ROW_FIELDS}
                FROM {table}
                WHERE exchange = ?
                  AND market_type = ?
                  AND symbol = ?
                  AND interval = ?
                  AND {scope_column} = ?
                  AND start_ms <= ?
                  AND end_ms >= ?
                  AND status NOT IN ('filled', 'superseded')
                ORDER BY
                  CASE
                    WHEN status IN (
                      'queued', 'repairing', 'verifying', 'partial', 'retry_wait'
                    ) AND (
                      (next_retry_at IS NOT NULL AND next_retry_at > ?)
                      OR COALESCE(last_checked_at, last_seen_at, first_seen_at) > ?
                    ) THEN 0
                    WHEN (
                      status = 'source_empty'
                      AND (next_retry_at IS NULL OR next_retry_at > ?)
                    ) OR (
                      status IN ('failed', 'unavailable')
                      AND next_retry_at IS NOT NULL
                      AND next_retry_at > ?
                    )
                    THEN 1
                    ELSE 2
                  END,
                  (end_ms - start_ms) ASC,
                  last_seen_at DESC,
                  id DESC
                LIMIT 1
                """,
                (
                    str(exchange or "binance").strip().lower(),
                    str(market_type or "spot").strip().lower(),
                    str(symbol or "").strip().upper(),
                    str(interval or "").strip(),
                    scope,
                    int(start_ms),
                    int(end_ms),
                    now,
                    fresh_after,
                    now,
                    now,
                ),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_suppressions(self, *, now_ms: int | None = None) -> list[dict[str, Any]]:
        """Return current terminal/cooldown rows for the submission cache."""
        now = int(_now_ms() if now_ms is None else now_ms)
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM {_ALL_ROWS}
                WHERE (
                    status = 'source_empty'
                    AND (next_retry_at IS NULL OR next_retry_at > ?)
                  )
                  OR (
                    status IN ('failed', 'unavailable')
                    AND next_retry_at IS NOT NULL
                    AND next_retry_at > ?
                  )
                ORDER BY exchange, market_type, symbol, interval,
                         start_ms ASC, end_ms ASC, id ASC
                """,
                (now, now),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_covering_suppression(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        now_ms: int | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> dict[str, Any] | None:
        """Read one exact/covering terminal submission suppression."""
        now = int(_now_ms() if now_ms is None else now_ms)
        scope = _identity_scope(exchange, series_identity)
        table, scope_column = _partition(scope)
        row_id = "-id" if scope else "id"
        with _connect(self._db_path) as conn:
            row = conn.execute(
                f"""
                SELECT {row_id} AS id, {_ROW_FIELDS}
                FROM {table}
                WHERE exchange = ?
                  AND market_type = ?
                  AND symbol = ?
                  AND interval = ?
                  AND {scope_column} = ?
                  AND start_ms <= ?
                  AND end_ms >= ?
                  AND (
                    (
                      status = 'source_empty'
                      AND (next_retry_at IS NULL OR next_retry_at > ?)
                    )
                    OR (
                      status IN ('failed', 'unavailable')
                      AND next_retry_at IS NOT NULL
                      AND next_retry_at > ?
                    )
                  )
                ORDER BY (end_ms - start_ms) ASC, last_seen_at DESC, id DESC
                LIMIT 1
                """,
                (
                    str(exchange or "binance").strip().lower(),
                    str(market_type or "spot").strip().lower(),
                    str(symbol or "").strip().upper(),
                    str(interval or "").strip(),
                    scope,
                    int(start_ms),
                    int(end_ms),
                    now,
                    now,
                ),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_open(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM {_ALL_ROWS}
                WHERE status NOT IN ('filled', 'source_empty', 'not_expected', 'superseded')
                ORDER BY priority ASC, first_seen_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_reconcilable(
        self,
        *,
        limit: int = 100,
        stale_before_ms: int | None = None,
        due_before_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return inactive outcomes plus active work whose lease is stale.

        A confirmed source-empty result is not active work, but later
        authoritative storage may make it stale.  Fresh queued/repairing rows
        are excluded so reconciliation cannot race the live scheduler.  The
        caller must still verify exact storage before mutating any row.
        """
        stale_before = int(
            stale_before_ms
            if stale_before_ms is not None
            else _now_ms() - _DEFAULT_STALE_AFTER_MS
        )
        due_before = int(due_before_ms if due_before_ms is not None else _now_ms())
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM {_ALL_ROWS}
                WHERE (
                     status IN ('source_empty', 'failed', 'unavailable', 'not_expected')
                     AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   )
                   OR (
                     status IN ('queued', 'repairing', 'verifying', 'partial')
                     AND COALESCE(last_checked_at, last_seen_at, first_seen_at) <= ?
                     AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   )
                   OR (
                     status = 'retry_wait'
                     AND COALESCE(last_checked_at, last_seen_at, first_seen_at) <= ?
                     AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   )
                ORDER BY
                  CASE
                    WHEN status IN ('queued', 'repairing', 'verifying', 'partial', 'retry_wait')
                    THEN 0
                    WHEN status IN ('failed', 'unavailable', 'not_expected')
                    THEN 1
                    ELSE 2
                  END,
                  COALESCE(last_checked_at, last_seen_at, first_seen_at) ASC,
                  id ASC
                LIMIT ?
                """,
                (
                    due_before,
                    stale_before,
                    due_before,
                    stale_before,
                    due_before,
                    limit,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_reconciled_checked(
        self,
        request: Any,
        *,
        next_retry_at: int | None = None,
    ) -> None:
        """Advance a verified-but-still-missing row through fair rechecks."""
        self._update(
            request,
            last_checked_at=_now_ms(),
            next_retry_at=next_retry_at,
        )

    def checkpoint_reconciliation_row(
        self,
        row_id: int,
        *,
        cursor_ms: int,
        scanned_bars: int,
        next_retry_at: int,
        error: str | None = None,
        row_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        """Persist exact-scan progress so a large range resumes next pass."""
        now = _now_ms()
        table = _row_table(row_id)
        with _connect(self._db_path) as conn:
            row = conn.execute(
                f"""
                SELECT status, last_seen_at, metadata_json, repair_ticket
                FROM {table}
                WHERE id = ?
                """,
                (abs(row_id),),
            ).fetchone()
            if row is None:
                return False
            if row_snapshot is not None and (
                str(row["status"]) != str(row_snapshot.get("status"))
                or int(row["last_seen_at"]) != int(
                    row_snapshot.get("last_seen_at", -1)
                )
                or row["metadata_json"] != row_snapshot.get("metadata_json")
                or row["repair_ticket"] != row_snapshot.get("repair_ticket")
            ):
                return False
            if str(row["status"]) not in {
                "source_empty",
                "failed",
                "unavailable",
                "not_expected",
                "queued",
                "repairing",
                "verifying",
                "partial",
                "retry_wait",
            }:
                return False
            original_metadata_json = row["metadata_json"]
            metadata = _metadata_object(row["metadata_json"])
            metadata["reconciliation_checkpoint"] = {
                "cursor_ms": int(cursor_ms),
                "scanned_bars": max(0, int(scanned_bars)),
                "updated_at": now,
            }
            cursor = conn.execute(
                f"""
                UPDATE {table}
                SET last_checked_at = ?,
                    next_retry_at = ?,
                    last_error = COALESCE(?, last_error),
                    metadata_json = ?
                WHERE id = ?
                  AND status = ?
                  AND last_seen_at = ?
                  AND metadata_json IS ?
                  AND repair_ticket IS ?
                """,
                (
                    now,
                    int(next_retry_at),
                    _bounded_error(error),
                    json.dumps(metadata, sort_keys=True),
                    abs(row_id),
                    str(row["status"]),
                    int(row["last_seen_at"]),
                    original_metadata_json,
                    row["repair_ticket"],
                ),
            )
            conn.commit()
        return bool(cursor.rowcount)

    def clear_reconciliation_checkpoint_row(
        self,
        row_id: int,
        *,
        row_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        """Drop a stale scan cursor after resolution or a confirmed gap."""
        table = _row_table(row_id)
        with _connect(self._db_path) as conn:
            row = conn.execute(
                f"""
                SELECT status, last_seen_at, metadata_json, repair_ticket
                FROM {table}
                WHERE id = ?
                """,
                (abs(row_id),),
            ).fetchone()
            if row is None:
                return False
            if row_snapshot is not None and (
                str(row["status"]) != str(row_snapshot.get("status"))
                or int(row["last_seen_at"]) != int(
                    row_snapshot.get("last_seen_at", -1)
                )
                or row["metadata_json"] != row_snapshot.get("metadata_json")
                or row["repair_ticket"] != row_snapshot.get("repair_ticket")
            ):
                return False
            original_metadata_json = row["metadata_json"]
            metadata = _metadata_object(row["metadata_json"])
            if metadata.pop("reconciliation_checkpoint", None) is None:
                return True
            cursor = conn.execute(
                f"""
                UPDATE {table}
                SET metadata_json = ?
                WHERE id = ?
                  AND status = ?
                  AND last_seen_at = ?
                  AND metadata_json IS ?
                  AND repair_ticket IS ?
                """,
                (
                    json.dumps(metadata, sort_keys=True),
                    abs(row_id),
                    str(row["status"]),
                    int(row["last_seen_at"]),
                    original_metadata_json,
                    row["repair_ticket"],
                ),
            )
            conn.commit()
        return bool(cursor.rowcount)

    def defer_reconciliation_row(
        self,
        row_id: int,
        *,
        next_retry_at: int,
        error: str | None = None,
        row_snapshot: dict[str, Any] | None = None,
        clear_checkpoint: bool = False,
    ) -> bool:
        """Defer a malformed/corrupt candidate that cannot form a request."""
        now = _now_ms()
        table = _row_table(row_id)
        with _connect(self._db_path) as conn:
            params: list[Any] = [
                now,
                int(next_retry_at),
                _bounded_error(error),
            ]
            metadata_assignment = ""
            if clear_checkpoint:
                expected_metadata_json = (
                    row_snapshot.get("metadata_json")
                    if row_snapshot is not None
                    else None
                )
                metadata = _metadata_object(expected_metadata_json)
                metadata.pop("reconciliation_checkpoint", None)
                metadata_assignment = ", metadata_json = ?"
                params.append(json.dumps(metadata, sort_keys=True))
            params.append(abs(row_id))
            guards = ""
            if row_snapshot is not None:
                try:
                    expected_last_seen_at = int(row_snapshot["last_seen_at"])
                except (KeyError, TypeError, ValueError):
                    return False
                guards = """
                  AND status = ?
                  AND last_seen_at = ?
                  AND metadata_json IS ?
                  AND repair_ticket IS ?
                """
                params.extend([
                    str(row_snapshot.get("status")),
                    expected_last_seen_at,
                    row_snapshot.get("metadata_json"),
                    row_snapshot.get("repair_ticket"),
                ])
            cursor = conn.execute(
                f"""
                UPDATE {table}
                SET last_checked_at = ?, next_retry_at = ?,
                    last_error = COALESCE(?, last_error)
                    {metadata_assignment}
                WHERE id = ?
                {guards}
                """,
                params,
            )
            conn.commit()
        return bool(cursor.rowcount)

    def health_summary(self, *, sample_limit: int = 50) -> dict[str, Any]:
        """Return exact open counts without materialising the full ledger."""
        now = _now_ms()
        with _connect(self._db_path) as conn:
            status_rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM {_ALL_ROWS}
                WHERE status NOT IN ('filled', 'source_empty', 'not_expected', 'superseded')
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
            age_row = conn.execute(
                f"""
                SELECT
                  SUM(CASE WHEN ? - first_seen_at < 300000 THEN 1 ELSE 0 END) AS lt_5m,
                  SUM(CASE WHEN ? - first_seen_at BETWEEN 300000 AND 3599999 THEN 1 ELSE 0 END) AS from_5m_to_1h,
                  SUM(CASE WHEN ? - first_seen_at BETWEEN 3600000 AND 86399999 THEN 1 ELSE 0 END) AS from_1h_to_1d,
                  SUM(CASE WHEN ? - first_seen_at >= 86400000 THEN 1 ELSE 0 END) AS gte_1d,
                  MIN(first_seen_at) AS oldest_open_at,
                  SUM(CASE WHEN last_checked_at IS NOT NULL AND ? - last_checked_at < 300000 THEN 1 ELSE 0 END) AS checked_lt_5m,
                  SUM(CASE WHEN last_checked_at IS NOT NULL AND ? - last_checked_at BETWEEN 300000 AND 3599999 THEN 1 ELSE 0 END) AS checked_5m_to_1h,
                  SUM(CASE WHEN last_checked_at IS NOT NULL AND ? - last_checked_at BETWEEN 3600000 AND 86399999 THEN 1 ELSE 0 END) AS checked_1h_to_1d,
                  SUM(CASE WHEN last_checked_at IS NOT NULL AND ? - last_checked_at >= 86400000 THEN 1 ELSE 0 END) AS checked_gte_1d
                FROM {_ALL_ROWS}
                WHERE status NOT IN ('filled', 'source_empty', 'not_expected', 'superseded')
                """,
                (now, now, now, now, now, now, now, now),
            ).fetchone()
            source_empty_count = int(conn.execute(
                f"SELECT COUNT(*) FROM {_ALL_ROWS} WHERE status = 'source_empty'"
            ).fetchone()[0])
        by_status = {str(row["status"]): int(row["count"]) for row in status_rows}
        ages = {
            key: int(age_row[key] or 0)
            for key in ("lt_5m", "from_5m_to_1h", "from_1h_to_1d", "gte_1d")
        }
        checked_ages = {
            "lt_5m": int(age_row["checked_lt_5m"] or 0),
            "from_5m_to_1h": int(age_row["checked_5m_to_1h"] or 0),
            "from_1h_to_1d": int(age_row["checked_1h_to_1d"] or 0),
            "gte_1d": int(age_row["checked_gte_1d"] or 0),
        }
        return {
            "open_total": sum(by_status.values()),
            "by_status": by_status,
            "age_buckets": ages,
            "last_checked_age_buckets": checked_ages,
            "oldest_open_at": age_row["oldest_open_at"],
            "source_empty_total": source_empty_count,
            "sample_limit": max(1, int(sample_limit)),
        }

    def _supersede_contained_source_empty(self, request: Any) -> int:
        """Bound drifting source-empty tails after the wider range is proven empty."""
        start_ms, end_ms = _request_range(request)
        now = _now_ms()
        reason = _bounded_reason(getattr(request, "reason", "unknown"))
        scope = _request_scope(request)
        table, scope_column = _partition(scope)
        with _connect(self._db_path) as conn:
            cursor = conn.execute(
                f"""
                UPDATE {table}
                SET status = 'superseded',
                    last_error = 'superseded_by_source_empty_range',
                    last_checked_at = ?,
                    resolved_at = ?,
                    next_retry_at = NULL
                WHERE exchange = ? AND market_type = ? AND symbol = ? AND interval = ?
                  AND {scope_column} = ?
                  AND reason = ? AND status = 'source_empty'
                  AND start_ms >= ? AND end_ms <= ?
                  AND NOT (start_ms = ? AND end_ms = ?)
                """,
                (
                    now,
                    now,
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    scope,
                    reason,
                    start_ms,
                    end_ms,
                    start_ms,
                    end_ms,
                ),
            )
            conn.commit()
        return int(cursor.rowcount or 0)

    def compact_source_empty_drift(self, *, limit: int = 10_000) -> int:
        """Safely retire legacy same-start source-empty range drift.

        A wider confirmed source-empty range subsumes an older/narrower row
        with the same series, reason, and start.  This does not infer any new
        market-data fact; it only removes redundant ledger cardinality.
        """
        now = _now_ms()
        changed = 0
        budget = max(1, int(limit))
        with _connect(self._db_path) as conn:
            for table, scope_column in ((_LEGACY_TABLE, "''"), (_SCOPED_TABLE, "series_scope")):
                conn.execute(
                    f"""
                    WITH ranked AS (
                      SELECT
                        id,
                        end_ms,
                        MAX(end_ms) OVER (
                          PARTITION BY exchange, market_type, symbol, interval,
                                       {scope_column}, reason, start_ms
                        ) AS widest_end
                      FROM {table}
                      WHERE status = 'source_empty'
                    ),
                    victims AS (
                      SELECT id
                      FROM ranked
                      WHERE end_ms < widest_end
                      ORDER BY id ASC
                      LIMIT ?
                    )
                    UPDATE {table}
                    SET status = 'superseded',
                        last_error = 'superseded_by_source_empty_range',
                        last_checked_at = ?,
                        resolved_at = ?,
                        next_retry_at = NULL
                    WHERE id IN (SELECT id FROM victims)
                    """,
                    (budget - changed, now, now),
                )
                changed += int(conn.execute("SELECT changes()").fetchone()[0])
                if changed >= budget:
                    break
        return changed

    def _update(
        self,
        request: Any,
        *,
        require_repair_ticket: bool = False,
        **values: Any,
    ) -> None:
        if not values:
            return
        assignments = []
        params: list[Any] = []
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        start_ms, end_ms = _request_range(request)
        scope = _request_scope(request)
        params.extend([
            request.exchange,
            request.market_type,
            request.symbol,
            request.interval,
            scope,
            start_ms,
            end_ms,
        ])
        ticket_clause = ""
        if require_repair_ticket:
            ticket_clause = " AND repair_ticket IS ?"
            params.append(request.request_id)
        table, scope_column = _partition(scope)
        with _connect(self._db_path) as conn:
            conn.execute(
                f"""
                UPDATE {table}
                SET {", ".join(assignments)}
                WHERE exchange = ?
                  AND market_type = ?
                  AND symbol = ?
                  AND interval = ?
                  AND {scope_column} = ?
                  AND start_ms = ?
                  AND end_ms = ?
                  {ticket_clause}
                """,
                params,
            )
            conn.commit()
