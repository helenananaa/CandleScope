"""Independently reconcile the five simulated fills after the native app exits."""
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
receipt = json.loads((root / "acceptance.json").read_text())
assert receipt["passed"]
steps = {step["name"]: step["evidence"] for step in receipt["steps"]}
account = steps["saved"]["account"]
database = root / "profile/data/trading-accounts.sqlite3"
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    rows = db.execute("SELECT symbol, position_side, side, price, qty, fee FROM fills "
                      "WHERE account_id = ? ORDER BY seq", (account,)).fetchall()
    leverage = Decimal(json.loads(db.execute("SELECT settings_json FROM accounts WHERE id = ?", (account,)).fetchone()[0])["leverage"])
assert len(rows) == 5
long_open, short_open, eth_open, long_close, short_close = rows
assert [(symbol, leg, side) for symbol, leg, side, *_ in rows] == [
    ("BTCUSDT", "LONG", "buy"), ("BTCUSDT", "SHORT", "sell"), ("ETHUSDT", "LONG", "buy"),
    ("BTCUSDT", "LONG", "sell"), ("BTCUSDT", "SHORT", "buy"),
]
def pnl(entry, close, direction):
    assert Decimal(entry[4]) == Decimal(close[4])
    return direction * (Decimal(close[3]) - Decimal(entry[3])) * Decimal(close[4])

long_pnl = pnl(long_open, long_close, 1)
short_pnl = pnl(short_open, short_close, -1)
initial = Decimal("1000000")
balance_before_restart = initial + long_pnl - sum(Decimal(row[5]) for row in rows[:4])
final_balance = balance_before_restart + short_pnl - Decimal(short_close[5])
assert balance_before_restart == Decimal(steps["saved"]["balance"])
assert final_balance == Decimal(steps["restored-and-closed-short"]["balance"])
held = steps["held"]
positions = held["positions"]
gross_margin = sum(Decimal(p["openQty"]) * Decimal(p["markPrice"]) / leverage for p in positions)
assert gross_margin == Decimal(held["usedMargin"])
print(json.dumps({"savedBalance": str(balance_before_restart), "finalBalance": str(final_balance),
                  "grossMarginWithThreePositions": str(gross_margin), "fillCount": len(rows)}))
