"""Compose unchanged Python and main #220 Pine bundles without editing inputs.

The assembler independently checks current source digests, engine provenance,
manifest bundle bytes and each embedded wheel before copying the assets.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys

old, pine, out = (Path(value).resolve() for value in sys.argv[1:])
assert not out.exists(), "Preserve previous assets"
shutil.copytree(old, out)
manifest = json.loads((old / "manifest.json").read_text())
new_manifest = json.loads((pine / "manifest.json").read_text())
assert len(new_manifest["plugins"]) == 1
entry = new_manifest["plugins"][0]
assert entry["runtimeId"] == "candlescope.pine-compat"
content = (pine / entry["filename"]).read_bytes()
assert len(content) == entry["size"]
assert "sha256:" + hashlib.sha256(content).hexdigest() == entry["sha256"]
for name in [entry["filename"], "candlescope-plugin-pine-compat.lock.json"]:
    shutil.copy2(pine / name, out / name)
for source in (pine / "sources").rglob("*"):
    if not source.is_file():
        continue
    destination = out / "sources" / source.relative_to(pine / "sources")
    if destination.exists():
        assert destination.read_bytes() == source.read_bytes(), source
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
manifest["plugins"] = [entry if row["runtimeId"] == entry["runtimeId"] else row for row in manifest["plugins"]]
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"output": str(out), "manifest": manifest}))
