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
  schema: 'candlescope.aggregation-joint-native/1',
  sourceCommit: process.env.CANDLESCOPE_AGGREGATION_PACKAGE_REVISION
    ?? execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  driverSourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  diagnosticLogging: Boolean(process.env.CANDLESCOPE_QA_LOG_BOOTSTRAP),
  scope: 'macOS arm64 packaged application; isolated profile; real public Binance USD-M history/realtime; no response substitution',
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
q.s.receipt.closedRetentionWitness = process.env.CANDLESCOPE_CLOSED_RETENTION_WITNESS === 'true';
const session = interval => ({ exchange: 'binance', marketType: 'futures', symbol: 'BTCUSDT', interval });
const PRIMARY = ['10007m'];
const charts = intervals => intervals.map(interval => ({ session: session(interval), indicators: [{name:'EMA',period:20},{name:'EMA',period:60}] }));
async function configure(charts, layout) {
  const configured = await q.configure(charts, layout);
  await q.record('workspace-configure', configured);
  assert.ok(['ready','applied'].includes(configured.result.state), JSON.stringify(configured.result));
  assert.deepEqual(configured.snapshot.cells.map(cell => cell.session), charts.map(chart => chart.session));
  return configured;
}
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
    q.s.page.on('request', request => {
      if (request.url().includes('/api/')) q.s.traffic.requests.push({at:Date.now(),url:request.url(),method:request.method(),body:request.postData()});
    });
    q.s.page.on('websocket', socket => {
      const row={url:socket.url(),openedAt:Date.now(),received:0,sent:[],first:[],last:[]};
      q.s.traffic.sockets.push(row);
      socket.on('framesent',event=>{if(row.sent.length<1000)row.sent.push(String(event.payload));});
      socket.on('framereceived',event=>{
        row.received++;
        if(!socket.url().includes('/stream'))return;
        const raw=String(event.payload);
        let message;
        try { const value=JSON.parse(raw);message=raw.length<=8192?value:{truncated:true,bytes:raw.length,type:value.type,keys:Object.keys(value)}; }
        catch { message={unparsed:true,bytes:raw.length}; }
        const sample={at:Date.now(),message};
        if(row.first.length<64)row.first.push(sample);
        row.last.push(sample);if(row.last.length>256)row.last.shift();
      });
      socket.on('close',()=>{row.closedAt=Date.now();});
    });
    q.s.page.on('requestfailed', request => q.s.traffic.failures.push({url:request.url(),error:request.failure()?.errorText}));
    q.s.page.on('response', response => {
      if(response.url().includes('/api/')) q.s.traffic.responses.push({url:response.url(),status:response.status()});
      if(response.status()>=400 && response.url().includes('/api/v1/klines/')) {
        response.text().then(body=>fs.appendFile(path.join(q.s.root,'http-errors.jsonl'),JSON.stringify({
          at:new Date().toISOString(),url:response.url(),status:response.status(),body:body.slice(0,16384)})+'\n')).catch(()=>{});
      }
    });
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
  await q.until(async () => {
    const view = await q.inspect();
    return view.ready && view.cells.length > 0
      && view.cells.every(cell => cell.runtime?.mode === 'live');
  }, 30_000);
  await q.record('initial-live-owner-ready', await q.inspect());
  await q.record('packaged-launch', { identity: q.s.identity, bootstrap: q.s.bootstrap });
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

let phase = 'launch';
let sampling = false;
let sampler;
const observedCpu = new Map();
async function sampleResources() {
  if (sampling || !running || !q.s.identity?.pid) return;
  sampling = true;
  try {
    const rows = execFileSync('ps', ['-axo','pid=,ppid=,rss=,time='], {encoding:'utf8'}).trim().split('\n').map(line => {
      const parts = line.trim().split(/\s+/);
      return {pid:Number(parts[0]),ppid:Number(parts[1]),rssKiB:Number(parts[2]),
        cpuSeconds:parts[3].split(':').reduce((value, part) => value*60+Number(part),0)};
    });
    const owned = new Set([q.s.identity.pid]);
    for (let pass=0;pass<10;pass++) for (const row of rows) if (owned.has(row.ppid)) owned.add(row.pid);
    const processes = rows.filter(row=>owned.has(row.pid));
    for (const row of processes) observedCpu.set(row.pid,Math.max(observedCpu.get(row.pid)??0,row.cpuSeconds));
    await fs.appendFile(path.join(q.s.root,'resource-samples.jsonl'),JSON.stringify({at:new Date().toISOString(),phase,
      scope:'sum of owned process RSS, shared pages can be counted more than once; cumulative CPU includes observed exited children',
      rssKiB:processes.reduce((value,row)=>value+row.rssKiB,0),
      cpuSeconds:[...observedCpu.values()].reduce((a,b)=>a+b,0),processes})+'\n');
  } finally { sampling = false; }
}

