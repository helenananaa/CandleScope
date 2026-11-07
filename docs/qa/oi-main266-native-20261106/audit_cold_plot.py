"""Independently compare recorded cold rows, read-only SQLite and actual pane points.

Usage: python3 audit_cold_plot.py /absolute/path/to/oi-main266-native-20261106
The supplied directory contains native/acceptance.json and native/profile/data/market.db.
No application projection or indicator code is imported.
"""
import json
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1])
receipt = json.loads((root / "native/acceptance.json").read_text())
assert receipt["passed"] and not receipt["errors"]

def step(name):
    return next(s["evidence"] for s in receipt["steps"] if s["name"] == name)

before = step("cold-storage-before-restart")
after = step("cold-storage-after-restart")
span = step("restart-restored")["range"]
assert len(before["rows"]) == 48
assert before["rows"] == after["rows"], "Cold full-row witnesses differ"
assert all(r in after["receipts"] for r in before["receipts"])
db = root / "native/profile/data/market.db"
with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as con:
    con.row_factory = sqlite3.Row
    assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    current = [dict(r) for r in con.execute(
        "SELECT * FROM open_interest_history WHERE exchange=? AND market_type=? "
        "AND symbol=? AND period=? AND event_time_ms BETWEEN ? AND ? ORDER BY event_time_ms",
        ("binance", "futures", "BTCUSDT", "5m", span["start"], span["end"]),
    )]
assert current == before["rows"], "Read-only disk rows differ from saved witness"
pane = step("actual-oi-pane-values-after-restart")
points = {round(p["time"] * 1000): p["value"] for p in pane["points"]}
matches = []
for row in current:
    event = row["event_time_ms"]
    assert event in points, f"Missing rendered event {event}"
    assert points[event] == row["open_interest"], f"Rendered value differs at {event}"
    matches.append({"event_time_ms": event, "storedValue": row["open_interest"],
                    "plottedValue": points[event]})
result = {
    "scope": "Read-only direct SQLite cold witness and captured actual renderer line; no application projection imports",
    "requestedRange": span, "rows": len(current),
    "allFullRowsEqualAcrossExitRestart": True,
    "allCurrentDiskRowsEqualSavedWitness": True,
    "allRequestedRowsPlottedAfterRestart": True, "pointMatches": matches,
    "paneCountsBeforeAfter": [step("actual-oi-pane-values-before-exit")["pointCount"], pane["pointCount"]],
    "queryReceiptCount": len(before["receipts"]),
    "rawTimeGridRemainders": sorted({r["event_time_ms"] % 300000 for r in current}),
    "qualificationLimit": "All48 observed Binance event times are5m-aligned; no new Native non-aligned timestamp or whole-visible-chart coverage claim. Visible legend may follow crosshair or provisional updates.",
}
(root / "independent-cold-and-plot-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"rows": len(current), "allRequestedRowsPlottedAfterRestart": True,
                  "sqliteQuickCheck": "ok"}))
