"""Independent Decimal oracle for captured native charts and their stored inputs.

Only public market rows are exported; the profile/account databases are not.
No CandleScope aggregation code is imported. --replay uses the exported inputs.
"""
import argparse
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3

parser=argparse.ArgumentParser()
parser.add_argument('native',type=Path)
parser.add_argument('--replay',action='store_true')
args=parser.parse_args()
plans={'45m':('15m',900000,2700000),'90m':('30m',1800000,5400000),
       '2d':('1d',86400000,172800000),'5d':('1d',86400000,432000000)}
fields=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
archive=args.native/'parity-inputs.json.gz'
if args.replay:
    cases=json.loads(gzip.decompress(archive.read_bytes()))
else:
    conn=sqlite3.connect(f'file:{args.native}/data/candlescope.db?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    cases=[]
    for capture in sorted(args.native.glob('*bars-*.json')):
        interval=capture.stem.split('bars-',1)[1]
        if interval not in plans:
            continue  # Native 3d authority is not replaced by daily reconstruction.
        base,width,target=plans[interval]
        for value in json.loads(capture.read_text()):
            if not value.get('is_closed'):
                continue
            start=int(value['time'])*1000
            rows=[dict(row) for row in conn.execute(
                'select open_time,close_time,open,high,low,close,volume,quote_volume,trades,'
                'taker_buy_base,taker_buy_quote,source from klines '
                'where exchange=? and market_type=? and symbol=? and interval=? '
                'and open_time>=? and open_time<? order by open_time',
                ('okx','futures','BTC-USDT-SWAP',base,start,start+target))]
            cases.append(dict(capture=capture.name,base=base,width=width,target=target,
                              chart=value,rows=rows))
    conn.close()
    archive.write_bytes(gzip.compress(json.dumps(cases,separators=(',',':')).encode(),mtime=0))

receipt={'oracle':'Decimal sums of individually normalized source quantities; no application reducer',
         'source_input_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
         'groups':{},'mismatches':[],'max_absolute_error':{},'max_relative_error':{}}
for case in cases:
    stats=receipt['groups'].setdefault(case['capture'],{'compared':0,'not_covered':0})
    rows=case['rows'];chart=case['chart'];start=int(chart['time'])*1000
    expected_opens=list(range(start,start+case['target'],case['width']))
    if ([r['open_time'] for r in rows]!=expected_opens
            or any(r['close_time']!=r['open_time']+case['width']-1 for r in rows)):
        stats['not_covered']+=1
        continue
    norm=lambda value: Decimal(str(round(float(value),8)))
    expected={'open':norm(rows[0]['open']),'high':max(norm(r['high']) for r in rows),
              'low':min(norm(r['low']) for r in rows),'close':norm(rows[-1]['close'])}
    for name in fields[4:]:
        values=[r[name] for r in rows]
        expected[name]=None if any(v is None for v in values) else (
            sum(int(v) for v in values) if name=='trades' else sum(norm(v) for v in values))
    for name,wanted in expected.items():
        actual=chart.get(name)
        if wanted is None or actual is None:
            match=actual is None and wanted is None
        else:
            error=abs(float(wanted)-float(actual))
            relative=error/max(abs(float(wanted)),1e-30)
            receipt['max_absolute_error'][name]=max(receipt['max_absolute_error'].get(name,0),error)
            receipt['max_relative_error'][name]=max(receipt['max_relative_error'].get(name,0),relative)
            match=math.isclose(float(actual),float(wanted),rel_tol=1e-12,abs_tol=1e-8)
        if not match:
            receipt['mismatches'].append(dict(capture=case['capture'],time=chart['time'],field=name,
                                               actual=actual,expected=str(wanted)))
    stats['compared']+=1
receipt['passed']=bool(receipt['groups'] and not receipt['mismatches']
                       and all(g['compared']>=10 for g in receipt['groups'].values()))
(args.native/'parity.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
if not receipt['passed']:
    raise SystemExit(1)
