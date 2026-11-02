"""Build a reviewable local candidate using the previously qualified runtime."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'output/seconds-contracts-20261102/native'
APP = OUT / 'Installed App/CandleScope.app'
SOURCE = Path('/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app')
assert not APP.exists(), 'Preserve earlier candidates; do not overwrite a receipt'
assert (ROOT / 'frontend/dist/index.html').exists()
for name in ('requirements.txt', 'ccxt-fork.lock.json'):
    assert (SOURCE / 'Contents/Resources/backend' / name).read_bytes() == (ROOT / 'backend' / name).read_bytes(), name
APP.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['/bin/cp', '-cR', str(SOURCE), str(APP)], check=True)
resources = APP / 'Contents/Resources'
shutil.rmtree(resources / 'backend/app')
for name in subprocess.check_output(['git', 'ls-files', '-z', 'backend/app'], cwd=ROOT, text=True).split('\0'):
    if name:
        target = resources / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
subprocess.run([str(resources / 'python-runtime/python/bin/python3.12'), '-m', 'compileall', '-q', str(resources / 'backend/app')], check=True)
subprocess.run(['node', str(ROOT / 'docs/qa/seconds-contracts-20261102/repack.mjs')], cwd=ROOT, check=True)
