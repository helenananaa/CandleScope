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
assert(!process.env.CANDLESCOPE_AGGREGATION_MARKET_DB_SEED,'#463 forbids market seeds');
const uiPlan=JSON.parse(await fs.readFile(path.join(repo,'output/issue-463-20261117/ui-plan.json'),'utf8'));
q.s.receipt = {
  schema: 'candlescope.aggregation-joint-native/1',
  sourceCommit: process.env.CANDLESCOPE_AGGREGATION_PACKAGE_REVISION
    ?? execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  driverSourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  diagnosticLogging: Boolean(process.env.CANDLESCOPE_QA_LOG_BOOTSTRAP),
  scope: 'macOS arm64 packaged application; isolated profile; real public Binance USD-M history/realtime; no response substitution',
  input: 'fresh isolated profile; UI preferences only; no market or computed indicator seed',
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
let demandAt=null;
const firstDemand={};
const frames=createWriteStream(path.join(q.s.root,'business-frames.jsonl'));
const launchAt=Date.now();

async function api(route) {
  return q.s.page.evaluate(async url => {
    const response = await fetch(url);
    assertResponse(response);
    function assertResponse(value) { if (!value.ok) throw Error('HTTP ' + value.status); }
    return response.json();
  }, q.s.backend + route);
}

function attachPage(page) {
  page.__qa463attached=true;
    const requestTimes = new WeakMap();
    page.on('request', request => {
      requestTimes.set(request, Date.now());
      if (request.url().includes('/api/')) q.s.traffic.requests.push({at:Date.now(),url:request.url(),method:request.method(),body:request.postData()});
    });
    page.on('websocket', socket => {
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
        if(socket.url().includes('/stream/klines') || socket.url().includes('/stream/indicators')) frames.write(JSON.stringify({...sample,url:socket.url()})+'\n');
        if(row.first.length<64)row.first.push(sample);
        row.last.push(sample);if(row.last.length>256)row.last.shift();
      });
      socket.on('close',()=>{row.closedAt=Date.now();});
    });
    page.on('requestfailed', request => q.s.traffic.failures.push({url:request.url(),error:request.failure()?.errorText}));
    page.on('response', response => {
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
    page.on('pageerror' , error => q.s.receipt.errors.push({ message: error.message }));
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
    const context=q.s.app.context();
    await context.addInitScript(({storage})=>{if(!localStorage.getItem('qa463-ui-only-configured')){for(const [key,value] of Object.entries(storage))localStorage.setItem(key,value);localStorage.setItem('qa463-ui-only-configured','true');}},uiPlan);
    context.on('page',attachPage);
    context.on('request',request=>{
      if(demandAt===null && request.resourceType()==='document' && /\/(index\.html)?(?:\?|$)/.test(request.url())) {
        demandAt=Date.now(); q.s.receipt.demandStartedAtMs=demandAt;
        q.s.receipt.startupElapsedMs=demandAt-launchAt;
        q.s.receipt.preDemandInventory=JSON.parse(execFileSync(process.env.CANDLESCOPE_QA_PYTHON,['-c',
          'import json,pathlib,sqlite3,sys; p=pathlib.Path(sys.argv[1]); d=p/"candlescope.db"; c=sqlite3.connect("file:"+str(d)+"?mode=ro",uri=True) if d.exists() else None; tables=[] if c is None else [r[0] for r in c.execute("select name from sqlite_master where type=\'table\'")]; print(json.dumps({"canonical_rows":0 if "klines" not in tables else c.execute("select count(*) from klines").fetchone()[0],"files":[{"name":str(f.relative_to(p)),"bytes":f.stat().st_size} for f in p.rglob("*") if f.is_file()]}))',q.s.profileRoot+'/data'],{encoding:'utf8'}));
      }
      if(request.url().includes('/api/v1/klines/')) {
        const interval=new URL(request.url()).searchParams.get('interval');
        if(PRIMARY.includes(interval) && !firstDemand[interval]) firstDemand[interval]={at:Date.now(),url:request.url()};
      }
    });
    q.s.page = await q.s.app.firstWindow({ timeout: 240_000 });
    if(!q.s.page.__qa463attached)attachPage(q.s.page);
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

async function waitForLiveFrames(label, since=0) {
  if (process.env.CANDLESCOPE_AGGREGATION_REQUIRE_LIVE !== 'true') return;
  let streams;
  await q.until(async () => {
    const diagnostics = await api('/api/v1/settings/cache-diagnostics');
    streams = diagnostics.data_manager.coordinator.streams;
    return ['1m', ...PRIMARY].every(interval => streams.some(stream =>
      stream.interval === interval && stream.bars_received > 0 && stream.last_bar_at_ms >= since));
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
  const additiveRoundoff = [];
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
        const drift = compareField(bar[field], stored[field], field, view.interval + ':' + bar.time + ':' + field);
        if (drift) additiveRoundoff.push({ interval: view.interval, time: bar.time, field, ...drift });
      }
    }
    const anchor = anchors[index];
    if (anchor) {
      const restored = closed.find(bar => bar.time === anchor.time);
      assert.ok(restored, 'saved historical anchor missing');
      for (const field of ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote']) {
        const drift = compareField(restored[field], anchor[field], field, 'restored ' + view.interval + ':' + field);
        if (drift) additiveRoundoff.push({ interval: view.interval, time: anchor.time, field, anchor: true, ...drift });
      }
    }
    result.push({ interval: view.interval, compared: closed.length,
      first: closed[0], last: closed.at(-1), anchor: closed.at(-Math.min(128, closed.length)) });
  }
  assert.deepEqual(q.s.receipt.errors, []);
  return { values: result, additiveRoundoff, workspace: await q.inspect(), diagnostics: await api('/api/v1/settings/cache-diagnostics') };
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
    const electronMetrics = await q.s.app.evaluate(({ app }) => app.getAppMetrics()).catch(() => null);
    for (const row of processes) observedCpu.set(row.pid,Math.max(observedCpu.get(row.pid)??0,row.cpuSeconds));
    await fs.appendFile(path.join(q.s.root,'resource-samples.jsonl'),JSON.stringify({at:new Date().toISOString(),phase,
      scope:'sum of owned process RSS, shared pages can be counted more than once; cumulative CPU includes observed exited children',
      rssKiB:processes.reduce((value,row)=>value+row.rssKiB,0),
      cpuSeconds:[...observedCpu.values()].reduce((a,b)=>a+b,0),processes,electronMetrics})+'\n');
  } finally { sampling = false; }
}

