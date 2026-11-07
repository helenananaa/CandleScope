"""Bind current wheel bytes and source fingerprints to this local bundle."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[3]
PRODUCT=Path(os.environ.get('PINE_BUNDLE_ROOT',str(ROOT/'output/issue-152-output-range-20261102/bundle2')))
PLUGINS=PRODUCT/'plugins'
lock=json.loads((PLUGINS/'candlescope-plugin-pine-compat.lock.json').read_text())
entry=json.loads((PLUGINS/'manifest.json').read_text())['plugins'][0]
bundle=PLUGINS/entry['filename']
sha=lambda value:'sha256:'+hashlib.sha256(value).hexdigest()
assert sha(bundle.read_bytes())==entry['sha256']
recipe=json.loads((ROOT/'frontend/scripts/desktop-plugin-sources.json').read_text())
assert lock['engineProvenance']==recipe['engines']['pine-compat-runtime']
loader=importlib.util.spec_from_file_location('desktop_source',ROOT/'frontend/scripts/prepare-desktop-plugins.py')
source=importlib.util.module_from_spec(loader);loader.loader.exec_module(source)
count=0
with zipfile.ZipFile(bundle) as package:
 for name,record in lock['wheels'].items():
  raw=package.read('wheels/'+record['artifactFilename'])
  assert sha(raw)==record['sha256'] and len(raw)==record['size']
  if name not in ('candlescope-plugin-sdk','candlescope-plugin-pine-compat'):continue
  expected=lock['sdkSourceSha256' if name=='candlescope-plugin-sdk' else 'bridgeSourceSha256']
  assert source.source_digest(ROOT/'packages'/name)==expected
  with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
   for path in subprocess.check_output(['git','ls-files','-z',f'packages/{name}/src'],cwd=ROOT,text=True).split('\0'):
    if path:
     assert wheel.read(path.split('/src/',1)[1])==(ROOT/path).read_bytes(),path
     count+=1
print(json.dumps({'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'bundleSha256':entry['sha256'],'bridgeSourceSha256':lock['bridgeSourceSha256'],'currentSourceFiles':count,'mismatches':[],'engineUnchanged':True},indent=2))
