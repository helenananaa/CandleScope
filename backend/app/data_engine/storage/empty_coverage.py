"""Default-series empty-window evidence participates in the D126 ledger.

These tables describe verified absence, not OHLCV rows. Their changes still
invalidate history views and must obey the same acquisition/deletion fences.
"""
from __future__ import annotations

from .revisions import IDENTITY_COLUMNS, RevisionStore, series_values


def default_identity_sql(alias: str, exchange: str) -> str:
    return (f"{alias}.provider_id={exchange} AND {alias}.venue={exchange} "
            f"AND {alias}.asset_class='crypto' AND {alias}.series_variant='native' "
            f"AND {alias}.price_adjustment='raw' AND {alias}.session_variant='continuous' "
            f"AND {alias}.volume_semantics='base_asset'")


def init_revision_triggers(conn, table: str, *, native: bool = False) -> None:
    assert table in {"native_empty_seconds", "trade_empty_buckets"}
    keys = ",".join(IDENTITY_COLUMNS)
    conn.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS {table}_immutable BEFORE UPDATE ON {table}
        BEGIN
            SELECT RAISE(ABORT, 'Empty coverage changes require delete and insert');
        END;
    """)
    for operation, alias in (("insert", "NEW"), ("delete", "OLD")):
        exchange = "'upbit'" if native else f"{alias}.exchange"
        market = "'spot'" if native else f"{alias}.market_type"
        interval = "'1s'" if native else f"{alias}.interval"
        values = (exchange, market, f"{alias}.symbol", interval,
                  exchange, exchange, "'crypto'", "'native'", "'raw'", "'continuous'", "'base_asset'")
        head = "(SELECT revision FROM kline_revision_clock WHERE singleton=1)"
        deletion = head if operation == "delete" else "0"
        if native and operation == "delete":
            # Atomic union replaces old spans without withdrawing any absence
            # evidence. It is a content revision, not permission to recreate
            # deleted candles. Actual clear/delete/invalidation stays fenced.
            deletion = ("CASE WHEN (SELECT mode FROM kline_mutation_context WHERE singleton=1)="
                        "'native_empty_union' THEN 0 ELSE " + head + " END")
        replace_native_delete = native and operation == "delete"
        migration_start = (f"BEGIN IMMEDIATE; DROP TRIGGER IF EXISTS {table}_change_delete;"
                           if replace_native_delete else "")
        migration_end = "COMMIT;" if replace_native_delete else ""
        family = " AND ".join(f"d.{name}={value}" for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval")
        selected_family = " AND ".join(f"{name}={value}" for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval")
        match = " AND ".join(f"d.{name}=klines.{name}" for name in IDENTITY_COLUMNS)
        conn.executescript(f"""
            {migration_start}
            CREATE TRIGGER IF NOT EXISTS {table}_change_{operation}
            AFTER {operation.upper()} ON {table} BEGIN
                UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1;
                INSERT INTO kline_series_changes VALUES
                    ({','.join(values)}, {head}, {deletion}, {alias}.start_ms, {alias}.end_ms, 'empty_{operation}')
                ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision,
                    delete_revision=MAX(delete_revision,excluded.delete_revision),
                    start_ms=MIN(start_ms,excluded.start_ms), end_ms=MAX(end_ms,excluded.end_ms),
                    operation=excluded.operation;
                DELETE FROM klines WHERE {selected_family} AND
                    EXISTS(SELECT 1 FROM kline_derived_series d WHERE {match} AND {family} AND d.interval<>{interval})
                    AND open_time<={alias}.end_ms AND COALESCE(close_time,open_time)>={alias}.start_ms
                    AND (SELECT mode FROM kline_mutation_context WHERE singleton=1)<>'retention';
            END;
            {migration_end}
        """)


def version(exchange, market_type, symbol, interval):
    from .klines_repo import _connect
    return RevisionStore(_connect).read_versions((series_values(symbol, interval, exchange, market_type),))[1][0]
