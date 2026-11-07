import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import * as q from './native-driver.mjs';

const seed = JSON.parse(await fs.readFile(q.s.root + '/research-seed.json', 'utf8'));
const continuous = '/api/v1/backtests/continuous';
const creates = [];
q.s.receipt.schema = 'candlescope.continuous-live-native/1';
q.s.receipt.transport = 'Actual packaged application and public Binance spot bars. Only the completed research input was seeded with deterministic bars.';
q.s.receipt.creates = creates;
const manifest = JSON.parse(await fs.readFile(q.s.root + '/source-package-manifest.json', 'utf8'));
q.s.receipt.driverCommit = q.s.receipt.sourceCommit;
q.s.receipt.sourceCommit = manifest.sourceCommit;
let running = false;

async function read(path) {
  const response = await fetch(q.s.backend + path);
  assert.equal(response.status, 200, path);
  return response.json();
}

async function launch() {
  running = true;
  const identity = await q.launch();
  q.s.page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === continuous + '/runs') {
      creates.push(request.postDataJSON());
    }
  });
  await q.record('launch', identity);
  const caps = await read(continuous + '/capabilities');
  assert.equal(caps.runtime_mode, 'LIVE');
  assert.equal(caps.execution_enabled, true);
  await q.enableControl();
}

async function quit() {
  const pid = q.s.bootstrap.sidecar.pid;
  await q.quit();
  await q.exited();
  running = false;
  const receipt = JSON.parse(await fs.readFile(q.s.root + '/sidecar-exit-status.json', 'utf8'));
  const exit = receipt.exits.find(entry => entry.pid === pid);
  assert.equal(exit?.code, 0);
  assert.equal(exit?.signal, null);
  assert.deepEqual(receipt.killRequests, []);
  await q.record('full-exit', {exit, owned: q.s.quitPids});
}

function coldAccount(id) {
  return JSON.parse(execFileSync('python3', [
    '-B', 'docs/qa/continuous-live-main268-20261107/cold_account.py',
    q.s.root + '/profile', id, seed.runId, process.env.CANDLESCOPE_QA_SEED_PROFILE,
  ], {encoding: 'utf8'}));
}

