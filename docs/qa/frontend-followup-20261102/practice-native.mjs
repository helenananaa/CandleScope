import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';

const fixture = JSON.parse(await fs.readFile(q.s.root + '/practice-fixture.json', 'utf8'));
q.s.receipt.schema = 'candlescope.practice-snapshot-stability-native/1';
q.s.receipt.sourceCommit = cp.execFileSync('git', ['rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
q.s.receipt.transport = 'Actual packaged app, bundled backend and ordinary localhost routes; explicit synthetic persisted practice ledger fixture.';
q.s.receipt.scope = 'Summary, trades, stats and detail financial values, actual account UI, normal full exit and restart. WAL concurrency is separately covered by SQLite/thread tests; no native order-matching claim.';
let running = false;
async function launch() {
  try { await q.record('launch', await q.launch()); running = true; }
  catch (error) { running = Boolean(q.s.app); q.s.identity ??= {pid:q.s.app?.process()?.pid}; throw error; }
}
async function quit() {
  await q.quit(); await q.exited(); running = false;
  await q.record('full-owned-exit', {elapsedMs:Date.now()-q.s.quitStartedAt, processes:q.s.quitPids});
}
async function read(suffix) {
  const response = await q.s.page.evaluate(async url => {
    const r = await fetch(url); return {status:r.status, body:await r.json()};
  }, q.s.backend + '/api/v1/trading/accounts/' + fixture.accountId + suffix);
  assert.equal(response.status, 200, JSON.stringify(response)); return response.body;
}
async function verify(name) {
  const summary = await read('/summary'), trades = await read('/trades');
  const stats = await read('/stats'), detail = await read('/trades/' + fixture.tradeId);
  assert.equal(summary.account.kind, 'practice');
  assert.equal(summary.balance, fixture.balance); assert.equal(summary.equity, fixture.balance);
  assert.equal(summary.closedTrades, 1); assert.deepEqual(summary.positions, []);
  assert.deepEqual(summary.workingOrders, []); assert.equal(trades.trades.length, 1);
  assert.equal(trades.trades[0].netPnl, fixture.netPnl); assert.equal(detail.netPnl, fixture.netPnl);
  assert.equal(stats.netPnl, fixture.statsNetPnl); assert.equal(stats.tradeCount, 1);
  const values = {summary, trades, stats, detail}; await q.record(name, values); return values;
}
async function show(name) {
  if (!await q.s.page.locator('.trading-panel').count()) await q.s.page.getByRole('button', {name:'交易账户',exact:true}).click();
  const panel = q.s.page.locator('.trading-panel');
  await panel.getByRole('combobox', {name:'当前账户',exact:true}).selectOption(fixture.accountId);
  await q.record('account-panel-before-tabs', {text:await panel.innerText(), html:await panel.evaluate(el=>el.outerHTML)});
  // The visible review badge is also part of this tab's accessible name.
  await panel.getByRole('tab', {name:/^历史(?:\s*待复盘)?$/}).click();
  await panel.getByText('BTCUSDT', {exact:true}).first().waitFor();
  await panel.screenshot({path:q.s.root + '/' + name + '.png'});
}
try {
  await launch(); const before = await verify('financial-projections'); await show('practice-snapshot'); await quit();
  await launch(); const after = await verify('restored-financial-projections');
  assert.deepEqual(after, before); await show('practice-snapshot-restored'); await quit();
  assert.deepEqual(q.s.receipt.errors, []); q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.failure = String(error.stack || error); process.exitCode = 1;
  if (q.s.page) await q.screenshot('practice-failure').catch(()=>{});
}
finally {
  if (running) try { await quit(); } catch (error) { q.s.receipt.exitFailure = String(error); }
  await q.save(); console.log(JSON.stringify({passed:q.s.receipt.passed ?? false, failure:q.s.receipt.failure}));
}
