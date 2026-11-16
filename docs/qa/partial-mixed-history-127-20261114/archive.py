"""Archive finite test/probe receipts; never archive the retained SQLite files."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

qa = Path(__file__).resolve().parent
root = qa.parents[2]
output = root / 'output/partial-mixed-history-127-20261114'
summaries = {}
for label in ('baseline', 'final-focused', 'default-final', 'backend-final'):
    document = ET.parse(output / (label + '.xml')).getroot()
    suites = [document] if document.tag == 'testsuite' else list(document.iter('testsuite'))
    stats = {name: sum(float(suite.get(name, '0')) for suite in suites)
             for name in ('tests', 'failures', 'errors', 'skipped', 'time')}
    if label == 'baseline':
        assert stats['failures'] == 2 and stats['errors'] == 0
    else:
        assert stats['failures'] == stats['errors'] == 0
    summaries[label] = stats
probe = json.loads((output / 'real-profile-b43/results.json').read_text())
assert probe['source_head'].startswith('b43d5a511') and not probe['source_diff']
assert probe['original_unchanged'] and probe['canonical_values_equal']
assert all(item['bars'] == 133 and not item['complete'] and item['history_state'] == 'pending'
           for item in probe['results'])
assert probe['results'][0]['metadata']['target_materialized_written'] == 0
assert probe['results'][0]['metadata']['target_materialized'] is False
paths = [*output.glob('*.log'), *output.glob('*.xml'),
         *output.glob('real-profile-b43/*.json'), *output.glob('native/*.json'),
         *output.glob('native/*.log'), *output.glob('native/partial-warm*/*.json'),
         *output.glob('native/partial-warm*/*.mjs'),
         *output.glob('native/partial-warm*/profile/logs/backend-sidecar.log')]
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
for image in output.glob('native/partial-warm*/*.png'):
    shutil.copyfile(image, qa / (image.parent.name + '-' + image.name))
index = []
for source in sorted(paths):
    if source.name == 'archive.log':
        continue
    payload = source.read_bytes()
    original_sha256 = hashlib.sha256(payload).hexdigest()
    if source.suffix == '.json':
        document = json.loads(payload)
        redact(document, source.relative_to(output).as_posix())
        payload = (json.dumps(document, indent=2) + '\n').encode()
    destination = qa / 'evidence' / (str(source.relative_to(output)) + '.gz')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(payload, mtime=0))
    assert gzip.decompress(destination.read_bytes()) == payload
    index.append(dict(source=source.relative_to(output).as_posix(),
        archive=destination.relative_to(qa).as_posix(), bytes=len(payload),
        original_sha256=original_sha256, archived_payload_sha256=hashlib.sha256(payload).hexdigest()))
files = ['backend/app/data_engine/data_manager/custom_query.py',
         'backend/app/data_engine/data_manager/mixed_query.py',
         'backend/tests/test_default_mixed_history_query.py']
receipt = dict(runtime_source_head=probe['source_head'],
    current_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    source_sha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
    tests=summaries, real_profile_probe=dict(bars=133, canonical_values_equal=True,
        original_unchanged=True, pending=True, target_writes=0),
    native_partial_paint=json.loads((output / 'native/partial-paint-observation.json').read_text()),
    scope='full backend collection predates the last test-only exact repair-span contract; '
          'default-final includes that added contract; final CI must collect all current tests; '
          'native baseline remains failed, no passing native/resource qualification')
(qa / 'evidence-index.json').write_text(json.dumps(index, indent=2) + '\n')
(qa / 'redactions.json').write_text(json.dumps(redactions, indent=2) + '\n')
(qa / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
