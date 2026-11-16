"""Preserve source, controlled costs/failures and native regression separately."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
out = root/'output/history-fetch-stream-127-20261113'
evidence = qa/'evidence'
evidence.mkdir(exist_ok=True)
def archive(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(source.read_bytes(), mtime=0))
for source in out.iterdir():
    if source.is_file() and source.suffix in {'.log', '.xml', '.json'}:
        archive(source, evidence/(source.name+'.gz'))
native = out/'native'
resources = native/'CandleScope.app/Contents/Resources'
manifest = json.loads((native/'package-source-manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
    assert hashlib.sha256((resources/name).read_bytes()).hexdigest() == digest
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest() == manifest['app_asar_sha256']
result = subprocess.run(['codesign','--verify','--deep','--strict', str(native/'CandleScope.app')], capture_output=True, text=True)
(native/'sign-after.log').write_text(result.stdout+result.stderr)
assert result.returncode == 0
(native/'package-after.json').write_text(json.dumps(dict(backend_files=len(manifest['files']),
    all_backend_matches_package_and_checkout=True, asar_matches=True, signature_status=0), indent=2)+'\n')
for source in native.iterdir():
    if source.is_file() and source.suffix in {'.json', '.log'}:
        archive(source, evidence/'native'/(source.name+'.gz'))
profile = native/'ordinary'
receipt = json.loads((profile/'acceptance.json').read_text())
redacted = []
def redact(value, path=''):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'contextToken' and isinstance(item, str):
                value[key] = '[REDACTED]'; redacted.append(path+'/'+key)
            else: redact(item, path+'/'+key)
    elif isinstance(value, list):
        for index, item in enumerate(value): redact(item, path+'/'+str(index))
redact(receipt)
(evidence/'native/acceptance.json.gz').write_bytes(gzip.compress((json.dumps(receipt, indent=2)+'\n').encode(), mtime=0))
for attempt in sorted(native.glob('ordinary-attempt*')):
    failed = json.loads((attempt/'acceptance.json').read_text())
    redact(failed, attempt.name)
    folder = evidence/'native'/attempt.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'acceptance.json.gz').write_bytes(gzip.compress((json.dumps(failed,indent=2)+'\n').encode(),mtime=0))
    for name in ['traffic.json','process.log','profile/logs/backend-sidecar.log']:
        source = attempt/name
        if source.exists(): archive(source,folder/(name.replace('/','_')+'.gz'))
for name in ['traffic.json', 'process.log', 'profile/logs/backend-sidecar.log']:
    source = profile/name
    if source.exists(): archive(source, evidence/'native'/(name.replace('/','_')+'.gz'))
for name in ['initial.png','recreated.png','restored.png']:
    shutil.copyfile(profile/name, qa/name)
(qa/'redactions.json').write_text(json.dumps(dict(policy='only ephemeral contextToken strings; numeric active_read_tokens retained', paths=redacted), indent=2)+'\n')
files = subprocess.check_output(['git','diff','--name-only','4520f8f725108a94af9205956572d037d4009464','--','backend',
    'packages/candlescope-plugin-pine-compat/scripts/qualify_host_contracts.py',
    '.github/workflows/pine-host-contracts.yml'], cwd=root, text=True).splitlines()
(qa/'source-hashes.json').write_text(json.dumps(dict(base='4520f8f725108a94af9205956572d037d4009464', product_head=manifest['product_head'],
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}), indent=2)+'\n')
(qa/'evidence-index.json').write_text(json.dumps({str(p.relative_to(qa)): dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    for p in sorted(evidence.rglob('*')) if p.is_file()}, indent=2)+'\n')
print('archived; original profiles, app and raw attempts retained')
