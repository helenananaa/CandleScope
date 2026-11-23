"""Preserve failed native qualifications without archiving profiles or credentials."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[3]
qa = Path(__file__).resolve().parent
out = root / 'output/aggregation-joint-acceptance-20261114'
native = out / 'native-candidate'
manifest = json.loads((native / 'package-source-manifest.json').read_text())
resources = native / 'CandleScope.app/Contents/Resources'
assert all(hashlib.sha256((resources / path).read_bytes()).hexdigest() == digest
           == hashlib.sha256((root / path).read_bytes()).hexdigest()
           for path, digest in manifest['files'].items())
assert hashlib.sha256((resources / 'app.asar').read_bytes()).hexdigest() == manifest['app_asar_sha256']
signature = subprocess.run(['codesign', '--verify', '--deep', '--strict', str(native / 'CandleScope.app')],
                           capture_output=True, text=True)
(native / 'sign-after-all.log').write_text(signature.stdout + signature.stderr)
assert signature.returncode == 0
redactions = []
def redact(value, location):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and key.lower() in {'contexttoken', 'authtoken', 'accesstoken', 'sessiontoken', 'token'}:
                value[key] = '[REDACTED]'
                redactions.append(location + '/' + key)
            else:
                redact(item, location + '/' + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            redact(item, location + '/' + str(index))

paths = [*out.glob('*.log'), *native.glob('*.json'), *native.glob('*.log'),
         *out.glob('partial-query-probe/*.json'), *out.glob('partial-query-probe/*.log'),
         *out.glob('partial-query-probe/*.py')]
cases = []
for label, driver in [('prime-cold', 'native.mjs'), ('usdm-prime-cold-baseline', 'native-usdm.mjs')]:
    profile = native / label
    receipt = json.loads((profile / 'acceptance.json').read_text())
    assert receipt['passed'] is False
    assert receipt['driverSha256'] == hashlib.sha256((qa / driver).read_bytes()).hexdigest()
    exits = [step for step in receipt['steps'] if step['name'] == 'full-process-exit']
    assert len(exits) == 1 and len(exits[0]['evidence']['processes']) == 10
    samples = [json.loads(line) for line in (profile / 'resource-samples.jsonl').read_text().splitlines()]
    summary = dict(samples=len(samples), peak_sum_rss_KiB=max(item['rssKiB'] for item in samples),
                   last_observed_cpu_seconds=samples[-1]['cpuSeconds'], first=samples[0]['at'], last=samples[-1]['at'],
                   scope='unpaired failed cold profile; sum of owned process RSS, not unique physical memory; no allocation/GC claim')
    (profile / 'resource-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    failed = next(step['evidence'] for step in receipt['steps'] if step['name'] == 'failure-state')
    cases.append(dict(case=label, passed=False, source_head=receipt['sourceCommit'],
                      bars=[cell['runtime']['barCount'] for cell in failed['workspace']['cells']],
                      errors=[cell['runtime']['error'] for cell in failed['workspace']['cells']],
                      owned_exits=10, resources=summary))
    paths += [*profile.glob('*.json'), *profile.glob('*.jsonl'), *profile.glob('*.log'),
              profile / 'profile/logs/backend-sidecar.log']
    for image in profile.glob('*.png'):
        shutil.copyfile(image, qa / (label + '-' + image.name))
records = []
for source in sorted(set(paths)):
    if not source.is_file():
        continue
    relative = source.relative_to(out).as_posix()
    payload = source.read_bytes()
    original_hash = hashlib.sha256(payload).hexdigest()
    if source.suffix == '.json':
        value = json.loads(payload)
        redact(value, relative)
        payload = (json.dumps(value, indent=2) + '\n').encode()
    destination = qa / 'evidence' / (relative + '.gz')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(payload, mtime=0))
    assert gzip.decompress(destination.read_bytes()) == payload
    records.append(dict(source=relative, archive=destination.relative_to(qa).as_posix(),
                        original_sha256=original_hash, archived_payload_sha256=hashlib.sha256(payload).hexdigest(),
                        bytes=len(payload)))
(qa / 'evidence-index.json').write_text(json.dumps(records, indent=2) + '\n')
(qa / 'redactions.json').write_text(json.dumps(dict(policy='only credential/context token strings; numeric tokens and market values retained', paths=redactions), indent=2) + '\n')
(qa / 'failed-qualification.json').write_text(json.dumps(dict(source_head=manifest['product_head'], backend_files=len(manifest['files']),
    all_backend_and_asar_hashes_match=True, strict_signature_status=0, cases=cases), indent=2) + '\n')
print(json.dumps(dict(archived_text_records=len(records), cases=cases)))
