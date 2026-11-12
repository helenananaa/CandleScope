"""Compare the migrated backend against the retained offline display oracle."""
from __future__ import annotations

import json
import math
from pathlib import Path
import random
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticKernel


def main():
    root = Path(__file__).resolve().parents[2]
    generator = random.Random(150)
    cases = []
    for size in (1, 2, 14, 100, 1500):
        for precision in (0, 2, 8):
            rows = []
            price = 100.0
            for index in range(size):
                opening = price
                price = round(price + generator.uniform(-3, 3), precision)
                rows.append(dict(time=1_700_000_040 + index * 60, open=opening,
                    close=price, high=round(max(opening, price) + 1, precision),
                    low=round(min(opening, price) - 1, precision), volume=2, is_closed=index < size - 1))
            for transform, mode in (("heikin-ashi", "traditional"), ("renko", "traditional"), ("renko", "atr")):
                cases.append(dict(transform=transform, settings=dict(mode=mode, boxSize=2, atrLength=14), rows=rows))
    result = subprocess.run([str(root / "frontend/node_modules/.bin/tsx"),
        str(root / "frontend/scripts/synthetic-reference.mts")],
        input=json.dumps(cases), text=True, capture_output=True, check=True, cwd=root)
    expected = json.loads(result.stdout)
    count = 0
    for case, reference in zip(cases, expected, strict=True):
        kernel = SyntheticKernel(SyntheticConfig(case["transform"], mode=case["settings"]["mode"], box_size=2))
        actual = kernel.replace(case["rows"])
        assert len(actual) == len(reference), (case["transform"], len(case["rows"]), len(actual), len(reference))
        for left, right in zip(actual, reference, strict=True):
            assert left["time"] == right["time"]
            for field in ("open", "high", "low", "close", "volume"):
                assert (field in left) == (field in right)
                if field in left:
                    assert math.isclose(left[field], right[field], rel_tol=1e-12, abs_tol=1e-8), (field, left, right)
            lm = left["customValues"]["chartProjection"]
            rm = right["customValues"]["chartProjection"]
            for field in ("projectorId", "sourceFromTime", "sourceToTime", "sourceOrdinal", "synthetic"):
                assert lm[field] == rm[field], (field, left, right)
            if case["transform"] == "renko":
                assert lm["provisional"] == rm["provisional"]
                assert left["customValues"]["renko"] == right["customValues"]["renko"]
            count += 1
    print(json.dumps({"status": "PASS", "cases": len(cases), "output_rows": count,
        "scope": "offline Python vs retained TypeScript display oracle; not native/performance acceptance"}))


if __name__ == "__main__":
    main()