async function footprint(label) {
  if (process.platform !== 'darwin') return;
  const lines = (await fs.readFile(path.join(q.s.root,'resource-samples.jsonl'),'utf8')).trim().split('\n');
  const sample = JSON.parse(lines.at(-1));
  const result = execFileSync('/usr/bin/footprint', ['--noCategories','-j',
    path.join(q.s.root,'footprint-'+label+'.json'), ...sample.processes.map(row=>String(row.pid))],
    {encoding:'utf8',timeout:20_000});
  await fs.writeFile(path.join(q.s.root,'footprint-'+label+'.txt'),result);
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
    const emaChecks = [];
    for (const period of [20,60]) {
      const line = view.lines.find(line=>line.name === 'EMA('+period+')');
      assert.ok(line,'missing EMA('+period+') on '+view.interval);
      const output = new Map(line.data.map(point=>[Number(point.time),point.value]));
      let sum=0, ema=null, checked=0;
      for (const [position,bar] of view.bars.entries()) {
        if (position < period) { sum+=bar.close; if (position === period-1) ema=sum/period; }
        else ema=2/(period+1)*bar.close+(1-2/(period+1))*ema;
        if (ema !== null && bar.is_closed) {
          const actual=output.get(bar.time);
          assert.ok(Number.isFinite(actual) && Math.abs(actual-ema)<=1e-7,
            view.interval+' EMA('+period+') '+bar.time+': '+actual+' != '+ema);
          checked++;
        }
      }
      assert.ok(checked>0); emaChecks.push({period,checked});
    }
    evidence.push({interval:view.interval,checkedClosed:closed.length,
      probe:probe[0].id,emaChecks,indicatorLines:view.lines.map(line=>({id:line.id,name:line.name,points:line.data.length}))});
  }
  await q.record('native-indicator-inputs-'+label,{evidence,workspace:await q.inspect(),
    scope:'two builtin local EMAs plus a supported frontend-JS close mirror on each real chart; closed inputs independently compared; no strategy qualification'});
}

