from pathlib import Path
import json, shutil, subprocess, datetime
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'output/alert-native-20261101'
APP=OUT/'Installed App/CandleScope.app'
SOURCE_ROOT=Path('/Users/ryanliang/.codex/worktrees/seconds-integration-20261101/CandleScope')
SOURCE=SOURCE_ROOT/'output/seconds-native-20261101/Installed App/CandleScope.app'
assert not APP.exists(), 'Preserve the previous candidate before rebuilding'
assert 'mismatches":[]' in (SOURCE_ROOT/'output/seconds-integration-20261101/source-match-tail.log').read_text()
assert not subprocess.check_output(['git','diff','ce30a253','--name-only','--','frontend','backend/requirements.txt','backend/scripts'],cwd=ROOT,text=True).strip()
APP.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['/bin/cp','-cR',str(SOURCE),str(APP)],check=True)
if not (ROOT/'frontend/dist').exists():
    subprocess.run(['/bin/cp','-cR',str(SOURCE_ROOT/'frontend/dist'),str(ROOT/'frontend/dist')],check=True)
resources=APP/'Contents/Resources'
shutil.rmtree(resources/'backend/app')
for name in subprocess.check_output(['git','ls-files','-z','backend/app'],cwd=ROOT,text=True).split('\0'):
    if not name: continue
    target=resources/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/name,target)
subprocess.run([str(resources/'python-runtime/python/bin/python3.12'),'-m','compileall','-q',str(resources/'backend/app')],check=True)
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(APP)],check=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(APP)],check=True)
(OUT/'assembly.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'app':str(APP),'assembly':'APFS clone of seconds candidate; unchanged current frontend/desktop and runtime dependencies. All current tracked backend/app copied and bundled-Python compiled; root signed and deep strict verified. Not a fresh full runtime build.'},indent=2)+'\n')
