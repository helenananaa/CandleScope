"""Verify bundled SDK/bridge wheel source bytes and pinned source fingerprints."""
from pathlib import Path
import hashlib
import io
import json
import os
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(os.environ['CANDLESCOPE_BATCH1_QA_ROOT'])
source_manifest=OUT/'source-package-manifest.json'
app=Path(json.loads(source_manifest.read_text())['app']) if source_manifest.exists() else OUT/'Installed App/CandleScope.app'
resources=app/'Contents/Resources/python-runtime/plugins'
sha=lambda data:'sha256:'+hashlib.sha256(data).hexdigest()
manifest=json.loads((resources/'manifest.json').read_text())
entry=next(x for x in manifest['plugins'] if x['runtimeId']=='candlescope.pine-compat')
bundle=resources/entry['filename'];assert sha(bundle.read_bytes())==entry['sha256']
lock=json.loads((resources/'candlescope-plugin-pine-compat.lock.json').read_text())
recipe=json.loads((ROOT/'frontend/scripts/desktop-plugin-sources.json').read_text());assert lock['engineProvenance']==recipe['engines']['pine-compat-runtime']
count=0;mismatches=[]
with zipfile.ZipFile(bundle) as package:
 for name in ('candlescope-plugin-sdk','candlescope-plugin-pine-compat'):
  record=lock['wheels'][name];raw=package.read('wheels/'+record['artifactFilename']);assert sha(raw)==record['sha256']
  with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
   for file in subprocess.check_output(['git','ls-files','-z',f'packages/{name}/src'],cwd=ROOT,text=True).split('\0'):
    if not file:continue
    relative=file.split('/src/',1)[1];count+=1
    if wheel.read(relative)!=(ROOT/file).read_bytes():mismatches.append(file)
print(json.dumps({'bundleSha256':entry['sha256'],'pluginSourceFiles':count,'mismatches':mismatches,'engineUnchanged':True}))
assert not mismatches