const outcomes=[], firstReady={}, readinessErrors={};
const readFields=['open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote'];
function indicatorOracle(view, full=true) {
  const issues=[], bars=view.bars, interval=view.interval;
  const require=(ok,why)=>{if(!ok)issues.push(why);};
  require(bars.length>0,'no bars');
  if(full) {require(bars.length>=128,'fewer than 128 bars');require(bars.filter(b=>b.is_closed).length>=127,'fewer than 127 closed bars');}
  require(new Set(bars.map(b=>b.time)).size===bars.length,'duplicate opens');
  for(let i=1;i<bars.length;i++)require(bars[i].time>bars[i-1].time,'unordered opens');
  if(full)for(let i=Math.max(1,bars.length-127);i<bars.length;i++)require(bars[i].time-bars[i-1].time===parseInt(interval)*60,'gap in final 128 target opens');
  const probe=view.lines.find(l=>l.id==='joint-close-'+(PRIMARY.indexOf(interval)+1));
  require(Boolean(probe),'JS close absent');
  const points=new Map((probe?.data??[]).map(p=>[Number(p.time),p.value]));
  let jsChecks=0,emaChecks=0;
  for(const bar of bars) {require(points.get(bar.time)===bar.close,'JS close mismatch '+bar.time);jsChecks++;}
  for(const period of [20,60]) {
    const line=view.lines.find(l=>l.name==='EMA('+period+')');require(Boolean(line),'EMA'+period+' absent');
    const values=new Map((line?.data??[]).map(p=>[Number(p.time),p.value]));let sum=0,ema=null;
    for(const [i,b] of bars.entries()) {
      if(i<period){sum+=b.close;if(i===period-1)ema=sum/period;}else ema=2/(period+1)*b.close+(1-2/(period+1))*ema;
      if(ema!==null){const actual=values.get(b.time);require(Number.isFinite(actual)&&Math.abs(actual-ema)<=1e-7,'EMA'+period+' mismatch '+b.time);emaChecks++;}
    }
  }
  return {interval,bars:bars.length,closed:bars.filter(b=>b.is_closed).length,jsChecks,emaChecks,
    issues:[...new Set(issues)].slice(0,12),last:bars.at(-1)};
}
async function sample(label,checkReady=true) {
  const at=Date.now(), workspace=await q.inspect(),views=await capture(q);
  const displays=await q.s.page.locator('[data-chart-cell-id]').evaluateAll(elements=>elements.map(e=>({cellId:e.getAttribute('data-chart-cell-id'),text:e.innerText})));
  const diagnostics=await api('/api/v1/settings/storage/health');
  const oracles=views.filter(v=>PRIMARY.includes(v.interval)).map(v=>indicatorOracle(v,true));
  if(checkReady)for(const oracle of oracles) {
    const cell=workspace.cells.find(c=>c.session.interval===oracle.interval);
    if(!firstReady[oracle.interval] && oracle.issues.length===0 && cell?.runtime.marketReady && !cell.runtime.loading && !cell.runtime.computing) {
      await q.s.page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      firstReady[oracle.interval]={at:Date.now(),demandAt,elapsedMs:Date.now()-demandAt,oracle,cellId:cell.cellId};
    }
    readinessErrors[oracle.interval]=oracle.issues;
  }
  const value={at,observedAt:Date.now(),label,workspace,views,displays,diagnostics,oracles};
  await fs.appendFile(path.join(q.s.root,'acceptance-timeline.jsonl'),JSON.stringify(value)+'\n');
  return value;
}
async function stage(name,fn) {
  const began=Date.now();try{const evidence=await fn();outcomes.push({name,passed:true,began,ended:Date.now(),evidence});await q.record(name,{passed:true,...evidence});return evidence;}
  catch(error){const result={name,passed:false,began,ended:Date.now(),error:String(error.stack||error)};outcomes.push(result);await q.record(name,result);return null;}
}
async function valuesStage(label,full=true) {
  const state=await sample(label,false),oracles=state.views.filter(v=>PRIMARY.includes(v.interval)).map(v=>indicatorOracle(v,full));
  assert.equal(oracles.length,4);assert(oracles.every(o=>!o.issues.length),JSON.stringify(oracles));
  return {at:state.at,oracles};
}
async function awaitFresh(label,timeoutMs=90000) {
  const before=await sample(label+'-before',false),end=Date.now()+timeoutMs;
  const prior=new Map(before.views.map(v=>[v.interval,JSON.stringify(v.bars.at(-1))]));
  while(Date.now()<end) {
    await q.delay(2000);const after=await sample(label,false);
    if(PRIMARY.every(i=>{const v=after.views.find(v=>v.interval===i);return v?.bars.length && JSON.stringify(v.bars.at(-1))!==prior.get(i) && !indicatorOracle(v,false).issues.length;}))return {before:before.at,after:after.at};
  }
  throw Error('No verified fresh chart/EMA/JS values for every interval within observation window');
}
let telemetry=false,telemetryTask;
async function startTelemetry(){telemetry=true;telemetryTask=(async()=>{while(telemetry){try{await sample('lifecycle-telemetry',false);}catch(error){await fs.appendFile(path.join(q.s.root,'observer-errors.jsonl'),JSON.stringify({at:Date.now(),error:String(error)})+'\n');}await q.delay(3000);}})();}
async function stopTelemetry(){telemetry=false;await telemetryTask;}
try {
  q.s.receipt.driverSha256=Buffer.from(await crypto.subtle.digest('SHA-256',await fs.readFile(fileURLToPath(import.meta.url)))).toString('hex');
  q.s.receipt.primaryIntervals=PRIMARY;q.s.receipt.netReadinessLimitMs=3000;
  q.s.receipt.netReadinessMs=null;q.s.receipt.netReadinessPassed=false;
  q.s.receipt.externalAttribution='Existing reported fetch totals lack a certified per-chart critical-path physical span graph. No cumulative subtraction; net timing remains unqualified.';
  await launch();
  assert.notEqual(demandAt,null,'Main document demand was not observed before renderer load');
  assert.equal(q.s.receipt.preDemandInventory.canonical_rows,0,'Cold demand started with canonical market rows');
  assert.deepEqual((await q.inspect()).cells.map(c=>c.session.interval),PRIMARY,'UI-only startup plan did not apply');
  await q.record('cold-preconditions',{demandAt,firstDemand,inventory:q.s.receipt.preDemandInventory,uiOnlyPlan:uiPlan.scope});
  sampler=setInterval(()=>sampleResources().catch(error=>q.s.receipt.errors.push({resourceSampling:String(error)})),2000);
  phase='cold-four-prime';
  const stop=Date.now()+300000;
  while(Date.now()<stop && PRIMARY.some(i=>!firstReady[i])) {await sample('cold');await q.delay(2000);}
  const cold=await sample('cold-observation-ended');
  q.s.receipt.coldObservationElapsedMs=Date.now()-demandAt;
  await q.record('cold-first-readiness',{firstReady,readinessErrors,elapsedMs:Date.now()-demandAt,
    passed:PRIMARY.every(i=>firstReady[i]),scope:'300s observation cap, not a replacement end-to-end acceptance threshold; net <=3s is still required'});
  await q.screenshot('cold-four');
  await sampleResources();await stage('cold-physical-footprint',()=>footprint('cold').then(()=>({captured:true})));
  phase='ten-minute-steady';
  const steadyAt=Date.now(),steady=[];
  for(let minute=0;minute<=10;minute++) {
    const due=steadyAt+minute*60000;
    while(Date.now()<due) {await q.delay(Math.min(5000,due-Date.now()));if(Date.now()<due)await sample('steady-progress');}
    const value=await sample('steady-minute-'+minute);steady.push(value);
    await q.record('steady-minute-'+minute,{at:value.at,oracles:value.oracles,workspace:value.workspace});
    if(minute===10)await q.screenshot('steady-ten-minutes');
  }
  await stage('ten-minute-values',async()=>{
    const unique={};for(const i of PRIMARY){const values=steady.map(s=>s.views.find(v=>v.interval===i));assert(values.every(v=>v && !indicatorOracle(v,true).issues.length),i+' incomplete or incorrect indicator samples');
      const signatures=values.map(v=>JSON.stringify({bar:v.bars.at(-1),lines:v.lines.map(l=>[l.id,l.data.at(-1)])}));unique[i]=new Set(signatures).size;assert.equal(unique[i],11,i+' did not have 11 distinct actual states');}
    return {samples:steady.length,elapsedMs:steady.at(-1).at-steady[0].at,unique};
  });
  await stage('steady-physical-footprint',()=>footprint('steady').then(()=>({captured:true})));
  await startTelemetry();
  phase='hidden-restored';
  await stage('hidden-restored',async()=>{
    const hidden=await q.s.app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>w.isVisible());w.minimize();return {id:w.id,minimized:w.isMinimized()};});
    await q.delay(5000);const visibility=await q.s.page.evaluate(()=>document.visibilityState);assert.equal(visibility,'hidden');
    await q.s.app.evaluate(({BrowserWindow},id)=>{const w=BrowserWindow.fromId(id);w.restore();w.show();},hidden.id);
    return {hidden,visibility,...await awaitFresh('restored')};
  });
  await stopTelemetry();
  phase='native-interval-controls';
  await stage('native-interval-controls',async()=>{
    await configure(charts(['1m','5m','15m','1h']),'quad');const stop=Date.now()+120000;
    while(Date.now()<stop){const state=await q.inspect();if(state.cells.every(c=>!c.runtime.loading && c.runtime.barCount>=128))break;await q.delay(2000);}
    const state=await sample('native-controls',false);assert.deepEqual(state.views.map(v=>v.interval),['1m','5m','15m','1h']);assert(state.views.every(v=>v.bars.length>=128));return {workspace:state.workspace};
  });
  phase='recreate-primes';
  await stage('recreate-primes',async()=>{await configure(charts(PRIMARY),'quad');await addProbes();return await awaitFresh('recreated');});
  const anchorState=await sample('historical-anchors',false);
  const anchors=anchorState.views.map(v=>({interval:v.interval,bar:v.bars.filter(b=>b.is_closed).at(-Math.min(128,v.bars.length-1))}));
  await q.record('historical-anchors',{anchors});
  await q.screenshot('before-save-restart');await quit();
  phase='saved-restart';
  await stage('saved-restart',async()=>{
    await launch();await awaitFresh('restarted');const state=await sample('restart-anchors',false);
    for(const a of anchors){assert(a.bar,'no historical anchor for '+a.interval);const b=state.views.find(v=>v.interval===a.interval)?.bars.find(b=>b.time===a.bar.time);assert(b,'saved anchor absent '+a.interval);for(const field of readFields)compareField(b[field],a.bar[field],field,a.interval+':saved-anchor:'+field);}
    return {anchors,oracles:state.views.map(v=>indicatorOracle(v,true))};
  });
  await q.screenshot('saved-restart');
  q.s.receipt.outcomes=outcomes;q.s.receipt.firstReady=firstReady;
  q.s.receipt.actualTotalElapsedMs=Date.now()-demandAt;
  q.s.receipt.functionalMatrixPassed=PRIMARY.every(i=>firstReady[i]) && outcomes.every(o=>o.passed);
  q.s.receipt.passed=q.s.receipt.functionalMatrixPassed && q.s.receipt.netReadinessPassed;
  q.s.receipt.failure=q.s.receipt.passed?null:'Joint acceptance incomplete: see per-stage results; certified net <=3s timing is required and currently unqualified.';
} catch(error) {
  q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack||error);q.s.receipt.failedPhase=phase;
  if(running)await q.screenshot('failure').catch(()=>{});
} finally {
  await stopTelemetry().catch(()=>{});clearInterval(sampler);
  if(running)await quit().catch(error=>q.s.receipt.cleanupFailure=String(error));
  await new Promise(resolve=>frames.end(resolve));
  q.s.receipt.outcomes=outcomes;q.s.receipt.firstReady=firstReady;q.s.receipt.readinessErrors=readinessErrors;
  await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure,phase}));
}
