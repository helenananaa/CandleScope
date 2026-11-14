import json, subprocess, statistics
from pathlib import Path
r=Path('/Users/ryanliang/.codex/worktrees/source-window-recovery-129-20261113/CandleScope')
o=r/'output/source-window-recovery-129-20261113'
python='/Users/ryanliang/.codex/worktrees/aggregation-closeout-20261112/CandleScope/.venv/bin/python'
results={mode:[] for mode in ('base','enabled')}
for pair in range(3):
    for mode in (('base','enabled') if pair%2==0 else ('enabled','base')):
        source=o/'base-backend' if mode=='base' else r
        prefix=f'hot-paired-{mode}-{pair}'
        with (o/(prefix+'.log')).open('w') as log:
            result=subprocess.run([python,str(r/'docs/qa/source-window-recovery-129-20261113/hot-cost.py'),
                '--source',str(source),'--mode',mode,'--attempts','1','--counts','2048','10007',
                '--output',str(o/(prefix+'.json'))],stdout=log,stderr=subprocess.STDOUT,cwd=r)
        if result.returncode:raise RuntimeError((prefix,result.returncode))
        results[mode].append(json.loads((o/(prefix+'.json')).read_text()))
        print(prefix,flush=True)
summary=[]
for pos,slots in enumerate((2048,10007)):
    rows={mode:[v['results'][pos]['trials'][0] for v in results[mode]] for mode in results}
    for old,new in zip(rows['base'],rows['enabled']):
        for key in ('canonical_sha256','event_sha256','watermarks'):
            assert old[key]==new[key],(slots,key)
    summary.append(dict(slots=slots,updates=500,all_values_events_watermarks_equal=True,
        median_aggregate_cpu_ms={mode:statistics.median(v['phases'][0]['cpu_ms'] for v in values) for mode,values in rows.items()},
        median_total_cpu_ms={mode:statistics.median(v['total_source_and_aggregate_cpu_ms'] for v in values) for mode,values in rows.items()},
        rows=rows))
(o/'hot-paired-summary.json').write_text(json.dumps(dict(scope='three alternating independent whole-backend pairs; 500 normal forming updates; original publisher throttle; no deferred scheduler/network; pre-loop GC reported; GC remains enabled',results=summary),indent=2)+'\n')
print(json.dumps([{key:value for key,value in row.items() if key!='rows'} for row in summary]),flush=True)
