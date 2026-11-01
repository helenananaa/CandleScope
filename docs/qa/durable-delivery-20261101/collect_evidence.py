"""Collect all paired runs, including the first adverse/confounded result."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DEST = Path(__file__).parent
OUT = ROOT / 'output/durable-delivery-20261101'
NATIVE = ROOT / 'output/durable-delivery-native-20261101'
artifacts = []


def read(path):
    return json.loads(path.read_text())


def keep(path, name):
    data = path.read_bytes()
    target = DEST / (name + '.gz')
    target.write_bytes(gzip.compress(data, mtime=0))
    artifacts.append({'file': target.name, 'sha256': hashlib.sha256(data).hexdigest(), 'uncompressed_bytes': len(data)})


runs = {}
reference = None
for name in ('baseline', 'candidate', 'baseline2', 'candidate2', 'candidate3', 'baseline3'):
    data = read(OUT / (name + '.json'))
    cases = data['cases']
    if reference is None:
        reference = cases
    for expected, case in zip(reference, cases):
        assert (expected['events'], expected['contention']) == (case['events'], case['contention'])
        assert case['canonical_sha256'] == expected['canonical_sha256']
        assert case['delivery_order_sha256'] == expected['delivery_order_sha256']
        assert case['pending'] == 0 and case['phases'] == {'published': case['events']}
        if name.endswith(('2', '3')):
            assert case['delivery_diagnostics']['acknowledgement_batch_size'] == (1 if name.startswith('baseline') else 16)
    runs[name] = [{'events': case['events'], 'contention': case['contention'],
                  'journal_transactions': case['journal_sql']['BEGIN'],
                  'drain_ms': case['drain_ms'], 'cpu_ms': case['cpu_ms'],
                  'publication_ms': case['publication_ms'],
                  'acknowledgement_batches': case.get('delivery_diagnostics', {}).get('acknowledgement_batches')}
                 for case in cases]
    keep(OUT / (name + '.json'), name + '.json')
    keep(OUT / (name + '.log'), name + '.log')

native = read(NATIVE / 'acceptance.json')
assert native['passed'] and not native['errors']
steps = {row['name']: row['evidence'] for row in native['steps']}
batch = steps['native-batch-recovery']
records = batch['after']['acknowledgement_records'] - batch['before']['acknowledgement_records']
count = batch['after']['acknowledgement_batches'] - batch['before']['acknowledgement_batches']
assert records == 64 and 0 < count < records
assert batch['recovered']['passed']
assert steps['restart-restores-values-and-published-receipts']['persisted']['passed']
exits = [row['evidence'] for row in native['steps'] if row['name'] == 'full-process-exit']
assert len(exits) == 2 and all(row['allExited'] for row in exits)
log = (NATIVE / 'profile/logs/backend-sidecar.log').read_text()
assert 'ERROR:' not in log and 'Traceback (most recent call last)' not in log
manifest = read(NATIVE / 'source-package-manifest.json')
assert not manifest['mismatches']
for name in ('acceptance.json', 'traffic.json', 'assembly.json', 'source-package-manifest.json', 'controlled-receipts.json', 'native.log'):
    keep(NATIVE / name, 'native-' + name)
keep(NATIVE / 'profile/logs/backend-sidecar.log', 'native-backend.log')
for name in ('baseline-regression.log', 'ack-tests.log', 'ack-final-tests.log', 'ack-bus-tests.log',
             'delivery-contract-tests.log', 'ack-crash-tests.log'):
    keep(OUT / name, name)
shutil.copy2(NATIVE / 'saved-durable-delivery.png', DEST / 'native-durable-delivery.png')
checks = {
    'schema': 'candlescope.durable-delivery-qualification/1',
    'source_commit': native['sourceCommit'],
    'collection_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'scope': 'Finite #121 stage: batch publication acknowledgements only; canonical commit/publication remain sequential.',
    'tests': {'journal_bridge': '45 passed', 'source_revision_consumer_contracts': '74 passed',
              'latest_acknowledgements': '14 passed including actual OS process exit after16 publications before acknowledgement',
              'counting': 'Overlapping selections; not an additive test total.'},
    'performance_runs': runs,
    'measurement_order': ['baseline (old source)', 'candidate (overlapped own regression test)',
                          'baseline2 batch1', 'candidate2 batch16', 'candidate3 batch16', 'baseline3 batch1'],
    'measurement_limits': [
        'All six raw runs retained, including first contention wall regression3988->4643ms.',
        'The first candidate overlapped this task regression tests. Four later counterbalanced runs were sequential with no other heavy owned work launched, but user/shared-host processes remained active.',
        'Counterbalanced256 without contention:768->561–573 journal transactions; CPU3802–4265->3231–3339ms. Shared-host wall time varies; no fixed speedup or latency SLA.',
        'Single-record delivery keeps3 journal transactions; batching benefits a backlog, not every isolated close.',
        'Real SQLite WAL with synchronous=NORMAL and busytimeout1000ms; injected competing lock holds, not a disk-speed or all-writer fairness qualification.',
        'Enqueue is outside drain timing and remains durable. SQL trace count includes trigger callbacks.',
    ],
    'native': {'passed': True, 'platform': 'macOS arm64', 'steps': len(native['steps']),
               'source_files': len(manifest['files']), 'dist_files': len(manifest['dist']),
               'assembly': manifest['assembly'], 'exit_ms': [row['elapsedMs'] for row in exits],
               'backend_exceptions': 0, 'controlled_records': records, 'acknowledgement_batches': count,
               'checks': ['Real public Binance BTC/ETH1m charts and independent MA20 numerical oracle',
                          'Real new close', '64 controlled committed-publication recovery receipts for existing real candles',
                          'Canonical candle hashes unchanged and receipts published',
                          'Saved workspace, full owned process-tree exit, restart restores values and receipts',
                          'Second full owned process-tree exit'],
               'limits': 'Recovery receipts are controlled replay, not64 extra exchange emissions; source/runtime assembly reused accepted frontend and runtime.'},
    'rollback': 'BAR_DELIVERY_ACK_BATCH_SIZE=1 on restart; no persistent schema change.',
    'recovery_contract': 'At most16 unconfirmed publications per default batch may replay after a crash; same durableIDs, existing live bus deduplication, restart remains at-least-once.50ms is checked between records, not a preemptive deadline.',
    'not_qualified': ['Windows installed acceptance', 'power loss', 'all SQLite writer fairness',
                      'removing idle submit flush', 'batching canonical writes', 'full issue121', 'full157 release acceptance'],
    'artifacts': artifacts,
}
(DEST / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'artifacts': len(artifacts), 'native_steps': len(native['steps']), 'records': records, 'batches': count}))
