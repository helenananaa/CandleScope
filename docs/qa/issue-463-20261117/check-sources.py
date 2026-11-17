"""Independent arithmetic over actual canonical native inputs after full shutdown."""
import collections,json,math,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
receipt=json.loads((root/'acceptance.json').read_text())
assert any(s['name']=='full-process-exit' for s in receipt['steps'])
records=[json.loads(line) for line in (root/'acceptance-timeline.jsonl').read_text().splitlines()]
snapshot=next(r for r in reversed(records) if {v['interval'] for v in r['views']}=={'89m','97m','101m','10007m'} and all(v['bars'] for v in r['views']))
database=(Path(sys.argv[2]).resolve() if len(sys.argv)>2 else root/'profile/data/candlescope.db')
c=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
fields=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
widths=[('1d',86400),('1h',3600),('15m',900),('1m',60)]
inputs={i:{r['open_time']//1000:dict(r) for r in c.execute("select * from klines where exchange='binance' and market_type='futures' and symbol='BTCUSDT' and interval=? and provider_id='binance' and venue='binance' and asset_class='crypto' and series_variant='native' and price_adjustment='raw' and session_variant='continuous' and volume_semantics='base_asset'",(i,))} for i,_ in widths}
def source_rows(start,end):
 fine=inputs['1m'];opens=range(start,end,60)
 if all(t in fine for t in opens):return [fine[t] for t in opens],{'1m':(end-start)//60}
 cursor=start; selected=[];counts=collections.Counter()
 while cursor<end:
  found=False
  for interval,width in widths:
   if cursor%width==0 and cursor+width<=end and cursor in inputs[interval]:
    selected.append(inputs[interval][cursor]);counts[interval]+=1;cursor+=width;found=True;break
  if not found:return None,{'first_missing_open_sec':cursor}
 return selected,dict(counts)
def reduce(rows):
 result=dict(open=rows[0]['open'],high=max(r['high'] for r in rows),low=min(r['low'] for r in rows),close=rows[-1]['close'])
 for f in fields[4:]:result[f]=None if any(r[f] is None for r in rows) else (sum(r[f] for r in rows) if f=='trades' else math.fsum(r[f] for r in rows))
 return result
summary=[]
for view in snapshot['views']:
 interval=view['interval'];width=int(interval[:-1])*60;checked=[];unverified=[];mismatches=[]
 for bar in view['bars']:
  if not bar.get('is_closed'):continue
  rows,recipe=source_rows(bar['time'],bar['time']+width)
  if rows is None:unverified.append({'time':bar['time'],**recipe});continue
  expected=reduce(rows);bad=[]
  for field in fields:
   a,b=bar.get(field),expected[field]
   tolerance=max(1e-8,4*2.220446049250313e-16*max(abs(a or 0),abs(b or 0))) if field in {'volume','quote_volume','taker_buy_base','taker_buy_quote'} else 0
   if not ((a is None and b is None) or (a is not None and b is not None and abs(a-b)<=tolerance)):
    bad.append({'field':field,'actual':a,'expected':b,'tolerance':tolerance})
  if bad:mismatches.append({'time':bar['time'],'recipe':recipe,'differences':bad})
  else:checked.append({'time':bar['time'],'recipe':recipe,'source_rows':len(rows)})
 summary.append({'interval':interval,'displayed':len(view['bars']),'verified_closed':len(checked),'unverified':unverified,'mismatches':mismatches,'checked':checked})
result={'scope':'Read-only actual native inputs and independent Python arithmetic; complete 1m preferred, otherwise explicit UTC native 1d/1h/15m/1m cover. Missing coverage is not a numerical pass. Canonical inputs were read after shutdown, so any mismatch needs revision attribution.',
 'snapshot_label':snapshot['label'],'snapshot_at':snapshot['at'],'per_chart':summary,
 'passed':all(s['verified_closed']>=127 and not s['unverified'] and not s['mismatches'] for s in summary)}
(root/'source-numeric.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':result['passed'],'charts':[{k:v for k,v in s.items() if k not in {'checked','unverified','mismatches'}}|{'unverified':len(s['unverified']),'mismatches':len(s['mismatches'])} for s in summary]}))
