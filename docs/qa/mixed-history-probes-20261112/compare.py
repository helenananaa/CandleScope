"""Validate two reports from the #367 source-default runner; emit work counts."""
import json
from pathlib import Path
import sys

before, after = (json.loads(Path(path).read_text()) for path in sys.argv[1:3])
assert len(before["results"]) == len(after["results"]) == 48
identity = ("period", "mode", "repeat", "phase", "range", "input_rows", "returned", "complete", "max_abs_delta")
for left, right in zip(before["results"], after["results"]):
    assert all(left[k] == right[k] for k in identity)
    assert left["complete"] and right["complete"]
    assert right["metadata"]["storage_reads"] <= left["metadata"]["storage_reads"]
    assert right["memory"]["reserved_bytes"] == 0
    assert all(right["blocks"][k] == 0 for k in ("leases", "views", "inflight", "retired_entries"))
summary = []
for period in (89, 97, 101, 10007):
    for mode in ("mixed_only", "fine_only"):
        select = dict(period=period, mode=mode, phase="target_absent")
        a, b = (next(r for r in report["results"] if r["repeat"] == 1 and all(r[k] == v for k, v in select.items()))
                for report in (before, after))
        av, bv = (next(r for r in report["summary"] if all(r[k] == v for k, v in select.items()))
                  for report in (before, after))
        summary.append(dict(period=period, mode=mode,
            canonical_sql_calls=[a["metadata"]["storage_reads"], b["metadata"]["storage_reads"]],
            candle_rows=[a["metadata"].get("mixed_page_rows"), b["metadata"].get("mixed_page_rows")],
            median_ms=[av["median_ms"], bv["median_ms"]]))
print(json.dumps(dict(paired_calls=48, final_bars=sum(r["returned"] for r in after["results"]),
                     passed=True, summary=summary), indent=2))
