"""Explicit snapshot bridge from completed downloads to immutable BAR history.

Replay readers never depend on the live database. Only this write-side adapter
reads it, validates the sealed one-minute range, and publishes archive revisions.
"""
from __future__ import annotations

from importlib.util import find_spec
from threading import Lock
from typing import Any

from app.data_engine.manual_history.models import JobState, JobTargetState, TargetStatus
from app.data_engine.storage.klines_repo import query_klines
from .catalog import ReplaySeriesIdentity
from .history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch

MAX_IMPORT_ROWS = 250_000
_IMPORT_LOCK = Lock()


class ManualReplayImportError(ValueError):
    pass


def import_unavailable_reason(replay_service: Any) -> str | None:
    if replay_service is None:
        return "replay_disabled"
    if replay_service.settings.replay_history_origin_uri is not None:
        return "remote_archive_read_only"
    if find_spec("pyarrow") is None:
        return "parquet_dependency_missing"
    return None


def import_completed_download(repository: Any, replay_service: Any, job_id: str) -> dict[str, Any]:
    reason = import_unavailable_reason(replay_service)
    if reason:
        raise ManualReplayImportError(reason)
    # Keep concurrent requests from accumulating large live-DB snapshots in RAM.
    if not _IMPORT_LOCK.acquire(blocking=False):
        raise ManualReplayImportError("replay_import_busy")
    try:
        job = repository.get_job(job_id)
        if job.state != JobState.SUCCEEDED:
            raise ManualReplayImportError("download_not_succeeded")
        collection = repository.get_collection(job.collection_id)
        coverage = {
            (t.symbol, t.canonical_interval): t
            for t in repository.list_collection_targets(job.collection_id)
        }
        targets = [t for t in repository.list_job_targets(job_id) if t.canonical_interval == "1m"]
        if not targets:
            raise ManualReplayImportError("one_minute_download_required")
        prepared = []
        total_rows = 0
        # Validate every target before publishing any of them. A lost/released
        # inventory or a gap must never turn into an apparent successful import.
        for target in targets:
            covered = coverage.get((target.symbol, "1m"))
            if (target.state != JobTargetState.READY or covered is None
                    or covered.status != TargetStatus.READY or target.sealed_end_open_ms is None):
                raise ManualReplayImportError("download_coverage_unavailable")
            start = covered.effective_start_ms
            end = target.sealed_end_open_ms
            expected = (end - start) // 60_000 + 1
            if start % 60_000 or end % 60_000 or expected <= 0:
                raise ManualReplayImportError("invalid_sealed_range")
            total_rows += expected
            if total_rows > MAX_IMPORT_ROWS:
                raise ManualReplayImportError("replay_import_row_limit")
            rows = query_klines(target.symbol, "1m", start_ms=start, end_ms=end,
                                limit=expected + 1, order="ASC", exchange=collection.exchange,
                                market_type=collection.market_type)
            if (len(rows) != expected or any(
                int(row["open_time"]) != start + index * 60_000
                or int(row["close_time"]) != start + (index + 1) * 60_000 - 1
                for index, row in enumerate(rows)
            )):
                raise ManualReplayImportError("download_coverage_changed")
            prepared.append((target, start, end, rows))
        writer = ReplayHistoryArchiveWriter(replay_service.settings.replay_history_archive_dir)
        imported = []
        for target, start, end, rows in prepared:
            identity = ReplaySeriesIdentity(collection.exchange, collection.market_type, target.symbol)
            manifest = writer.import_batches(identity, "1m", [ReplayHistoryImportBatch(
                rows=rows,
                source_provider="local_manual_history_snapshot",
                source_object_key=job_id,
                source_period=f"{start}:{end}",
            )], listing_boundary_source="local_manual_history_snapshot")
            imported.append({**identity.to_dict(), "interval": "1m", "rows": len(rows),
                             "source_revision": manifest.catalog_epoch})
        return {"status": "ok", "job_id": job_id, "imported": imported, "rows": total_rows}
    finally:
        _IMPORT_LOCK.release()
