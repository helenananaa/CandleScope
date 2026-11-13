"""Overlay all committed backend sources on a retained macOS arm64 base app."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('source_app', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
assert subprocess.check_output(['git', 'diff', 'HEAD', '--', 'backend/app'], cwd=root) == b''
args.output.mkdir(parents=True, exist_ok=True)
app = args.output / 'CandleScope.app'
assert not app.exists(), 'preserve earlier app and choose a fresh output directory'
subprocess.run(['cp', '-cR', str(args.source_app), str(app)], check=True)
resources = app / 'Contents/Resources'
files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=root, text=True).splitlines()
hashes = {}
for name in files:
    source, destination = root/name, resources/name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
for p in (resources/'backend/app').rglob('__pycache__'):
    shutil.rmtree(p)
for p in (resources/'backend/app').rglob('*.pyc'):
    p.unlink()
manifest = {'product_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    'base_build': 'ef8f0e0fa6df299a823f4460b701eb1c3c98361f', 'clone_source_app': str(args.source_app),
    'assembly': 'APFS clone; all tracked backend/app overlaid; frontend/runtime/plugins unchanged',
    'files': hashes, 'app_asar_sha256': hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()}
(args.output/'package-source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
for flags, name in [(['--force', '--deep', '--sign', '-', '--preserve-metadata=entitlements,requirements,flags'], 'sign.log'),
                    (['--verify', '--deep', '--strict'], 'sign-before.log')]:
    result = subprocess.run(['codesign', *flags, str(app)], capture_output=True, text=True)
    (args.output/name).write_text(result.stdout+result.stderr)
    assert result.returncode == 0
print(json.dumps({'product_head': manifest['product_head'], 'app_files': len(hashes), 'app': str(app)}))
