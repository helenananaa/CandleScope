"""Generate immutable c1 boundary rules from the pinned IANA distribution.

Run with tzdata==2026.3. Regenerating different rules requires a new wire
version; never overwrite c1 after publication. The identical JSON is shipped
with Python and the browser so OS/browser tzdb updates cannot alter buckets.
"""
import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo
import tzdata

assert tzdata.__version__ == "2026.3" and tzdata.IANA_VERSION == "2026c"
root = Path(__file__).resolve().parents[2]
start = int(datetime(1969, 1, 1, tzinfo=timezone.utc).timestamp())
end = int(datetime(2402, 1, 1, tzinfo=timezone.utc).timestamp())
result = dict(schema="calendar-basis-rules/1", iana_version="2026c", wire_version="c1",
              min_time_ms=0, max_time_ms=int(datetime(2400, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
              boundary_policy="reject-ambiguous-or-nonexistent", zones={})
for name in ("UTC", "Asia/Shanghai", "America/New_York"):
    with files("tzdata.zoneinfo").joinpath(name).open("rb") as stream:
        zone = ZoneInfo.from_file(stream, key=name)
    def offset(at):
        return int(datetime.fromtimestamp(at, timezone.utc).astimezone(zone).utcoffset().total_seconds())
    previous, transitions = offset(start), [[start, offset(start)]]
    for at in range(start + 86400, end + 1, 86400):
        current = offset(at)
        if current != previous:
            lo, hi = at - 86400, at
            while hi - lo > 1:
                middle = (lo + hi) // 2
                if offset(middle) == previous: lo = middle
                else: hi = middle
            transitions.append([hi, current])
        previous = current
    result["zones"][name] = transitions
payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
for path in (root / "backend/app/data_engine/basis_rules/calendar-v1.json", root / "frontend/data/calendar-v1.json"):
    path.write_text(payload)
print({"version": result["iana_version"], "bytes": len(payload), "zones": {k: len(v) for k,v in result["zones"].items()}})
