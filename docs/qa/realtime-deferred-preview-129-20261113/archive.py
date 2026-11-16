"""Keep final evidence and failed candidates; redact ephemeral context strings."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
out = root/'output/realtime-deferred-preview-129-20261113'
evidence = qa/'evidence'
redacted = []

def redact(value, path):
    if isinstance(value,dict):
        for key,item in value.items():
            if key=='contextToken' and isinstance(item,str):
                value[key]='[REDACTED]'; redacted.append(path+'/'+key)
            else: redact(item,path+'/'+key)
    elif isinstance(value,list):
        for index,item in enumerate(value): redact(item,path+'/'+str(index))

def archive(source):
    relative=source.relative_to(out)
    destination=evidence/(str(relative)+'.gz')
    destination.parent.mkdir(parents=True,exist_ok=True)
    payload=source.read_bytes()
    if source.suffix=='.json':
        data=json.loads(payload); redact(data,str(relative))
        payload=(json.dumps(data,indent=2)+'\n').encode()
    destination.write_bytes(gzip.compress(payload,mtime=0))

native=out/'native'
resources=native/'CandleScope.app/Contents/Resources'
manifest=json.loads((native/'package-source-manifest.json').read_text())
for name,digest in manifest['files'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
    assert hashlib.sha256((resources/name).read_bytes()).hexdigest()==digest
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()==manifest['app_asar_sha256']
result=subprocess.run(['codesign','--verify','--deep','--strict',str(native/'CandleScope.app')],capture_output=True,text=True)
(native/'sign-after.log').write_text(result.stdout+result.stderr)
assert result.returncode==0
(native/'package-after.json').write_text(json.dumps(dict(backend_files=len(manifest['files']),
    all_backend_matches_package_and_checkout=True,asar_matches=True,signature_status=0),indent=2)+'\n')
for source in out.iterdir():
    if source.is_file() and source.suffix in {'.log','.xml','.json'}: archive(source)
for candidate in sorted(out.glob('native*')):
    if not candidate.is_dir(): continue
    for source in candidate.iterdir():
        if source.is_file() and source.suffix in {'.json','.log'}: archive(source)
    for profile in candidate.iterdir():
        if not profile.is_dir() or profile.suffix=='.app' or not (profile/'acceptance.json').exists(): continue
        for source in profile.iterdir():
            if source.is_file() and source.suffix in {'.json','.log'}: archive(source)
        sidecar=profile/'profile/logs/backend-sidecar.log'
        if sidecar.exists(): archive(sidecar)
        if (profile/'failure.png').exists():
            destination=evidence/candidate.name/profile.name/'failure.png'
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(profile/'failure.png',destination)
for profile in ('ordinary','witness'):
    receipt=json.loads((native/profile/'acceptance.json').read_text()); assert receipt['passed']
    for name in ('initial','recreated','restored'):
        shutil.copyfile(native/profile/(name+'.png'),qa/(profile+'-'+name+'.png'))
(qa/'redactions.json').write_text(json.dumps(dict(policy='only ephemeral contextToken strings; numeric active_read_tokens retained',paths=redacted),indent=2)+'\n')
files=subprocess.check_output(['git','diff','--name-only','8a85612d107dae02c733b4416241c901e9252735','--','backend',
    'packages/candlescope-plugin-pine-compat/scripts/qualify_host_contracts.py',
    '.github/workflows/pine-host-contracts.yml'],cwd=root,text=True).splitlines()
(qa/'source-hashes.json').write_text(json.dumps(dict(base='8a85612d107dae02c733b4416241c901e9252735',product_head=manifest['product_head'],
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}),indent=2)+'\n')
(qa/'evidence-index.json').write_text(json.dumps({str(p.relative_to(qa)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    for p in sorted(evidence.rglob('*')) if p.is_file()},indent=2)+'\n')
print('archived final and failed candidates; original profiles/apps retained')
