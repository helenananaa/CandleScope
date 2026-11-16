"""Retain the native runtime, overlay complete backend and freshly built frontend."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
output = root / 'output/mixed-history-viewport-127-20261114' / os.environ.get('CANDLESCOPE_NATIVE_CANDIDATE', 'native-candidate')
source = Path('/Users/ryanliang/.codex/worktrees/aggregation-joint-acceptance-20261114/CandleScope/output/aggregation-joint-acceptance-20261114/native-candidate/CandleScope.app')
app = output / 'CandleScope.app'
assert not app.exists()
output.mkdir(parents=True, exist_ok=True)
baseline = 'ef8f0e0fa6df299a823f4460b701eb1c3c98361f'
retained = ['frontend/desktop', 'frontend/package.json', 'frontend/package-lock.json',
            'packages/candlescope-control', 'backend/requirements.txt',
            'backend/requirements-parquet.txt', 'backend/ccxt-fork.lock.json']
assert not subprocess.check_output(['git', 'diff', '--name-only', baseline, 'HEAD', '--', *retained], cwd=root)
assert not subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '--', 'backend/app', 'frontend/src'], cwd=root)
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
unpacked = output / 'asar-input'
subprocess.run(['node', '--input-type=module', '-e',
    'import * as asar from "@electron/asar"; asar.extractAll(process.argv[1], process.argv[2]);',
    str(resources / 'app.asar'), str(unpacked)], cwd=root / 'frontend', check=True)
old_dist = unpacked / 'dist'
old_dist.rename(output / 'retained-dist')
shutil.copytree(root / 'frontend/dist', unpacked / 'dist')
subprocess.run(['node', '--input-type=module', '-e',
    'import * as asar from "@electron/asar"; await asar.createPackage(process.argv[1], process.argv[2]);',
    str(unpacked), str(resources / 'app.asar')], cwd=root / 'frontend', check=True)
header_hash = subprocess.check_output(['node', '--input-type=module', '-e',
    'import * as asar from "@electron/asar"; import {createHash} from "node:crypto"; '
    'console.log(createHash("sha256").update(asar.getRawHeader(process.argv[1]).headerString).digest("hex"));',
    str(resources / 'app.asar')], cwd=root / 'frontend', text=True).strip()
plist_path = app / 'Contents/Info.plist'
plist = plistlib.loads(plist_path.read_bytes())
assert plist['ElectronAsarIntegrity']['Resources/app.asar']['algorithm'] == 'SHA256'
plist['ElectronAsarIntegrity']['Resources/app.asar']['hash'] = header_hash
plist_path.write_bytes(plistlib.dumps(plist))
frontend = {str(path.relative_to(root / 'frontend/dist')): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (root / 'frontend/dist').rglob('*') if path.is_file()}
manifest = dict(product_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    scope='macOS arm64 retained runtime/plugins/desktop; freshly built frontend and complete tracked backend overlaid; not a fresh release build',
    retained_runtime_build=baseline, source_app=str(source), retained_paths_unchanged=retained,
    files=hashes, frontend_dist=frontend,
    asar_header_sha256=header_hash,
    app_asar_sha256=hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest())
(output / 'package-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
for name, command in [('sign', ['codesign', '--force', '--deep', '--sign', '-', str(app)]),
                      ('sign-before', ['codesign', '--verify', '--deep', '--strict', str(app)])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (output / (name + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
print(f'Verified {len(hashes)} backend files, {len(frontend)} fresh dist files and strict signature')