try {
  q.s.receipt.schema = 'candlescope.partial-first-paint-native/1';
  q.s.receipt.driverSha256 = Buffer.from(await crypto.subtle.digest('SHA-256', await fs.readFile(fileURLToPath(import.meta.url)))).toString('hex');
  q.s.receipt.scope += '; focused partial-data presentation observation, not joint readiness qualification';
  q.s.receipt.indicatorsPerCell = ['local EMA20', 'local EMA60'];
  await launch();
  sampler = setInterval(() => sampleResources().catch(error => q.s.receipt.errors.push({resourceSampling: String(error)})), 2000);
  phase = 'partial-single-prime';
  await configure(charts(PRIMARY), 'single');
  const observations = [];
  for (let sample = 0; sample < 12; sample++) {
    await q.delay(15000);
    const workspace = await q.inspect();
    const display = await q.s.page.evaluate(() => [...document.querySelectorAll('[data-chart-cell-id]')].map(cell => {
      const overlay = cell.querySelector('.loading-overlay');
      const bounds = element => {
        const r = element.getBoundingClientRect();
        return {x:r.x,y:r.y,width:r.width,height:r.height};
      };
      return {cellId:cell.getAttribute('data-chart-cell-id'), partial:overlay?.classList.contains('loading-overlay--partial') ?? false,
        overlay:overlay ? bounds(overlay) : null, cell:bounds(cell),
        pointerEvents:overlay ? getComputedStyle(overlay).pointerEvents : null,
        status:overlay?.getAttribute('role'), text:overlay?.textContent,
        canvases:[...cell.querySelectorAll('canvas')].map(bounds)};
    }));
    const observation = {sample, at:new Date().toISOString(), workspace, display};
    observations.push(observation);
    await q.record('partial-display-'+sample, observation);
    console.log(JSON.stringify({sample,cells:workspace.cells.map(cell=>({id:cell.cellId,bars:cell.runtime.barCount,
      loading:cell.runtime.loading,ready:cell.runtime.marketReady,partial:display.find(row=>row.cellId===cell.cellId)?.partial}))}));
    if (sample === 3 || sample === 11) await q.screenshot('partial-display-'+sample);
  }
  const witnessed = new Set();
  for (const observation of observations) for (const cell of observation.workspace.cells) {
    const display = observation.display.find(row => row.cellId === cell.cellId);
    if (cell.runtime.loading && !cell.runtime.marketReady && cell.runtime.barCount > 0 && display?.partial) {
      assert.equal(display.pointerEvents, 'none');
      assert.equal(display.status, 'status');
      assert.ok(display.overlay.height < display.cell.height / 2);
      assert.ok(display.canvases.some(canvas => canvas.width > 0 && canvas.height > 0));
      witnessed.add(cell.cellId);
    }
  }
  assert.equal(witnessed.size, PRIMARY.length, 'every cold chart must witness nonblocking pending data');
  await q.record('partial-presentation-result', {witnessed:[...witnessed],
    scope:'owned source projection and nonblocking loading status observed; screenshot must be inspected separately; original 128-bar/marketReady and all later joint gates remain unqualified'});
  await q.record('source-observation', await capture(q));
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.passed = false;
  q.s.receipt.failure = String(error.stack || error);
  process.exitCode = 1;
  if (running) {
    await q.record('failure-state', {phase,workspace:await q.inspect().catch(error=>String(error))}).catch(()=>{});
    await q.screenshot('failure').catch(()=>{});
  }
} finally {
  clearInterval(sampler);
  if (running) await quit().catch(error=>{q.s.receipt.cleanupFailure=String(error);process.exitCode=1;});
  await q.save();
  console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure,phase}));
}
