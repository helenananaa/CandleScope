import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import cp from 'node:child_process';

export function setup(q) {
  const root=q.s.root, data=path.join(root,'profile-verified/data');
  const repo=path.resolve(root,'../..');
  fs.mkdirSync(data,{recursive:true});
  q.s.env={...q.s.env,
    KLINES_DB_PATH:path.join(data,'candlescope.db'), REPLAY_DB_PATH:path.join(data,'replay.db'),
    REPLAY_HISTORY_ARCHIVE_DIR:path.join(data,'replay-history'), REPLAY_HISTORY_ORIGIN_URI:' ',
    REPLAY_ENABLED:'1', SYMBOL_CATALOG_SNAPSHOT_PATH:path.join(data,'fixture-symbol-catalog.json'),
  };
  if(!fs.existsSync(path.join(root,'fixture-verified.json'))) {
    assert.ok(!fs.existsSync(q.s.env.KLINES_DB_PATH),'Do not reseed an existing profile');
    const seeded=cp.spawnSync('/Users/ryanliang/CandleScope/backend/.venv/bin/python',
      [path.join(root,'seed-fixture.py')],{cwd:path.join(repo,'backend'),encoding:'utf8',env:{...q.s.env,
        CANDLE_DATA_DIR:data,CANDLE_QA_FIXTURE_RECEIPT:path.join(root,'fixture-verified.json'),
        PYTHONPATH:path.join(repo,'frontend/.desktop-runtime/runtime/site-packages')+':'+path.join(repo,'backend')}});
    fs.writeFileSync(path.join(root,'seed.log'),seeded.stdout+'\n'+seeded.stderr);
    assert.equal(seeded.status,0,seeded.stderr);
    fs.writeFileSync(q.s.env.SYMBOL_CATALOG_SNAPSHOT_PATH,JSON.stringify({version:1,revision:1,saved_at:Date.now()/1000,
      markets:[{exchange:'binance',market_type:'spot',last_success_at:Date.now()/1000,
        symbols:['BTC','ETH'].map(baseAsset=>({exchange:'binance',marketType:'spot',symbol:baseAsset+'USDT',
          baseAsset,quoteAsset:'USDT',status:'TRADING',active:true}))}]}));
  }
}
