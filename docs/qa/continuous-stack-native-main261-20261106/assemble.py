"""Build a reviewable local candidate using the previously qualified runtime."""
from pathlib import Path
import shutil
import os
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(os.environ.get('CANDLESCOPE_BATCH1_QA_ROOT', str(ROOT / 'output/continuous-stack-native-main261-20261106/native-current')))
APP = OUT / 'Installed App/CandleScope.app'
SOURCE = Path(os.environ.get('CANDLESCOPE_QA_RUNTIME_SOURCE', '/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app'))
assert not APP.exists(), 'Preserve earlier candidates; do not overwrite a receipt'
assert (ROOT / 'frontend/dist/index.html').exists()
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(SOURCE)], check=True)
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
# Mirror current pure-Python SDK bytes into both packaged lookup locations.
for package, module_name in [('candlescope-plugin-sdk','candlescope_plugin_sdk'),
                             ('candlescope-backtest-sdk','candlescope_backtest_sdk')]:
    source_module = ROOT / 'packages' / package / 'src' / module_name
    for target in [resources / 'packages' / package / 'src' / module_name,
                   resources / 'python-runtime/site-packages' / module_name]:
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source_module, target, ignore=shutil.ignore_patterns('__pycache__'))
subprocess.run([str(resources / 'python-runtime/python/bin/python3.12'), '-m', 'compileall', '-q', str(resources / 'backend/app')], check=True)
assert os.environ.get('CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS') == '1'
receipt = subprocess.check_output([str(resources / 'python-runtime/python/bin/python3.12'), '-B',
    str(ROOT / 'docs/qa/continuous-stack-native-main261-20261106/verify_current_plugins.py')], cwd=ROOT, text=True)
(OUT / 'reused-plugin-source-verification.json').write_text(receipt)
subprocess.run(['node', str(ROOT / 'docs/qa/continuous-stack-native-main261-20261106/repack.mjs')], cwd=ROOT, check=True)
