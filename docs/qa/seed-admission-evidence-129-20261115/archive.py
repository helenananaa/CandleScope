"""Archive completed native observations and checks without profiles or databases."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil

qa = Path(__file__).resolve().parent
root = qa.parents[2]
output = root / 'output/seed-admission-evidence-129-20261115'
index, redactions = [], []

def redact(value, location):
    if isinstance(value, dict):
        for key, item in value.items():
            name = key.lower()
            if isinstance(item, str) and (name.endswith('token') or name in {'password', 'secret', 'authorization', 'cookie', 'apikey'}):
                value[key] = '[REDACTED]'
                redactions.append(location + '/' + key)
            else:
                redact(item, location + '/' + key)
    elif isinstance(value, list):
        for position, item in enumerate(value):
            redact(item, location + '/' + str(position))

def archive(source, label):
    payload = source.read_bytes()
    original = hashlib.sha256(payload).hexdigest()
    if source.suffix == '.json':
        document = json.loads(payload)
        redact(document, label)
        payload = (json.dumps(document, indent=2) + '\n').encode()
    destination = qa / 'evidence' / (label + '.gz')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(payload, mtime=0))
    assert gzip.decompress(destination.read_bytes()) == payload
    index.append(dict(source=str(source), archive=str(destination.relative_to(qa)),
        original_sha256=original, archived_payload_sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))

for source in sorted(output.iterdir()):
    if source.is_file() and source.suffix in {'.log', '.json', '.xml'}:
        archive(source, source.name)
for name in ('native-diagnostic', 'native-dispatch-cold'):
    run = output / name
    receipt = json.loads((run / 'acceptance.json').read_text())
    assert not receipt.get('cleanupFailure')
    assert any(step['name'] == 'full-process-exit' for step in receipt['steps'])
    for source in sorted(run.iterdir()):
        if source.is_file() and source.suffix in {'.json', '.jsonl', '.log'}:
            archive(source, name + '/' + source.name)
        elif source.suffix == '.png':
            destination = qa / (name + '-' + source.name)
            shutil.copyfile(source, destination)
            payload = source.read_bytes()
            index.append(dict(source=str(source), archive=destination.name,
                original_sha256=hashlib.sha256(payload).hexdigest(),
                archived_payload_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), bytes=len(payload)))
    backend = run / 'profile/logs/backend-sidecar.log'
    if backend.exists():
        archive(backend, name + '/backend-sidecar.log')
for source in sorted((output / 'native-dispatch-candidate').iterdir()):
    if source.is_file() and source.suffix in {'.json', '.log'}:
        archive(source, 'native-candidate/' + source.name)
(qa / 'evidence-index.json').write_text(json.dumps(index, indent=2) + '\n')
(qa / 'redactions.json').write_text(json.dumps(redactions, indent=2) + '\n')
print(json.dumps(dict(archives=len(index), redactions=len(redactions))))
