"""Reuse committed public-market QA history in a fresh study/control profile."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
source, output = (Path(arg).resolve() for arg in sys.argv[1:])
assert source.is_relative_to(root / "output") and source.name == "candlescope.db"
assert output.is_relative_to(root / "output")
processes = subprocess.check_output(["ps", "-axo", "command="], text=True)
assert str(source.parents[2] / "Installed App") not in processes
assert str(output / "Installed App") not in processes
destination = output / "profile/data/candlescope.db"
assert not destination.exists(), "Preserve previous profiles"
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as before:
    rows = before.execute("SELECT COUNT(*) FROM klines").fetchone()[0]
    with sqlite3.connect(destination) as after:
        before.backup(after)
        assert after.execute("SELECT COUNT(*) FROM klines").fetchone()[0] == rows
receipt = {"kind": "Warm public-market database only; fresh study, financial and control state. No cold-history claim.",
           "source": str(source), "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "destinationSha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "rows": rows}
(output / "market-seed.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
