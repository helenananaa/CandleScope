"""Assemble a retained runtime/frontend with every current backend app file."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate', default='native-final')
args = parser.parse_args()
assert args.candidate.startswith('native-') and Path(args.candidate).name == args.candidate
root = Path(__file__).resolve().parents[3]
out = root / 'output/source-window-recovery-129-20261113' / args.candidate
out.mkdir(parents=True, exist_ok=True)
source = Path('/Users/ryanliang/.codex/worktrees/realtime-forming-retention-129-20261113/CandleScope/output/realtime-forming-retention-129-20261113/native/CandleScope.app')
app = out / 'CandleScope.app'
assert not app.exists()
subprocess.run(['cp', '-cR', str(source), str(app)], check=True)
resources = app / 'Contents/Resources'
files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=root, text=True).splitlines()
hashes = {}
for name in files:
    target = resources / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / name, target)
    hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
manifest = dict(product_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    scope='macOS arm64 retained frontend/runtime/plugins; all tracked backend app files overlaid; not a fresh release build',
    frontend_runtime_build='ef8f0e0fa6df299a823f4460b701eb1c3c98361f',
    source_app=str(source), files=hashes,
    app_asar_sha256=hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest())
(out / 'package-source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
for name, command in [('sign', ['codesign', '--force', '--deep', '--sign', '-', str(app)]),
                      ('sign-before', ['codesign', '--verify', '--deep', '--strict', str(app)])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (out / (name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == 0
print(f'qualified {len(hashes)} source hashes and strict signature')
