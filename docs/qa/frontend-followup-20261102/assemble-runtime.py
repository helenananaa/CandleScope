"""Assemble the combined candidate without rebuilding unchanged engine binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument("source_app", type=Path)
parser.add_argument("plugin_assets", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
app = args.output.resolve() / "Installed App/CandleScope.app"
assert not app.exists(), "Preserve candidate attempts; use a new output"
subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT, check=True)
subprocess.run(["git", "diff", "--exit-code", "codex/python-indicator-author-20261101", "HEAD", "--",
                "backend/requirements.txt", "backend/requirements-parquet.txt", "backend/ccxt-fork.lock.json",
                "packages", "frontend/desktop", "frontend/scripts/desktop-plugin-sources.json",
                "frontend/scripts/prepare-desktop-plugins.py",
                # Repacked JavaScript only; engine/runtime and all other desktop
                # inputs retain the equality check. Source verifier covers ASAR.
                ":(exclude)frontend/desktop/workspace-bus-hub.mjs",
                ":(exclude)frontend/desktop/workspace-bus-hub.test.mjs"], cwd=ROOT, check=True)
assets = args.plugin_assets.resolve()
plugins = json.loads((assets / "manifest.json").read_text())
assert plugins["schemaVersion"] == 2
assert {item["runtimeId"] for item in plugins["plugins"]} == {"candlescope.pine-compat", "candlescope.python-indicator"}
assert len(plugins["plugins"]) == 2
for item in plugins["plugins"]:
    content = (assets / item["filename"]).read_bytes()
    assert len(content) == item["size"]
    assert "sha256:" + hashlib.sha256(content).hexdigest() == item["sha256"]
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(args.source_app)], check=True)
app.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["/bin/cp", "-cR", str(args.source_app), str(app)], check=True)
resources = app / "Contents/Resources"
shutil.rmtree(resources / "backend/app")
for name in subprocess.check_output(["git", "ls-files", "-z", "backend/app"], cwd=ROOT, text=True).split("\0"):
    if not name:
        continue
    destination = resources / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, destination)
shutil.rmtree(resources / "python-runtime/plugins")
subprocess.run(["/bin/cp", "-cR", str(assets), str(resources / "python-runtime/plugins")], check=True)
subprocess.run([str(resources / "python-runtime/python/bin/python3.12"), "-m", "compileall", "-q", str(resources / "backend/app")], check=True)
subprocess.run(["node", str(Path(__file__).with_name("repack-runtime.mjs")), str(app), str(args.output.resolve())], cwd=ROOT, check=True)
