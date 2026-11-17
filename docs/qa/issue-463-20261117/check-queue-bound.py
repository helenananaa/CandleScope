"""Find an initial required target input blocked in the eligible LOCAL queue.

This proves a failure lower bound under #463's explicit no-exemption rule for
internal queueing; it does not reconstruct or claim an exact net wall time.
"""
import json,math,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
root=Path(sys.argv[1]).resolve();receipt=json.loads((root/'acceptance.json').read_text())
chunks={};first={};windows={}
for line in (root/'acceptance-timeline.jsonl').open():
 row=json.loads(line)
 for chunk in row['diagnostics']['backfill'].get('recent_chunks',[]):chunks[chunk['sequence']]=chunk
 for view in row['views']:
  if view['interval'] not in {'89m','97m','101m','10007m'}:continue
  if row['label'].startswith(('cold','steady')):
   windows[view['interval']]=view['bars']
   for bar in view['bars']:
    if bar.get('is_closed'):first.setdefault((view['interval'],bar['time']),{'at':row['at'],'label':row['label'],'bar':bar})
requests=json.loads((root/'traffic.json').read_text())['requests'];proofs=[]
for interval,bars in windows.items():
 closed=[b for b in bars if b.get('is_closed')];required={b['time'] for b in closed[-127:]};candidates=[]
 for chunk in chunks.values():
  if (chunk['interval']!=interval or chunk['symbol']!='BTCUSDT' or chunk['market_type']!='futures'
      or chunk['status']!='completed' or chunk['ready_queue_ms']<=3000 or chunk['not_eligible_wait_ms']!=0):continue
  for opened in sorted(required):
   if not chunk['start_ms']<=opened*1000<=chunk['end_ms']:continue
   adopted=first[(interval,opened)]
   if adopted['at']<chunk['started_at_ms']:continue
   owner_requests=[]
   for request in requests:
    q=parse_qs(urlsplit(request['url']).query)
    if q.get('interval')!=[interval] or 'request_scope' not in q or q.get('request_generation')!=['1']:continue
    if not (int(q.get('start_ms',['0'])[0])<=opened*1000<=int(q.get('end_ms',[str(2**63-1)])[0])):continue
    prefix='scope:'+q['request_scope'][0]+':1:'
    if any(owner.startswith(prefix) for owner in chunk['demand_owner_ids']):owner_requests.append(request)
   if not owner_requests:continue
   wall_queue=chunk['started_at_ms']-chunk['queued_at_ms']
   conservative=min(chunk['ready_queue_ms'],wall_queue)
   candidates.append({'interval':interval,'required_target_open_sec':opened,'required_closed_count':len(required),
    'first_adoption':adopted,'initial_owner_request':owner_requests[0],
    'chunk_receipt':chunk,'local_queue_lower_bound_ms':conservative,
    'clock_note':'minimum of monotonic eligible queue and wall queue; noneligible wait is zero; no cumulative request durations were subtracted'})
   break
 if candidates:proofs.append(max(candidates,key=lambda p:p['local_queue_lower_bound_ms']))
result={'passed_net_3s':False if proofs else None,'exact_net_ms':None,
 'local_queue_lower_bound_ms':max((p['local_queue_lower_bound_ms'] for p in proofs),default=None),
 'basis':'Initial generation-1 chart scope, a required final-127 closed target open, matching completed work, first closed adoption after dispatch, and eligible internal queue with zero quota-ineligible wait. #463 explicitly includes internal scheduling/concurrency queues even when other communication overlaps.',
 'proofs':proofs,'scope':'Failure lower bound only, not a full per-chart external wait subtraction or exact net readiness result.'}
(root/'queue-lower-bound.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed_net_3s':result['passed_net_3s'],'lower_bound_ms':result['local_queue_lower_bound_ms'],'charts':[(p['interval'],p['local_queue_lower_bound_ms'],p['required_target_open_sec']) for p in proofs]}))
