"""Retain the verified frontend/runtime and overlay the complete backend."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
candidate = root / "output/mixed-prefix-input-129-20261114/native-identity-candidate"
source = Path("/Users/ryanliang/.codex/worktrees/partial-first-paint-127-20261114/CandleScope/output/partial-first-paint-127-20261114/native-candidate")
prior = json.loads((source / "package-source-manifest.json").read_text())
retained = [*prior["retained_paths_unchanged"], "frontend/src", "frontend/scripts"]
assert not subprocess.check_output(["git", "diff", "--name-only", prior["product_head"], "HEAD", "--", *retained], cwd=root)
assert not subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "backend/app"], cwd=root)
app = candidate / "CandleScope.app"
assert not app.exists()
candidate.mkdir(parents=True, exist_ok=True)
subprocess.run(["cp", "-cR", str(source / "CandleScope.app"), str(app)], check=True)
resources = app / "Contents/Resources"
assert hashlib.sha256((resources / "app.asar").read_bytes()).hexdigest() == prior["app_asar_sha256"]
files = subprocess.check_output(["git", "ls-files", "backend/app"], cwd=root, text=True).splitlines()
hashes = {}
for name in files:
    target = resources / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / name, target)
    hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
assert not [str(path.relative_to(resources)) for path in (resources / "backend/app").rglob("*.py")
            if str(path.relative_to(resources)) not in hashes]
manifest = dict(product_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    scope="macOS arm64 retained verified runtime/plugins/desktop/frontend; complete tracked backend overlaid; not a fresh release build",
    retained_runtime_build=prior["retained_runtime_build"], frontend_source_head=prior["product_head"],
    retained_paths_unchanged=retained, source_app=str(source / "CandleScope.app"),
    files=hashes, frontend_dist=prior["frontend_dist"],
    app_asar_sha256=prior["app_asar_sha256"])
(candidate / "package-source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
for name, command in [("sign", ["codesign", "--force", "--deep", "--sign", "-", str(app)]),
                      ("sign-before", ["codesign", "--verify", "--deep", "--strict", str(app)])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (candidate / (name + ".log")).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
print(f"Verified {len(hashes)} backend files, unchanged frontend ASAR and strict signature")
