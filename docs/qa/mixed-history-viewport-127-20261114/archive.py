"""Archive finite receipts, preserving failures and excluding profiles/databases."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

qa = Path(__file__).resolve().parent
root = qa.parents[2]
output = root / 'output/mixed-history-viewport-127-20261114'
prior = Path('/Users/ryanliang/.codex/worktrees/mixed-history-admission-127-20261114/CandleScope/output/mixed-history-admission-127-20261114')
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

for base, label in ((prior, 'planning-development'), (output, 'viewport-development')):
    for source in sorted(base.iterdir()):
        if not source.is_file() or source.suffix not in {'.log', '.xml', '.jsonl'} or source.name == 'archive.log':
            continue
        # A running redirected test log is not a terminal receipt.
        if source.suffix == '.log' and source.with_suffix('.xml').exists():
            try:
                ET.parse(source.with_suffix('.xml'))
            except ET.ParseError:
                continue
        if source.name == 'backend-dispatch-full.log' and not source.with_suffix('.xml').exists():
            continue
        archive(source, label + '/' + source.name)
    for source in sorted(base.glob('plan-*/results.json')):
        archive(source, label + '/' + str(source.relative_to(base)))

native = []
for run in sorted(output.glob('native-*')):
    receipt = run / 'acceptance.json'
    if not receipt.exists():
        continue
    document = json.loads(receipt.read_text())
    if not any(step['name'] == 'full-process-exit' for step in document.get('steps', [])):
        continue
    native.append(dict(run=run.name, passed=document.get('passed'),
        source=document.get('sourceCommit'), diagnostic=document.get('diagnosticLogging'),
        failure=document.get('failure')))
    for source in sorted(run.iterdir()):
        if source.is_file() and source.suffix in {'.json', '.jsonl', '.log'}:
            archive(source, run.name + '/' + source.name)
        elif source.suffix == '.png':
            shutil.copyfile(source, qa / (run.name + '-' + source.name))
    source = run / 'profile/logs/backend-sidecar.log'
    if source.exists():
        archive(source, run.name + '/backend-sidecar.log')
for candidate in sorted(output.glob('native-*candidate')):
    for source in sorted(candidate.iterdir()):
        if source.is_file() and source.suffix in {'.json', '.log'}:
            archive(source, candidate.name + '/' + source.name)
for source in sorted((output / 'task-diagnostic-bootstrap').glob('*.py')):
    archive(source, 'diagnostic-bootstrap/' + source.name)

tests = {}
for source in sorted(output.glob('*.xml')):
    document = ET.parse(source).getroot()
    suites = [document] if document.tag == 'testsuite' else list(document.iter('testsuite'))
    tests[source.stem] = {name: sum(float(suite.get(name, '0')) for suite in suites)
                          for name in ('tests', 'failures', 'errors', 'skipped', 'time')}
(qa / 'evidence-index.json').write_text(json.dumps(index, indent=2) + '\n')
(qa / 'redactions.json').write_text(json.dumps(redactions, indent=2) + '\n')
(qa / 'verification.json').write_text(json.dumps(dict(
    archive_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    native=native, tests=tests), indent=2) + '\n')
print(json.dumps(dict(archives=len(index), native=native, tests=tests)))
