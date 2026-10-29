"""One-time preservation-first isolation of unversioned live K-line storage.

Frozen local datasets and replay snapshots are separate stores and untouched.
All legacy rows remain queryable in klines_legacy_basis_v1; no timestamp-only
heuristic upgrades their provenance. The full pre-migration SQLite backup is
an additional offline rollback artifact.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid


def migrate_basis_storage(conn: sqlite3.Connection, path: Path, create_table_sql: str) -> None:
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    backup_path = None
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS bar_basis_migrations (version INTEGER PRIMARY KEY, report TEXT NOT NULL)")
        if conn.execute("SELECT 1 FROM bar_basis_migrations WHERE version=1").fetchone():
            conn.commit()
            return
        count = conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0]
        if count:
            # A separate read connection snapshots the committed database while
            # our reserved writer lock prevents competing mutations.
            backup_path = path.with_name(path.name + f".pre-basis-v1-{uuid.uuid4().hex}.sqlite")
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as source:
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
                    if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("bar_basis_backup_verification_failed")
                    if backup.execute("SELECT COUNT(*) FROM klines").fetchone()[0] != count:
                        raise RuntimeError("bar_basis_backup_count_mismatch")
            # Keep rows verbatim. Existing archive receipts cannot suppress a
            # rebuild: their import path also checks rows in the active table.
            indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='klines' AND sql IS NOT NULL").fetchall()
            conn.execute("ALTER TABLE klines RENAME TO klines_legacy_basis_v1")
            for (name,) in indexes:
                conn.execute('DROP INDEX "' + name.replace('"', '""') + '"')
            conn.execute(create_table_sql)
            conn.execute("""CREATE TABLE legacy_bar_basis_audit AS
                SELECT exchange, market_type, provider_id, venue, symbol, interval, source,
                       COUNT(*) AS rows, MIN(open_time) AS first_open_ms, MAX(open_time) AS last_open_ms,
                       'unknown' AS qualification, 'source_rule_version_missing' AS reason
                FROM klines_legacy_basis_v1
                GROUP BY exchange, market_type, provider_id, venue, symbol, interval, source""")
        report = dict(version=1, legacy_rows=count, backup=str(backup_path) if backup_path else None,
                      legacy_table="klines_legacy_basis_v1" if count else None,
                      action="retained_and_isolated" if count else "fresh_store",
                      rule="No unversioned OHLCV is promoted by inspecting timestamps alone")
        conn.execute("INSERT INTO bar_basis_migrations VALUES (1, ?)", (json.dumps(report),))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def migration_report(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT report FROM bar_basis_migrations WHERE version=1").fetchone()
    return json.loads(row[0]) if row else {}


def restore_backup(backup_path: Path, destination: Path) -> None:
    """Restore to a new file; never overwrite post-migration user activity."""
    with destination.open("xb"):
        pass
    try:
        with sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True) as source:
            with sqlite3.connect(destination) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("bar_basis_restore_verification_failed")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
