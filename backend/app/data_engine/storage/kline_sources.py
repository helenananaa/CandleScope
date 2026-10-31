"""Durable source snapshots, revision selection and replay for native klines.

All observations retain the full envelope (including decimal strings and raw JSON).
Selection is separate from observation: stale/conflicting frames remain auditable.
REST uses a database watermark captured BEFORE I/O, not a guessed exchange clock.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing, nullcontext
from decimal import Decimal
from typing import Any

from app.data_engine.ingestion.models import (
    DataSource,
    MarketEvent,
    RawMessage,
    StreamDescriptor,
    StreamType,
)
from . import klines_repo

_DECIMALS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quoteVolume",
    "takerBuyBaseVolume",
    "takerBuyQuoteVolume",
)
_VALUES = (
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decimal_identity(value: str | None) -> tuple | None:
    if value is None:
        return None
    # Decimal.normalize() rounds to the ambient context (usually 28 digits).
    # Preserve arbitrary source precision while ignoring insignificant zeros.
    sign, digits, exponent = Decimal(value).as_tuple()
    digits = list(digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return (sign, digits, exponent) if digits else (0, [], 0)


def series(descriptor: StreamDescriptor) -> str:
    return _json(
        [
            descriptor.exchange,
            descriptor.market_type,
            descriptor.symbol.upper(),
            descriptor.interval,
        ]
    )


def _schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS kline_source_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, series TEXT NOT NULL, open_time INTEGER NOT NULL,
        observation_hash TEXT NOT NULL, value_hash TEXT NOT NULL, envelope_json TEXT NOT NULL,
        data_json TEXT NOT NULL, source TEXT NOT NULL, event_time INTEGER NOT NULL,
        received_at INTEGER NOT NULL, rest_watermark INTEGER, decision TEXT NOT NULL,
        UNIQUE(series, open_time, observation_hash))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS kline_source_heads (
        series TEXT NOT NULL, open_time INTEGER NOT NULL, observation_id INTEGER NOT NULL,
        revision INTEGER NOT NULL, value_hash TEXT NOT NULL, is_closed INTEGER NOT NULL,
        source TEXT NOT NULL, ws_event_time INTEGER, delivered_revision INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(series, open_time))""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS kline_source_history ON kline_source_observations(series, open_time, id)"
    )


def rest_watermark() -> int:
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(id),0) FROM kline_source_observations"
            ).fetchone()[0]
        )


def _head(conn, key, opened):
    return conn.execute(
        """SELECT h.*, o.envelope_json, o.data_json, o.event_time, o.received_at
        FROM kline_source_heads h JOIN kline_source_observations o ON o.id=h.observation_id
        WHERE h.series=? AND h.open_time=?""",
        (key, opened),
    ).fetchone()


def _decision(previous, event, value_hash, watermark):
    if previous is None:
        return "selected"
    if previous["is_closed"] and not event.data["is_closed"]:
        return "stale"
    if event.source != DataSource.WEBSOCKET:
        return (
            "selected"
            if watermark is not None and previous["observation_id"] <= watermark
            else "stale"
        )
    source_time = (
        previous["ws_event_time"]
        if event.data["source_candle"].get("eventTime") is not None
        else None
    )
    if source_time is not None:
        if event.event_time_ms < source_time:
            return "stale"
        if event.event_time_ms == source_time and previous["value_hash"] != value_hash:
            return "reconcile"
    if (
        previous["is_closed"]
        and (
            previous["source"] != DataSource.WEBSOCKET.value
            or event.data["source_candle"].get("eventTime") is None
        )
        and previous["value_hash"] != value_hash
    ):
        return "reconcile"
    if not event.data["is_closed"]:
        old = json.loads(previous["envelope_json"])
        new = event.data["source_candle"]
        for name in (
            "volume",
            "quoteVolume",
            "takerBuyBaseVolume",
            "takerBuyQuoteVolume",
        ):
            if (
                new.get(name) is not None
                and old.get(name) is not None
                and Decimal(new[name]) < Decimal(old[name])
            ):
                return "stale"
        if (
            new.get("trades") is not None
            and old.get("trades") is not None
            and new["trades"] < old["trades"]
        ):
            return "stale"
    return "selected"


def record(
    event: MarketEvent,
    descriptor: StreamDescriptor,
    *,
    rest_watermark: int | None = None,
    _connection=None,
) -> dict:
    envelope = dict(event.data["source_candle"])
    envelope.pop("_source_receipt", None)
    key, opened = series(descriptor), event.data["open_time"]
    semantic = {name: _decimal_identity(envelope[name]) for name in _DECIMALS}
    semantic.update(
        timestamp=opened,
        closeTime=envelope["closeTime"],
        trades=envelope["trades"],
        closed=event.data["is_closed"],
    )
    for name in ("sourceVolume", "volumeCcy"):
        if name in envelope:
            semantic[name] = _decimal_identity(envelope[name])
    for name in ("volumeUnit", "quoteVolumeUnit", "sourceVolumeUnit", "volumeCcyUnit"):
        if name in envelope:
            semantic[name] = envelope[name]
    value_hash = hashlib.sha256(_json(semantic).encode()).hexdigest()
    observation_hash = hashlib.sha256(
        _json([envelope, event.source.value, rest_watermark]).encode()
    ).hexdigest()
    data = {key: value for key, value in event.data.items() if key != "source_candle"}
    with (
        closing(klines_repo._connect())
        if _connection is None
        else nullcontext(_connection)
    ) as conn:
        with conn if _connection is None else nullcontext():
            if _connection is None:
                _schema(conn)
                conn.execute("BEGIN IMMEDIATE")
            previous = _head(conn, key, opened)
            existing = conn.execute(
                "SELECT * FROM kline_source_observations WHERE series=? AND open_time=? AND observation_hash=?",
                (key, opened, observation_hash),
            ).fetchone()
            if existing is not None:
                selected = (
                    previous is not None
                    and previous["observation_id"] == existing["id"]
                )
                status = (
                    "selected"
                    if selected
                    else (
                        "reconcile" if existing["decision"] == "reconcile" else "stale"
                    )
                )
                return {
                    "status": status,
                    "observation_id": existing["id"],
                    "ref": _ref(previous) if selected else None,
                }
            decision = _decision(previous, event, value_hash, rest_watermark)
            cursor = conn.execute(
                """INSERT INTO kline_source_observations
                (series,open_time,observation_hash,value_hash,envelope_json,data_json,source,event_time,received_at,rest_watermark,decision)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    opened,
                    observation_hash,
                    value_hash,
                    _json(envelope),
                    _json(data),
                    event.source.value,
                    event.event_time_ms,
                    event.received_at_ms,
                    rest_watermark,
                    decision,
                ),
            )
            observation_id = cursor.lastrowid
            if decision != "selected":
                return {
                    "status": decision,
                    "observation_id": observation_id,
                    "ref": None,
                }
            revision = (
                1
                if previous is None
                else previous["revision"] + int(previous["value_hash"] != value_hash)
            )
            ws_time = (
                envelope.get("eventTime")
                if event.source == DataSource.WEBSOCKET
                else (previous["ws_event_time"] if previous else None)
            )
            conn.execute(
                """INSERT INTO kline_source_heads(series,open_time,observation_id,revision,value_hash,is_closed,source,ws_event_time)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(series,open_time) DO UPDATE SET
                observation_id=excluded.observation_id,revision=excluded.revision,value_hash=excluded.value_hash,
                is_closed=excluded.is_closed,source=excluded.source,ws_event_time=excluded.ws_event_time""",
                (
                    key,
                    opened,
                    observation_id,
                    revision,
                    value_hash,
                    int(event.data["is_closed"]),
                    event.source.value,
                    ws_time,
                ),
            )
            return {
                "status": decision,
                "observation_id": observation_id,
                "ref": {"series": key, "open_time": opened, "revision": revision},
            }


