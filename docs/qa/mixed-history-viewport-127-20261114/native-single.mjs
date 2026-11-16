// Isolate the same 10007m cold viewport gate; no shared four-chart qualification.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';

const output = process.env.CANDLESCOPE_SINGLE_OUTPUT;
const executablePath = process.env.CANDLESCOPE_AGGREGATION_NATIVE_EXECUTABLE;
assert.ok(output && executablePath);
await fs.mkdir(output, {recursive: false});
q.s.root = output;
q.s.profileRoot = output + '/profile';
const manifest = JSON.parse(await fs.readFile(path.resolve(path.dirname(executablePath),
  '../../..', 'package-source-manifest.json'), 'utf8'));
assert.equal(execFileSync('git', ['diff', '--name-only', manifest.product_head, 'HEAD', '--',
  'backend/app', 'frontend/src'], {encoding:'utf8'}), '');
const proxy = process.env.CANDLESCOPE_QA_HTTP_PROXY;
if (proxy) {
  const parsed = new URL(proxy);
  assert.equal(parsed.hostname, '127.0.0.1');
  assert.equal(parsed.username + parsed.password, '');
  q.s.env.HTTPS_PROXY = q.s.env.HTTP_PROXY = proxy;
  q.s.env.NO_PROXY = '127.0.0.1,localhost,::1';
}
q.s.receipt = {schema:'candlescope.composed-single-cold/1', sourceCommit:manifest.product_head,
  driverHead:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  scope:'fresh isolated unseeded macOS arm64 native profile; real public USD-M; one 10007m chart with EMA20/60; original 128-bar ready gate; no four-chart/resource qualification',
  passed:false, steps:[], errors:[]};
const pending = new Set();
let running = false;
try {
  await q.launch({executablePath,profileRoot:q.s.profileRoot});
  running = true;
  q.s.page.on('response', response => {
    if (response.status()<400 || !response.url().includes('/api/v1/klines/')) return;
    const task = (async () => {
      const body=await response.text().catch(error=>String(error));
      await fs.appendFile(output+'/http-errors.jsonl',JSON.stringify({at:new Date().toISOString(),
        status:response.status(),url:response.url(),body:body.slice(0,16384)})+'\n');
    })();
    pending.add(task);task.finally(()=>pending.delete(task)).catch(()=>{});
  });
  await q.s.page.evaluate(()=>window.candlescopeDesktop.aiControlSetMode('control',true));
  q.s.control = new ControlClient(q.s.profileRoot+'/control/connection.json');
  await q.s.control.connect();
  await q.until(async()=>{
    const view=await q.inspect();
    return view.ready && view.cells.length>0 && view.cells.every(cell=>cell.runtime?.mode==='live');
  },30000);
  await q.record('packaged-launch',{identity:q.s.identity,bootstrap:q.s.bootstrap});
  const session={exchange:'binance',marketType:'futures',symbol:'BTCUSDT',interval:'10007m'};
  const configured=await q.configure([{session,indicators:[{name:'EMA',period:20},{name:'EMA',period:60}]}],'single');
  await q.record('workspace-configure',configured);
  assert.ok(['ready','applied'].includes(configured.result.state));
  assert.deepEqual(configured.snapshot.cells.map(cell=>cell.session),[session]);
  const began=Date.now();
  await q.until(async()=>{
    const view=await q.inspect(), cell=view.cells[0];
    return view.cells.length===1 && cell.runtime.barCount>=128 && cell.runtime.marketReady
      && !cell.runtime.loading && !cell.runtime.initialHistoryPending && cell.runtime.indicatorsReady
      && !cell.runtime.computing && cell.runtime.indicatorOutputPoints.length===2
      && cell.runtime.indicatorOutputPoints.every(value=>value>0) && !cell.runtime.indicatorErrors.length;
  },180000);
  await q.record('cold-single-ready',{elapsedMs:Date.now()-began,workspace:await q.inspect(),values:await capture(q)});
  await q.screenshot('cold-single-ready');
  q.s.receipt.passed=true;
} catch(error) {
  q.s.receipt.failure=String(error.stack??error);
  if(running) {
    const health=await q.s.page.evaluate(async url=>(await fetch(url+'/api/v1/settings/storage/health')).json(),q.s.backend).catch(error=>String(error));
    await q.record('failure-state',{workspace:await q.inspect().catch(error=>String(error)),health});
    await q.screenshot('failure').catch(()=>{});
  }
} finally {
  await Promise.allSettled([...pending]);
  if(running) {
    await q.quit();await q.exited();running=false;
    await q.record('full-process-exit',{processes:q.s.quitPids});
  }
  await q.save();
  console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure}));
}
if(!q.s.receipt.passed) process.exitCode=1;
