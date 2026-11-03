"""Finite synthetic BAR fixture; caller must choose a new owned QA profile."""
import json,os,sqlite3,time
from pathlib import Path
from scripts import replay_smoke_fixture as fixture

root=Path(os.environ['CANDLESCOPE_BATCH1_QA_ROOT']).resolve()
assert root.name.startswith('replay-manager-service-native-') and root.parent.name=='output'
database=Path(os.environ['KLINES_DB_PATH']).resolve()
assert database==root/'profile/data/candlescope.db' and not database.exists()
fixture.FIXTURE_SYMBOLS=(("BTCUSDT",30000.0),("ETHUSDT",2000.0))
fixture.FIXTURE_ROWS=15000
fixture._seed_klines()
from app.data_engine.storage.klines_repo import upsert_klines
with sqlite3.connect(database) as db:
 db.row_factory=sqlite3.Row
 db.execute("UPDATE klines SET source='backfill'");db.commit()
 for symbol,_ in fixture.FIXTURE_SYMBOLS:
  groups={}
  for row in db.execute("SELECT * FROM klines WHERE symbol=? AND interval='1m' ORDER BY open_time",(symbol,)):
   groups.setdefault(row['open_time']//300000*300000,[]).append(row)
  rows=[]
  for at,group in groups.items():
   if len(group)!=5 or group[0]['open_time']!=at:continue
   rows.append({'open_time':at,'close_time':at+299999,'open':group[0]['open'],'high':max(x['high'] for x in group),
    'low':min(x['low'] for x in group),'close':group[-1]['close'],'volume':sum(x['volume'] for x in group),
    'quote_volume':sum(x['quote_volume'] or 0 for x in group),'trades':sum(x['trades'] or 0 for x in group),
    'taker_buy_base':sum(x['taker_buy_base'] or 0 for x in group),'taker_buy_quote':sum(x['taker_buy_quote'] or 0 for x in group)})
  assert upsert_klines(symbol,'5m',rows,source='backfill',exchange='binance',market_type='spot')==len(rows)
manifests=fixture._seed_replay_history_archive()
(root/'fixture.json').write_text(json.dumps({'scope':'Finite synthetic BTC/ETH 1m and independent five-row 5m aggregation; public-like metadata, no online source qualification','startMs':fixture.FIXTURE_START_MS,'rowsPerSymbol':fixture.FIXTURE_ROWS,'manifests':manifests},indent=2,default=str)+'\n')
Path(os.environ['SYMBOL_CATALOG_SNAPSHOT_PATH']).write_text(json.dumps({'version':1,'revision':1,'saved_at':time.time(),'markets':[{'exchange':'binance','market_type':'spot','last_success_at':time.time(),'symbols':[{'exchange':'binance','marketType':'spot','symbol':base+'USDT','baseAsset':base,'quoteAsset':'USDT','status':'TRADING','active':True} for base in ['BTC','ETH']]}]}))
print(json.dumps({'database':str(database),'archiveSeries':len(manifests)}))
