import fs from 'node:fs';
import path from 'node:path';
export function setup(q){
 const data=path.join(q.s.root,'profile/data');fs.mkdirSync(data,{recursive:true});
 q.s.env={...q.s.env,KLINES_DB_PATH:path.join(data,'candlescope.db'),REPLAY_DB_PATH:path.join(data,'replay.db'),
   REPLAY_HISTORY_ARCHIVE_DIR:path.join(data,'replay-history'),REPLAY_HISTORY_ORIGIN_URI:' ',REPLAY_ENABLED:'1',
   SYMBOL_CATALOG_SNAPSHOT_PATH:path.join(data,'fixture-symbol-catalog.json')};
 if(!fs.existsSync(q.s.env.SYMBOL_CATALOG_SNAPSHOT_PATH))fs.writeFileSync(q.s.env.SYMBOL_CATALOG_SNAPSHOT_PATH,JSON.stringify({version:1,revision:1,saved_at:Date.now()/1000,markets:[{exchange:'binance',market_type:'spot',last_success_at:Date.now()/1000,symbols:[{exchange:'binance',marketType:'spot',symbol:'BTCUSDT',baseAsset:'BTC',quoteAsset:'USDT',status:'TRADING',active:true}]}]}));
}
