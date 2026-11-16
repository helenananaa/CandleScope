"""Verify the retained candidate after all owned native processes exit."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
output = root / "output/partial-first-paint-127-20261114"
candidate = output / "native-candidate"
manifest = json.loads((candidate / "package-source-manifest.json").read_text())
resources = candidate / "CandleScope.app/Contents/Resources"
for name, expected in manifest["files"].items():
    assert hashlib.sha256((resources / name).read_bytes()).hexdigest() == expected, name
assert hashlib.sha256((resources / "app.asar").read_bytes()).hexdigest() == manifest["app_asar_sha256"]
result = subprocess.run(["codesign", "--verify", "--deep", "--strict",
                         str(candidate / "CandleScope.app")], capture_output=True, text=True)
(candidate / "sign-after.log").write_text(result.stdout + result.stderr)
assert result.returncode == 0
receipts = []
for name in ("native-cold", "native-single-cold"):
    receipt = json.loads((output / name / "acceptance.json").read_text())
    assert receipt["sourceCommit"] == manifest["product_head"]
    assert not receipt.get("cleanupFailure")
    exits = [step for step in receipt["steps"] if step["name"] == "full-process-exit"]
    assert len(exits) == 1
    receipts.append(dict(run=name, passed=receipt["passed"],
                         owned_processes_exited=len(exits[0]["evidence"]["processes"])))
report = dict(product_head=manifest["product_head"], backend_files=len(manifest["files"]),
              asar_sha256=manifest["app_asar_sha256"], signature="strict pass", native=receipts)
(output / "package-after.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
