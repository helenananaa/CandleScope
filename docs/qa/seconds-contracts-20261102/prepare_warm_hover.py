"""Preserve a completed cold qualification before reopening its QA profile."""
from pathlib import Path
import json
import os
import shutil
import subprocess

source = Path(os.environ["CANDLESCOPE_COLD_QA_ROOT"]).resolve()
target = Path(os.environ["CANDLESCOPE_BATCH1_QA_ROOT"]).resolve()
receipt = json.loads((source / "acceptance.json").read_text())
manifest = json.loads((source / "source-package-manifest.json").read_text())
assert receipt.get("passed") is True
assert receipt["sourceCommit"] == manifest["sourceCommit"]
assert not target.exists(), "Preserve prior hover receipts"
profile = source / "profile"
processes = subprocess.check_output(["ps", "-axo", "args="], text=True)
assert not any(str(profile) in row for row in processes.splitlines()), "QA profile is still running"
target.mkdir(parents=True)
snapshot = target / "profile-snapshot-before-hover"
subprocess.run(["/bin/cp", "-cR", str(profile), str(snapshot)], check=True)
# Keep the verified immutable app at its original path: profile plugin venvs
# may refer to its bundled Python. No second runtime/app copy is necessary.
(target / "Installed App").symlink_to(source / "Installed App", target_is_directory=True)
for original, copied in [("acceptance.json", "original-acceptance.json"),
                         ("source-package-manifest.json", "source-package-manifest.json")]:
    shutil.copy2(source / original, target / copied)
(target / "profile-provenance.json").write_text(json.dumps({
    "sourceCommit": manifest["sourceCommit"], "profileRoot": str(profile),
    "snapshot": str(snapshot), "coldQualification": str(source / "acceptance.json"),
    "scope": "Warm reopen; original cold receipt and pre-hover profile snapshot preserved",
}, indent=2) + "\n")
print(json.dumps({"prepared": str(target), "profile": str(profile), "snapshot": str(snapshot)}))
