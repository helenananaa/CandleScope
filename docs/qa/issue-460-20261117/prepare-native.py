"""Clone a verified integrated frontend/runtime; overlay committed #460 backend."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[3]
base = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
assert not target.exists(), 'Use a new disposable candidate'
prior = json.loads((base / 'package-source-manifest.json').read_text())
retained = ['frontend', 'packages', 'backend/native', 'backend/requirements.txt',
            'backend/requirements-parquet.txt', 'backend/ccxt-fork.lock.json']
assert not subprocess.check_output(['git', 'diff', '--name-only', prior['product_head'], 'HEAD', '--', *retained], cwd=repo)
assert not subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '--', 'frontend', 'backend/app'], cwd=repo)
app = base / 'CandleScope.app'
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
target.mkdir(parents=True)
subprocess.run(['cp', '-cR', str(app), str(target / 'CandleScope.app')], check=True)
resources = target / 'CandleScope.app/Contents/Resources'
shutil.rmtree(resources / 'backend/app')
files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=repo, text=True).splitlines()
hashes = {}
for name in files:
    destination = resources / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo / name, destination)
    hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
manifest = dict(prior, product_head=head, files=hashes, source_app=str(app),
    frontend_source_head=prior['product_head'],
    scope='macOS arm64 retained integrated frontend/CI runtime/plugins; complete committed #460 backend overlay; not a fresh release or joint acceptance')
assert hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest() == prior['app_asar_sha256']
(target / 'package-source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
for name, command in [('sign', ['codesign', '--force', '--deep', '--sign', '-', str(target / 'CandleScope.app')]),
                      ('verify', ['codesign', '--verify', '--deep', '--strict', str(target / 'CandleScope.app')])]:
    result = subprocess.run(command, capture_output=True, text=True)
    (target / (name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == 0
print(json.dumps({'head': head, 'candidate': str(target), 'files': len(hashes)}))
