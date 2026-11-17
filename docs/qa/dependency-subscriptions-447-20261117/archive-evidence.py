"""Archive fresh public-market QA receipts, never profiles, databases or runtime."""
from pathlib import Path
import gzip, hashlib, json, platform, re, subprocess, sys

source = Path(sys.argv[1]).resolve()
destination = Path(__file__).resolve().parent / 'evidence'
assert not destination.exists(), 'Preserve existing evidence instead of overwriting'
destination.mkdir()
paths = list(source.glob('*.log')) + list(source.glob('*.xml')) + [source/'ui-plan.json',source/'regression-identity.json']
for candidate in ('candidate','candidate-final','candidate-concurrent','candidate-replan','candidate-executor'):
    paths += [source/candidate/name for name in ('package-source-manifest.json','sign.log','verify.log')]
for name in ('native-cold', 'native-cold-final','native-cold-concurrent','native-cold-replan'):
    paths += [p for p in (source/name).iterdir() if p.is_file()]
for name in ('native-cold','native-cold-final','native-cold-concurrent','native-cold-replan'):
    paths += [source/name/'profile/logs/backend-sidecar.log']
index = []
for path in sorted(paths):
    raw = path.read_bytes()
    if path.suffix != '.png':
        assert not re.search(rb'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{30,}', raw), path
        assert not re.search(rb'(?i)(?:authorization|x-mbx-apikey)["\s:]+(?:bearer\s+)?[A-Za-z0-9_-]{32,}', raw), path
        assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', raw), path
    relative = path.relative_to(source)
    target = destination / str(relative)
    if path.suffix != '.png':
        target = target.with_name(target.name + '.gz')
        payload = gzip.compress(raw, compresslevel=9, mtime=0)
    else:
        payload = raw
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    index.append({'source': str(relative), 'artifact': str(target.relative_to(destination)),
                  'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                  'artifact_bytes': len(payload), 'artifact_sha256': hashlib.sha256(payload).hexdigest()})
(destination/'index.json').write_text(json.dumps(index, indent=2)+'\n')
(destination/'SHA256SUMS').write_text(''.join(
    hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(destination))+'\n'
    for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
print(json.dumps({'artifacts':len(index),'compressed_bytes':sum(r['artifact_bytes'] for r in index)}))
