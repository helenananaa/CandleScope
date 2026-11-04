import time,statistics,json,types,sys
from unittest.mock import patch
from app.api.v1.klines import _bounded_latest_tail_range
from app.data_engine.history.calendar import SessionCalendar
from pathlib import Path
old=types.ModuleType('calendar_before_qa');sys.modules[old.__name__]=old
exec(compile(Path('/tmp/candlescope-goal-20261104/calendar-before-a5.py').read_text(),old.__name__,'exec'),old.__dict__)
results={};ranges=[]
for label,klass in [('before',old.SessionCalendar),('after',SessionCalendar)]:
 samples=[];counts=[];original=klass.expected_opens
 count=[0]
 def observed(self,*args,**kwargs):
  for value in original(self,*args,**kwargs):count[0]+=1;yield value
 klass.expected_opens=observed
 try:
  with patch('app.api.v1.klines.time.time',return_value=1793793600):
   for _ in range(5):
    c=klass(calendar_id='qa.tail',timezone_name='UTC',weekly_sessions={d:(('09:30','16:00'),) for d in range(5)})
    count[0]=0;start=time.perf_counter();a,b=_bounded_latest_tail_range(interval='1m',limit=1000,calendar=c);duration=(time.perf_counter()-start)*1000
    samples.append(duration);counts.append(count[0]);assert c.count_expected(a,b,'1m')==1000;ranges.append((a,b))
 finally:klass.expected_opens=original
 results[label]={'samplesMs':samples,'medianMs':statistics.median(samples),'emittedPlanningOpens':counts}
assert len(set(ranges))==1
results.update(fixedNowMs=1793793600000,requestedBars=1000,identicalRange=list(ranges[0]),scope='local controlled planning only; not exchange/native latency/SLO')
print(json.dumps(results))
