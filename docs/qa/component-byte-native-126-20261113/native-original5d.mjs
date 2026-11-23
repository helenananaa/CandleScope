// Run with CANDLESCOPE_PLAYWRIGHT_PACKAGE pointing at a package containing
// playwright-core. The tested app and all profiles remain under output/.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import * as q from '../backend-batch1-20261101/driver.mjs';
import { capture } from '../backend-batch1-20261101/value-probe.mjs';
import { ControlClient } from '../../../packages/candlescope-control/client.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const qaProxy = process.env.CANDLESCOPE_QA_HTTP_PROXY;
if (qaProxy) {
  const route = new URL(qaProxy);
  assert.equal(route.hostname, '127.0.0.1');
  assert.equal(route.username + route.password, '');
  q.s.env.HTTPS_PROXY = q.s.env.HTTP_PROXY = qaProxy;
  q.s.env.NO_PROXY = '127.0.0.1,localhost,::1';
}
q.s.root = process.env.CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT
  ?? path.join(repo, 'output/aggregation-closeout-20261112/native');
await fs.mkdir(q.s.root, { recursive: true });
await assert.rejects(fs.stat(path.join(q.s.root, 'profile')), { code: 'ENOENT' });
const seedDatabase = process.env.CANDLESCOPE_AGGREGATION_MARKET_DB_SEED;
if (seedDatabase) {
  const target = path.join(q.s.root, 'profile/data/candlescope.db');
  await fs.mkdir(path.dirname(target), { recursive: true });
  execFileSync(process.env.CANDLESCOPE_QA_PYTHON ?? path.join(repo, '.venv/bin/python'), ['-c',
    'import sqlite3,sys; a=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close()',
    seedDatabase, target]);
}
q.s.receipt = {
  schema: 'candlescope.aggregation-closeout-native/1',
  sourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  scope: 'macOS arm64 packaged application; isolated profile; real public OKX history/realtime; no response substitution',
  input: seedDatabase ? 'fresh profile with only an explicit canonical SQLite backup from earlier public-data QA; not cold-load qualification'
    : 'fresh isolated profile with no seeded market history',
  steps: [], errors: [],
};
const executablePath = path.join(repo, 'frontend/desktop-dist/mac-arm64/CandleScope.app/Contents/MacOS/CandleScope');
const { _electron } = createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const minimumBars = process.env.CANDLESCOPE_AGGREGATION_DEEP_HISTORY === 'true' ? 500 : 128;
q.s.receipt.minimumBars = minimumBars;
q.s.receipt.transportConfiguration = { httpProxy: qaProxy ?? null, httpTimeoutSeconds: 8,
  scope: 'existing local proxy selected for this isolated process; no OS/user network setting changed' };
const session = interval => ({ exchange: 'okx', marketType: 'spot', symbol: 'BTC-USDT', interval });
const charts = intervals => intervals.map(interval => ({ session: session(interval), indicators: [] }));
let running = false;

async function api(route) {
  return q.s.page.evaluate(async url => {
    const response = await fetch(url);
    assertResponse(response);
    function assertResponse(value) { if (!value.ok) throw Error('HTTP ' + value.status); }
    return response.json();
  }, q.s.backend + route);
}

async function launch() {
  try {
    q.s.profileRoot = q.s.root + '/profile';
    q.s.app = await _electron.launch({ executablePath, args: ['--no-sandbox'], timeout: 240_000,
      env: { ...q.s.env, PYTHONUNBUFFERED: '1',
        CANDLESCOPE_DESKTOP_USER_DATA: q.s.profileRoot, CANDLE_DATA_DIR: q.s.profileRoot + '/data',
        CANDLESCOPE_DESKTOP_UI_PORT: '0', CANDLESCOPE_DESKTOP_BACKEND_PORT: '0',
        CANDLESCOPE_DESKTOP_SIDECAR_TIMEOUT_MS: '210000',
        CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: q.s.profileRoot + '/plugins',
        CANDLESCOPE_LOCAL_DATA_DIR: q.s.profileRoot + '/local-data' } });
    const output = createWriteStream(path.join(q.s.root, 'process.log'), { flags: 'a' });
    q.s.app.process().stdout?.pipe(output, { end: false });
    q.s.app.process().stderr?.pipe(output, { end: false });
    running = true;
    q.s.identity = { pid: q.s.app.process().pid };
    q.s.page = await q.s.app.firstWindow({ timeout: 240_000 });
    q.s.page.on('requestfailed', request => q.s.traffic.failures.push({url:request.url(),error:request.failure()?.errorText}));
    q.s.page.on('response', response => { if(response.url().includes('/api/')) q.s.traffic.responses.push({url:response.url(),status:response.status()}); });
    q.s.page.on('pageerror' , error => q.s.receipt.errors.push({ message: error.message }));
    await q.s.page.waitForFunction(() => Boolean(window.candlescopeDesktop), null, { timeout: 30_000 });
    q.s.identity = await q.s.app.evaluate(({ app }) => ({ packaged: app.isPackaged,
      pid: process.pid, userData: app.getPath('userData'), resources: process.resourcesPath }));
    assert.equal(q.s.identity.packaged, true);
    q.s.bootstrap = await q.s.page.evaluate(() => window.candlescopeDesktop.getBootstrap());
    q.s.backend = new URL(q.s.bootstrap.sidecar.healthUrl).origin;
  } catch (error) {
    running = Boolean(q.s.app);
    q.s.identity ??= { pid: q.s.app?.process()?.pid };
    throw error;
  }
  await q.s.page.evaluate(() => window.candlescopeDesktop.aiControlSetMode('control', true));
  q.s.control = new ControlClient(q.s.profileRoot + '/control/connection.json');
  await q.s.control.connect();
  await q.record('packaged-launch', { identity: q.s.identity, bootstrap: q.s.bootstrap });
}

