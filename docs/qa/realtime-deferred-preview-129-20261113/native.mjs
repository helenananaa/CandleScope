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

if (process.env.BAR_AGG_UPDATE_THROTTLE_MS) {
  assert(/^\d{1,6}$/.test(process.env.BAR_AGG_UPDATE_THROTTLE_MS));
  q.s.env.BAR_AGG_UPDATE_THROTTLE_MS = process.env.BAR_AGG_UPDATE_THROTTLE_MS;
}
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const qaProxy = process.env.CANDLESCOPE_QA_HTTP_PROXY;
if (qaProxy) {
  const route = new URL(qaProxy);
  assert.equal(route.hostname, '127.0.0.1');
  assert.equal(route.username + route.password, '');
  q.s.env.HTTPS_PROXY = q.s.env.HTTP_PROXY = qaProxy;
  q.s.env.NO_PROXY = '127.0.0.1,localhost,::1';
}
if (process.env.CANDLESCOPE_QA_LOG_BOOTSTRAP) {
  q.s.env.PYTHONPATH = process.env.CANDLESCOPE_QA_LOG_BOOTSTRAP;
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
  sourceCommit: process.env.CANDLESCOPE_AGGREGATION_PACKAGE_REVISION
    ?? execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  driverSourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  diagnosticLogging: Boolean(process.env.CANDLESCOPE_QA_LOG_BOOTSTRAP),
  scope: 'macOS arm64 packaged application; isolated profile; real public OKX history/realtime; no response substitution',
  input: seedDatabase ? 'fresh profile with only an explicit canonical SQLite backup from earlier public-data QA; not cold-load qualification'
    : 'fresh isolated profile with no seeded market history',
  steps: [], errors: [],
};
const executablePath = process.env.CANDLESCOPE_AGGREGATION_NATIVE_EXECUTABLE
  ?? path.join(repo, 'frontend/desktop-dist/mac-arm64/CandleScope.app/Contents/MacOS/CandleScope');
const sourceManifest = JSON.parse(await fs.readFile(path.resolve(path.dirname(executablePath),
  '../../..', 'package-source-manifest.json'), 'utf8'));
assert.equal(q.s.receipt.sourceCommit, sourceManifest.product_head);
const { _electron } = createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const minimumBars = process.env.CANDLESCOPE_AGGREGATION_DEEP_HISTORY === 'true' ? 500 : 128;
q.s.receipt.minimumBars = minimumBars;
q.s.receipt.transportConfiguration = { httpProxy: qaProxy ?? null, httpTimeoutSeconds: 8,
  scope: 'existing local proxy selected for this isolated process; no OS/user network setting changed' };
q.s.receipt.previewConfiguration = { throttleMs: Number(process.env.BAR_AGG_UPDATE_THROTTLE_MS ?? 250),
  witness: process.env.CANDLESCOPE_AGGREGATION_PREVIEW_WITNESS === 'true',
  scope: 'existing process configuration and read-only public diagnostics; no bootstrap hook, extra subscription or source replacement' };
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

async function waitForLiveFrames(label) {
  if (process.env.CANDLESCOPE_AGGREGATION_REQUIRE_LIVE !== 'true') return;
  let streams;
  await q.until(async () => {
    const diagnostics = await api('/api/v1/settings/cache-diagnostics');
    streams = diagnostics.data_manager.coordinator.streams;
    return ['1m','15m','30m','45m','90m'].every(interval => streams.some(stream =>
      stream.interval === interval && stream.bars_received > 0));
  }, 120_000);
  await q.record('live-frames-' + label, { streams });
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
    let before = (await q.inspect()).cells.find(value => value.cellId === cellId).runtime.barCount;
    for (let page = 0; before < minimumBars && page < 8; page++) {
      const action = await q.execute(cellId, 'loadMoreLeft', {});
      assert.equal(action.state, 'applied');
      await q.record('explicit-left-history', { cellId, before, page, action });
      await q.until(async () => {
        const cell = (await q.inspect()).cells.find(value => value.cellId === cellId);
        return !cell.runtime.loadingMoreLeft && cell.runtime.barCount > before;
      }, 120_000);
      before = (await q.inspect()).cells.find(value => value.cellId === cellId).runtime.barCount;
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

async function witnessPreview(label) {
  if (process.env.CANDLESCOPE_AGGREGATION_PREVIEW_WITNESS !== 'true') return;
  let before, selected, after;
  await q.until(async () => {
    before = (await api('/api/v1/settings/cache-diagnostics')).data_manager.aggregation_previews;
    selected = before.watermarks.find(row => ['45m','90m'].includes(row.interval)
      && row.symbol === 'BTC-USDT' && row.dirty && row.input > row.computed
      && Date.now()+20000 < row.bucket_start_ms+Number.parseInt(row.interval)*60000);
    return before.running && selected;
  }, 120_000);
  await q.record('preview-dirty-' + label, { preview: before, selected });
  await q.until(async () => {
    after = (await api('/api/v1/settings/cache-diagnostics')).data_manager.aggregation_previews;
    const row = after.watermarks.find(row => row.interval === selected.interval
      && row.symbol === selected.symbol && row.bucket_start_ms === selected.bucket_start_ms);
    return row && row.computed >= selected.input && row.published >= selected.input
      && after.published > before.published;
  }, 120_000);
  await q.record('preview-flushed-' + label, { preview: after, observed: selected });
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
  await waitForLiveFrames('initial');
  const initial = await verify(['45m', '90m']);
  await q.record('initial-derived-targets', initial);
  await witnessPreview('initial');
  await q.screenshot('initial');
  await q.configure(charts(['1m', '5m']), 'split-vertical');
  const native = await verify(['1m', '5m']);
  const streamHealth = await api('/api/v1/settings/storage/health');
  const fetcher = streamHealth.backfill_engine?.fetcher;
  assert.equal(fetcher?.last_history_request?.payload_kind, 'receipt', JSON.stringify(fetcher));
  await q.record('native-stream-receipt-path', { ...native, streamHealth });
  await q.record('released-derived-targets', await api('/api/v1/settings/cache-diagnostics'));
  await q.configure(charts(['45m', '90m']), 'split-vertical');
  const anchors = initial.values.map(value => value.anchor);
  await waitForLiveFrames('recreated');
  const reopened = await verify(['45m', '90m'], anchors);
  await q.record('recreated-within-same-bucket', reopened);
  await witnessPreview('recreated');
  await q.screenshot('recreated');
  await quit();
  await launch();
  await waitForLiveFrames('restarted');
  const restored = await verify(['45m', '90m'], anchors);
  await q.record('saved-exit-restart', restored);
  await witnessPreview('restarted');
  await q.screenshot('restored');
  await quit();
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.passed = false;
  q.s.receipt.failure = String(error.stack || error);
  process.exitCode = 1;
  if (running) {
    await q.record('failure-state', { workspace: await q.inspect().catch(error => String(error)),
      diagnostics: await api('/api/v1/settings/cache-diagnostics').catch(error => String(error)),
      storageHealth: await api('/api/v1/settings/storage/health').catch(error => String(error)),
      support: await api('/api/v1/support/diagnostics').catch(error => String(error)) }).catch(() => {});
    await q.screenshot('failure').catch(() => {});
  }
} finally {
  if (running) await quit().catch(error => { q.s.receipt.cleanupFailure = String(error); });
  await q.save();
  console.log(JSON.stringify({ passed: q.s.receipt.passed, failure: q.s.receipt.failure }));
}
