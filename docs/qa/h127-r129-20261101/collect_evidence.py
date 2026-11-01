"""Retain successful, adverse and failed runs without turning component evidence into release acceptance."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DEST = Path(__file__).parent
OUT = ROOT / 'output/h127-r129-20261101'
NATIVE = ROOT / 'output/h127-r129-native-20261101'
artifacts = []


def read(path):
    return json.loads(path.read_text())


def keep(path, name):
    data = path.read_bytes()
    target = DEST / (name + '.gz')
    target.write_bytes(gzip.compress(data, mtime=0))
    artifacts.append(dict(file=target.name, sha256=hashlib.sha256(data).hexdigest(),
                          uncompressed_bytes=len(data)))


runs = {}
reference = None
for name in ('baseline3', 'candidate', 'candidate2', 'candidate3', 'baseline4', 'final-default'):
    data = read(OUT / (name + '.json'))
    hashes = [(c['history_rows'], c['final_sha256']) for c in data['cases']]
    if reference is None:
        reference = hashes
    assert reference == hashes
    assert all(c['oracle_equal'] for c in data['cases'])
    runs[name] = dict(source=data['source_commit'], enabled=data['prefix_enabled'],
        minimum=data.get('minimum_prefix_rows', 64),
        cases=[{key: c[key] for key in ('history_rows', 'warm_ms', 'update_ms', 'correction_ms',
                                       'cpu_ms', 'loop_lag_ms', 'initial_shape', 'memory')}
               for c in data['cases']])
    keep(OUT / (name + '.json'), name + '.json')
final = runs['final-default']
assert final['minimum'] == 2048
assert [c['initial_shape']['compact'] for c in final['cases']] == [False, False, True]
for path in sorted(OUT.glob('*.log')):
    keep(path, path.name)

failed_attempts = []
for attempt in sorted((NATIVE / 'attempts').glob('*')):
    if not attempt.is_dir():
        continue
    receipt = read(attempt / 'acceptance.json')
    failed_attempts.append(dict(attempt=attempt.name, source=receipt['sourceCommit'],
                               failure=receipt.get('failure'), passed=receipt.get('passed', False)))
    for name in ('acceptance.json', 'traffic.json', 'assembly.json', 'source-package-manifest.json', 'native.log', 'diagnostic-stop.json', 'latest-probe.json', 'latest-probe-summary.json'):
        path = attempt / name
        if path.exists():
            keep(path, attempt.name + '-' + name)
    path = attempt / 'profile/logs/backend-sidecar.log'
    if path.exists():
        keep(path, attempt.name + '-backend.log')

native = read(NATIVE / 'acceptance.json')
assert native['passed'] and not native['errors']
steps = {step['name']: step['evidence'] for step in native['steps']}
for name in ('qualified-multipage-prefix-and-live-values', 'restart-restores-handoff-and-values'):
    last = steps[name]['diagnostics']['history_prefix']['last_adoption']
    assert last['complete'] and last['accepted_slots'] >= 2048 and last['pages'] >= 8
assert steps['new-native-close-with-prefix-refresh']['diagnostics']['history_prefix']['refreshes'] > 0
assert steps['restart-rollback-preserves-values']['diagnostics']['history_prefix'] == {'enabled': False}
exits = [s['evidence'] for s in native['steps'] if s['name'] == 'full-process-exit']
assert len(exits) == 3 and all(s['allExited'] for s in exits)
manifest = read(NATIVE / 'source-package-manifest.json')
assert not manifest['mismatches'] and manifest['sourceCommit'] == native['sourceCommit']
log = (NATIVE / 'profile/logs/backend-sidecar.log').read_text()
# The aborted old viewport request intentionally raises CancelledError after
# draining request-owned computation. Uvicorn logs that explicit control flow
# as an ASGI exception; retain it and do not claim zero backend exceptions.
expected_disconnects = log.count('asyncio.exceptions.CancelledError: indicator HTTP request disconnected')
assert expected_disconnects == 1
assert log.count('ERROR:') == expected_disconnects
assert log.count('Traceback (most recent call last)') == expected_disconnects
for name in ('acceptance.json', 'traffic.json', 'assembly.json', 'source-package-manifest.json', 'native.log'):
    keep(NATIVE / name, 'native-' + name)
keep(NATIVE / 'profile/logs/backend-sidecar.log', 'native-backend.log')
shutil.copy2(NATIVE / 'saved-prefix-handoff.png', DEST / 'native-prefix-handoff.png')
checks = dict(
    schema='candlescope.h127-r129-qualification/1', source_commit=native['sourceCommit'],
    collection_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    scope='Finite H127-to-R129 canonical history prefix plus live component overlay, not full issues127/129.',
    admission=dict(minimum_elapsed_source_rows=2048, maximum_target_source_rows=65536,
                   maximum_targets=128, maximum_tasks=64, maximum_seeds=8,
                   page_rows=256, compact_prefix_bytes=32768,
                   sources='Existing H127 qualified Binance/OKX default native1m–1d identities; fixed UTC epoch targets tiled exactly by their source.'),
    tests=dict(integrated='120 earlier integration selection passed',
               source_readiness='112 related source-gap/bridge/recovery cases passed; 3 real DataManager cases failed before the fix',
               prefix_revision_recovery='32 selection and final11 cases passed; initial source-write conflict regression failed before the fix',
               frontend_recovery='479 market-data tests passed, both TypeScript configs and Vite desktop build passed; visible forming recovery and exact pending-owner tests include before-fix failures',
               physical_clock_admission='78 tests passed; actual two-demand admission test failed before proven historical server-time reuse',
               architecture='70 architecture/runtime cases,33 reader/warm cases passed after owner-boundary extraction',
               large_viewport_and_handoff='141 passed; two realSQLite viewport cases failed before the page-size fix',
               direct_fence_and_B130='80 passed', size_selection='19 passed',
               counting='Overlapping selections, not additive. All earlier failed logs retained.'),
    performance_runs=runs,
    performance_limits=[
        'All successful, adverse and failed runs are retained. First two baseline attempts exposed QA route/freshness mistakes and are not measurements.',
        'Initial candidate has higher live, correction and CPU costs; rejected as the broad default.',
        'Direct existing D126 source-version read replaces a new B130 view and repeated global change polls on each live input.',
        'Reverse candidate3/baseline4:4000-row warm265/471ms, maximum loop lag13.45/471.89ms; CPU641/542ms and correction294/5.5ms. Compact retention and responsiveness improve while CPU/live/correction costs can increase.',
        'Default admission narrowed to at least2048 elapsed source rows. This measured cutoff is not a universal optimum.',
        'Final default-mode run verifies selection and numeric hashes after integrating PR197; shared host load increased. Do not compare it as an isolated speedup against earlier runs.',
        'Coarse source revision invalidates the entire prefix after a source write. Correction still performs a bounded rebuild; not a per-bar amendment optimization.',
        'Memory estimates include retained prefix and owner slots; shared B130/history/cache budgets are separately accounted, not a whole-process RSS claim.',
        'Real isolated SQLite with controlled input and actual DataManager/bridge/cache; no network during benchmarks. No fixed latency SLA.'
    ],
    native=dict(passed=True, platform='macOS arm64', steps=len(native['steps']),
                source_files=len(manifest['files']), dist_files=len(manifest['dist']),
                assembly=manifest['assembly'], exit_ms=[s['elapsedMs'] for s in exits],
                renderer_exceptions=0, backend_logged_exceptions=expected_disconnects,
                backend_exception_review='One expected HTTP client-disconnect CancelledError from _run_until_request_disconnect after request work cancellation/drain; no other ERROR or traceback. Not zero backend logged exceptions.',
                cold_ready_seconds=443.058,
                cold_load_limit='Real public cold qualification took roughly7m23s from packaged launch to first prefix+value proof. This is functional acceptance, not a cold-load latency SLA or isolated performance improvement.',
                scope=native['scope'],
                checks=['Real public Binance1m and qualified long derived interval, multipage prefix proof',
                        'Independent MA20/MA3 oracle for all available comparable points and every paintable closed viewport point, actual return-to-realtime UI action, then new1m close',
                        'Saved workspace, full owned exit and restart restores values and prefix',
                        'Second exit, rollback disabled on restart, same workspace values',
                        'Third full owned process-tree exit']),
    rollback='HISTORY_PREFIX_ENABLED=0 on restart; persisted candles and workspace remain usable.',
    failed_native_attempts=failed_attempts,
    not_qualified=['Windows installed acceptance', 'all157 release acceptance', 'all127/129 scope',
                   'all-source mixed histories', 'monthly/session/synthetic/seconds prefixes',
                   'native destructive canonical amendment/deletion fault soak', 'fixed performance SLA'],
    artifacts=artifacts)
(DEST / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(artifacts=len(artifacts), native_steps=len(native['steps']))))
