"""Preserve failed gates, bounded scheduler receipts and physical package identity."""
import collections,gzip,hashlib,json,subprocess,sys
from datetime import datetime
from pathlib import Path
root=Path(sys.argv[1]).resolve();candidate=Path(sys.argv[2]).resolve()
receipt=json.loads((root/'acceptance.json').read_text());manifest=json.loads((candidate/'package-source-manifest.json').read_text())
assert receipt['sourceCommit']==manifest['product_head']
resources=candidate/'CandleScope.app/Contents/Resources'
for name,digest in manifest['files'].items():assert hashlib.sha256((resources/name).read_bytes()).hexdigest()==digest,name
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()==manifest['app_asar_sha256']
subprocess.run(['codesign','--verify','--deep','--strict',str(candidate/'CandleScope.app')],check=True)
extract_code='const a=require(process.argv[1]),c=require("node:crypto"),fs=require("node:fs");const m=JSON.parse(fs.readFileSync(process.argv[3]));for(const [p,h] of Object.entries(m.frontend_files)){if(c.createHash("sha256").update(a.extractFile(process.argv[2],p)).digest("hex")!==h)throw Error(p)}process.stdout.write(String(Object.keys(m.frontend_files).length));'
asar_package=Path(sys.argv[3]).resolve()
frontend_verified=int(subprocess.check_output(['node','-e',extract_code,str(asar_package),str(resources/'app.asar'),str(candidate/'package-source-manifest.json')],text=True))
chunks={};routes={};states=[];readiness=[];steady=[]
launches=[(int(datetime.fromisoformat(s['at'].replace('Z','+00:00')).timestamp()*1000),s['evidence']['identity']['pid']) for s in receipt['steps'] if s['name']=='packaged-launch']
def owner_at(at):return next((pid for when,pid in reversed(launches) if when<=at),launches[0][1] if launches else 0)
with (root/'acceptance-timeline.jsonl').open() as source:
 for line in source:
  row=json.loads(line);states.append({'at':row['at'],'label':row['label'],'chart_counts':{o['interval']:o['bars'] for o in row['oracles']},'runtime':[{k:c['runtime'].get(k) for k in ('marketReady','initialHistoryPending','loading','barCount','indicatorsReady')}|{'interval':c['session']['interval']} for c in row['workspace']['cells']]})
  if row['label'].startswith('steady-minute-'):steady.append({'at':row['at'],'label':row['label'],'oracles':row['oracles']})
  backfill=row['diagnostics'].get('backfill',{})
  for chunk in backfill.get('recent_chunks',[]):chunks[(owner_at(row['at']),chunk['sequence'])]=dict(chunk,observed_app_pid=owner_at(row['at']))
  fetcher=row['diagnostics'].get('backfill_engine',{}).get('fetcher',{})
  for route in fetcher.get('recent_source_routes',[]):routes[(owner_at(row['at']),route['sequence'])]=dict(route,observed_app_pid=owner_at(row['at']))
(root/'scheduler-chunks.json').write_text(json.dumps(sorted(chunks.values(),key=lambda r:r['sequence']),indent=2)+'\n')
(root/'source-routes.json').write_text(json.dumps(sorted(routes.values(),key=lambda r:r['sequence']),indent=2)+'\n')
queue={}
for interval in ('89m','97m','101m','10007m'):
 group=[r for r in chunks.values() if r['interval']==interval and r['symbol']=='BTCUSDT' and r['market_type']=='futures']
 queue[interval]={'attempts':len(group),'max_ready_queue_ms':max((r['ready_queue_ms'] for r in group),default=0),'max_not_eligible_wait_ms':max((r['not_eligible_wait_ms'] for r in group),default=0),'statuses':dict(collections.Counter(r['status'] for r in group))}
profile=Path(next(s['evidence']['identity']['userData'] for s in receipt['steps'] if s['name']=='packaged-launch'))
log=(profile/'logs/backend-sidecar.log').read_text(); lines=log.splitlines();terminals=collections.Counter()
for i,line in enumerate(lines):
 if line.startswith('Traceback (most recent call last)'):
  j=i+1
  while j<len(lines) and (lines[j].startswith(' ') or not lines[j]):j+=1
  if j<len(lines):terminals[lines[j]]+=1
