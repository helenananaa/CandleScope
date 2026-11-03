"""Rebuild the current Python bridge; reuse only the verified identical SDK wheel."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[3]
old, out = (Path(value).resolve() for value in sys.argv[1:])
assert not out.exists(), "Preserve previous attempts"
shutil.copytree(old, out)
wheels = out / "rebuilt-python-wheels"
wheels.mkdir()
def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value
def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
lock = json.loads((old / "python-indicator.lock.json").read_text())
manifest = json.loads((old / "manifest.json").read_text())
entry = next(row for row in manifest["plugins"] if row["runtimeId"] == "candlescope.python-indicator")
source = module(ROOT / "frontend/scripts/prepare-desktop-plugins.py", "current_sources")
assert lock["sdkSourceSha256"] == source.source_digest(ROOT / "packages/candlescope-plugin-sdk")
sdk = next(row for row in lock["wheels"] if row["filename"].startswith("candlescope_plugin_sdk-"))
with zipfile.ZipFile(old / entry["filename"]) as archive:
    (wheels / sdk["filename"]).write_bytes(archive.read("wheels/" + sdk["filename"]))
assert sha(wheels / sdk["filename"]) == sdk["sha256"]
subprocess.run([str(Path.home() / ".local/bin/uv"), "build", "--wheel", "--python", sys.executable,
                "--out-dir", str(wheels), str(ROOT / "packages/candlescope-plugin-python-indicator")], check=True)
canonicalizer = module(ROOT / "packages/candlescope-plugin-pine-compat/scripts/canonicalize_wheel.py", "current_canonicalizer")
bridge = next(wheels.glob("candlescope_plugin_python_indicator-*.whl"))
canonicalizer.canonicalize(bridge)
builder = module(ROOT / "packages/candlescope-plugin-python-indicator/scripts/build_bundle.py", "current_python_builder")
# Existing bundles remain in old; the new output copy is replaced only by the formal builder.
(out / entry["filename"]).unlink()
result = builder.build([bridge, wheels / sdk["filename"]], out / entry["filename"])
entry.update(sha256=result.sha256, size=result.size)
lock.update(sourceSha256=source.source_digest(ROOT / "packages/candlescope-plugin-python-indicator"),
            wheels=[{"filename": file.name, "sha256": sha(file)} for file in sorted(wheels.glob("*.whl"))])
(out / "python-indicator.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"manifest": manifest, "pythonLock": lock}))
shutil.rmtree(wheels)