def record_batch(events, descriptor, watermark):
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        return [
            record(event, descriptor, rest_watermark=watermark, _connection=conn)
            for event in events
        ]


def _ref(head) -> dict:
    return {key: head[key] for key in ("series", "open_time", "revision")}


def latest(descriptor: StreamDescriptor, opened: int) -> dict | None:
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        row = _head(conn, series(descriptor), opened)
        if row is None:
            return None
        result = dict(row)
        result["envelope"] = json.loads(result.pop("envelope_json"))
        result["data"] = json.loads(result.pop("data_json"))
        return result


def observations(descriptor: StreamDescriptor, opened: int) -> list[dict]:
    from .source_retention import restore_row

    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        return [
            restore_row(conn, "kline_source_observations", dict(row))
            for row in conn.execute(
                "SELECT * FROM kline_source_observations WHERE series=? AND open_time=? ORDER BY id",
                (series(descriptor), opened),
            )
        ]


def acknowledge(ref: dict) -> None:
    with closing(klines_repo._connect()) as conn, conn:
        conn.execute(
            "UPDATE kline_source_heads SET delivered_revision=? WHERE series=? AND open_time=? AND revision=?",
            (ref["revision"], ref["series"], ref["open_time"], ref["revision"]),
        )


def pending(descriptor: StreamDescriptor, limit: int = 500) -> list[RawMessage]:
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        rows = conn.execute(
            """SELECT h.*,o.envelope_json,o.source,o.received_at FROM kline_source_heads h
            JOIN kline_source_observations o ON h.observation_id=o.id
            WHERE h.series=? AND h.delivered_revision<h.revision ORDER BY h.open_time LIMIT ?""",
            (series(descriptor), limit),
        ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["envelope_json"])
            payload["_source_receipt"] = {
                "status": "selected",
                "observation_id": row["observation_id"],
                "ref": _ref(row),
            }
            result.append(
                RawMessage(
                    payload,
                    DataSource(row["source"]),
                    StreamType.KLINE,
                    row["received_at"],
                    endpoint="source-journal://replay",
                )
            )
        return result


