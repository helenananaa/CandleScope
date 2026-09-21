"""Durable, bounded metadata for previously discovered query-only symbols."""
import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def exchange_rows(path: Path, rows: list[tuple[str, dict]] | None = None) -> list[dict]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=5) as db:
            db.execute("CREATE TABLE IF NOT EXISTS symbols (identity TEXT PRIMARY KEY, payload TEXT NOT NULL, seen REAL NOT NULL)")
            if rows:
                db.executemany("INSERT OR REPLACE INTO symbols VALUES (?, ?, ?)",
                               [(key, json.dumps(row, ensure_ascii=False), time.time()) for key, row in rows])
                db.execute("DELETE FROM symbols WHERE identity NOT IN (SELECT identity FROM symbols ORDER BY seen DESC, identity LIMIT 3000)")
            return [json.loads(item[0]) for item in db.execute("SELECT payload FROM symbols ORDER BY seen, identity")]
    except (OSError, sqlite3.Error, ValueError):
        logger.warning("Provider discovery metadata store unavailable", exc_info=True)
        return []
