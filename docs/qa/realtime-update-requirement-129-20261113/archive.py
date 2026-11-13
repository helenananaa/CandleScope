"""Keep raw attempts and revision-specific native observations reviewable."""
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
out = root/'output/realtime-demand-preview-129-20261113'
evidence = qa/'evidence'
evidence.mkdir(exist_ok=True)

def archive(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(source.read_bytes(), mtime=0))

for source in out.iterdir():
    if source.is_file() and source.suffix in {'.log', '.xml', '.json'}:
        archive(source, evidence/(source.name+'.gz'))
archive(out/'qualified-pine/provenance.json', evidence/'qualified-pine-provenance.json.gz')
package = out/'native-package'
manifest = json.loads((package/'package-source-manifest.json').read_text())
resources = package/'CandleScope.app/Contents/Resources'
for filename, digest in manifest['files'].items():
    assert hashlib.sha256((resources/filename).read_bytes()).hexdigest() == digest
    assert hashlib.sha256((root/filename).read_bytes()).hexdigest() == digest
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest() == manifest['app_asar_sha256']
result = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(package/'CandleScope.app')],
                        capture_output=True, text=True)
(package/'sign-after.log').write_text(result.stdout+result.stderr)
assert result.returncode == 0
(package/'package-after.json').write_text(json.dumps({'backend_files': len(manifest['files']),
    'all_backend_matches_package_and_checkout': True, 'asar_matches': True, 'signature_status': 0}, indent=2)+'\n')
for source in package.iterdir():
    if source.is_file() and source.suffix in {'.log', '.json', '.jsonl'}:
        archive(source, evidence/'native'/(source.name+'.gz'))

redactions = {}
for name in ['ordinary', 'witness-profile', 'witness-profile2']:
    directory = package/name
    receipt = json.loads((directory/'acceptance.json').read_text())
    paths = []
    def redact(value, path=''):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'contextToken' and isinstance(item, str):
                    value[key] = '[REDACTED]'
                    paths.append(path+'/'+key)
                else:
                    redact(item, path+'/'+key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                redact(item, path+'/'+str(index))
    redact(receipt)
    destination = evidence/'native'/name
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'acceptance.json.gz').write_bytes(gzip.compress((json.dumps(receipt, indent=2)+'\n').encode(), mtime=0))
    redactions[name] = paths
    for filename in ['traffic.json', 'process.log', 'profile/logs/backend-sidecar.log']:
        source = directory/filename
        if source.exists():
            archive(source, destination/(filename.replace('/', '_')+'.gz'))
    if name != 'witness-profile':
        for filename in ['initial.png', 'recreated.png', 'restored.png', 'failure.png']:
            source = directory/filename
            if source.exists():
                shutil.copyfile(source, qa/(name+'-'+filename))
(qa/'redactions.json').write_text(json.dumps({'policy': 'only ephemeral contextToken strings; active_read_tokens counts retained',
    'paths': redactions}, indent=2)+'\n')
files = subprocess.check_output(['git', 'diff', '--name-only', '6f590578a8e5e7bb52407c295d8d5a693b35cf91', 'HEAD'], cwd=root, text=True).splitlines()
(qa/'source-hashes.json').write_text(json.dumps({'base': '6f590578a8e5e7bb52407c295d8d5a693b35cf91',
    'product_head': manifest['product_head'], 'files': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files}}, indent=2)+'\n')
(qa/'evidence-index.json').write_text(json.dumps({str(p.relative_to(qa)): {
    'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
    for p in sorted(evidence.rglob('*')) if p.is_file()}, indent=2)+'\n')
print('archived source and native evidence; originals retained')
