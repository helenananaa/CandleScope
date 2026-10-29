"""Re-fetch missing evidence without claiming it is the original observation.

The old canonical row is durably backed up before network I/O. A caller-owned
pipeline delivers replacement source snapshots, so native/derived/cache/event
publication follows the same recovery path as live data. Failed deliveries
remain pending in the source journal; reruns resume them.
"""

from __future__ import annotations

import json
import time
from contextlib import closing

from app.core.executors import run_storage
from app.data_engine.ingestion.models import StreamType, TransportRequest
from . import klines_repo, kline_sources


def _backup(descriptor, row):
    with closing(klines_repo._connect()) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS source_enrichment_audit (
            series TEXT NOT NULL, open_time INTEGER NOT NULL, original_json TEXT NOT NULL,
            started_at INTEGER NOT NULL, checked_at INTEGER, status TEXT NOT NULL,
            evidence_origin TEXT NOT NULL, observation_id INTEGER, differences_json TEXT,
            PRIMARY KEY(series,open_time))""")
        conn.execute(
            """INSERT OR IGNORE INTO source_enrichment_audit
            (series,open_time,original_json,started_at,status,evidence_origin)
            VALUES(?,?,?,?,?,?)""",
            (
                kline_sources.series(descriptor),
                row["open_time"],
                json.dumps(row, sort_keys=True),
                int(time.time() * 1000),
                "pending",
                "historical_refetch",
            ),
        )
        return dict(
            conn.execute(
                "SELECT * FROM source_enrichment_audit WHERE series=? AND open_time=?",
                (kline_sources.series(descriptor), row["open_time"]),
            ).fetchone()
        )


def _finish(descriptor, opened, status, observation_id=None, differences=None):
    with closing(klines_repo._connect()) as conn, conn:
        conn.execute(
            """UPDATE source_enrichment_audit SET checked_at=?, status=?, observation_id=?, differences_json=?
            WHERE series=? AND open_time=?""",
            (
                int(time.time() * 1000),
                status,
                observation_id,
                json.dumps(differences or {}, sort_keys=True),
                kline_sources.series(descriptor),
                opened,
            ),
        )


async def enrich(descriptor, config, plugin, deliver, *, start_ms, end_ms, limit=300):
    if (
        descriptor.exchange not in {"binance", "okx"}
        or descriptor.market_type not in {"spot", "futures"}
        or descriptor.stream_type != StreamType.KLINE
    ):
        raise ValueError("enrichment supports Binance/OKX spot and linear swap klines")
    if (
        not config.ccxt_fork_kline_enabled
        or not 1 <= limit <= 1000
        or end_ms < start_ms
    ):
        raise ValueError(
            "enable the qualified fork and supply a bounded range (1..1000 rows)"
        )
    rows = await run_storage(
        klines_repo.query_klines,
        descriptor.symbol,
        descriptor.interval,
        start_ms,
        end_ms,
        limit=limit,
        exchange=descriptor.exchange,
        market_type=descriptor.market_type,
    )
    result = {
        "scanned": len(rows),
        "matched": 0,
        "revised": 0,
        "unavailable": 0,
        "already_evidenced": 0,
        "evidence_origin": "historical_refetch",
        "next_start_ms": rows[-1]["open_time"] + 1 if rows else None,
    }
    groups = []
    for row in rows:
        head = await run_storage(kline_sources.latest, descriptor, row["open_time"])
        if head and head["delivered_revision"] >= head["revision"]:
            result["already_evidenced"] += 1
            continue
        audit = await run_storage(_backup, descriptor, row)
        item = (row, json.loads(audit["original_json"]))
        if (
            not groups
            or len(groups[-1]) >= 300
            or groups[-1][-1][0]["close_time"] + 1 != row["open_time"]
        ):
            groups.append([])
        groups[-1].append(item)
    for group in groups:
        try:
            messages = await plugin.fetch_history_with_config(
                TransportRequest(
                    descriptor,
                    limit=len(group),
                    start_ms=group[0][0]["open_time"],
                    end_ms=group[-1][0]["open_time"],
                ),
                config,
            )
        except Exception:
            for row, _ in group:
                await run_storage(
                    _finish, descriptor, row["open_time"], "retryable_error"
                )
            raise
        by_time = {}
        for msg in messages:
            by_time.setdefault(msg.payload.get("timestamp"), []).append(msg)
        for row, original in group:
            opened = row["open_time"]
            try:
                exact = by_time.get(opened, [])
                head = await run_storage(kline_sources.latest, descriptor, opened)
                if len(exact) != 1 or not head or not head["is_closed"]:
                    await run_storage(_finish, descriptor, opened, "unavailable")
                    result["unavailable"] += 1
                    continue
                differences = {
                    name: {
                        "before": original.get(name),
                        "refetched": head["data"].get(name),
                    }
                    for name in kline_sources._VALUES
                    if original.get(name) != head["data"].get(name)
                }
                await deliver(exact[0])
                final = await run_storage(kline_sources.latest, descriptor, opened)
                if final["delivered_revision"] < final["revision"]:
                    raise RuntimeError("enrichment projection is still pending")
                status = "revised" if differences else "matched"
                await run_storage(
                    _finish,
                    descriptor,
                    opened,
                    status,
                    head["observation_id"],
                    differences,
                )
                result[status] += 1
            except Exception:
                await run_storage(_finish, descriptor, opened, "retryable_error")
                raise
    return result
