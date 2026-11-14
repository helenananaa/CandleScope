import json, os, statistics, subprocess
from pathlib import Path
import argparse, sys
parser=argparse.ArgumentParser(description='Three alternating whole-backend pairs with explicit barrier CPU separated.')
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--candidate',type=Path,default=Path(__file__).resolve().parents[3])
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--python',default=sys.executable)
args=parser.parse_args()
root=args.candidate.resolve()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
baseline=args.baseline.resolve()
python=args.python
harness=Path(__file__).with_name('hot-phase-cost.py')
results={mode:[] for mode in ('base','enabled')}
for pair in range(3):
 for mode in (('base','enabled') if pair%2==0 else ('enabled','base')):
  source=baseline if mode=='base' else root
  prefix=f'hot-paired-{mode}-{pair}'
  with (out/(prefix+'.log')).open('w') as log:
   process=subprocess.run([python,str(harness),'--source',str(source),'--mode',mode,'--attempts','1','--counts','2048','10007','--output',str(out/(prefix+'.json'))],stdout=log,stderr=subprocess.STDOUT,cwd=root,env={**os.environ,'CANDLE_DATA_DIR':str(out/(prefix+'-data')),'DATA_DIR':str(out/(prefix+'-data'))})
  if process.returncode: raise RuntimeError((prefix,process.returncode))
  results[mode].append(json.loads((out/(prefix+'.json')).read_text()))
  print(prefix,flush=True)
summary=[]
for position,slots in enumerate((2048,10007)):
 rows={mode:[value['results'][position]['trials'][0] for value in trials] for mode,trials in results.items()}
 for old,new in zip(rows['base'],rows['enabled']):
  for name in ('canonical_sha256','event_sha256','watermarks'):
   assert old[name]==new[name],(slots,name)
 summary.append(dict(slots=slots,updates=500,all_values_events_watermarks_equal=True,medians={mode:{name:statistics.median(value[name] for value in trials) for name in ('source_record_cpu_ms','ingest_cpu_ms','barrier_cpu_ms','total_source_and_aggregate_cpu_ms')} for mode,trials in rows.items()},rows=rows))
(out/'paired-summary.json').write_text(json.dumps(dict(scope='Three alternating independent whole-backend pairs; 500 forming inputs; explicit per-input delivery barrier measured separately; final original deadline included; no network; no overall application/RSS qualification',results=summary),indent=2)+'\n')
print(json.dumps([{key:value for key,value in row.items() if key!='rows'} for row in summary]),flush=True)
