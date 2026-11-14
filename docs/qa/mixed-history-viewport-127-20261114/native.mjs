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
const PRIMARY = ['89m','97m','101m','10007m'];
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

async function waitForLiveFrames(label) {
  if (process.env.CANDLESCOPE_AGGREGATION_REQUIRE_LIVE !== 'true') return;
  let streams;
  await q.until(async () => {
    const diagnostics = await api('/api/v1/settings/cache-diagnostics');
    streams = diagnostics.data_manager.coordinator.streams;
    return ['1m', ...PRIMARY].every(interval => streams.some(stream =>
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
      symbol: 'BTCUSDT', interval: view.interval, exchange: 'binance', market_type: 'futures',
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

const closeProbe = id => ({id,name:'Joint native close input',kind:'script',executionTarget:'local',
  language:'frontend-js',securityMode:'safe',
  script:'plot("close",bars.map(bar=>bar.close),{pane:"main",color:"#f59e0b"});',params:{},visible:true});

async function addProbes() {
  for (let index=0;index<PRIMARY.length;index++) {
    const action=await q.execute('cell-'+(index+1),'addIndicator',closeProbe('joint-close-'+(index+1)));
    assert.equal(action.state,'applied',JSON.stringify(action));
  }
}

async function verifyConsumers(label) {
  await q.until(async()=>{
    const view=await q.inspect();
    return view.cells.length===4 && view.persistence.state==='saved' && view.cells.every(cell=>
      cell.runtime.marketReady && !cell.runtime.loading && cell.runtime.barCount>=128
      && cell.runtime.indicatorsReady && !cell.runtime.computing && !cell.runtime.indicatorErrors?.length
      && cell.runtime.indicatorOutputPoints.length>=3 && cell.runtime.indicatorOutputPoints.every(count=>count>0));
  },60000);
  const views=await capture(q);
  assert.deepEqual(views.map(view=>view.interval),PRIMARY);
  const evidence=[];
  for (const [index,view] of views.entries()) {
    const probe=view.lines.filter(line=>line.id==='joint-close-'+(index+1));
    assert.equal(probe.length,1,JSON.stringify(view.lines.map(line=>({id:line.id,name:line.name,points:line.data.length}))));
    const points=new Map(probe[0].data.map(point=>[Number(point.time),point.value]));
    assert.equal(points.size,probe[0].data.length);
    const closed=view.bars.filter(bar=>bar.is_closed);
    assert.ok(closed.length>=127);
    for (const bar of closed) assert.equal(points.get(bar.time),bar.close,view.interval+':'+bar.time);
    evidence.push({interval:view.interval,checkedClosed:closed.length,
      probe:probe[0].id,indicatorLines:view.lines.map(line=>({id:line.id,name:line.name,points:line.data.length}))});
  }
  await q.record('native-indicator-inputs-'+label,{evidence,workspace:await q.inspect(),
    scope:'two builtin local EMAs plus a supported frontend-JS close mirror on each real chart; closed inputs independently compared; no strategy qualification'});
}

try {
  q.s.receipt.driverSha256=Buffer.from(await crypto.subtle.digest('SHA-256',await fs.readFile(fileURLToPath(import.meta.url)))).toString('hex');
  q.s.receipt.primaryIntervals=PRIMARY;
  q.s.receipt.indicatorsPerCell=['local EMA20','local EMA60','frontend-JS close mirror'];
  q.s.receipt.resourceSampling='2s owned process tree RSS/CPU; stage diagnostics; not a paired RSS/GC/alloc qualification';
  await launch();
  sampler=setInterval(()=>sampleResources().catch(error=>q.s.receipt.errors.push({resourceSampling:String(error)})),2000);
  await sampleResources();
  phase='cold-four-prime';
  const coldBegan=Date.now();
  await configure(charts(PRIMARY),'quad');
  const initial=await verify(PRIMARY);
  await q.record('cold-prime-targets',{...initial,elapsedMs:Date.now()-coldBegan});
  await addProbes();
  await verifyConsumers('cold');
  await q.screenshot('cold-primes');
  await waitForLiveFrames('cold-primes');

  phase='four-prime-steady';
  for(let minute=0;minute<10;minute++) {
    await q.delay(60000);
    await q.record('prime-steady-minute-'+(minute+1),{workspace:await q.inspect(),diagnostics:await api('/api/v1/settings/cache-diagnostics')});
  }
  await q.record('steady-prime-canonical',await verify(PRIMARY));
  await verifyConsumers('steady');
  await q.screenshot('steady-primes');

  phase='hidden';
  const hidden=await q.s.app.evaluate(({BrowserWindow})=>{
    const window=BrowserWindow.getAllWindows().find(value=>value.isVisible());
    if(!window)throw Error('No visible native window');
    window.minimize();return {id:window.id,minimized:window.isMinimized()};
  });
  await q.delay(5000);
  await q.record('actual-window-hidden',{hidden,documentVisibility:await q.s.page.evaluate(()=>document.visibilityState),
    diagnostics:await api('/api/v1/settings/cache-diagnostics')});
  await q.s.app.evaluate(({BrowserWindow},id)=>{const window=BrowserWindow.fromId(id);window.restore();window.show();},hidden.id);
  phase='restored-visible';
  await verifyConsumers('restored-visible');
  await q.record('visible-prime-canonical',await verify(PRIMARY));
  await q.screenshot('restored-visible');

  phase='native-controls-and-release';
  await configure(charts(['1m','5m','15m','1h']),'quad');
  await q.record('native-controls',await verify(['1m','5m','15m','1h']));
  await q.record('released-prime-resources',await api('/api/v1/settings/cache-diagnostics'));
  phase='warm-prime-recreation';
  const anchors=initial.values.map(value=>value.anchor);
  await configure(charts(PRIMARY),'quad');
  await q.record('warm-prime-recreation',await verify(PRIMARY,anchors));
  await addProbes();
  await verifyConsumers('recreated');
  await q.screenshot('recreated-primes');
  await quit();
  phase='saved-prime-restart';
  await launch();
  await q.record('saved-prime-restart',await verify(PRIMARY,anchors));
  await verifyConsumers('restarted');
  await q.screenshot('restarted-primes');
  await sampleResources();
  await quit();
  const serverErrors=q.s.traffic.responses.filter(response=>response.status>=500);
  await q.record('server-response-audit',{serverErrors});
  assert.deepEqual(serverErrors,[]);
  assert.deepEqual(q.s.receipt.errors,[]);
  q.s.receipt.passed=true;
} catch(error) {
  q.s.receipt.passed=false;
  q.s.receipt.failure=String(error.stack||error);
  process.exitCode=1;
  if(running) {
    await q.record('failure-state',{phase,workspace:await q.inspect().catch(error=>String(error)),
      diagnostics:await api('/api/v1/settings/cache-diagnostics').catch(error=>String(error)),
      storageHealth:await api('/api/v1/settings/storage/health').catch(error=>String(error))}).catch(()=>{});
    await q.screenshot('failure').catch(()=>{});
  }
} finally {
  clearInterval(sampler);
  if(running)await quit().catch(error=>{q.s.receipt.cleanupFailure=String(error);});
  await q.save();
  console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure,phase}));
}

