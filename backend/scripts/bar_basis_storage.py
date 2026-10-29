"""Inspect the legacy-basis audit or restore its backup to a separate database.

Usage: PYTHONPATH=backend python backend/scripts/bar_basis_storage.py audit DB
       PYTHONPATH=backend python backend/scripts/bar_basis_storage.py restore BACKUP NEW_DB
The application must be stopped before an operator selects a restored profile.
"""
import argparse
import json
from pathlib import Path
import sqlite3

from app.data_engine.storage.basis_migration import migration_report, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("database", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "restore":
        restore_backup(args.backup.resolve(), args.destination.resolve())
        print(json.dumps({"restored": str(args.destination.resolve()), "original_unchanged": True}))
        return
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report = migration_report(conn) if "bar_basis_migrations" in tables else {"status": "not_migrated"}
        conn.row_factory = sqlite3.Row
        groups = [dict(row) for row in conn.execute("SELECT * FROM legacy_bar_basis_audit")] if "legacy_bar_basis_audit" in tables else []
        print(json.dumps({"migration": report, "legacy_groups": groups}, indent=2))


if __name__ == "__main__":
    main()
