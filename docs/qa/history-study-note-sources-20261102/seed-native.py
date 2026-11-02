"""Controlled historical-note fixture on real committed public-market history.

Only the explicitly owned QA profile is written. Synthetic note save times
exercise temporal projections; no human historical-authorship claim is made.
"""
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import time

from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore

root = Path(__file__).resolve().parents[3]
source, out = (Path(value).resolve() for value in sys.argv[1:])
assert out.is_relative_to(root / "output")
destination = out / "profile/data/candlescope.db"
assert not destination.exists(), "Preserve previous QA profiles"
commands = subprocess.check_output(["ps", "-axo", "command="], text=True).splitlines()
assert not any(command.strip().startswith(str(source.parents[2] / "Installed App/CandleScope.app") + "/") for command in commands)
assert not any(command.strip().startswith(str(out / "Installed App/CandleScope.app") + "/") for command in commands)
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as before, sqlite3.connect(destination) as after:
    before.backup(after)
    times = [row[0] for row in after.execute(
        "SELECT open_time FROM klines WHERE exchange='binance' AND market_type='spot' "
        "AND provider_id='binance' AND venue='binance' AND asset_class='crypto' "
        "AND series_variant='native' AND price_adjustment='raw' AND session_variant='continuous' "
        "AND volume_semantics='base_asset' AND symbol='BTCUSDT' AND interval='1m' ORDER BY open_time")]
runs, current = [], []
for stamp in times:
    if current and stamp != current[-1] + 60_000:
        runs.append(current)
        current = []
    current.append(stamp)
runs.append(current)
selected = max(runs, key=len)[-160:]
assert len(selected) == 160 and selected[-1] < int(time.time() * 1000)

class Clock:
    now = selected[0] - 1000
    def __call__(self):
        return self.now

class NoMarket:
    def latest_bar(self, *_args):
        raise AssertionError("Fixture must not read market marks")
    def bars(self, *_args):
        raise AssertionError("Fixture must not read market history")

clock = Clock()
store = TradingStore(out / "profile/data/trading-accounts.sqlite3")
service = TradingAccountService(store, snapshot_dir=out / "profile/data/trading-snapshots", market=NoMarket(), clock=clock)
instrument = {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT"}
try:
    a = service.create_account({"kind": "manual", "name": "Native source A"})
    b = service.create_account({"kind": "manual", "name": "Native source B"})
    clock.now = selected[30] + 1
    original = service.create_entry(a["id"], {**instrument, "kind": "quick", "body": "Native original version one"})
    clock.now = selected[110] + 1
    service.save_entry(original["id"], {"body": "Native original future version two"})
    clock.now = selected[130] + 1
    future = service.create_entry(a["id"], {**instrument, "kind": "quick", "body": "Native future-created note"})
    clock.now = int(time.time() * 1000)
    review = service.create_entry(a["id"], {**instrument, "kind": "quick", "body": "Native later source review", "marketTimeMs": selected[40] + 1})
    clock.now = selected[20] + 1
    legacy = service.create_entry(a["id"], {**instrument, "kind": "quick", "body": "Native unavailable latest text"})
    with store.transaction() as connection:
        connection.execute("UPDATE journal_revisions SET history_complete=0 WHERE entry_id=?", (legacy["id"],))
    clock.now = selected[10] + 1
    other = service.create_entry(b["id"], {**instrument, "kind": "quick", "body": "Native other account source"})
    counts = {table: store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in
              ("accounts", "orders", "fills", "cash_flows", "journal_entries", "journal_revisions")}
    assert counts == {"accounts": 2, "orders": 0, "fills": 0, "cash_flows": 0, "journal_entries": 5, "journal_revisions": 6}
finally:
    store.close()
receipt = {"schema": "candlescope.study-original-notes-fixture/1",
    "scope": "Synthetic note timestamps via real owning service; warm real public market DB; fresh QA study/financial/control state; no actual historical human-author claim",
    "source": str(source), "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "destinationSha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    "a": a["id"], "b": b["id"], "original": original["id"], "future": future["id"], "review": review["id"], "legacy": legacy["id"], "other": other["id"],
    "fromMs": selected[0], "toMs": selected[-1] + 60_000,
    "beforeMs": selected[100], "afterMs": selected[120], "earlyMs": selected[25], "counts": counts}
(out / "fixture.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
