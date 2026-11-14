"""Verify retained packages, diagnostic source and full-process exits."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
output = root / "output/seed-admission-evidence-129-20261115"
baseline = Path("/Users/ryanliang/.codex/worktrees/mixed-prefix-input-129-20261114/CandleScope/output/mixed-prefix-input-129-20261114/native-identity-candidate")
candidate = output / "native-dispatch-candidate"
packages = []
for name, directory in (("trace-baseline", baseline), ("dispatch-candidate", candidate)):
    manifest = json.loads((directory / "package-source-manifest.json").read_text())
    app = directory / "CandleScope.app"
    resources = app / "Contents/Resources"
    for path, expected in manifest["files"].items():
        assert hashlib.sha256((resources / path).read_bytes()).hexdigest() == expected, path
    assert hashlib.sha256((resources / "app.asar").read_bytes()).hexdigest() == manifest["app_asar_sha256"]
    result = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                            capture_output=True, text=True)
    (output / (name + "-sign-after.log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
    packages.append(dict(name=name, product_head=manifest["product_head"],
                         backend_files=len(manifest["files"]), asar_sha256=manifest["app_asar_sha256"],
                         signature="strict pass"))
driver_hash = hashlib.sha256((qa / "native.mjs").read_bytes()).hexdigest()
observations = []
for index, run in enumerate(("native-diagnostic", "native-dispatch-cold")):
    receipt = json.loads((output / run / "acceptance.json").read_text())
    assert receipt["sourceCommit"] == packages[index]["product_head"]
    assert receipt["driverSha256"] == driver_hash
    assert receipt["diagnosticLogging"] == (index == 0)
    assert not receipt.get("cleanupFailure")
    exits = [step for step in receipt["steps"] if step["name"] == "full-process-exit"]
    assert len(exits) == 1
    observations.append(dict(run=run, source=receipt["sourceCommit"], passed=receipt["passed"],
                             diagnostic=receipt["diagnosticLogging"],
                             owned_processes_exited=len(exits[0]["evidence"]["processes"])))
report = dict(packages=packages, observations=observations, driver_sha256=driver_hash,
              retained_bootstrap_sha256=hashlib.sha256((qa / "bootstrap/sitecustomize.py").read_bytes()).hexdigest())
(output / "package-after.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
