"""Clone the qualified runtime/frontend and replace only current backend source."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BASE = "358e49965fef5504ab73d96933cd2c02705b7120"
ASAR_SHA = "4d838503f8311579468f69fa0da5d27b918590718230c26656a2aef0ebffad76"
parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
source = args.source.resolve()
output = args.output.resolve()
app = output / "Installed App/CandleScope.app"
assert not app.exists(), "Preserve existing candidates; choose a new output"
subprocess.run(["git", "diff", "--exit-code", BASE, "HEAD", "--", "frontend", "packages"], cwd=ROOT, check=True)
subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT, check=True)
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(source)], check=True)
source_asar = source / "Contents/Resources/app.asar"
assert hashlib.sha256(source_asar.read_bytes()).hexdigest() == ASAR_SHA
app.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["/bin/cp", "-cR", str(source), str(app)], check=True)
resources = app / "Contents/Resources"
shutil.rmtree(resources / "backend/app")
files = subprocess.check_output(["git", "ls-files", "-z", "backend/app"], cwd=ROOT, text=True).split("\0")
manifest = {}
for name in filter(None, files):
    destination = resources / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, destination)
    expected = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == expected, name
    manifest[name] = expected
subprocess.run([str(resources / "python-runtime/python/bin/python3.12"), "-m", "compileall", "-q", str(resources / "backend/app")], check=True)
assert hashlib.sha256((resources / "app.asar").read_bytes()).hexdigest() == ASAR_SHA
subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
receipt = {
    "sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "applicationSource": "4a981dac98d0df802b279f764c8e4d88d4a81bae",
    "assembly": "APFS clone of the source-verified official PR211 arm64 candidate; replace current tracked backend/app, compile with its bundled Python, retain byte-identical app.asar, deep ad-hoc sign and strictly verify. Not a fresh runtime or frontend build.",
    "sourceApp": str(source),
    "candidateApp": str(app),
    "inheritedAsarSha256": ASAR_SHA,
    "frontendAndPackagesUnchangedFrom": BASE,
    "backendFiles": manifest,
    "mismatches": [],
}
(output / "assembly.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"app": str(app), "backendFiles": len(manifest), "mismatches": []}))