def references_current(conn, refs: list[dict]) -> bool:
    for ref in refs:
        row = conn.execute(
            "SELECT revision FROM kline_source_heads WHERE series=? AND open_time=?",
            (ref["series"], ref["open_time"]),
        ).fetchone()
        if row is None or row[0] != ref["revision"]:
            return False
    return True


def closed_components(key: str, start: int, end: int) -> list[dict]:
    """Rebuild a cold derived bucket from its durable native components."""
    with closing(klines_repo._connect()) as conn:
        return [
            {"ref": _ref(row), "data": json.loads(row["data_json"])}
            for row in conn.execute(
                """SELECT h.*,o.data_json FROM kline_source_heads h
                JOIN kline_source_observations o ON h.observation_id=o.id
                WHERE h.series=? AND h.is_closed=1 AND h.open_time>=? AND h.open_time<?
                ORDER BY h.open_time""",
                (key, start, end),
            )
        ]


def filter_projection_rows(
    conn,
    rows: list[dict],
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    interval: str,
    native_identity: bool,
) -> list[dict]:
    """Called INSIDE the projection writer's transaction; old work cannot win a race."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kline_source_heads'"
        ).fetchone()
        is None
    ):
        return rows
    key = series(
        StreamDescriptor(
            symbol,
            StreamType.KLINE,
            interval=interval,
            exchange=exchange,
            market_type=market_type,
        )
    )
    result = []
    for row in rows:
        refs = row.get("source_refs", [])
        if refs and not references_current(conn, refs):
            continue
        head = _head(conn, key, row["open_time"]) if native_identity else None
        if head is not None:
            data = json.loads(head["data_json"])
            if not head["is_closed"] or any(row.get(k) != data[k] for k in _VALUES):
                continue
            refs = [_ref(head)]
        verified = dict(row, _source_verified=bool(refs))
        if (
            head is not None
            and head["source"] in {DataSource.HTTP.value, DataSource.HTTP_BACKFILL.value}
            and _ref(head) in row.get("source_refs", [])
        ):
            verified["_history_source_ref"] = _ref(head)
        result.append(verified)
    return result


def acknowledge_history_projection(conn, rows: list[dict]) -> None:
    """Consume REST history only inside its accepted native write transaction.

    History is delivered through backfill completion, not the realtime startup
    replay. A rollback must leave both the projection and receipt uncommitted.
    Derived writes and websocket receipts retain their market-delivery ack.
    """
    for row in rows:
        ref = row.get("_history_source_ref")
        if ref is not None:
            conn.execute(
                "UPDATE kline_source_heads SET delivered_revision=? "
                "WHERE series=? AND open_time=? AND revision=?",
                (ref["revision"], ref["series"], ref["open_time"], ref["revision"]),
            )
