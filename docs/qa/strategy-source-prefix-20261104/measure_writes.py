"""Controlled SQLite overhead probe; baseline disables ONLY these new QA triggers."""
from pathlib import Path
import json
import os
import statistics
import time
from contextlib import closing

from app.core import config
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import series_values

root=Path(os.environ['PREFIX_WRITE_QA_ROOT']);root.mkdir(parents=True,exist_ok=False)
start,step,count=1700000040000,60000,1000
rows=[dict(open_time=start+i*step,close_time=start+(i+1)*step-1,open=100,high=250,low=50,
           close=100+i%20,volume=10,quote_volume=1000,trades=10,taker_buy_base=5,taker_buy_quote=500) for i in range(count)]
records=[]
for trial in range(3):
    # Alternate direction to reduce a monotone warm-cache/thermal bias.
    for mode in (['baseline','zero','16','128'] if trial%2==0 else ['128','16','zero','baseline']):
        path=root/f'{trial}-{mode}.db';klines_repo.KLINES_DB_PATH=path;config.KLINES_DB_PATH=path
        klines_repo.init_klines_storage();adapter=klines_repo.KlinesRepoAdapter()
        if mode=='baseline':
            with closing(klines_repo._connect()) as conn,conn:
                for op in ['insert','update','delete']:conn.execute(f'DROP TRIGGER kline_prefix_watch_{op}')
        watches=0 if mode in ['baseline','zero'] else int(mode)
        store=adapter.revision_store.prefix_watches
        for index in range(watches):
            first=store.register(f'qa-{index}',series_values('BTCUSDT','1m','binance','spot'),from_ms=start-step*1000,committed_through_ms=start-step*1000-1)
            proof=store.prepare(first,committed_through_ms=first.through_ms,through_ms=start-1)
            with store.commit_guard(proof):pass
        begin=time.perf_counter()
        klines_repo.upsert_klines('BTCUSDT','1m',rows,source='backfill_rest_verified')
        elapsed=(time.perf_counter()-begin)*1000
        with closing(klines_repo._connect()) as conn:
            actual=[tuple(row) for row in conn.execute('SELECT open_time,close_time,open,high,low,close,volume FROM klines ORDER BY open_time')]
            expected=[tuple(row[k] for k in ['open_time','close_time','open','high','low','close','volume']) for row in rows]
            assert actual==expected
            assert conn.execute('SELECT revision FROM kline_revision_clock').fetchone()[0]==count
            assert conn.execute('SELECT count(*) FROM kline_prefix_watches WHERE version<>0').fetchone()[0]==0
        records.append({'trial':trial,'mode':mode,'watches':watches,'rows':count,'commitMs':elapsed})
result={'scope':'actual KlinesRepo same input/transaction; baseline only removes new prefix triggers in private QA DB; 1000 closed tail appends, no full-runtime/SLO claim',
        'records':records,'medianCommitMs':{mode:statistics.median(row['commitMs'] for row in records if row['mode']==mode) for mode in ['baseline','zero','16','128']}}
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
