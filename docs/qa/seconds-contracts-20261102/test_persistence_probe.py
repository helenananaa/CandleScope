"""Offline checks for the native cold-storage witness (stdlib only)."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from persistence_probe import IDENTITY, inspect_storage


class PersistenceProbeTest(unittest.TestCase):
    def test_exact_identity_missing_rows_and_read_only_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "data.db"
            identity = ("binance", "spot", "binance", "binance", "crypto", "BTCUSDT", "1s",
                        "native", "raw", "continuous", "base_asset")
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE klines (" + ",".join(field + " TEXT" for field in IDENTITY)
                           + ",open_time INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL)")
                db.execute("INSERT INTO klines VALUES (" + ",".join("?" for _ in range(17)) + ")",
                           (*identity, 1000, 1, 3, 1, 2, 0.3))
                # A second provider with the same symbol/time cannot satisfy a gap.
                other = (*identity[:2], "other", *identity[3:])
                db.execute("INSERT INTO klines VALUES (" + ",".join("?" for _ in range(17)) + ")",
                           (*other, 2000, 1, 3, 1, 2, 0.3))
            digest = hashlib.sha256(database.read_bytes()).hexdigest()
            row = {"time": 1, "open": 1, "high": 3, "low": 1, "close": 2, "volume": 0.3}
            cell = {"cellId": "cell-1", "session": {"exchange": "binance", "marketType": "spot",
                    "symbol": "BTCUSDT", "interval": "1s"}, "first": 1, "last": 2, "rows": [row]}
            exact = inspect_storage(database, [cell])
            self.assertTrue(exact["matchesSaved"])
            self.assertEqual(len(exact["cells"][0]["rows"]), 1)
            changed = inspect_storage(database, [{**cell, "rows": [{**row, "close": 2.01}, {**row, "time": 2}]}])
            self.assertFalse(changed["matchesSaved"])
            self.assertEqual(changed["mismatches"][0], {"cellId": "cell-1", "time": 1,
                             "field": "close", "saved": 2.01, "disk": 2.0})
            self.assertEqual(len(changed["mismatches"]), 6)
            self.assertTrue(all(item["disk"] is None for item in changed["mismatches"][1:]))
            self.assertEqual(digest, hashlib.sha256(database.read_bytes()).hexdigest())

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "absent.db"
            with self.assertRaises(sqlite3.OperationalError):
                inspect_storage(database, [])
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
