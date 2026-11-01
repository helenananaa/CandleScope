from pathlib import Path
import json, shutil, subprocess
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/fixed-dataset-native-20261101'
APP=OUT/'Installed App/CandleScope.app'
SOURCE=Path('/Users/ryanliang/.codex/worktrees/h127-r129-adoption-20261101/CandleScope/output/h127-r129-native-20261101/Installed App/CandleScope.app')
assert not APP.exists(), 'Candidate already exists; preserve it before reassembly'
APP.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['/bin/cp','-cR',str(SOURCE),str(APP)],check=True)
resources=APP/'Contents/Resources'
shutil.rmtree(resources/'backend/app')
for name in subprocess.check_output(['git','ls-files','-z','backend/app'],cwd=ROOT,text=True).split('\0'):
    if not name: continue
    target=resources/name; target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/name,target)
subprocess.run([str(resources/'python-runtime/python/bin/python3.12'),'-m','compileall','-q',str(resources/'backend/app')],check=True)
subprocess.run(['node',str(ROOT/'docs/qa/fixed-dataset-results-20261101/repack-frontend.mjs')],cwd=ROOT,check=True)
