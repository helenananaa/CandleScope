import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema = 'candlescope.stability-cold-chart-native/1';
q.s.receipt.sourceCommit = cp.execFileSync('git', ['rev-parse','HEAD'], {encoding:'utf8'}).trim();
q.s.receipt.transport = 'Packaged bundled backend; real public provider traffic, ordinary app requests, no substituted responses or limiter reset.';
q.s.receipt.scope = 'Cold 5m chart, independent historical sibling viewport, backend row equality, persisted interval selection and normal full-process restart. This is not a before/after performance attribution or a deterministic native reproduction of the unscoped-interest race.';
let running = false;
async function launch() {
  try { await q.record('launch', await q.launch()); running = true; await q.enableControl(); }
  catch (error) { running = Boolean(q.s.app); q.s.identity ??= {pid:q.s.app?.process()?.pid}; throw error; }
}
async function quit() {
  await q.quit(); await q.exited(); running = false;
  await q.record('full-owned-exit', {elapsedMs:Date.now()-q.s.quitStartedAt, processes:q.s.quitPids});
}
async function surface() {
  return q.s.page.evaluate(() => {
    const element = document.querySelector('[data-chart-cell-id]');
    let node = element?.[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))];
    while (node?.return) node = node.return;
    const seen = new Set(), charts = [];
    function visit(n) {
      if (!n) return;
      const p = n.memoizedProps;
      if (p?.seriesStore && p.datasetKey && !seen.has(p.seriesStore)) {
        seen.add(p.seriesStore); let parent = n, cellId;
        while (parent) { cellId ??= parent.memoizedProps?.['data-chart-cell-id']; parent = parent.return; }
        charts.push({cellId, interval:p.interval, rows:p.seriesStore.snapshot(), rightTruncated:p.seriesStore.rightTruncated});
      }
      visit(n.child); visit(n.sibling);
    }
    visit(node?.stateNode?.current); return charts;
  });
}
async function verifyRows(name) {
  const chart = (await surface()).find(c=>c.interval==='5m'); assert.ok(chart);
  const rows = chart.rows.filter(row=>row.is_closed!==false);
  assert.ok(rows.length >= 499);
  const url = new URL(q.s.backend+'/api/v1/klines/range');
  for (const [key,value] of Object.entries({symbol:'BTCUSDT', interval:'5m', start_ms:rows[0].time*1000,
    end_ms:rows.at(-1).time*1000, exchange:'binance', market_type:'spot', repair:'none', strict:'true'})) url.searchParams.set(key,String(value));
  const answer = await q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},String(url));
  assert.equal(answer.status,200);
  const bars = answer.body.data; assert.equal(bars.length, rows.length);
  for (let i=0;i<rows.length;i++) {
    assert.equal(Number(bars[i].open_time)/1000,Number(rows[i].time));
    for (const field of ['open','high','low','close','volume']) assert.equal(Number(bars[i][field]),Number(rows[i][field]));
  }
  await q.record(name,{compared:rows.length,first:rows[0].time,last:rows.at(-1).time});
}
try {
  const database=q.s.root+'/profile/data/candlescope.db';
  const count=Number(cp.execFileSync('/Users/ryanliang/CandleScope/backend/.venv/bin/python',['-c',
    "import sqlite3,sys;db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(db.execute(\"select count(*) from klines where symbol='BTCUSDT' and interval='5m'\").fetchone()[0])",database],{encoding:'utf8'}));
  assert.equal(count,0,'preserve previous data; do not relabel a warm 5m series as cold');
  await q.record('no-persisted-target-bars',{symbol:'BTCUSDT',interval:'5m',count});
  await launch();
  const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');
  assert.equal(configured.result.state,'ready'); await q.ready(2,60_000);
  const left=(await surface()).find(c=>c.cellId==='cell-1'); assert.ok(left);
  const end=left.rows.at(-1).time-3600;
  assert.equal((await q.execute('cell-1','visibleTimeRange',{from:end-1800,to:end})).state,'applied');
  await q.delay(500); const before=(await q.query('cell-1')).snapshot.visibleRange;
  const started=Date.now(); assert.equal((await q.execute('cell-2','interval',{interval:'5m'})).state,'applied');
  await q.ready(2,60_000); const elapsedMs=Date.now()-started;
  const after=(await q.query('cell-1')).snapshot.visibleRange; assert.deepEqual(after,before);
  await q.record('cold-target-ready-and-sibling-preserved',{elapsedMs,before,after});
  await verifyRows('cold-closed-rows-match-backend'); await q.screenshot('cold-five-minute'); await quit();
  await launch(); await q.ready(2,60_000);
  assert.deepEqual((await surface()).map(c=>c.interval).sort(),['1m','5m']);
  await verifyRows('restored-closed-rows-match-backend'); await q.screenshot('cold-five-minute-restored'); await quit();
  assert.deepEqual(q.s.receipt.errors,[]); q.s.receipt.passed=true;
} catch (error) {
  q.s.receipt.failure=String(error.stack||error); process.exitCode=1;
  if (q.s.page) {
    await q.screenshot('cold-chart-failure').catch(()=>{});
    q.s.receipt.health=await q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+'/api/v1/settings/storage/health').catch(String);
  }
} finally {
  if (running) try {await quit();} catch(error) {q.s.receipt.exitFailure=String(error);}
  await q.save(); console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
