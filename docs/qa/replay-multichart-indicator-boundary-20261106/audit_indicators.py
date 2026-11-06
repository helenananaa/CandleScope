"""Audit actual Native transport and rendered legends using only CSV/Decimal."""
import csv
import json
import re
import sys
from decimal import Decimal as D
from pathlib import Path

root = Path(sys.argv[1])
receipt = json.loads((root / "acceptance.json").read_text())
identities = json.loads((root / "multimarket-identities.json").read_text())
computations = json.loads((root / "indicator-computations.json").read_text())
assert receipt["passed"] and not receipt["errors"]
tracks = {t["track_id"]: t for t in identities["tracks"]}
initial = next(s["evidence"]["afterAdd"] for s in receipt["steps"]
               if s["name"] == "two-imported-markets-added-through-native-ui")
source = {}
for tid, track in tracks.items():
    filename = "imported-replay.csv" if track["symbol"] == "BTCUSDT" else "second-replay.csv"
    with (root / filename).open() as stream:
        source[tid] = [{"time": int(row["time"]), **{k: D(row[k]) for k in
                        ("open", "high", "low", "close", "volume")}}
                       for row in csv.DictReader(stream)]
    assert len(source[tid]) == 6000
    assert max(row["high"] for row in source[tid]) >= 1000000


def projection(tid, interval, boundary):
    """Aggregate only already closed imported one-minute bars, including a partial display bucket."""
    width = {"1m": 60000, "5m": 300000}[interval]
    grouped = {}
    for row in source[tid]:
        if row["time"] + 59999 > boundary:
            continue
        bucket = row["time"] // width * width
        grouped.setdefault(bucket, []).append(row)
    return [(bucket, {"open": rows[0]["open"], "high": max(r["high"] for r in rows),
                      "low": min(r["low"] for r in rows), "close": rows[-1]["close"],
                      "volume": sum(r["volume"] for r in rows), "rows": rows})
            for bucket, rows in sorted(grouped.items())]


def ma_values(projected):
    return {at: sum(v["close"] for _, v in projected[index - 4:index + 1]) / D(5)
            for index, (at, _) in enumerate(projected) if index >= 4}


input_rows = output_points = partial_rows = 0
bindings = set()
for observation in computations:
    assert "observationError" not in observation, observation
    request, response = observation["request"], observation["response"]
    assert observation["status"] == 200 and response["status"] == "ready"
    tid, interval, boundary = (request[k] for k in
                               ("track_id", "display_interval", "revealed_boundary_ms"))
    track = tracks[tid]
    assert observation["url"].endswith("/" + track["adapter_session_id"] + "/indicator-compute")
    assert request["name"] == "MA" and request["params"] == {"period": 5}
    assert request["data_epoch"] == initial[tid]["data_epoch"]
    seed = response["seed"]
    assert seed["run_id"] == identities["runId"] and seed["session_id"] == track["adapter_session_id"]
    assert seed["track_id"] == tid and seed["data_epoch"] == request["data_epoch"]
    assert seed["identity"]["exchange"] == track["exchange"]
    assert seed["identity"]["symbol"] == track["symbol"]
    assert seed["identity"]["display_interval"] == interval
    expected = projection(tid, interval, boundary)
    buckets = dict(expected)
    averages = ma_values(expected)
    requested = set()
    for bar in request["bars"]:
        at = bar["open_time_ms"]
        requested.add(at)
        independent = buckets[at]
        for key in ("open", "high", "low", "close", "volume"):
            assert D(bar[key]) == independent[key], (tid, interval, boundary, key, bar, independent)
        assert bar["last_base_open_ms"] == independent["rows"][-1]["time"]
        assert bar["first_base_open_ms"] == independent["rows"][0]["time"]
        assert bar["last_base_open_ms"] + 59999 <= boundary
        assert bar["component_count"] == len(independent["rows"])
        assert bar["expected_components"] == {"1m": 1, "5m": 5}[interval]
        if not bar["is_closed"]:
            partial_rows += 1
            assert bar["close_time_ms"] > boundary
        else:
            assert bar["close_time_ms"] <= boundary
        input_rows += 1
    payload = response["payload"]
    assert payload["ok"] and not payload["error"] and len(payload["lines"]) == 1
    for point in payload["lines"][0]["data"]:
        at = point["time"] * 1000
        assert at in requested
        assert abs(D(str(point["value"])) - averages[at]) < D("0.000000001"), (point, averages[at])
        output_points += 1
    bindings.add((tid, interval, boundary))
assert len(computations) >= 4 and partial_rows > 0 and input_rows > 0 and output_points > 0
assert {i for _, i, _ in bindings} == {"1m", "5m"}
assert {t for t, _, _ in bindings} == set(tracks)

rendered = []
steps = receipt["steps"]
initial_boundary = initial["track-1"]["cursor"]["virtual_time_ms"]
latest_boundary = max(s["evidence"]["review"]["projection"]["cursor"]["virtual_time_ms"]
                      for s in steps if s["name"] == "native-review-track-and-version")
for index, step in enumerate(steps):
    if not step["name"].startswith("actual-indicator-legends-"):
        continue
    if "-review-" in step["name"]:
        # The actual jump response immediately following these observations
        # supplies its immutable selected time; it is not the live parent time.
        following = steps[index + 1]
        assert following["name"] == "native-review-track-and-version"
        boundary = following["evidence"]["review"]["projection"]["cursor"]["virtual_time_ms"]
    else:
        boundary = initial_boundary if step["name"].endswith("-initial") else latest_boundary
    for row in step["evidence"]:
        tid = row["track"]
        interval = "1m" if step["name"].endswith("-initial") or tracks[tid]["symbol"] == "ETHUSDT" else "5m"
        projected = projection(tid, interval, boundary)
        at, bar = projected[-1]
        expected = ma_values(projected)[at]
        assert len(row["numbers"]) == 1
        actual = D(row["numbers"][0].replace(",", ""))
        assert abs(actual - expected) <= D("0.00005"), (step["name"], row, expected)
        for label, key in [("开盘", "open"), ("最高", "high"), ("最低", "low"), ("收盘", "close")]:
            match = re.search(label + r"\s*([\d,.]+)", row["legend"])
            assert match and D(match[1].replace(",", "")) == bar[key], (row, key, bar)
        rendered.append({"stage": step["name"], "track": tid, "interval": interval,
                         "boundary": boundary, "lastBucket": at, "expectedMA5": str(expected),
                         "renderedMA5": str(actual), "lastRevealedBaseOpen": bar["rows"][-1]["time"]})
assert len(rendered) == 22
assert {r["boundary"] for r in rendered} == {initial_boundary, latest_boundary}
result = {"passed": True, "source": receipt["sourceCommit"], "oracle": "stdlib CSV/Decimal only; no application imports",
          "computations": len(computations), "inputRows": input_rows, "outputPoints": output_points,
          "partialDisplayRows": partial_rows, "renderedObservations": rendered,
          "scope": "two imported BAR sources, MA5, 1m/5m, actual live/review/restart legends and canonical transport; not other indicator engines or all future-data scenarios"}
(root / "independent-indicator-oracle.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "renderedObservations"}))
