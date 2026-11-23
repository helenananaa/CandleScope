"""Run unchanged against baseline/product; batch and canonical-page math proof."""
import hashlib
import json
from pathlib import Path
import sys
from app.data_engine import interval_policy as policy

mode=sys.argv[1]
MINUTE=60000


def rows(period,mixed):
    result=[]
    for bucket in range(2):
        at=bucket*period*MINUTE;stop=at+period*MINUTE
        while at<stop:
            width=next((w for w in (60*MINUTE,15*MINUTE,5*MINUTE,MINUTE)
                        if mixed and at%w==0 and at+w<=stop),MINUTE)
            index=len(result)
            volume=1e8 if index%17==0 else 3e-8+index/13
            result.append(dict(open_time=at,close_time=at+width-1,interval=f'{width//MINUTE}m',
                open=100.+index%11,high=130.+index%5,low=90.-index%3,close=101.+index%13,
                volume=volume,quote_volume=5*volume,trades=index%23,
                taker_buy_base=volume/3,taker_buy_quote=volume))
            at+=width
    return result


cases=[]
for period in (89,97,101,10007):
 for mixed in (False,True):
  for fault in ('normal','gap','duplicate','unknown','bad_grid','bad_close','nonfinite','forming_target'):
   values=rows(period,mixed);now=2*period*MINUTE
   index=min(3,len(values)-1)
   if fault=='gap':del values[index]
   elif fault=='duplicate':values.insert(index,dict(values[index]))
   elif fault=='unknown':values[index]['quote_volume']=None
   elif fault=='bad_grid':values[index]['interval']='5m'
   elif fault=='bad_close':values[index]['close_time']-=1
   elif fault=='nonfinite':values[index]['volume']=float('nan')
   elif fault=='forming_target':now-=1
   # Batch input is deliberately out of order; canonical pages are ordered.
   unordered=list(reversed(values))
   identifier=f'{period}/{mixed}/{fault}'
   fingerprint=hashlib.sha256(json.dumps(unordered,sort_keys=True).encode()).hexdigest()
   if mode=='batch':
    result=policy.aggregate_kline_rows(unordered,target_interval=f'{period}m',source_interval=None,now_ms=now)
   else:
    stream=policy.ClosedKlineRowStream(target_interval=f'{period}m',source_interval=None,now_ms=now)
    result=[];page_rows=int(mode)
    for start in range(0,len(values),page_rows):result.extend(stream.push(values[start:start+page_rows]))
    result.extend(stream.finish())
   cases.append(dict(case=identifier,input_hash=fingerprint,result=result))
print(json.dumps(dict(mode=mode,module=str(Path(policy.__file__).resolve()),
    source_sha256=hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest(),cases=cases),indent=2))
