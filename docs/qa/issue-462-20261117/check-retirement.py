"""Inspect the failed second witness without turning its overall result green."""
import json
from pathlib import Path
import sqlite3
import sys

root=Path(sys.argv[1]).resolve()
receipt=json.loads((root/'acceptance.json').read_text())
timeline=[json.loads(line) for line in (root/'recovery-timeline.jsonl').read_text().splitlines()]
first=timeline[0]['diagnostics']['market_data_control']['source_continuity']
last=timeline[-1]['diagnostics']['market_data_control']['source_continuity']
forming=[g for g in first['pending'] if g['detail']['forming_source_gap_ids']]
assert {g['interval'] for g in forming}=={'89m','97m','101m','10007m'}
assert last['forming_snapshots_required']==4 and not last['tracking_exhausted']
assert not any(g['detail']['forming_source_gap_ids'] for g in last['pending'])
assert not ({g['detail']['gap_id'] for g in forming}&{g['detail']['gap_id'] for g in last['pending']})
source=next(g for g in first['pending'] if g['interval']=='1m')
lower,upper=source['detail']['range_start_ms'],source['detail']['range_end_ms']
c=sqlite3.connect(f'file:{root}/profile/data/candlescope.db?mode=ro',uri=True)
inputs=c.execute("select open_time from klines where symbol='BTCUSDT' and interval='1m' and market_type='futures' and exchange='binance' and open_time between ? and ? order by open_time",(lower,upper)).fetchall()
assert [r[0] for r in inputs]==list(range(lower,upper+1,60000))
for gap in forming:
    assert not c.execute("select 1 from klines where symbol='BTCUSDT' and interval=? and market_type='futures' and exchange='binance' and open_time=?",(gap['interval'],gap['detail']['range_start_ms'])).fetchall(),'forming target must not be persisted as final'
log=(root/'profile/logs/backend-sidecar.log').read_text()
assert 'history target generation expired' not in log
summary={'forming_dependency_retirement_passed':True,'native_witness_passed':receipt['passed'],
         'actual_total_elapsed_ms':receipt['actualTotalElapsedMs'],'failure':receipt.get('failure'),
         'source_gap':source,'canonical_source_rows':len(inputs),'forming_gaps_retired':forming,
         'final_continuity':last,'generation_expired_count':0,
         'continuation_revision_rejections':log.count('Timeout loop error: history continuation source revision expired'),
         'remaining_scope':'Older closed 89m/97m repair and missing first-two JS probes remain in this run. No four-chart native pass, net-time or full lifecycle claim.'}
(root/'retirement-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in {'source_gap','forming_gaps_retired','final_continuity','failure'}}))
