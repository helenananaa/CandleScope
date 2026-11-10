"""Verify reused plugin bundles against current tracked sources and pins."""
from pathlib import Path
import hashlib
import io
import json
import os
import subprocess
import zipfile

root=Path(__file__).resolve().parents[3]
assets=Path(os.environ['CANDLESCOPE_NATIVE_QA_ROOT'])/'Installed App/CandleScope.app/Contents/Resources/python-runtime/plugins'
sha=lambda data:'sha256:'+hashlib.sha256(data).hexdigest()
manifest=json.loads((assets/'manifest.json').read_text())
entry=next(item for item in manifest['plugins'] if item['runtimeId']=='candlescope.pine-compat')
bundle=assets/entry['filename'];assert sha(bundle.read_bytes())==entry['sha256']
lock=json.loads((assets/'candlescope-plugin-pine-compat.lock.json').read_text())
recipe=json.loads((root/'frontend/scripts/desktop-plugin-sources.json').read_text())
assert lock['engineProvenance']==recipe['engines']['pine-compat-runtime']
count=0;mismatches=[]
with zipfile.ZipFile(bundle) as package:
    for name in ['candlescope-plugin-sdk','candlescope-plugin-pine-compat']:
        record=lock['wheels'][name];raw=package.read('wheels/'+record['artifactFilename'])
        assert sha(raw)==record['sha256']
        with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
            for file in subprocess.check_output(['git','ls-files','-z',f'packages/{name}/src'],cwd=root,text=True).split('\0'):
                if not file:continue
                count+=1
                if wheel.read(file.split('/src/',1)[1])!=(root/file).read_bytes():mismatches.append(file)
assert not mismatches,mismatches
print(json.dumps({'bundleSha256':entry['sha256'],'sourceFiles':count,'mismatches':mismatches,'enginePinMatches':True}))
