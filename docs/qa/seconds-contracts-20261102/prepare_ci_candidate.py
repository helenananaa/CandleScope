"""Verify the actual current CI download and relocate its unmodified app.

No application launch, frontend replacement, signing or runtime reuse occurs.
Original downloaded artifacts are retained. A new output root is required.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[3]
DOWNLOAD=ROOT/'output/seconds-contracts-20261102/ci-arm64-150bb85c'
OUT=Path(os.environ['CANDLESCOPE_BATCH1_QA_ROOT'])
META=json.loads((DOWNLOAD/'github-artifact.json').read_text())
HEAD='150bb85c8c715190d0c2c55198aa7cd1ec33877d'
assert META['id']==13145235521 and META['workflow_run']['head_sha']==HEAD
assert META['workflow_run']['id']==41442721624 and not META['expired']
ARCHIVE=DOWNLOAD/'artifact.zip'
def digest(stream):
    h=hashlib.sha256()
    while part:=stream.read(1024*1024):
        h.update(part)
    return h.hexdigest()
assert ARCHIVE.stat().st_size==META['size_in_bytes']
with ARCHIVE.open('rb') as stream:
    outer_sha=digest(stream)
assert 'sha256:'+outer_sha==META['digest']
assert not OUT.exists(), 'Preserve all previous candidates'
OUT.mkdir(parents=True)
with zipfile.ZipFile(ARCHIVE) as archive:
    names=archive.namelist()
    def member(basename):
        matches=[name for name in names if Path(name).name==basename]
        assert len(matches)==1, (basename,matches)
        return matches[0]
    manifest=json.loads(archive.read(member('build-manifest.json')))
    assert manifest['commit']==HEAD and manifest['arch']=='arm64'
    assert manifest['platform']=='darwin' and manifest['workflowRun']=='41442721624'
    assert manifest['signature']=='ad-hoc' and manifest['notarized'] is False
    assert len(manifest['artifacts'])==2
    sums=archive.read(member('SHA256SUMS')).decode()
    for artifact in manifest['artifacts']:
        name=artifact['name']
        assert Path(name).name==name and name.endswith(('.dmg','.zip'))
        entry=archive.getinfo(member(name));assert entry.file_size==artifact['size']
        with archive.open(entry) as stream:
            actual=digest(stream)
        assert actual==artifact['sha256'] and f'{actual}  {name}\n' in sums
        if name.endswith('.zip'):
            target=OUT/name
            with archive.open(entry) as source,target.open('xb') as dest:
                shutil.copyfileobj(source,dest)
            app_zip=target
    (OUT/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'SHA256SUMS').write_text(sums)
subprocess.run(['/usr/bin/ditto','-x','-k',str(app_zip),str(OUT/'Installed App')],check=True)
assert (OUT/'Installed App/CandleScope.app').is_dir()
receipt={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'artifact':META,'verifiedOuterSha256':outer_sha,'buildManifest':manifest,
         'appZip':str(app_zip),'appLaunched':False,
         'assembly':'Original CI arm64 ZIP relocated with ditto. No repack, runtime replacement, code-signing or application launch.'}
(OUT/'ci-artifact-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
subprocess.run(['node',str(ROOT/'docs/qa/seconds-contracts-20261102/capture_ci_candidate.mjs')],cwd=ROOT,check=True)
subprocess.run(['node',str(ROOT/'frontend/scripts/verify-macos-package.mjs'),str(OUT/'Installed App/CandleScope.app'),'arm64'],cwd=ROOT,check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
subprocess.run(['node',str(ROOT/'docs/qa/seconds-contracts-20261102/verify.mjs')],cwd=ROOT,check=True)
print(json.dumps({'sourceCommit':HEAD,'appLaunched':False,'originalCiArtifactVerified':True,'root':str(OUT)}))
