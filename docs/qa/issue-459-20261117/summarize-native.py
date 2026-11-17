"""Collect bounded scheduler receipts without inferring net readiness."""
import collections
import json
from pathlib import Path
import subprocess
import sys

out=Path(sys.argv[1]);repo=Path(__file__).resolve().parents[3]
subprocess.run([sys.executable,str(repo/'docs/qa/issue-458-20261117/summarize-native.py'),str(out)],check=True,capture_output=True)
run=out/'native-cold';a=json.loads((run/'acceptance.json').read_text())
rows={};states=[]
for line in (run/'source-timeline.jsonl').read_text().splitlines():
    sample=json.loads(line);scheduler=sample['diagnostics'].get('backfill') or {}
    if 'chunk_receipt_sequence' not in scheduler:continue
    for row in scheduler.get('recent_chunks',[]):rows[row['sequence']]=row
    states.append({'at_ms':sample['at'],'ready_chunks':scheduler['ready_chunks'],
        'running_chunks':scheduler['running_chunks'],'max_concurrency':scheduler['max_concurrency'],
        'chunk_receipt_sequence':scheduler['chunk_receipt_sequence'],
        'chunk_receipts_dropped':scheduler['chunk_receipts_dropped'],
        'fairness_rotations':scheduler['fairness_rotations'],'aged_dispatches':scheduler['aged_dispatches'],
        'foreground_reserve_dispatches':scheduler['foreground_reserve_dispatches'],
        'active':scheduler['active'],'pending':scheduler['pending']})
ordered=[rows[key] for key in sorted(rows)]
assert ordered and all(r['ready_queue_ms']>=0 and r['not_eligible_wait_ms']>=0 for r in ordered)
assert all(r['effective_target_bars']>0 and r['planned_source_rows']<=r['source_row_budget'] for r in ordered)
assert all(s['running_chunks']<=s['max_concurrency']+(s['max_concurrency']==1) for s in states)
primary=['89m','97m','101m','10007m'];per_interval={}
for interval in primary:
    selected=[r for r in ordered if r['exchange']=='binance' and r['market_type']=='futures'
              and r['symbol']=='BTCUSDT' and r['interval']==interval]
    per_interval[interval]={'attempt_receipts':len(selected),'statuses':dict(collections.Counter(r['status'] for r in selected)),
        'first_started_at_ms':min((r['started_at_ms'] for r in selected),default=None),
        'max_ready_queue_ms':max((r['ready_queue_ms'] for r in selected),default=None),
        'max_ineligible_wait_ms':max((r['not_eligible_wait_ms'] for r in selected),default=None),
        'max_bypasses_before_dispatch':max((r['bypasses_before_dispatch'] for r in selected),default=None)}
summary=json.loads((out/'native-summary.json').read_text())
summary['scheduler']={'receipt_count':len(ordered),'max_sequence':max(rows),
    'missing_sequences':[n for n in range(1,max(rows)+1) if n not in rows],
    'retained_row_limit':256,'sample_count':len(states),
    'max_ready_queue':max(s['ready_chunks'] for s in states),
    'max_running':max(s['running_chunks'] for s in states),
    'nominal_concurrency':sorted({s['max_concurrency'] for s in states}),
    'foreground_reserve_dispatches':max(s['foreground_reserve_dispatches'] for s in states),
    'aged_dispatches':max(s['aged_dispatches'] for s in states),
    'statuses':dict(collections.Counter(r['status'] for r in ordered)),
    'primary_progress':per_interval,
    'maintenance_examples':[r for r in ordered if r['symbol']=='ETHUSDT' and r['interval']=='1m'][:4],
    'timing_boundary':'ineligible time includes probe/retry/quota; not certified external blocking. Worker and reported phases can overlap. No subtraction from wall time.'}
(out/'scheduler-receipts.json').write_text(json.dumps(ordered,indent=2)+'\n')
(out/'scheduler-states.json').write_text(json.dumps(states,indent=2)+'\n')
(out/'native-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
