import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import * as q from '../continuous-live-main268-20261107/native-driver.mjs';

const input = JSON.parse(await fs.readFile(q.s.root + '/controlled-repair-copy.json', 'utf8'));
const correction = JSON.parse(await fs.readFile(q.s.root + '/controlled-revision.json', 'utf8'));
const manifest = JSON.parse(await fs.readFile(q.s.root + '/source-package-manifest.json', 'utf8'));
const base = '/api/v1/backtests/continuous';
const route = base + '/runs/' + input.account.id;
q.s.receipt.schema = 'candlescope.native-continuous-repair/1';
q.s.receipt.driverCommit = q.s.receipt.sourceCommit;
q.s.receipt.sourceCommit = manifest.sourceCommit;
q.s.receipt.transport = 'Packaged app, actual local HTTP/WS and production source journal. One controlled source correction in a cold copy of the verified LIVE profile.';
const mutations = [];
q.s.receipt.mutations = mutations;
let running = false;
async function read(path) {
  const response = await fetch(q.s.backend + path);
  assert.equal(response.status, 200, path);
  return response.json();
}
async function waitStatus(predicate) {
  return q.until(async () => {
    await q.checkCircuit();
    const status = await read(route);
    await fs.writeFile(q.s.root + '/current-status.json', JSON.stringify(status, null, 2));
    return predicate(status) ? status : false;
  }, 90000);
}
async function launch() {
  running = true;
  await q.record('launch', await q.launch());
  q.s.page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path.startsWith(base) && !path.endsWith('/results/query')) {
      mutations.push({path, body: request.postDataJSON()});
    }
  });
  await q.checkCircuit();
}
async function openAccount() {
  const page = q.s.page;
  const account = page.locator('[data-continuous-account="' + input.account.id + '"]');
  if (!await page.locator('[data-continuous-strategy]').isVisible()) {
    await page.getByRole('button', {name: /^图表策略/}).click();
  }
  await account.waitFor();
  return account;
}
async function quit() {
  const pid = q.s.bootstrap.sidecar.pid;
  await q.quit();
  await q.exited();
  running = false;
  const sidecar = JSON.parse(await fs.readFile(q.s.root + '/sidecar-exit-status.json', 'utf8'));
  const exit = sidecar.exits.find(entry => entry.pid === pid);
  assert.equal(exit?.code, 0);
  assert.equal(exit?.signal, null);
  assert.deepEqual(sidecar.killRequests, []);
  await q.record('full-exit', {exit, owned: q.s.quitPids});
}
function cold() {
  return JSON.parse(execFileSync('python3', [
    '-B', 'docs/qa/continuous-live-main268-20261107/cold_account.py',
    q.s.root + '/profile', input.account.id, input.researchId, input.researchProfile,
  ], {encoding:'utf8'}));
}
try {
  await q.record('controlled-source-revision', correction);
  await launch();
  const stale = await waitStatus(status => status.run?.phase === 'REPAIR_REQUIRED');
  assert.equal(stale.run.sequence, input.account.sequence);
  assert.equal(stale.run.event_time_ms, input.account.eventTimeMs);
  const account = await openAccount();
  const staleValues = await account.locator('.continuous-account dd').allTextContents();
  assert.deepEqual(staleValues, [input.account.equity, input.account.positionQty, String(input.account.sequence)]);
  const repair = q.s.page.locator('[data-continuous-repair]');
  await repair.getByRole('button', {name:'预览修复范围', exact:true}).click();
  await repair.getByText('保存的初始输入也发生了修订，需要从原始起点重新构建。', {exact:true}).waitFor();
  const confirm = repair.getByRole('button', {name:'确认并修复', exact:true});
  assert.equal(await confirm.isDisabled(), true);
  assert.equal(mutations.filter(row => row.path.endsWith('/repairs')).length, 0);
  await repair.scrollIntoViewIfNeeded();
  await q.screenshot('repair-preview');
  await q.record('stale-account-and-preview', {stale, staleValues, text:await repair.innerText()});
  await repair.getByRole('checkbox', {name:'我确认此范围，并授权使用本运行保存的代码和配置更新账户结果。', exact:true}).check();
  await confirm.click();
  const repaired = await waitStatus(status => status.run?.phase === 'PAUSED' &&
    status.repair?.phase === 'COMMITTED' && status.repair.progress?.resources_released);
  await repair.getByText('修复完成', {exact:true}).waitFor();
  assert.equal(repaired.run.sequence, input.account.sequence);
  assert.notEqual(repaired.identity.data_revision, stale.identity.data_revision);
  await q.record('repaired-account', repaired);
  await quit();
  const first = cold();
  assert.equal(first.sequence, input.account.sequence);
  assert.notDeepEqual(first.fills, input.account.fills);
  await q.record('cold-repaired-before-restart', first);
  await launch();
  const restored = await waitStatus(status => status.run?.phase === 'PAUSED' && status.repair?.phase === 'COMMITTED');
  assert.deepEqual(restored.identity, repaired.identity);
  const reopened = await openAccount();
  await q.s.page.locator('[data-continuous-repair]').getByText('修复完成', {exact:true}).waitFor();
  const rendered = await reopened.locator('.continuous-account dd').allTextContents();
  assert.deepEqual(rendered, [first.equity, first.positionQty, String(first.sequence)]);
  await reopened.scrollIntoViewIfNeeded();
  await q.screenshot('repaired-account-after-restart');
  assert.equal(mutations.filter(row => row.path.endsWith('/repairs')).length, 1);
  assert.equal(mutations.filter(row => row.path === base + '/runs').length, 0);
  await quit();
  const second = cold();
  const {databaseSha256: before, ...firstState} = first;
  const {databaseSha256: after, ...secondState} = second;
  assert.deepEqual(secondState, firstState);
  await q.record('cold-repaired-after-restart', {second, rendered, before, after});
  assert.deepEqual(q.s.receipt.errors, []);
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.failure = String(error.stack || error);
  process.exitCode = 1;
  if (q.s.page && !q.s.page.isClosed()) {
    await fs.writeFile(q.s.root + '/failure-page.txt', await q.s.page.locator('body').ariaSnapshot().catch(() => ''));
    await q.screenshot('failure').catch(() => {});
  }
} finally {
  if (running && q.s.app) {
    try { await quit(); } catch (error) { q.s.receipt.cleanupFailure = String(error.stack || error); }
  }
  await q.save();
  console.log(JSON.stringify({passed:q.s.receipt.passed ?? false,failure:q.s.receipt.failure,steps:q.s.receipt.steps.length}));
}
