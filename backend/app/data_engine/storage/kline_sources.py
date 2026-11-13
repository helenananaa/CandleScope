"""Durable source snapshots, revision selection and replay for native klines.

All observations retain the full envelope (including decimal strings and raw JSON).
Selection is separate from observation: stale/conflicting frames remain auditable.
REST uses a database watermark captured BEFORE I/O, not a guessed exchange clock.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
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
    # This is metadata of the original selected-source owner, not a second
    # revision ledger. Legacy content has no newer deletion permission.
    for table in ('kline_source_heads', 'kline_source_observations'):
        if 'permission_floor' not in {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN permission_floor INTEGER NOT NULL DEFAULT 0')


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
    from .revisions import acquisition_delete_floor, current_revision, StaleAcquisition
    requested_permission = acquisition_delete_floor(None)
    observation_identity = [envelope, event.source.value, rest_watermark]
    if event.source != DataSource.WEBSOCKET and requested_permission is not None:
        # Original pre-I/O D126 permission is part of a REST observation's
        # audit identity. Concurrent old/fresh requests must not alias one row.
        observation_identity.append({'permission_floor': requested_permission})
    observation_hash = hashlib.sha256(
        _json(observation_identity).encode()
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
            try:
                head_revision = current_revision(conn)
            except sqlite3.OperationalError as error:
                if 'no such table: kline_revision_clock' not in str(error):
                    raise
                # Standalone legacy journals have no D126 permission owner.
                head_revision = 0
            permission = (requested_permission if requested_permission is not None else
                          head_revision if event.source == DataSource.WEBSOCKET else 0)
            if type(permission) is not int or not 0 <= permission <= head_revision:
                raise StaleAcquisition('source observation has invalid original deletion permission')
            if (previous is not None and previous['value_hash'] == value_hash
                    and event.source != DataSource.WEBSOCKET and requested_permission is not None
                    and permission > previous['permission_floor']):
                # A real fresh request can confirm the SAME semantic content,
                # even when its value selection loses a concurrent watermark
                # race. Do not reselect an old value or change its revision.
                conn.execute('UPDATE kline_source_heads SET permission_floor=MAX(permission_floor,?) '
                             'WHERE series=? AND open_time=? AND value_hash=?',
                             (permission,key,opened,value_hash))
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
                    "permission_floor": (max(previous['permission_floor'], permission)
                        if selected and event.source != DataSource.WEBSOCKET and requested_permission is not None
                        else previous['permission_floor'] if selected else 0),
                }
            decision = _decision(previous, event, value_hash, rest_watermark)
            cursor = conn.execute(
                """INSERT INTO kline_source_observations
                (series,open_time,observation_hash,value_hash,envelope_json,data_json,source,event_time,received_at,rest_watermark,decision,permission_floor)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    permission,
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
            permission_floor = (
                (max(previous['permission_floor'], permission)
                 if event.source != DataSource.WEBSOCKET and requested_permission is not None
                 else previous['permission_floor'])
                if previous is not None and previous['value_hash'] == value_hash
                else permission
            )
            conn.execute(
                """INSERT INTO kline_source_heads(series,open_time,observation_id,revision,value_hash,is_closed,source,ws_event_time,permission_floor)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(series,open_time) DO UPDATE SET
                observation_id=excluded.observation_id,revision=excluded.revision,value_hash=excluded.value_hash,
                is_closed=excluded.is_closed,source=excluded.source,ws_event_time=excluded.ws_event_time,
                permission_floor=excluded.permission_floor""",
                (
                    key,
                    opened,
                    observation_id,
                    revision,
                    value_hash,
                    int(event.data["is_closed"]),
                    event.source.value,
                    ws_time,
                    permission_floor,
                ),
            )
            return {
                "status": decision,
                "observation_id": observation_id,
                "ref": {"series": key, "open_time": opened, "revision": revision},
                "permission_floor": permission_floor,
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


def pending(descriptor: StreamDescriptor, limit: int = 500, *, include_history=False) -> list[RawMessage]:
    """Replay market-owned receipts; interrupted historical pages stay with backfill.

    Their observations and unacknowledged revision remain durable. History's
    repair ledger reissues uncommitted work instead of pushing old bars through
    live continuity. Legacy receipts without an owner retain their old behavior.
    """
    with closing(klines_repo._connect()) as conn, conn:
        _schema(conn)
        rows = conn.execute(
            """SELECT h.*,o.envelope_json,o.source,o.received_at FROM kline_source_heads h
            JOIN kline_source_observations o ON h.observation_id=o.id
            WHERE h.series=? AND h.delivered_revision<h.revision
            AND (? OR COALESCE(json_extract(o.envelope_json,'$._source_delivery_owner'),'market')!='history')
            ORDER BY h.open_time LIMIT ?""",
            (series(descriptor), include_history, limit),
        ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["envelope_json"])
            payload["_source_receipt"] = {
                "status": "selected",
                "observation_id": row["observation_id"],
                "ref": _ref(row),
                "permission_floor": row['permission_floor'],
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


def validate_component_preview(conn, components, *, symbol, interval, exchange,
                               market_type, series_identity, revision_floor) -> str:
    """No writes/acknowledgments: validate at most 256 immutable source leaves.

    A superseding observation is normal source progress, not a repair request.
    Canonical deletion/amendment requires the existing snapshot recovery path.
    Unknown enhancements remain unknown, not a comparison against diagnostic zero.
    """
    from .revisions import current_revision,series_change,series_values
    from app.data_engine.kline_quality import kline_source_quality
    from app.data_engine.market_data.kline_metrics import declared_enhanced_fields
    from app.data_engine.interval_policy import parse_interval_spec
    if (not 0<len(components)<=256 or type(revision_floor) is not int
            or not series_identity.is_legacy_default_for(exchange)):
        return 'unavailable'
    if revision_floor>current_revision(conn):
        return 'canonical_changed'
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kline_source_heads'").fetchone() is None:
        return 'unavailable'
    source_values=set()
    # References and all scalar comparisons share this transaction. Decode one
    # bounded normalized row at a time; never retain all envelopes or source rows.
    for held in components:
        ref=held.get('source_ref')
        if ref is None:
            # A warm-start canonical leaf may predate source-journal receipts.
            # It still needs an exact current canonical comparison below.
            width=held['close_time_ms']+1-held['open_time_ms']
            if not held['is_closed'] or width<=0 or width%60000:
                return 'unavailable'
            spec=parse_interval_spec(str(width//60000)+'m')
            if spec is None:
                return 'unavailable'
            source_interval=spec.canonical
            mask=held['enhanced_fields']
        else:
            if (set(ref)!={'series','open_time','revision'} or not isinstance(ref['series'],str)
                    or len(ref['series'])>1024 or type(ref['open_time']) is not int
                    or type(ref['revision']) is not int):
                return 'unavailable'
            try:
                source=json.loads(ref['series'])
            except ValueError:
                return 'unavailable'
            if (not isinstance(source,list) or len(source)!=4
                    or source[:3]!=[exchange,market_type,symbol] or not isinstance(source[3],str)
                    or ref['open_time']!=held['open_time_ms']):
                return 'unavailable'
            source_interval=source[3]
            row=conn.execute('''SELECT h.revision,h.is_closed,
                CASE WHEN length(o.data_json)<=8192 THEN o.data_json ELSE NULL END AS data_json
                FROM kline_source_heads h JOIN kline_source_observations o ON o.id=h.observation_id
                WHERE h.series=? AND h.open_time=?''',(ref['series'],ref['open_time'])).fetchone()
            if row is None or row['revision']!=ref['revision']:
                return 'superseded'
            if row['data_json'] is None:
                return 'unavailable'
            data=json.loads(row['data_json'])
            mask=declared_enhanced_fields(exchange,market_type,data)
            if (data.get('open_time')!=held['open_time_ms'] or data.get('close_time')!=held['close_time_ms']
                    or bool(row['is_closed'])!=held['is_closed'] or mask!=held['enhanced_fields']
                    or any(data.get(name)!=held[name] for name in ('open','high','low','close','volume',*mask))):
                return 'unavailable'
        values=series_values(symbol,source_interval,exchange,market_type,series_identity)
        source_values.add(values)
        if len(source_values)>31:
            return 'unavailable'
        change=series_change(conn,values)
        if change is not None and change['delete_revision']>revision_floor:
            return 'canonical_changed'
        where,params,_=klines_repo._series_where(exchange=exchange,market_type=market_type,
            symbol=symbol,interval=source_interval,series_identity=series_identity)
        canonical=conn.execute('SELECT '+','.join((*_VALUES,'source'))+' FROM klines WHERE '
            +' AND '.join(where)+' AND open_time=?',(*params,held['open_time_ms'])).fetchone()
        if held['is_closed']:
            if (canonical is None or any(canonical[name]!=held[name] for name in
                    ('open','high','low','close','volume',*mask))
                    or canonical['close_time']!=held['close_time_ms']):
                return 'canonical_changed'
        elif canonical is not None and kline_source_quality(canonical['source']).trusted_final:
            return 'canonical_changed'
    target=series_change(conn,series_values(symbol,interval,exchange,market_type,series_identity))
    if target is not None and target['revision']>revision_floor:
        return 'canonical_changed'
    return 'current'


def closed_components(key: str, start: int, end: int) -> list[dict]:
    """Rebuild a cold derived bucket from its durable native components."""
    with closing(klines_repo._connect()) as conn:
        return [
            {"ref": _ref(row), "data": json.loads(row["data_json"]),
             "permission_floor": row['permission_floor'] if 'permission_floor' in row.keys() else 0}
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
        return [row for row in rows if 'source_window' not in row]
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
        source_window_verified = False
        if 'source_window' in row:
            from app.data_engine.aggregation.source_window import SourceWindowVersion
            from app.data_engine.aggregation.blocks import BlockUnavailable
            try:
                version = SourceWindowVersion.from_dict(row['source_window'])
                if (native_identity and version.start_ms == row['open_time']
                        and version.through_ms <= row['close_time'] + 1
                        and source_window_allows_target(conn, version, interval,
                            expected=(exchange, market_type, symbol))):
                    source_window_verified = True
            except (ValueError, TypeError, BlockUnavailable):
                pass
            if not source_window_verified:
                continue
        refs = row.get("source_refs", [])
        if refs and not references_current(conn, refs):
            continue
        head = _head(conn, key, row["open_time"]) if native_identity else None
        if head is not None:
            data = json.loads(head["data_json"])
            if not head["is_closed"] or any(row.get(k) != data[k] for k in _VALUES):
                continue
            refs = [_ref(head)]
        verified = dict(row, _source_verified=bool(refs) or source_window_verified)
        # This marker is a result of the transaction's source-head validation,
        # never authority supplied by a caller or a previously filtered row.
        verified.pop("_history_source_ref", None)
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


# Selected source values have their own revision domain. Do not use the global
# observation ID watermark (stale/unselected messages also advance it), and do
# not relabel these counters as canonical D126 revisions. Current heads remain
# hot through source-retention and their semantic revisions only advance.
def _source_window_args(key, start, end, width):
    from app.data_engine.aggregation.source_window import MAX_SOURCE_WINDOW_ROWS
    from app.data_engine.interval_policy import parse_interval_spec, IntervalAlignment

    if not isinstance(key, str) or not 0 < len(key) <= 1024:
        raise ValueError("selected-source series required")
    try:
        identity = json.loads(key)
    except (ValueError, TypeError):
        raise ValueError("selected-source series required") from None
    if (
        not isinstance(key, str)
        or len(key) > 1024
        or not isinstance(identity, list)
        or len(identity) != 4
        or any(not isinstance(v, str) or not v for v in identity)
    ):
        raise ValueError("selected-source series required")
    spec = parse_interval_spec(identity[3])
    if (
        spec is None
        or spec.alignment is not IntervalAlignment.FIXED_EPOCH
        or spec.phase_ms
        or any(type(v) is not int for v in (start, end, width))
        or width != spec.nominal_ms
        or not 0 <= start < end < 2**63
        or start % width
        or end % width
        or not 1 <= (end - start) // width <= MAX_SOURCE_WINDOW_ROWS
    ):
        raise ValueError("bounded fixed selected-source window required")


def _source_window_counts(conn, key, start, end, width):
    from app.data_engine.aggregation.blocks import BlockUnavailable

    slots = (end - start) // width
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kline_source_heads'"
        ).fetchone()
        is None
    ):
        raise BlockUnavailable("selected-source heads are unavailable")
    # Bound physical metadata work too: malformed/off-grid extra heads cannot
    # turn a finite requested grid into an unlimited scan or Python collection.
    floor_column = (
        "permission_floor"
        if "permission_floor"
        in {row[1] for row in conn.execute("PRAGMA table_info(kline_source_heads)")}
        else "0 AS permission_floor"
    )
    row = conn.execute(
        """SELECT COUNT(*) AS total,
        COALESCE(SUM(CASE WHEN is_closed=1 THEN 1 ELSE 0 END),0) AS closed,
        COALESCE(SUM(CASE WHEN is_closed=1 THEN revision ELSE 0 END),0) AS revisions,
        COALESCE(MIN(CASE WHEN is_closed=1 THEN permission_floor END),0) AS floor
        FROM (SELECT is_closed,revision,"""
        + floor_column
        + """ FROM kline_source_heads
        WHERE series=? AND open_time>=? AND open_time<? ORDER BY open_time LIMIT ?)""",
        (key, start, end, slots + 1),
    ).fetchone()
    if row["total"] > slots or row["revisions"] < row["closed"]:
        raise BlockUnavailable("selected-source heads exceed the qualified grid")
    return row["closed"], row["revisions"], row["floor"]


def source_window_current(conn, version):
    """Transaction-local content fence; original D126 permissions stay separate."""
    from app.data_engine.aggregation.source_window import SourceWindowVersion
    from .revisions import (
        current_revision,
        series_change,
        series_values,
        IDENTITY_COLUMNS,
        BLOCK_CHANGE_WINDOW,
    )

    if type(version) is not SourceWindowVersion:
        raise ValueError("selected-source version required")
    _source_window_args(
        version.series, version.start_ms, version.through_ms, version.source_width_ms
    )
    head = current_revision(conn)
    if head < version.acquisition_revision or _source_window_counts(
        conn,
        version.series,
        version.start_ms,
        version.through_ms,
        version.source_width_ms,
    ) != (version.closed_count, version.revision_sum, version.permission_floor):
        return False
    exchange, market_type, symbol, interval = json.loads(version.series)
    key = series_values(symbol, interval, exchange, market_type)
    change = series_change(conn, key)
    if change is None or change["revision"] <= version.acquisition_revision:
        return True
    if change["revision"] > head:
        return False
    # Reuse D126's finite mutation footprints. Native closes beyond the source
    # seam do not invalidate this read; a correction within it does. Query only
    # scalar metadata, never materialize unrelated payloads/identity strings.
    gap = head - version.acquisition_revision
    if not 0 < gap <= BLOCK_CHANGE_WINDOW:
        return False
    count = conn.execute(
        "SELECT COUNT(*) FROM kline_block_changes WHERE revision>? AND revision<=?",
        (version.acquisition_revision, head),
    ).fetchone()[0]
    if count != gap:
        return False
    changed = conn.execute(
        "SELECT 1 FROM kline_block_changes WHERE revision>? AND revision<=? AND "
        + " AND ".join(name + "=?" for name in IDENTITY_COLUMNS)
        + " AND start_ms<? AND end_ms>=? LIMIT 1",
        (
            version.acquisition_revision,
            head,
            *key,
            version.through_ms,
            version.start_ms,
        ),
    ).fetchone()
    return changed is None


def source_window_allows_target(conn, version, interval, *, expected=None):
    """Current source content and original deletion permission, kept separate."""
    from app.data_engine.interval_policy import parse_interval_spec, IntervalAlignment
    from .revisions import Acquisition, StaleAcquisition, series_values
    from .derived_history_fence import check_deletions

    if not source_window_current(conn, version):
        return False
    exchange, market_type, symbol, source_interval = json.loads(version.series)
    if expected is not None and (exchange, market_type, symbol) != expected:
        return False
    spec = parse_interval_spec(interval)
    if (
        spec is None
        or spec.alignment is not IntervalAlignment.FIXED_EPOCH
        or spec.phase_ms
        or spec.floor_ms(version.start_ms) != version.start_ms
        or version.through_ms > spec.next_ms(version.start_ms)
        or spec.nominal_ms % version.source_width_ms
        or version.closed_count <= 0
    ):
        return False
    try:
        check_deletions(
            conn,
            Acquisition(version.permission_floor),
            series_values(symbol, interval, exchange, market_type),
            series_values(symbol, source_interval, exchange, market_type),
        )
    except StaleAcquisition:
        return False
    return True


def capture_source_window(key, start, end, width):
    """Capture a bounded closed-value range; no schema/write/cache side effect.

    The last selected close defines the seam. A future forming tail is outside
    this receipt. Missing/unclosed interior slots remain explicit partial data.
    Consumers must not assume this range is a contiguous temporal prefix.
    """
    from app.data_engine.aggregation.blocks import (
        BlockUnavailable,
        BlockRevisionChanged,
    )
    from app.data_engine.aggregation.source_window import SourceWindowVersion
    from .revisions import current_revision

    _source_window_args(key, start, end, width)
    with closing(klines_repo._connect()) as conn:
        conn.execute("BEGIN")
        acquired = current_revision(conn)
        expected = _source_window_counts(conn, key, start, end, width)
        row = conn.execute(
            """SELECT open_time FROM kline_source_heads WHERE series=?
            AND open_time>=? AND open_time<? AND is_closed=1 ORDER BY open_time DESC LIMIT 1""",
            (key, start, end),
        ).fetchone()
        if row is None:
            from app.data_engine.aggregation.source_window import EmptySourceWindow
            raise EmptySourceWindow("selected-source window has no confirmed components")
        through = row["open_time"] + width
        if (row["open_time"] - start) % width or through > end:
            raise BlockUnavailable("selected-source seam is off grid")
        actual = _source_window_counts(conn, key, start, through, width)
        if actual != expected:
            raise BlockRevisionChanged("selected-source window changed during capture")
        return SourceWindowVersion(
            key, start, through, width, *actual[:2], acquired, actual[2]
        )


def read_source_window_page(
    version, position_ms=None, *, max_rows=128, _connection=None, _pinned=False
):
    """Read at most 128 bounded normalized source values with fresh fences.

    No complete-window list is created. Caller reserves decode work before
    scheduling this worker and must validate again before adopting/publishing.
    This low-level receipt alone is not a cold-recovery implementation.
    """
    from app.data_engine.aggregation.blocks import (
        BlockUnavailable,
        BlockRevisionChanged,
    )
    from app.data_engine.aggregation.source_window import (
        SourceWindowVersion,
        SourceWindowPage,
        MAX_SOURCE_PAGE_ROWS,
        MAX_SOURCE_DATA_BYTES,
    )
    from app.data_engine.readonly import ReadonlyFields

    if type(version) is not SourceWindowVersion:
        raise ValueError("selected-source version required")
    position = version.start_ms if position_ms is None else position_ms
    if (
        type(position) is not int
        or not version.start_ms <= position < version.through_ms
        or (position - version.start_ms) % version.source_width_ms
        or type(max_rows) is not int
        or not 1 <= max_rows <= MAX_SOURCE_PAGE_ROWS
    ):
        raise ValueError("bounded selected-source page required")
    if _pinned and (_connection is None or not _connection.in_transaction):
        raise ValueError("pinned source pages require an existing read transaction")
    with (
        closing(klines_repo._connect())
        if _connection is None
        else nullcontext(_connection)
    ) as conn:
        if not _pinned and not source_window_current(conn, version):
            raise BlockRevisionChanged("selected-source window expired before page")
        rows = conn.execute(
            """SELECT h.open_time,h.revision,
            CASE WHEN length(CAST(o.data_json AS BLOB))<=? THEN o.data_json ELSE NULL END AS data_json
            FROM kline_source_heads h JOIN kline_source_observations o ON o.id=h.observation_id
            WHERE h.series=? AND h.is_closed=1 AND h.open_time>=? AND h.open_time<?
            ORDER BY h.open_time LIMIT ?""",
            (
                MAX_SOURCE_DATA_BYTES,
                version.series,
                position,
                version.through_ms,
                max_rows,
            ),
        ).fetchall()
        values = []
        for row in rows:
            if row["data_json"] is None:
                raise BlockUnavailable(
                    "selected-source component exceeds decode allowance"
                )
            try:
                data = json.loads(row["data_json"])
            except (ValueError, TypeError, RecursionError):
                raise BlockUnavailable(
                    "selected-source component is malformed"
                ) from None
            if (
                type(row["revision"]) is not int
                or row["revision"] < 1
                or not isinstance(data, dict)
                or type(data.get("open_time")) is not int
                or type(data.get("close_time")) is not int
                or data.get("is_closed") is not True
                or data["open_time"] != row["open_time"]
                or (row["open_time"] - version.start_ms) % version.source_width_ms
                or data["close_time"] + 1 != row["open_time"] + version.source_width_ms
            ):
                raise BlockUnavailable(
                    "selected-source component is not on the qualified closed grid"
                )
            from math import isfinite
            from app.data_engine.aggregation.semantics import valid_ohlcv

            if (
                any(
                    type(data.get(name)) not in (int, float)
                    for name in ("open", "high", "low", "close", "volume")
                )
                or not valid_ohlcv(
                    tuple(
                        data[name]
                        for name in ("open", "high", "low", "close", "volume")
                    )
                )
                or any(
                    data.get(name) is not None
                    and (
                        type(data[name]) not in (int, float) or not isfinite(data[name])
                    )
                    for name in (
                        "quote_volume",
                        "trades",
                        "taker_buy_base",
                        "taker_buy_quote",
                    )
                )
            ):
                raise BlockUnavailable(
                    "selected-source component has malformed normalized values"
                )
            # Original unknown payloads remain in the journal. Recovery needs
            # only scalar candle fields; do not retain arbitrary decoded trees
            # in every value of a page.
            data = {name: data.get(name) for name in (*_VALUES, "is_closed")}
            values.append(
                ReadonlyFields(
                    dict(
                        ref=dict(
                            series=version.series,
                            open_time=row["open_time"],
                            revision=row["revision"],
                        ),
                        data=data,
                    )
                )
            )
        rows = ()
        if not values or (not _pinned and not source_window_current(conn, version)):
            raise BlockRevisionChanged("selected-source window expired during page")
        next_position = values[-1]["data"]["close_time"] + 1
        return SourceWindowPage(
            version,
            position,
            None if next_position == version.through_ms else next_position,
            tuple(values),
        )
