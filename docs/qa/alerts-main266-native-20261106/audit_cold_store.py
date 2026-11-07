"""QA-only, read-only cold alert JSON and recorded numeric-window audit.

Usage: python3 -B audit_cold_store.py /absolute/path/to/alerts-main266-native-20261106
"""
import json
import math
import sys
from pathlib import Path

from numeric_oracle import compute

root = Path(sys.argv[1])
receipt = json.loads((root / "native/acceptance.json").read_text())
assert receipt["passed"] and not receipt["errors"]
steps = receipt["steps"]
cold = [s["evidence"] for s in steps if s["name"] == "cold-alert-store-after-exit"]
assert len(cold) == 3
assert cold[1] == cold[2], "Disabled cold rules/history changed across second restart"
disk = json.loads((root / "native/profile/data/alerts.json").read_text())
assert disk == cold[-1], "Final cold JSON differs from recorded post-exit witness"
rules = disk["rules"]
assert len(rules) == 2 and all(not r["enabled"] for r in rules)
assert all(a["type"] in {"in_app", "history"} for r in rules
           for a in r["actions"] if a.get("enabled", True))
events = disk["history"]
assert len({e["id"] for e in events}) == len(events)
keys = [(e["ruleId"], json.dumps(e["evaluationCursor"], sort_keys=True)) for e in events]
assert len(set(keys)) == len(keys), "Duplicate accepted evaluation cursor"
assert any(e.get("acknowledgedAt") for e in events)
resumed = next(s["evidence"] for s in steps if s["name"] == "restarted-background-rule-admits-new-close")
active_before_restart = next(r for r in cold[0]["rules"] if r["enabled"])
saved_cursor = active_before_restart["lastAcceptedCursor"]
assert resumed["savedCursor"] == saved_cursor
assert resumed["values"]
for item in resumed["values"]:
    event = item["event"]
    assert event["ruleId"] == active_before_restart["id"]
    assert event["evaluationCursor"]["barTime"] > saved_cursor["barTime"]
checked = []
for step in steps:
    evidence = step["evidence"]
    items = evidence if isinstance(evidence, list) else evidence.get("values", []) if isinstance(evidence, dict) else []
    for item in items:
        if not isinstance(item, dict) or "canonicalRows" not in item:
            continue
        event = item["event"]
        assert int(item["canonicalRows"][-1]["time"]) * 1000 == event["evaluationCursor"]["barTime"]
        expected = compute(item["canonicalRows"])
        for key, value in expected.items():
            assert math.isclose(value, event["values"][key], rel_tol=1e-10, abs_tol=1e-9), key
        assert any(e["id"] == event["id"] and e["values"] == event["values"] for e in events)
        checked.append({"eventId": event["id"], "cursor": event["evaluationCursor"], "expected": expected})
assert len(checked) >= 4
# The packaged facade creates an outbox only when webhook delivery is configured.
assert not (root / "native/profile/data/alerts-outbox.sqlite3").exists()
assert all(d["type"] == "in_app" or d["status"] == "skipped"
           for e in events for d in e["dispatch"])
assert all(any(d["type"] == "in_app" and d["detail"] == "toast_rendered"
               for d in e["dispatch"]) for e in events)
result = {
    "scope": "Read-only final alert JSON, dispatch receipts, recorded canonical windows and independent arithmetic; no application imports",
    "coldExits": len(cold), "coldDisabledStateEqualAcrossRestart": True,
    "finalDiskEqualsColdWitness": True, "rules": len(rules), "events": len(events),
    "uniqueEvaluationCursors": True, "acknowledged": True,
    "savedCursor": saved_cursor,
    "newCursorsAfterRestart": [item["event"]["evaluationCursor"] for item in resumed["values"]],
    "independentlyCheckedWindows": checked, "localOnlyChannels": True,
    "webhookOutboxAbsent": True, "inAppToastReceipts": len(events),
    "externalDeliveryQualified": False,
}
(root / "independent-cold-and-numeric-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"coldExits": len(cold), "events": len(events), "checkedWindows": len(checked),
                  "uniqueEvaluationCursors": True, "webhookOutboxAbsent": True}))