async function verify(intervals, anchors = []) {
  // First prove the shipped staged viewport. Explicit pagination then verifies
  // deep history independently of the still-open cold hydration qualification.
  for (let index = 0; index < intervals.length; index++) {
    const cellId = 'cell-' + (index + 1);
    await q.s.page.locator('[data-chart-cell-id="' + cellId + '"]').click({ position: { x: 120, y: 120 } });
    await q.until(async () => {
      const cell = (await q.inspect()).cells.find(value => value.cellId === cellId);
      return cell?.session.interval === intervals[index] && cell.runtime.marketReady
        && !cell.runtime.loading && cell.runtime.barCount >= 128;
    }, 180_000);
    const before = (await q.inspect()).cells.find(value => value.cellId === cellId).runtime.barCount;
    if (before < minimumBars) {
      const action = await q.execute(cellId, 'loadMoreLeft', {});
      assert.equal(action.state, 'applied');
      await q.record('explicit-left-history', { cellId, before, action });
    }
  }
  await q.until(async () => {
    const view = await q.inspect();
    return view.cells.length === intervals.length && view.persistence.state === 'saved'
      && view.cells.every(cell => cell.runtime.marketReady && !cell.runtime.loading
        && cell.runtime.barCount >= minimumBars);
  }, 240_000);
  const views = await capture(q);
  assert.deepEqual(views.map(view => view.interval), intervals);
  const result = [];
  for (const [index, view] of views.entries()) {
    const closed = view.bars.filter(bar => bar.is_closed);
    assert.ok(closed.length >= minimumBars - 1);
    const params = new URLSearchParams({
      symbol: 'BTC-USDT', interval: view.interval, exchange: 'okx', market_type: 'spot',
      start_ms: String(closed[0].time * 1000), end_ms: String(closed.at(-1).time * 1000),
      repair: 'none', wait_ms: '0', strict: 'true', limit: '2000',
    });
    let readback;
    let pendingRecorded = false;
    await q.until(async () => {
      readback = await api('/api/v1/klines/range?' + params);
      if (!readback.complete && !pendingRecorded) {
        pendingRecorded = true;
        await q.record('strict-read-waiting-for-consistent-history', {
          interval: view.interval, complete: readback.complete,
          historyState: readback.history_state, metadata: readback.metadata,
          requested: { start: closed[0].time, end: closed.at(-1).time },
          rows: readback.data?.length,
        });
      }
      return readback.complete === true;
    }, 120_000);
    const rows = new Map(readback.data.map(bar => [bar.time, bar]));
    for (const bar of closed) {
      const stored = rows.get(bar.time);
      assert.ok(stored, 'missing canonical bar ' + bar.time);
      for (const field of ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote']) {
        assert.equal(bar[field] ?? null, stored[field] ?? null, view.interval + ':' + field);
      }
    }
    const anchor = anchors[index];
    if (anchor) {
      const restored = closed.find(bar => bar.time === anchor.time);
      assert.ok(restored, 'saved historical anchor missing');
      for (const field of ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote']) {
        assert.equal(restored[field] ?? null, anchor[field] ?? null, 'restored ' + view.interval + ':' + field);
      }
    }
    result.push({ interval: view.interval, compared: closed.length,
      first: closed[0], last: closed.at(-1), anchor: closed.at(-Math.min(128, closed.length)) });
  }
  assert.deepEqual(q.s.receipt.errors, []);
  return { values: result, workspace: await q.inspect(), diagnostics: await api('/api/v1/settings/cache-diagnostics') };
}

async function quit() {
  let timer;
  try {
    await Promise.race([q.quit(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('packaged quit timeout')), 45_000);
    })]);
  } finally { clearTimeout(timer); }
  await q.exited();
  running = false;
  await q.record('full-process-exit', { processes: q.s.quitPids, elapsedMs: Date.now() - q.s.quitStartedAt });
}

try {
  await launch();
  await q.configure(charts(['45m', '90m']), 'split-vertical');
  const initial = await verify(['45m', '90m']);
  await q.record('initial-derived-targets', initial);
  await q.screenshot('initial');
  await q.configure(charts(['1m', '5m']), 'split-vertical');
  await q.ready(2, 120_000);
  await q.record('released-derived-targets', await api('/api/v1/settings/cache-diagnostics'));
  await q.configure(charts(['45m', '90m']), 'split-vertical');
  const anchors = initial.values.map(value => value.anchor);
  const reopened = await verify(['45m', '90m'], anchors);
  await q.record('recreated-within-same-bucket', reopened);
  await q.screenshot('recreated');
  await quit();
  await launch();
  const restored = await verify(['45m', '90m'], anchors);
  await q.record('saved-exit-restart', restored);
  await q.screenshot('restored');
  await quit();
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.passed = false;
  q.s.receipt.failure = String(error.stack || error);
  process.exitCode = 1;
  if (running) {
    await q.record('failure-state', { workspace: await q.inspect().catch(error => String(error)),
      diagnostics: await api('/api/v1/settings/cache-diagnostics').catch(error => String(error)) }).catch(() => {});
    await q.screenshot('failure').catch(() => {});
  }
} finally {
  if (running) await quit().catch(error => { q.s.receipt.cleanupFailure = String(error); });
  await q.save();
  console.log(JSON.stringify({ passed: q.s.receipt.passed, failure: q.s.receipt.failure }));
}
