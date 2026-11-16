"""Summarize retained route observations; never infer a net readiness pass."""
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1])
acceptance = json.loads((run / 'acceptance.json').read_text())
routes, attempts = {}, {}
last_health = {}
source = run / 'source-health.jsonl'
if not source.exists():
    source = run / 'source-timeline.jsonl'
for line in source.read_text().splitlines():
    sample = json.loads(line)
    health = sample.get('health', sample.get('diagnostics', {}))
    fetcher = health.get('backfill_engine', {}).get('fetcher', {})
    if not fetcher:
        continue
    last_health = health
    for route in fetcher.get('recent_source_routes', []):
        routes[route['sequence']] = route
    for attempt in fetcher.get('public_admission', {}).get('recent', []):
        attempts[attempt['attempt_id']] = attempt
observed = next((s['evidence'] for s in acceptance['steps']
                 if s['name'] == 'source-routing-observed'), {})
sequences = sorted(routes)
summary = dict(schema='candlescope.issue460.native-routing/1',
    source_commit=acceptance['sourceCommit'], scope=acceptance['scope'],
    first_readiness_observed=acceptance.get('firstReadinessObserved', False),
    actual_total_observed_ms=acceptance.get('actualTotalElapsedMs'),
    observation_censored=not acceptance.get('firstReadinessObserved', False),
    net_readiness_ms=None, net_readiness_qualified=False,
    net_time_reason=acceptance.get('netReadinessReason'),
    failure=acceptance.get('failure'),
    cells=[dict(interval=c['session']['interval'], **{k:c['runtime'].get(k)
                for k in ['barCount', 'marketReady', 'indicatorsReady', 'loading']})
           for c in observed.get('workspace', {}).get('cells', [])],
    route_sequences=sequences,
    route_sequence_gaps=[i for i in range(1, max(sequences, default=0)+1) if i not in routes],
    source_routes=[routes[i] for i in sequences],
    public_attempt_count=len(attempts), public_attempts_are_not_subtracted=True,
    reconcile_metrics=last_health.get('backfill_engine', {}).get('reconciler', {}).get('metrics'),
    raw_artifacts={p.name:dict(bytes=p.stat().st_size,
                   sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                   for p in run.iterdir() if p.is_file() and p.name != 'routing-summary.json'})
(run / 'routing-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ['source_commit','first_readiness_observed',
      'actual_total_observed_ms','cells','public_attempt_count']}))
