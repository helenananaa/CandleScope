// Targeted partial-history paint observation, not cold-start qualification.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import { ControlClient } from '../../../packages/candlescope-control/client.mjs';

const root = process.cwd();
const output = process.env.CANDLESCOPE_PARTIAL_NATIVE_OUTPUT;
const executable = process.env.CANDLESCOPE_PARTIAL_NATIVE_EXECUTABLE;
const database = process.env.CANDLESCOPE_PARTIAL_NATIVE_DATABASE;
assert.ok(output && executable && database && process.env.CANDLESCOPE_QA_PYTHON);
await fs.mkdir(output, { recursive: false });
q.s.root = output;
q.s.profileRoot = path.join(output, 'profile');
const target = path.join(q.s.profileRoot, 'data/candlescope.db');
await fs.mkdir(path.dirname(target), { recursive: true });
execFileSync(process.env.CANDLESCOPE_QA_PYTHON, ['-c',
  'import pathlib,sqlite3,sys; a=sqlite3.connect(pathlib.Path(sys.argv[1]).resolve().as_uri()+"?mode=ro",uri=True); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close()',
  database, target]);
const sourceHead = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const manifest = JSON.parse(await fs.readFile(path.resolve(path.dirname(executable),
  '../../..', 'package-source-manifest.json'), 'utf8'));
assert.equal(manifest.product_head, sourceHead);
const proxy = process.env.CANDLESCOPE_QA_HTTP_PROXY;
if (proxy) {
  const parsed = new URL(proxy);
  assert.equal(parsed.hostname, '127.0.0.1');
  assert.equal(parsed.username + parsed.password, '');
  q.s.env.HTTPS_PROXY = q.s.env.HTTP_PROXY = proxy;
  q.s.env.NO_PROXY = '127.0.0.1,localhost,::1';
}
q.s.receipt = {
  schema: 'candlescope.partial-target-native/1', sourceCommit: sourceHead,
  driverSha256: Buffer.from(await crypto.subtle.digest('SHA-256',
    await fs.readFile(fileURLToPath(import.meta.url)))).toString('hex'),
  scope: 'retained public USD-M canonical SQLite backup in a fresh profile; '
    + 'one 89m chart and two built-in EMAs; real backend/network; '
    + 'partial-history paint only, not cold/complete-history/indicator/strategy/resource qualification',
  passed: false, steps: [], errors: [],
};
let running = false;
try {
  const identity = await q.launch({ executablePath: executable, profileRoot: q.s.profileRoot });
  running = true;
  await q.record('packaged-launch', { identity: identity.identity });
  await q.s.page.evaluate(() => window.candlescopeDesktop.aiControlSetMode('control', true));
  q.s.control = new ControlClient(path.join(q.s.profileRoot, 'control/connection.json'));
  await q.s.control.connect();
  await q.until(async () => {
    const snapshot = await q.inspect();
    return snapshot.ready && snapshot.cells.length > 0
      && snapshot.cells.every(cell => cell.runtime?.mode === 'live');
  }, 30_000);
  await q.record('initial-live-owner-ready', await q.inspect());
  const session = { exchange: 'binance', marketType: 'futures', symbol: 'BTCUSDT', interval: '89m' };
  const configured = await q.configure([{ session,
    indicators: [{ name: 'EMA', period: 20 }, { name: 'EMA', period: 60 }] }], 'single');
  await q.record('workspace-configure', configured);
  assert.ok(['ready', 'applied'].includes(configured.result.state));
  assert.deepEqual(configured.snapshot.cells.map(cell => cell.session), [session]);
  await q.until(async () => {
    const snapshot = await q.inspect();
    return snapshot.cells.length === 1 && snapshot.cells[0].runtime.barCount >= 100;
  }, 180_000);
  await q.record('partial-history-painted', await q.inspect());
  await q.screenshot('partial-history-painted');
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.errors.push({ message: error.message, stack: error.stack });
  try { await q.record('failure-state', await q.inspect()); await q.screenshot('failure'); } catch {}
} finally {
  if (q.s.app) {
    q.s.identity ??= { pid: q.s.app.process().pid };
    let timer;
    try {
      await Promise.race([q.quit(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error('packaged quit timeout')), 45_000);
      })]);
    } finally { clearTimeout(timer); }
    await q.exited();
    await q.record('full-process-exit', { processes: q.s.quitPids });
    running = false;
  }
  await q.save();
  assert.equal(running, false);
}
if (!q.s.receipt.passed) process.exitCode = 1;
