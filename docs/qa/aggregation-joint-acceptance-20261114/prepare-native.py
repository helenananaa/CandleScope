"""Assemble a fresh app with the current complete backend; preserve all prior apps."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
output = root / 'output/aggregation-joint-acceptance-20261114/native-candidate'
source = Path('/Users/ryanliang/.codex/worktrees/realtime-forming-retention-129-20261113/CandleScope/output/realtime-forming-retention-129-20261113/native/CandleScope.app')
app = output / 'CandleScope.app'
assert not app.exists()
output.mkdir(parents=True, exist_ok=True)
baseline = 'ef8f0e0fa6df299a823f4460b701eb1c3c98361f'
unchanged = ['frontend', 'packages/candlescope-control', 'backend/requirements.txt',
             'backend/requirements-parquet.txt', 'backend/ccxt-fork.lock.json']
assert not subprocess.check_output(['git', 'diff', '--name-only', baseline, 'HEAD', '--', *unchanged], cwd=root)
subprocess.run(['cp', '-cR', str(source), str(app)], check=True)
resources = app / 'Contents/Resources'
files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=root, text=True).splitlines()
hashes = {}
for name in files:
    target = resources / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / name, target)
    hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
extra = sorted(str(path.relative_to(resources)) for path in (resources / 'backend/app').rglob('*.py')
               if str(path.relative_to(resources)) not in hashes)
assert not extra, extra
manifest = dict(product_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    scope='macOS arm64 retained runtime/plugins and unchanged frontend; complete tracked backend overlaid; not a fresh release build',
    frontend_runtime_build=baseline, source_app=str(source), frontend_and_dependency_paths_unchanged=unchanged,
    files=hashes, app_asar_sha256=hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest())
(output / 'package-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
for name, command in [('sign', ['codesign', '--force', '--deep', '--sign', '-', str(app)]),
                      ('sign-before', ['codesign', '--verify', '--deep', '--strict', str(app)])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (output / (name + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
print(f'Verified {len(hashes)} backend files, unchanged frontend/dependency paths and strict signature')