try {
  await launch();
  await q.record('configured', await q.configure([{
    session: q.session('BTCUSDT', '1m'), indicators: [],
  }], 'single'));
  await q.ready(1, 90000);
  const page = q.s.page;
  const researchWindow = q.s.app.waitForEvent('window');
  await page.evaluate(() => window.candlescopeDesktop.openAppPage('/strategy.html?source=imported'));
  const research = await researchWindow;
  await research.waitForURL(url => url.pathname === '/strategy.html');
  await research.getByTestId('strategy-research-result-slot').waitFor();
  const drawer = research.getByRole('dialog', {name: '数据来源', exact: true});
  if (await drawer.isVisible()) await drawer.getByRole('button', {name: '关闭', exact: true}).click();
  const hostMode = research.getByRole('button', {name: 'CandleScope 撮合 / 教学模板', exact: true});
  if (await hostMode.isVisible()) await hostMode.click();
  await research.getByRole('button', {name: '运行记录', exact: true}).click();
  const history = research.getByRole('dialog', {name: '运行记录', exact: true});
  await history.waitFor();
  const {runs} = await read('/api/v1/backtests/runs');
  await q.record('research-history', {text: await history.innerText(), runIds: runs.map(run => run.run_id)});
  const row = history.locator('article').filter({hasText: seed.runId.slice(-8)});
  await row.getByRole('button', {name: '查看结果', exact: true}).click({timeout: 10000});
  const sendBack = research.getByRole('button', {name: '将当前选定版本挂回图表', exact: true});
  await sendBack.click();
  const dialog = page.getByRole('dialog', {name: '应用选定研究版本', exact: true});
  await dialog.waitFor();
  assert.equal(new URL(page.url()).searchParams.has('research-version'), false);
  await dialog.getByLabel('目标图表', {exact: true}).selectOption('cell-1');
  await q.screenshot('research-version-target');
  await dialog.getByRole('button', {name: '创建独立图表草稿', exact: true}).click();
  await dialog.waitFor({state: 'hidden'});
  await page.getByLabel('运行模式', {exact: true}).selectOption('HISTORY_LIVE');
  const panel = page.locator('[data-continuous-strategy]');
  await panel.waitFor();
  const start = panel.getByRole('button', {name: '初始化新运行', exact: true});
  const trusted = page.getByTestId('strategy-python-confirm');
  assert.equal(await trusted.isChecked(), false);
  assert.equal(await start.isDisabled(), true);
  assert.equal(creates.length, 0);
  assert.equal(await panel.getByLabel('初始余额', {exact: true}).inputValue(), '5000');
  await q.record('frozen-version-applied', await q.inspect());
  await trusted.check();
  await start.click();
  const account = await q.until(async () => {
    await q.checkCircuit();
    const {runs} = await read(continuous + '/runs');
    return runs.length === 1 && runs[0].phase === 'LIVE' && runs[0].sequence > 0 ? runs[0] : false;
  }, 150000);
  assert.equal(creates.length, 1);
  assert.equal(creates[0].provider.source_text, seed.selected.program.source_text);
  assert.deepEqual(creates[0].provider.parameters, seed.selected.configuration.parameters);
  assert.equal(creates[0].from_ms, seed.selected.configuration.start_time_ms);
  assert.equal(creates[0].execution.initial_balance, '5000');
  await page.locator('[data-continuous-account="' + account.id + '"]').waitFor();
  await q.screenshot('live-chart-account');
  await q.record('live-account', account);
  await quit();
  const cold = coldAccount(account.id);
  await q.record('cold-account-before-restart', cold);
  await launch();
  const restored = await q.until(async () => {
    await q.checkCircuit();
    const result = await read(continuous + '/runs/' + account.id);
    return result.run?.phase === 'LIVE' && result.run.sequence > cold.sequence ? result : false;
  }, 150000);
  await q.record('same-account-advanced', {...restored, observedMs: Date.now()});
  assert.equal(creates.length, 1);
  assert.equal((await read(continuous + '/runs')).runs.length, 1);
  const reopened = q.s.page.locator('[data-continuous-account="' + account.id + '"]');
  if (!await reopened.isVisible()) {
    const dock = q.s.page.getByRole('button', {name: /^图表策略/});
    if (await dock.isVisible()) await dock.click();
  }
  await reopened.waitFor();
  const rendered = await reopened.locator('.continuous-account dd').allTextContents();
  assert.ok(Number(rendered[2]) >= restored.run.sequence);
  assert.equal(await q.s.page.getByTestId('strategy-python-confirm').isChecked(), false);
  await q.screenshot('restarted-chart-account');
  await quit();
  const after = coldAccount(account.id);
  assert.ok(after.sequence > cold.sequence && after.eventTimeMs > cold.eventTimeMs);
  assert.deepEqual(after.fills.slice(0, cold.fills.length), cold.fills);
  await q.record('cold-account-after-restart', {after, rendered});
  assert.deepEqual(q.s.receipt.errors, []);
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.failure = String(error.stack || error);
  process.exitCode = 1;
  if (q.s.page && !q.s.page.isClosed()) {
    await fs.writeFile(q.s.root + '/failure-page.txt', await q.s.page.locator('body').ariaSnapshot().catch(() => ''));
    await q.screenshot('failure').catch(() => {});
    for (const [index, window] of q.s.app.windows().entries()) {
      await fs.writeFile(q.s.root + '/failure-window-' + index + '.txt',
        await window.locator('body').ariaSnapshot().catch(() => ''));
    }
  }
} finally {
  if (running && q.s.app) {
    try { await quit(); } catch (error) { q.s.receipt.cleanupFailure = String(error.stack || error); }
  }
  await q.save();
  console.log(JSON.stringify({passed: q.s.receipt.passed ?? false, failure: q.s.receipt.failure, steps: q.s.receipt.steps.length}));
}
