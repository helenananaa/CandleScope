"""Independently verify committed SQLite state after all app owners exited."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

profile, run_id, research_id, seed_profile = sys.argv[1:]
profile, seed_profile = Path(profile), Path(seed_profile)


def read(path):
    wal = path.with_name(path.name + "-wal")
    assert path.is_file() and (not wal.exists() or wal.stat().st_size == 0), path
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    return db


def research(path):
    with read(path) as db:
        return {
            table: [dict(r) for r in db.execute(
                f"SELECT * FROM {table} WHERE run_id=?", (research_id,)
            )]
            for table in ("backtest_runs", "backtest_reports")
        }


assert research(profile / "data/backtest.db") == research(seed_profile / "data/backtest.db")
database = profile / "data/continuous-strategy.sqlite3"
fingerprint = hashlib.sha256(database.read_bytes()).hexdigest()
with read(database) as db:
    assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    row = db.execute(
        "SELECT r.*,c.wire,c.sequence AS cp_sequence,c.event_time_ms AS cp_time,"
        " c.data_revision AS cp_data_revision FROM runs r JOIN checkpoints c"
        " ON c.run_id=r.id AND c.revision=r.checkpoint_revision WHERE r.id=?", (run_id,)
    ).fetchone()
    assert (row["sequence"], row["event_time_ms"], row["data_revision"]) == (
        row["cp_sequence"], row["cp_time"], row["cp_data_revision"]
    )
    checkpoint = json.loads(row["wire"])
    account = checkpoint["engine"]["account"]
    equity = Decimal(account["quote_balance"]) + Decimal(account["position_qty"]) * Decimal(account["mark"])
    epoch = db.execute("SELECT epoch_id FROM active_continuous_epochs WHERE run_id=?", (run_id,)).fetchone()
    table, owner = ("epoch_result_items", epoch[0]) if epoch else ("result_items", run_id)
    fills = [json.loads(r[0]) for r in db.execute(
        f"SELECT wire FROM {table} WHERE run_id=? AND kind='fills' ORDER BY item_index", (owner,)
    )]
assert hashlib.sha256(database.read_bytes()).hexdigest() == fingerprint
print(json.dumps({
    "id": run_id, "sequence": row["sequence"], "eventTimeMs": row["event_time_ms"],
    "phase": row["phase"], "generation": row["generation"], "checkpointRevision": row["checkpoint_revision"],
    "databaseSha256": fingerprint, "equity": str(equity), "positionQty": account["position_qty"],
    "fills": fills, "researchRunAndReportUnchanged": True,
}))
