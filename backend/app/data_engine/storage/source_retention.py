"""Lossless cold storage for aged source logs, with transactional hot-log cleanup.

Heads remain hot for revision replay and cold derived-bucket reconstruction.
Archived rows keep their IDs and hashes for duplicate detection. A compressed
copy must round-trip and hash-verify before removing the hot JSON in the SAME
SQLite transaction; interruption can never leave a dangling archive reference.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from contextlib import closing

from . import klines_repo


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS source_log_archives (
        source_table TEXT NOT NULL, row_id INTEGER NOT NULL, sha256 TEXT NOT NULL,
        payload BLOB NOT NULL, archived_at INTEGER NOT NULL,
        PRIMARY KEY(source_table,row_id))""")


def restore_row(conn, table, row):
    if row.get("payload_json", row.get("envelope_json")) != "":
        return row
    archive = conn.execute(
        "SELECT sha256,payload FROM source_log_archives WHERE source_table=? AND row_id=?",
        (table, row["id"]),
    ).fetchone()
    if archive is None:
        raise RuntimeError("missing source archive")
    raw = gzip.decompress(archive["payload"])
    if hashlib.sha256(raw).hexdigest() != archive["sha256"]:
        raise RuntimeError("source archive checksum mismatch")
    return json.loads(raw)


def compact(*, retention_days=30, batch_size=500, now_ms=None):
    if retention_days < 1 or not 1 <= batch_size <= 5000:
        raise ValueError("source retention requires >=1 day and batch size 1..5000")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    cutoff = now - retention_days * 86400000
    report = {"archived": 0, "json_bytes": 0, "compressed_bytes": 0, "cutoff": cutoff}
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in ("kline_source_observations", "market_source_observations"):
            if table not in tables:
                continue
            if table == "kline_source_observations":
                # Protect every head including undelivered revisions. Existing
                # source refs use series/open/revision; current heads stay hot.
                query = """SELECT o.* FROM kline_source_observations o
                    WHERE received_at<? AND envelope_json!=''
                    AND NOT EXISTS(SELECT 1 FROM kline_source_heads h WHERE h.observation_id=o.id)
                    ORDER BY id LIMIT ?"""
            else:
                query = """SELECT * FROM market_source_observations WHERE received_at<?
                    AND archived=0 ORDER BY id LIMIT ?"""
            for row in conn.execute(query, (cutoff, batch_size)).fetchall():
                original = dict(row)
                raw = json.dumps(
                    original, sort_keys=True, separators=(",", ":")
                ).encode()
                packed = gzip.compress(raw, mtime=0)
                digest = hashlib.sha256(raw).hexdigest()
                if gzip.decompress(packed) != raw:
                    raise RuntimeError("source archive round-trip failed")
                conn.execute(
                    "INSERT INTO source_log_archives VALUES(?,?,?,?,?)",
                    (table, row["id"], digest, packed, now),
                )
                # Verify the persisted bytes before hot-log cleanup.
                restore_row(
                    conn,
                    table,
                    dict(
                        original,
                        **(
                            {"envelope_json": ""}
                            if table.startswith("kline")
                            else {"payload_json": ""}
                        ),
                    ),
                )
                if table == "kline_source_observations":
                    conn.execute(
                        "UPDATE kline_source_observations SET envelope_json='',data_json='' WHERE id=?",
                        (row["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE market_source_observations SET payload_json='',archived=1 WHERE id=?",
                        (row["id"],),
                    )
                report["archived"] += 1
                report["json_bytes"] += len(raw)
                report["compressed_bytes"] += len(packed)
    return report
