"""Read-only installed-profile verification; never imports a provider or requests public data."""
from pathlib import Path
import hashlib
import io
import json
import os
import zipfile

root=Path(os.environ['CANDLESCOPE_BATCH1_QA_ROOT']).absolute()
resources=root/'Installed App/CandleScope.app/Contents/Resources/python-runtime/plugins'
profile=root/'profile/data/plugins'
registry=json.loads((profile/'runtime-registry.json').read_text())
active=next(row for row in registry['plugins'] if row['id']=='candlescope.pine-compat')
assert active['enabled'] is True and active['autoStart'] is True
manifest=json.loads((resources/'manifest.json').read_text())
bundle=next(row for row in manifest['plugins'] if row['runtimeId']==active['id'])
assert active['managed']['bundleSha256']==bundle['sha256']
install=profile/'installs'/active['id']/active['managed']['installationId']
assert Path(active['launch']['workingDirectory'])==install
assert Path(active['launch']['executable'])==install/'venv/bin/python'
site=install/'venv/lib/python3.12/site-packages'
lock=json.loads((resources/'candlescope-plugin-pine-compat.lock.json').read_text())
sha=lambda data:'sha256:'+hashlib.sha256(data).hexdigest()
raw=(resources/bundle['filename']).read_bytes();assert sha(raw)==bundle['sha256']
files={};mismatches=[];counts={}
with zipfile.ZipFile(io.BytesIO(raw)) as package:
    for name,record in lock['wheels'].items():
        raw_wheel=package.read('wheels/'+record['artifactFilename']);assert sha(raw_wheel)==record['sha256']
        counts[name]=0
        with zipfile.ZipFile(io.BytesIO(raw_wheel)) as wheel:
            for item in wheel.infolist():
                if item.is_dir() or any(part.endswith(('.dist-info','.data')) for part in Path(item.filename).parts):
                    continue
                expected=wheel.read(item);path=site/item.filename
                counts[name]+=1
                files[item.filename]=sha(expected)
                if not path.is_file() or path.read_bytes()!=expected:mismatches.append(item.filename)
result={'bundleSha256':bundle['sha256'],'runtimeId':active['id'],'enabled':active['enabled'],
    'installationId':active['managed']['installationId'],'registryExecutable':active['launch']['executable'],
    'wheelModuleFileCounts':counts,'installedModuleSha256':files,'mismatches':mismatches,
    'scope':'Owned profile registry and installed SDK/Pine/core module bytes equal verified wheels; no provider import, public request or full Native acceptance claim.'}
print(json.dumps(result,indent=2))
assert not mismatches
