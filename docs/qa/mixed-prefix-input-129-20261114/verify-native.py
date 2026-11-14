"""Check retained source, ASAR, signatures and full owned-process exits."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
output = root / "output/mixed-prefix-input-129-20261114"
baseline = Path("/Users/ryanliang/.codex/worktrees/partial-first-paint-127-20261114/CandleScope/output/partial-first-paint-127-20261114/native-candidate")
candidate = output / "native-identity-candidate"
reports = []
for name, directory in (("baseline", baseline), ("candidate", candidate)):
    manifest = json.loads((directory / "package-source-manifest.json").read_text())
    app = directory / "CandleScope.app"
    resources = app / "Contents/Resources"
    for source, expected in manifest["files"].items():
        assert hashlib.sha256((resources / source).read_bytes()).hexdigest() == expected, source
    assert hashlib.sha256((resources / "app.asar").read_bytes()).hexdigest() == manifest["app_asar_sha256"]
    result = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                            capture_output=True, text=True)
    (output / (name + "-sign-after.log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
    reports.append(dict(candidate=name, product_head=manifest["product_head"],
                        backend_files=len(manifest["files"]), asar_sha256=manifest["app_asar_sha256"],
                        signature="strict pass"))
receipts = []
for run in ("native-baseline-cold", "native-budget-diagnostic", "native-identity-cold"):
    receipt = json.loads((output / run / "acceptance.json").read_text())
    assert not receipt.get("cleanupFailure")
    exits = [step for step in receipt["steps"] if step["name"] == "full-process-exit"]
    assert len(exits) == 1
    expected_head = reports[1 if run == "native-identity-cold" else 0]["product_head"]
    assert receipt["sourceCommit"] == expected_head
    receipts.append(dict(run=run, product_head=expected_head, passed=receipt["passed"],
                         owned_processes_exited=len(exits[0]["evidence"]["processes"])))
report = dict(packages=reports, observations=receipts)
(output / "package-after.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
