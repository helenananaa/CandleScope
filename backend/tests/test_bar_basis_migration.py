from pathlib import Path
import sqlite3

import pytest

from app.data_engine.storage import klines_repo
from app.data_engine.storage.basis_migration import migration_report, restore_backup


def test_unknown_legacy_rows_are_retained_isolated_and_restoreable(tmp_path, monkeypatch):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    old = dict(open_time=1704067200000, close_time=1704153599999, open=1, high=3, low=1, close=2, volume=4, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0)
    klines_repo.upsert_klines("BTC-USDT", "1d", [old], exchange="okx", source="historical_unknown_build")
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE bar_basis_migrations")
        before = conn.execute("SELECT * FROM klines").fetchall()
    klines_repo.init_klines_storage()
    with sqlite3.connect(path) as conn:
        report = migration_report(conn)
        assert report["legacy_rows"] == 1
        assert conn.execute("SELECT * FROM klines_legacy_basis_v1").fetchall() == before
        assert conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0] == 0
        assert conn.execute("SELECT qualification, reason FROM legacy_bar_basis_audit").fetchone() == ("unknown", "source_rule_version_missing")
    # Rebuild into the active namespace, leaving old OHLCV and backup intact.
    klines_repo.upsert_klines("BTC-USDT", "1d", [{**old, "volume": 5}], exchange="okx", source="backfill_rest_verified")
    klines_repo.init_klines_storage()
    with sqlite3.connect(path) as conn:
        assert migration_report(conn) == report
        assert conn.execute("SELECT volume FROM klines").fetchone()[0] == 5
        assert conn.execute("SELECT volume FROM klines_legacy_basis_v1").fetchone()[0] == 4
    restored = tmp_path / "restored.sqlite"
    restore_backup(Path(report["backup"]), restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT * FROM klines").fetchall() == before
    with pytest.raises(FileExistsError):
        restore_backup(Path(report["backup"]), restored)


def test_backup_failure_does_not_remove_active_data(tmp_path, monkeypatch):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE bar_basis_migrations")
        # Force a transactional migration failure after a verified backup.
        conn.execute("CREATE TABLE klines_legacy_basis_v1 (sentinel INTEGER)")
    klines_repo.upsert_klines("BTC-USDT", "1m", [dict(open_time=0, close_time=59999, open=1, high=1, low=1, close=1, volume=1, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0)])
    with pytest.raises(sqlite3.OperationalError):
        klines_repo.init_klines_storage()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0] == 1
