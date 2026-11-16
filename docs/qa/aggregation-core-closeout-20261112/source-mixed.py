"""Bounded evidence using checksum-verified official Binance USD-M archives.

Run from backend with this QA root as argument. Inputs must be downloaded first;
this script neither changes production admission nor contacts a public endpoint.
"""
from __future__ import annotations
import asyncio, csv, hashlib, io, json, math, os, sys, time, zipfile
from dataclasses import replace, asdict
from decimal import Decimal
from pathlib import Path

root = Path(sys.argv[1]).resolve()
os.environ['CANDLE_DATA_DIR'] = str(root / 'isolated-data')
os.environ['KLINES_DB_PATH'] = str(root / 'isolated-data/candlescope.db')
assert not Path(os.environ['KLINES_DB_PATH']).exists(), 'Use a new isolated output root'
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource
from app.data_engine.storage import klines_repo

FIELDS = ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
COLS = (1,2,3,4,5,7,8,9,10)
MINUTE = 60000
inputs = json.loads((root / 'inputs.json').read_text())
raw = {}
for value in inputs:
    file = root / 'archives' / Path(value['url']).name
    assert hashlib.sha256(file.read_bytes()).hexdigest() == value['sha256']
    assert (file.with_name(file.name + '.CHECKSUM')).read_text().split()[0] == value['sha256']
    with zipfile.ZipFile(file) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            raw[value['interval']] = {int(row[0]):row for row in csv.reader(io.TextIOWrapper(stream)) if row and row[0].isdigit()}
fine = raw['1m']
start = min(fine)
# Freeze a contiguous first-half sample before later archive gaps; no assertion
# about availability outside this explicitly sampled qualification range.
end = start + 16 * 86400000

def oracle(opened, width):
    rows = [fine.get(t) for t in range(opened, opened + width, MINUTE)]
    assert rows and all(rows), 'No fabricated no-trade exclusion'
    return dict(zip(FIELDS, [Decimal(rows[0][1]),max(Decimal(r[2]) for r in rows),
        min(Decimal(r[3]) for r in rows),Decimal(rows[-1][4]),
        *[sum((Decimal(r[c]) for r in rows),Decimal(0)) for c in (5,7,8,9,10)]]))

def equivalent(a,b):
    return math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-8)

def ranges(opens,width):
    result=[]
    for t in sorted(opens):
        if result and result[-1][1]==t:result[-1]=(result[-1][0],t+width)
        else:result.append((t,t+width))
    return tuple(result)

klines_repo.init_klines_storage()
grids=[]; qualification=[]
for interval,width in [('1h',60*MINUTE),('15m',15*MINUTE),('5m',5*MINUTE),('1m',MINUTE)]:
    accepted=[]; rejected=[]; deltas={f:0.0 for f in FIELDS}; rows=[]
    for opened,r in sorted(raw[interval].items()):
        if not start <= opened or opened+width > end:continue
        if interval!='1m':
            reference=oracle(opened,width)
            mismatched=[f for f,c in zip(FIELDS,COLS) if not equivalent(r[c],reference[f])]
            for f,c in zip(FIELDS,COLS):deltas[f]=max(deltas[f],abs(float(Decimal(r[c])-reference[f])))
            if mismatched:
                rejected.append({'open_ms':opened,'fields':mismatched});continue
        accepted.append(opened)
        rows.append(dict(open_time=opened,close_time=int(r[6]),is_closed=True,
            **{f:int(r[c]) if f=='trades' else float(r[c]) for f,c in zip(FIELDS,COLS)},
            enhanced_fields=['quote_volume','trades','taker_buy_base','taker_buy_quote']))
    key=SeriesKey('BTCUSDT',interval,market_type='futures')
    # Real records are still written by D126's repository owner, not SQL patches.
    klines_repo.upsert_klines(key.symbol,interval,rows,source='backfill_archive_verified',market_type='futures')
    if accepted:grids.append(FixedHistorySource(key,width,0,ranges(accepted,width),frozenset(FIELDS),'binance-usdm-202610/first16days-decimal-parity'))
    qualification.append({'interval':interval,'accepted':len(accepted),'rejected':len(rejected),
        'first_rejections':rejected[:10],'max_abs_deltas':deltas})
config=DataManagerConfig();config.query.auto_backfill=False
dm=DataManager(config);dm.set_storage(klines_repo.KlinesRepoAdapter())
results=[]
try:
    for minutes in (89,97,101,10007):
        width=minutes*MINUTE; first=((start+width-1)//width)*width
        count=2 if minutes==10007 else 6
        for opened in range(first,first+count*width,width):
            if opened+width>end:break
            expected=oracle(opened,width)
            for page_rows in ((256,) if minutes==10007 else (1,7,256)):
                target=SeriesKey('BTCUSDT',f'{minutes}m',market_type='futures')
                started=time.perf_counter()
                with dm.read_mixed_history_blocks(target,opened,opened+width,tuple(grids),page_rows=page_rows,required_fields=frozenset(FIELDS)) as read:pass
                projected=read.summary.values.project(enhanced_complete=True)
                assert read.summary.is_authoritative(opened,opened+width)
                assert all(equivalent(projected[f],expected[f]) for f in FIELDS),(minutes,opened,projected,expected)
                results.append({'minutes':minutes,'open_ms':opened,'page_rows':page_rows,
                    'expected':{f:str(v) for f,v in expected.items()},'actual':projected,
                    'receipt':asdict(read.receipt),'elapsed_ms':(time.perf_counter()-started)*1000})
    assert dm.memory_budget.snapshot()['reserved_bytes']==0
    report={'input':'recorded official archives; no live/realtime qualification',
        'sample_range':[start,end],'tolerance':{'rel':1e-12,'abs':1e-8},
        'qualification':qualification,'results':results,'diagnostics':dm.shared_blocks.snapshot()}
    (root/'source-mixed.json').write_text(json.dumps(report,default=str,indent=2)+'\n')
    print(json.dumps({'compared_targets':len(results),'qualification':qualification,'passed':True}))
finally:
    asyncio.run(dm.shutdown())
