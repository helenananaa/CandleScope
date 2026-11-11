"""Rebuild current source bundles using verified unchanged engine build inputs.

The existing qualified application provides a hash-verified engine wheel and
source archive; the official source builder rebuilds the SDK/bridge every time.
No user plugin installation or profile is read or changed.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(os.environ['CANDLESCOPE_BATCH1_QA_ROOT'])
SOURCE=Path('/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app/Contents/Resources/python-runtime/plugins')
def sha(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
recipe=json.loads((ROOT/'frontend/scripts/desktop-plugin-sources.json').read_text())
lock=json.loads((SOURCE/'candlescope-plugin-pine-compat.lock.json').read_text())
engine=recipe['engines']['pine-compat-runtime'];assert lock['engineProvenance']==engine
manifest=json.loads((SOURCE/'manifest.json').read_text());entry=next(x for x in manifest['plugins'] if x['runtimeId']=='candlescope.pine-compat')
bundle=SOURCE/entry['filename'];assert sha(bundle)==entry['sha256']
cache=OUT/'current-plugin-cache';downloads=cache/'downloads';downloads.mkdir(parents=True,exist_ok=True)
archive=SOURCE/'sources'/engine['archive']['filename'];assert sha(archive)==engine['archive']['sha256']
assert sha(ROOT/engine['patch'])==engine['patchSha256']
shutil.copy2(archive,downloads/archive.name)
target=f'{platform.system()}-{platform.machine()}'
key=hashlib.sha256(json.dumps([engine,target,'3.12'],sort_keys=True).encode()).hexdigest()
wheelhouse=cache/'wheels'/key;wheelhouse.mkdir(parents=True,exist_ok=True)
record=lock['wheels']['pine-compat-runtime'];wheel=wheelhouse/record['artifactFilename']
with zipfile.ZipFile(bundle) as archive:wheel.write_bytes(archive.read('wheels/'+wheel.name))
assert sha(wheel)==record['sha256'] and wheel.stat().st_size==record['size']
(wheelhouse/'wheel.json').write_text(json.dumps({'filename':wheel.name,'sha256':sha(wheel)}))
(OUT/'engine-cache-provenance.json').write_text(json.dumps({'qualifiedBundle':str(bundle),'qualifiedBundleSha256':sha(bundle),'engineProvenance':engine,'verifiedEngineWheel':record,'target':target,'cacheKey':key},indent=2)+'\n')
python=OUT/'Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3.12'
environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1',
             'PYTHONPATH':os.pathsep.join([str(python.parents[2]/'site-packages'),str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')])}
subprocess.run([str(python),'-B',str(ROOT/'frontend/scripts/prepare-desktop-plugins.py'),'--output',str(OUT/'current-plugins'),'--cache',str(cache),'--uv','/Users/ryanliang/.local/bin/uv'],check=True,cwd=ROOT,env=environment)
resources=OUT/'Installed App/CandleScope.app/Contents/Resources/python-runtime/plugins'
shutil.rmtree(resources);shutil.copytree(OUT/'current-plugins',resources)
