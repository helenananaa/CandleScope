"""Read the already-running native 1m source, without a new stream or repair."""
import json,sys,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
root=Path(sys.argv[1]).resolve();end=time.monotonic()+800
while time.monotonic()<end:
 try:
  receipt=json.loads((root/'acceptance.json').read_text());launch=next(s for s in receipt['steps'] if s['name']=='packaged-launch');break
 except (FileNotFoundError,json.JSONDecodeError,StopIteration):time.sleep(.05)
else:raise SystemExit('No continuation launch receipt')
u=urlsplit(launch['evidence']['bootstrap']['sidecar']['healthUrl']);url=f'{u.scheme}://{u.netloc}/api/v1/klines/latest?symbol=BTCUSDT&interval=1m&limit=2&exchange=binance&market_type=futures&repair=none'
count=0;errors=0
with (root/'base-input-observer.jsonl').open('w') as output:
 while time.monotonic()<end:
  at=int(time.time()*1000)
  try:
   with urllib.request.urlopen(url,timeout=8) as response:body=json.load(response)
   output.write(json.dumps({'at':at,'observed_at':int(time.time()*1000),'body':body})+'\n');output.flush();count+=1
  except Exception as error:
   errors+=1;output.write(json.dumps({'at':at,'error':str(error)})+'\n');output.flush()
   if errors>3:break
  try:
   receipt=json.loads((root/'acceptance.json').read_text())
   if any(s['name']=='full-process-exit' for s in receipt['steps']):break
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.25)
(root/'base-input-observer-summary.json').write_text(json.dumps({'count':count,'errors':errors,'scope':__doc__})+'\n')
print(json.dumps({'count':count,'errors':errors}))
