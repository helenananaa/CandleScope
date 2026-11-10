"""Read-only retention preview for committed replay trade days."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from app.core.executors import run_archive
from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
from app.replay.storage.sqlite_store import ReplaySQLiteStore

_MAX_REFERENCES = 2_000
_MAX_REFERENCED_OBJECTS = 32_768


def _saved_partitions(connection: sqlite3.Connection) -> tuple[dict[str, int], bool]:
    # Every saved trade session counts, including stopped sessions whose
    # in-memory pin was released. The lightweight ref owns the object list.
    rows = connection.execute(
        """
        SELECT CASE WHEN length(ref.snapshot_ref_json) <= 2097152
                    THEN ref.snapshot_ref_json END AS snapshot_ref_json,
               ref.data_epoch
        FROM replay_dataset_ref AS ref
        JOIN replay_session AS session USING (session_id)
        WHERE CASE
            WHEN NOT json_valid(ref.snapshot_ref_json) OR NOT json_valid(session.config_json)
                THEN 1
            ELSE lower(json_extract(session.config_json, '$.source_kind')) = 'agg_trade'
                 OR lower(json_extract(ref.snapshot_ref_json, '$.source_kind')) = 'agg_trade'
                 OR json_type(ref.snapshot_ref_json, '$.trade_dataset_ref') IS NOT NULL
        END
        ORDER BY ref.session_id
        LIMIT ?
        """,
        (_MAX_REFERENCES + 1,),
    )
    counts: Counter[str] = Counter()
    complete = True
    objects_left = _MAX_REFERENCED_OBJECTS
    for index, row in enumerate(rows):
        if index == _MAX_REFERENCES:
            complete = False
            break
        try:
            envelope = json.loads(row["snapshot_ref_json"])
            reference = RawAggTradeDatasetRef.from_dict(envelope["trade_dataset_ref"])
            if reference.data_epoch != row["data_epoch"]:
                raise ValueError("saved trade dataset epoch differs from its reference")
        except (KeyError, OverflowError, TypeError, ValueError):
            complete = False
            continue
        if len(reference.objects) > objects_left:
            complete = False
            break
        objects_left -= len(reference.objects)
        counts.update({item.object_id.rsplit("/", 1)[0] for item in reference.objects})
    return dict(counts), complete


async def preview(
    store: ReplaySQLiteStore, archive: object, *, limit: int,
) -> dict[str, object]:
    inventory = getattr(archive, "verified_retention_inventory", None)
    result = {
        "protocol": "replay.raw-trade-retention.preview.v1",
        "policy_state": "UNMANAGED",
        "reference_scope": "CURRENT_REPLAY_STORE_AND_PROCESS",
        "estimated_reclaim_bytes": 0,
        "limit": limit,
    }
    if not callable(inventory):
        return {
            **result, "status": "UNAVAILABLE", "saved_reference_scan_complete": False,
            "observed_bytes": 0, "items": [], "unreadable_day_count": 0, "truncated": False,
        }
    # Sample active pins before reading saved references. A session that
    # publishes and releases its pin between these reads remains represented.
    report = await run_archive(inventory, limit=limit)
    saved, complete = await store.run_extension_read(_saved_partitions)
    for item in report["items"]:
        reference_count = saved.get(item.pop("partition_key"), 0)
        item["saved_reference_count"] = reference_count
        if reference_count:
            item["protection_reasons"].append("SAVED_REPLAY_REFERENCE")
        if not complete:
            item["protection_reasons"].append("SAVED_REFERENCE_SCAN_INCOMPLETE")
    return {
        **result,
        **report,
        "status": "PREVIEW",
        "saved_reference_scan_complete": complete,
        "observed_bytes": sum(item["byte_size"] for item in report["items"]),
    }
