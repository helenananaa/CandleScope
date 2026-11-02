from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/python-indicator-native-20261101'
APP=OUT/'Installed App/CandleScope.app'
SOURCE=Path('/Users/ryanliang/.codex/worktrees/account-data-manager-20261101/CandleScope/output/account-state-native-20261101/Installed App/CandleScope.app')
assert not APP.exists(), 'Preserve previous candidate before assembly'
APP.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['/bin/cp','-cR',str(SOURCE),str(APP)],check=True)
res=APP/'Contents/Resources'
shutil.rmtree(res/'backend/app')
for file in subprocess.check_output(['git','ls-files','-z','backend/app'],cwd=ROOT,text=True).split('\0'):
    if file:
        dest=res/file;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/file,dest)
subprocess.run([str(res/'python-runtime/python/bin/python3.12'),'-m','compileall','-q',str(res/'backend/app')],check=True)
shutil.rmtree(res/'python-runtime/plugins')
subprocess.run(['/bin/cp','-cR',str(ROOT/'output/python-indicator-author-20261101/desktop-plugins'),str(res/'python-runtime/plugins')],check=True)
subprocess.run(['node',str(ROOT/'docs/qa/python-indicator-author-20261101/repack-frontend.mjs')],cwd=ROOT,check=True)