result={'passed':receipt.get('passed',False),'qualification_kind':receipt.get('schema'),'scope':receipt.get('scope'),'functional_matrix_passed':receipt.get('functionalMatrixPassed',False),
 'net_readiness_passed':receipt.get('netReadinessPassed'),'net_readiness_ms':receipt.get('netReadinessMs'),
 'net_attribution':'No certified per-chart critical-path physical request/quota span graph; do not subtract cumulative fetch totals. Evidence gap is separate from observed functional failures.',
 'cold_observed_ready':receipt.get('coldObservedReady',False),'product_head':manifest['product_head'],'backend_files_verified':len(manifest['files']),'retained_frontend_files_verified':frontend_verified,'app_asar_sha256':manifest['app_asar_sha256'],
 'pre_demand_canonical_rows':receipt.get('preDemandInventory',{}).get('canonical_rows'),
 'demand_started_at_ms':receipt.get('demandStartedAtMs'),'actual_total_elapsed_ms':receipt.get('actualTotalElapsedMs'),
 'first_ready':receipt.get('firstReady',{}),'cold_observation_elapsed_ms':receipt.get('coldObservationElapsedMs'),
 'outcomes':receipt.get('outcomes',[]),'states':states,'steady':steady,'queue':queue,
 'scheduler_sequences':{'count':len(chunks),'by_app_pid':{str(pid):{'first':min(seq for p,seq in chunks if p==pid),'last':max(seq for p,seq in chunks if p==pid),'missing':sorted(set(range(min(seq for p,seq in chunks if p==pid),max(seq for p,seq in chunks if p==pid)+1))-{seq for p,seq in chunks if p==pid})} for pid in {p for p,_ in chunks}}},
 'source_route_count':len(routes),'traceback_terminal_lines':dict(terminals),'full_exit_observed':any(s['name']=='full-process-exit' for s in receipt['steps'])}
result['traceback_scope']='Entire persisted profile backend log, including later continuations; occurrences are not distinct defects or restricted to this receipt.'
if (root/'queue-lower-bound.json').exists():
 proof=json.loads((root/'queue-lower-bound.json').read_text())
 result.update(net_readiness_passed=proof['passed_net_3s'],net_readiness_ms=None,
  net_attribution='FAILURE LOWER BOUND from required generation-1 closed targets waiting in the eligible internal queue; exact net remains uncomputed. Internal concurrency/scheduling queues count under the explicit acceptance rule, including overlap with other communication.',
  required_local_queue_lower_bound_ms={p['interval']:p['local_queue_lower_bound_ms'] for p in proof['proofs']})
# Diagnostic concurrency and sharing observations; never wall-clock deductions.
last_backfill=row['diagnostics'].get('backfill',{})
last_fetcher=row['diagnostics'].get('backfill_engine',{}).get('fetcher',{})
result['last_input_subscriptions']={k:v for k,v in last_fetcher.get('input_subscriptions',{}).items() if k!='active_input_sample'}
result['last_fetch_counters']=last_fetcher.get('metrics',{}).get('counters',{})
result['logical_admission']=last_backfill.get('logical_admission')
result['readiness_errors']=receipt.get('readinessErrors',{})
result['diagnostic_observations']={'max_running_chunks':0,'max_capacity_waiting_chunks':0,'max_shared_subscriptions':0,'max_stale_inputs_retired':0}
for line in (root/'acceptance-timeline.jsonl').open():
 record=json.loads(line); d=record['diagnostics']; b=d.get('backfill',{}); f=d.get('backfill_engine',{}).get('fetcher',{}).get('input_subscriptions',{})
 for name,value in [('max_running_chunks',b.get('running_chunks',0)),('max_capacity_waiting_chunks',b.get('capacity_waiting_chunks',0)),('max_shared_subscriptions',f.get('shared_page_subscriptions',0)),('max_stale_inputs_retired',f.get('stale_inputs_retired',0))]:
  result['diagnostic_observations'][name]=max(result['diagnostic_observations'][name],value)
# Overlap of sampled execution spans proves logical parent-chunk concurrency.
# Missing ring receipts only reduce this bound; this is not physical I/O timing.
parent_spans=collections.defaultdict(list)
for chunk in chunks.values():
 parent=(chunk['observed_app_pid'],chunk['request_id'])
 if chunk['finished_at_ms']>chunk['started_at_ms']:
  parent_spans[parent].extend([(chunk['started_at_ms'],1),(chunk['finished_at_ms'],-1)])
parent_peaks=[]
for events in parent_spans.values():
 active=peak=0
 for at,delta in sorted(events):
  active+=delta;peak=max(peak,active)
 parent_peaks.append(peak)
result['max_observed_parent_workers_lower_bound']=max(parent_peaks,default=0)
result['last_working_set_admission']=row['diagnostics'].get('backfill_engine',{}).get('working_set_admission',{})
result['last_phase_resumptions']=last_backfill.get('phase_resumptions',0)
result['primary_attempts']={
 'statuses':dict(collections.Counter(c['status'] for c in chunks.values() if c['symbol']=='BTCUSDT' and c['market_type']=='futures' and c['interval'] in ('89m','97m','101m','10007m'))),
 'defer_reasons':dict(collections.Counter(c.get('defer_reason') for c in chunks.values() if c['symbol']=='BTCUSDT' and c['market_type']=='futures' and c['interval'] in ('89m','97m','101m','10007m')))}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'states','steady','outcomes','first_ready','traceback_terminal_lines'}}))
