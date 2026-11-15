"""Clone a retained macOS runtime; overlay current backend and optional built UI."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import plistlib

root = Path(__file__).resolve().parents[3]
output = root / 'output/large-interval-throughput-127-20261115' / (sys.argv[1] if len(sys.argv) > 1 else 'candidate')
source = Path('/Users/ryanliang/CandleScope/.claude/worktrees/local-chunk-burst/output/local-chunk-burst-rerun-20261115/candidate/CandleScope.app')
app = output / 'CandleScope.app'
assert not app.exists()
output.mkdir(parents=True, exist_ok=True)
frontend_head = '02bbf13ca7521e384c36aacf42884c0016a2f6f7'
built_frontend = '--frontend' in sys.argv[2:]
unchanged = ['packages/candlescope-control', 'backend/requirements.txt',
             'backend/requirements-parquet.txt', 'backend/ccxt-fork.lock.json']
if not built_frontend:
    unchanged.append('frontend')
assert not subprocess.check_output(['git', 'diff', '--name-only', frontend_head, 'HEAD', '--', *unchanged], cwd=root)
subprocess.run(['cp', '-cR', str(source), str(app)], check=True)
resources = app / 'Contents/Resources'
frontend_hashes = {}
if built_frontend:
    payload = output / 'app-payload'
    payload.mkdir()
    for name in ('dist', 'desktop'):
        shutil.copytree(root / 'frontend' / name, payload / name)
    shutil.copyfile(root / 'frontend/package.json', payload / 'package.json')
    for path in sorted(payload.rglob('*')):
        if path.is_file():
            frontend_hashes[str(path.relative_to(payload))] = hashlib.sha256(path.read_bytes()).hexdigest()
    subprocess.run(['node', str(root / 'frontend/node_modules/@electron/asar/bin/asar.js'),
                    'pack', str(payload), str(resources / 'app.asar')], check=True)
    header_hash = subprocess.check_output(['node', '-e',
        'const a=require(process.argv[1]); const c=require("node:crypto"); '
        'process.stdout.write(c.createHash("sha256").update(a.getRawHeader(process.argv[2]).headerString).digest("hex"));',
        str(root / 'frontend/node_modules/@electron/asar'), str(resources / 'app.asar')], text=True)
    plist_path = app / 'Contents/Info.plist'
    with plist_path.open('rb') as stream:
        plist = plistlib.load(stream)
    plist['ElectronAsarIntegrity'] = {'Resources/app.asar': {'algorithm': 'SHA256', 'hash': header_hash}}
    with plist_path.open('wb') as stream:
        plistlib.dump(plist, stream)
    frontend_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
# This is a new disposable candidate; never change the retained source app.
shutil.rmtree(resources / 'backend/app')
files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=root, text=True).splitlines()
hashes = {}
for name in files:
    target = resources / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / name, target)
    hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
manifest = dict(product_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    scope=('macOS arm64 retained runtime/plugins; freshly built current frontend and complete current backend overlaid; not a fresh runtime/release build'
           if built_frontend else 'macOS arm64 retained runtime/plugins and unchanged frontend; complete current backend overlaid; not a fresh release build'),
    frontend_source_head=frontend_head, source_app=str(source), retained_paths_unchanged=unchanged,
    files=hashes, frontend_files=frontend_hashes,
    app_asar_sha256=hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest())
(output / 'package-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
for name, command in [('sign', ['codesign', '--force', '--deep', '--sign', '-', str(app)]),
                      ('sign-verify', ['codesign', '--verify', '--deep', '--strict', str(app)])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (output / (name + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0
print(f'Verified {len(hashes)} backend files, frontend/dependency parity and strict signature')
