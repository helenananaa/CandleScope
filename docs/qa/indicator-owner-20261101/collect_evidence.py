"""Collect inspectable local qualification, preserving failed attempts separately."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'output/indicator-owner-20261101'
NATIVE = ROOT / 'output/indicator-owner-native-20261101-shutdown'
DEST = Path(__file__).parent


def read(path):
    return json.loads(path.read_text())


def compressed(source, name):
    data = source.read_bytes()
    target = DEST / (name + '.gz')
    target.write_bytes(gzip.compress(data, mtime=0))
    return {'file': target.name, 'sha256': hashlib.sha256(data).hexdigest(), 'uncompressed_bytes': len(data)}


native = read(NATIVE / 'acceptance.json')
assert native['passed'] and not native['errors']
steps = {row['name']: row['evidence'] for row in native['steps']}
assert steps['real-provider-new-close']['diagnostics']['engine']['serial_owner']['generation'] == 0
assert steps['owned-compute-child-recovery']['after']['generation'] == 1
exits = [row['evidence'] for row in native['steps'] if row['name'] == 'full-process-exit']
assert len(exits) == 2 and all(row['allExited'] for row in exits)
assert 'ERROR:    Exception in ASGI application' not in (NATIVE / 'profile/logs/backend-sidecar.log').read_text()
manifest = read(NATIVE / 'source-package-manifest.json')
assert not manifest['mismatches']
manifest['assembly'] = read(NATIVE / 'assembly.json')['assembly']
(NATIVE / 'source-package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

files = []
for name in ['socket-final-baseline.json', 'socket-final-processes.json']:
    files.append(compressed(OUT / name, name))
for name in ['acceptance.json', 'traffic.json', 'assembly.json', 'source-package-manifest.json']:
    files.append(compressed(NATIVE / name, 'native-' + name))
files.append(compressed(NATIVE / 'profile/logs/backend-sidecar.log', 'native-backend.log'))
for name in ['final-transport-regression.log', 'warm-final-tests.log', 'transport-final-tests.log',
             'compatibility-tests.log', 'compute-batch-final-tests.log', 'reconnect-recovery-tests.log',
             'warm-resubscribe-before.log', 'shutdown-final-tests.log']:
    files.append(compressed(OUT / name, name))
for suffix, label in [('', 'attempt1'), ('-final', 'attempt2'), ('-verified', 'attempt3'), ('-accepted', 'attempt4')]:
    prior = ROOT / ('output/indicator-owner-native-20261101' + suffix)
    files.append(compressed(prior / 'acceptance.json', label + '-native.json'))
    if (prior / 'failed-startup-cleanup.json').exists():
        files.append(compressed(prior / 'failed-startup-cleanup.json', label + '-cleanup.json'))
shutil.copy2(NATIVE / 'saved-hosted-indicators.png', DEST / 'native-hosted-indicators.png')
baseline, candidate = (read(OUT / name) for name in ['socket-final-baseline.json', 'socket-final-processes.json'])
comparison = []
for before, after in zip(baseline['cases'], candidate['cases']):
    assert before['final_values_sha256'] == after['final_values_sha256']
    assert before['full_recompute_parity'] and after['full_recompute_parity']
    comparison.append({'instances': after['instances'], 'history_jobs': after['history_jobs'],
        'baseline_loop_p95_ms': before['loop_lag_ms']['p95'], 'candidate_loop_p95_ms': after['loop_lag_ms']['p95'],
        'baseline_delivery_p95_ms': before['delivery_ms']['p95'], 'candidate_delivery_p95_ms': after['delivery_ms']['p95'],
        'baseline_cpu_ms': before['process_cpu_ms'],
        'candidate_parent_realtime_cpu_ms': after['process_cpu_ms'] + after['worker_cpu_ms'],
        'candidate_history_process_cpu_ms': after['history_executor'].get('worker', {}).get('cpu_seconds', 0) * 1000,
        'realtime_peak_rss_bytes': after['worker_peak_rss_bytes'],
        'history_peak_rss_bytes': after['history_executor'].get('worker', {}).get('peak_rss_bytes')})
checks = {'schema': 'candlescope.indicator-owner-qualification/1',
    'source_commit': native['sourceCommit'], 'collection_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
    'scope': 'Builtin realtime serial ownership and separate builtin history capacity. Selected #120 P1/P2 contracts, not all #120 or all four goal batches.',
    'tests': {'backend_integration': '262 passed, 5 pre-existing warnings before warm-key followup',
              'latest_owner_ws_warm_lifecycle': '77 passed after warm-key and terminal WebSocket fixes',
              'final_transport': '8 passed', 'final_compute_batch': '12 passed',
              'compatibility': '75 passed, 1 skipped and 1 obsolete executor-test setup failure; corrected capacity test and all 12 compute-batch tests then passed',
              'before_fix_reproduction': 'warm resubscribe failed both thread and process with KeyError; retained log'},
    'native': {'passed': True, 'platform': 'macOS arm64', 'source_files': len(manifest['files']),
               'dist_files': len(manifest['dist']), 'steps': len(native['steps']),
               'exit_ms': [row['elapsedMs'] for row in exits],
               'transport': native['transport'], 'assembly': manifest['assembly'],
               'checks': ['two hosted MA charts and independent numerical oracle', 'shared same-definition instance',
                          'real new close with no spontaneous generation change', 'independent parameters',
                          'owned compute child failure and exactly one recovery', 'saved workspace and full process-tree exit',
                          'restart restores numerical values', 'last unsubscribe releases active references']},
    'attempts': {'attempt1': 'recovery reconnect became permanent HTTP fallback; fixed',
                 'attempt2': 'original script passed, but audit found warm resubscribe KeyError recovery and receive-after-close ASGI error; superseded',
                 'attempt3': 'QA default firstWindow30s expired before window opened; all owned processes subsequently exited via normal Browser.close; superseded',
                 'attempt4': 'normal native flow and exactly-one fault recovery passed; extended later with an active suspended history job at quit',
                 'final': 'fresh profile with QA firstWindow90s matching desktop startup budget; no production timeout change'},
    'performance': comparison,
    'performance_limits': 'Shared local machine with other development processes active; one final paired run, not an SLA. CPU includes child processes; RSS values are individual lifetime peaks, not a simultaneous total. IPC counters include seeding and final result retrieval. Separate processes improve loop isolation at additional CPU and memory cost.',
    'rollback': 'INDICATOR_REALTIME_ISOLATED=0 and INDICATOR_HISTORY_PROCESS_ENABLED=0 before restart restore legacy execution; no persistent schema changes.',
    'not_qualified': ['Windows installed acceptance', 'all157 release acceptance', 'Pine/Python/backtest shared-resource budgets',
                      'all builtin formulas in native UI', 'H127/R129 adoption', 'cold provider-registry bootstrap latency',
                      'preview coalescing and general scheduler fairness'],
    'artifacts': files}
(DEST / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps({'native_steps': len(native['steps']), 'artifacts': len(files), 'comparison': comparison}, indent=2))
