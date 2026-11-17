// Issue #462 forming/live recovery witness; not joint acceptance.
// Derived integration driver; source driver SHA-256: a35f47d0962a68c7a47b35e70be84987f335565bcea6a4a2880d9d12a70d5bc7
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
import { compareField } from '../large-interval-throughput-127-20261115/numeric.mjs';

if (process.env.BAR_AGG_UPDATE_THROTTLE_MS) {
  assert(/^\d{1,6}$/.test(process.env.BAR_AGG_UPDATE_THROTTLE_MS));
  q.s.env.BAR_AGG_UPDATE_THROTTLE_MS = process.env.BAR_AGG_UPDATE_THROTTLE_MS;
}
const diagnosticIssue = process.env.CANDLESCOPE_QA_DIAGNOSTIC_ISSUE ?? '462';
assert(/^\d+$/.test(diagnosticIssue));
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
  q.s.receipt.demandStartedAtMs = Date.now();
  const configured = await q.configure(charts, layout);
  await q.record('workspace-configure', configured);
  assert.ok(['ready','applied'].includes(configured.result.state), JSON.stringify(configured.result));
  assert.deepEqual(configured.snapshot.cells.map(cell => cell.session), charts.map(chart => chart.session));
  return configured;
}
let running = false;
const business = [];
const wire = createWriteStream(path.join(q.s.root,'business-frames.jsonl'));

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
    const requestTimes = new WeakMap();
    q.s.page.on('request', request => {
      requestTimes.set(request, Date.now());
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
        if(message?.type !== 'pong') { wire.write(JSON.stringify({...sample,url:socket.url()})+'\n'); business.push(sample); if(business.length>4096)business.shift(); }
        if(row.first.length<64)row.first.push(sample);
        row.last.push(sample);if(row.last.length>256)row.last.shift();
      });
      socket.on('close',()=>{row.closedAt=Date.now();});
    });
    q.s.page.on('requestfailed', request => q.s.traffic.failures.push({url:request.url(),error:request.failure()?.errorText}));
    q.s.page.on('response', response => {
      if(response.url().includes('/api/')) {
        const observedAt=Date.now(), startedAt=requestTimes.get(response.request());
        const record={url:response.url(),status:response.status(),observedAt,startedAt,elapsedMs:startedAt == null ? null : observedAt-startedAt};
        q.s.traffic.responses.push(record);
        if(response.url().includes('/api/v1/klines/')) response.json().then(body=>{
          const rows=body.data??[];
          record.result={count:rows.length,first:rows[0]?.time,last:rows.at(-1)?.time,complete:body.complete,history_state:body.history_state,
            retryable:body.retryable,metadata:body.cache??body.metadata,stream_version:body.stream_version};
        }).catch(error=>{record.bodyReadError=String(error);});
      }
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

const closeProbe = id => ({id,name:'Joint native close input',kind:'script',executionTarget:'local',
  language:'frontend-js',securityMode:'safe',
  script:'plot("close",bars.map(bar=>bar.close),{pane:"main",color:"#f59e0b"});',params:{},visible:true});

async function addProbes() {
  for (let index=0;index<PRIMARY.length;index++) {
    const action=await q.execute('cell-'+(index+1),'addIndicator',closeProbe('joint-close-'+(index+1)));
    assert.equal(action.state,'applied',JSON.stringify(action));
  }
}


const samples=[];
async function observe(label) {
  const began=Date.now(), distinct=Object.fromEntries(PRIMARY.map(i=>[i,new Set()]));
  while(Date.now()-began<180000) {
    const at=Date.now(), views=await capture(q), workspace=await q.inspect();
    const source=await api('/api/v1/klines/latest?symbol=BTCUSDT&interval=1m&limit=2&exchange=binance&market_type=futures&repair=none');
    const diagnostics=await api('/api/v1/settings/storage/health');
    const value={at,label,workspace,source,diagnostics,views};
    await fs.appendFile(path.join(q.s.root,'recovery-timeline.jsonl'),JSON.stringify(value)+'\n');
    for(const [index,view] of views.entries()) {
      const bar=view.bars.at(-1), line=view.lines.find(l=>l.id==='joint-close-'+(index+1));
      const point=line?.data.find(p=>Number(p.time)===bar?.time);
      if(bar && !bar.is_closed && point?.value===bar.close) {
        const signature=JSON.stringify([bar.time,bar.close,bar.volume]);
        distinct[view.interval]?.add(signature);
        samples.push({at,label,interval:view.interval,bar,point});
      }
    }
    if(PRIMARY.every(i=>distinct[i].size>=4)) {
      await q.record('actual-value-updates-'+label,{began,ended:Date.now(),elapsedMs:Date.now()-began,
        distinct:Object.fromEntries(PRIMARY.map(i=>[i,distinct[i].size])),workspace});
      await q.record('recovery-diagnostics-'+label,await api('/api/v1/settings/cache-diagnostics'));
      await q.screenshot('actual-values-'+label);
      return;
    }
    await q.delay(2000);
  }
  throw Error('Actual forming chart/JS values did not change four times for every interval: '+JSON.stringify(Object.fromEntries(PRIMARY.map(i=>[i,distinct[i].size]))));
}
try {
  q.s.receipt.scope += '; #462 current forming input/WS/chart/JS witness; seeded public history is not cold qualification';
  q.s.receipt.driverSha256=Buffer.from(await crypto.subtle.digest('SHA-256',await fs.readFile(fileURLToPath(import.meta.url)))).toString('hex');
  q.s.receipt.netReadinessMs=null;
  q.s.receipt.netReadinessPassed=false;
  await launch();
  await configure(charts(PRIMARY),'quad');
  await addProbes();
  await observe('initial');
  await q.record('before-renderer-reload',{workspace:await q.inspect(),at:Date.now()});
  await q.s.page.reload();
  await q.s.page.waitForFunction(()=>Boolean(window.candlescopeDesktop),null,{timeout:30000});
  await q.until(async()=> (await q.inspect()).cells.length===4,30000);
  await observe('resnapshot');
  q.s.receipt.passed=true;
  q.s.receipt.scopeNote='Scoped actual-value witness only. Controlled canonical-gap and epoch regressions are separate. No ten-minute, cold 3s, full history or lifecycle claim.';
} catch(error) {
  q.s.receipt.passed=false;
  q.s.receipt.failure=String(error.stack||error);
  if(running) await q.screenshot('failure').catch(()=>{});
} finally {
  q.s.receipt.endedAtMs=Date.now();
  q.s.receipt.actualTotalElapsedMs=q.s.receipt.endedAtMs-q.s.receipt.demandStartedAtMs;
  await fs.writeFile(path.join(q.s.root,'actual-value-samples.json'),JSON.stringify(samples,null,2)+'\n');
  if(running)await quit().catch(error=>{q.s.receipt.cleanupFailure=String(error);});
  await new Promise(resolve=>wire.end(resolve));
  await q.save();
  console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure,actualTotalElapsedMs:q.s.receipt.actualTotalElapsedMs}));
}
