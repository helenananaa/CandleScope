"""Decoded public REST/WS envelopes, retained independently of unified fields."""

from __future__ import annotations

import hashlib
import json
import importlib.resources
from functools import lru_cache
from contextlib import closing

from . import klines_repo


@lru_cache(maxsize=1)
def _provenance():
    build = json.loads(
        importlib.resources.files("ccxt").joinpath("candlescope_build.json").read_text()
    )
    return json.dumps(
        {"capture_schema": "candlescope.public.raw.v1", **build}, sort_keys=True
    )


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS market_source_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, stream_key TEXT NOT NULL,
        transport TEXT NOT NULL, received_at INTEGER NOT NULL, endpoint TEXT NOT NULL,
        payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)""")
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(market_source_observations)")
    }
    if "provenance_json" not in columns:
        conn.execute(
            "ALTER TABLE market_source_observations ADD COLUMN provenance_json TEXT"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS market_source_age ON market_source_observations(archived,received_at)"
    )


def _record(conn, descriptor, transport, received_at, endpoint, payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    conn.execute(
        """INSERT INTO market_source_observations
        (stream_key,transport,received_at,endpoint,payload_json,sha256,provenance_json) VALUES(?,?,?,?,?,?,?)""",
        (
            descriptor.key,
            transport,
            received_at,
            endpoint,
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
            _provenance(),
        ),
    )


def record_rest(descriptor, responses):
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        for item in responses:
            _record(
                conn,
                descriptor,
                "rest",
                item["received_at"],
                item["endpoint"],
                item["payload"],
            )


def record_ws(descriptor, message):
    from app.exchanges.ccxt_ext.source_capture import RAW_ONLY

    payload = message.payload
    if isinstance(payload, dict) and payload.get(RAW_ONLY):
        payload = payload["raw"]
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        _record(
            conn, descriptor, "ws", message.received_at_ms, message.endpoint, payload
        )


def observations(descriptor):
    from .source_retention import restore_row

    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        return [
            restore_row(conn, "market_source_observations", dict(row))
            for row in conn.execute(
                "SELECT * FROM market_source_observations WHERE stream_key=? ORDER BY id",
                (descriptor.key,),
            )
        ]
