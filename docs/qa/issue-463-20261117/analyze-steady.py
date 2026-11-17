"""Audit fixed samples and first consistent captured states near each minute.

Raw instantaneous failures are retained. Settled observations use the first
strictly correct captured state within 15s of each nominal minute, never a
relaxed numerical tolerance or fabricated sample; this is supplemental to the
original driver verdict, not permission to turn the joint result green.
"""
import json,re,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();rows=[json.loads(l) for l in (root/'acceptance-timeline.jsonl').open()]
nominal=[r for r in rows if re.fullmatch(r'steady-minute-\d+',r['label'])]
assert len(nominal)==11
start=nominal[0]['at'];frames=[json.loads(l) for l in (root/'business-frames.jsonl').open()]
frames=[r for r in frames if r['message'].get('type')=='kline']
base=[]
if (root/'base-input-observer.jsonl').exists():
 for line in (root/'base-input-observer.jsonl').open():
  record=json.loads(line)
  if record.get('body',{}).get('data'):base.append(record)
charts=[]
for interval in ('89m','97m','101m','10007m'):
 chosen=[];missing=[]
 for minute in range(11):
  due=start+minute*60000;candidate=None
  for sample in rows:
   if not due<=sample['at']<=due+15000:continue
   oracle=next((o for o in sample['oracles'] if o['interval']==interval),None)
   if not oracle or oracle['issues']:continue
   view=next(v for v in sample['views'] if v['interval']==interval);bar=view['bars'][-1]
   display=next(d for d in sample['displays'] if d['cellId']==view['cellId'])['text']
   rendered=re.search(r'\bC\s*([0-9,]+\.[0-9]+)',display)
   if not rendered or abs(float(rendered[1].replace(',',''))-bar['close'])>.005:continue
   wire=[r for r in frames if r['at']<=sample['at'] and r['message'].get('interval')==interval and r['message'].get('market_type')=='futures' and r['message']['data']['time']==bar['time'] and r['message']['data']['close']==bar['close'] and abs(r['message']['data']['volume']-bar['volume'])<=1e-6]
   source=[r for r in base if r['at']<=sample['observedAt'] and r['observed_at']>=sample['at']-3000 and r['body']['data'][-1]['close']==bar['close'] and bar['time']<=r['body']['data'][-1]['time']<bar['time']+int(interval[:-1])*60]
   candidate={'minute':minute,'at':sample['at'],'label':sample['label'],'settle_observation_ms':sample['at']-due,'oracle':oracle,'bar':bar,
    'lines_last':[{k:v for k,v in l.items() if k!='data'}|{'last':l['data'][-1] if l['data'] else None} for l in view['lines']],
    'screen_C':rendered[1],'matching_business_ws':wire[-1] if wire else None,'matching_base_read':source[-1] if source else None}
   break
  if candidate:chosen.append(candidate)
  else:missing.append(minute)
 signatures={json.dumps({'bar':r['bar'],'lines':r['lines_last']},sort_keys=True) for r in chosen}
 charts.append({'interval':interval,'captured_consistent_states':len(chosen),'missing_minutes':missing,'distinct_states':len(signatures),
  'ws_correlated':sum(r['matching_business_ws'] is not None for r in chosen),'base_correlated':sum(r['matching_base_read'] is not None for r in chosen),
  'selected_span_ms':chosen[-1]['at']-chosen[0]['at'] if len(chosen)>1 else None,'chosen':chosen})
result={'scope':__doc__,'nominal_samples':11,'nominal_all_four_correct':sum(all(not o['issues'] for o in r['oracles']) for r in nominal),
 'settled_chart_values_observed':all(c['captured_consistent_states']==11 and c['distinct_states']==11 and c['selected_span_ms']>=600000 for c in charts),
 'full_input_ws_screen_chain':all(c['base_correlated']==11 and c['ws_correlated']==11 for c in charts),'charts':charts}
(root/'steady-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'charts','scope'}}|{'charts':[{k:v for k,v in c.items() if k!='chosen'} for c in charts]}))
