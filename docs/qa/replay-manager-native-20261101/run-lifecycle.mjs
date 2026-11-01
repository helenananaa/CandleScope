import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import * as q from './acceptance-driver.mjs';
import {capture} from './value-probe.mjs';
import {setup} from './setup-native.mjs';
setup(q);
q.s.receipt.schema='candlescope.replay-manager-native-lifecycle/1';
const manager=()=>q.s.page.evaluate(()=>window.__CANDLESCOPE_REPLAY_DATA__?.snapshot().replay);
const cursor=()=>q.s.page.locator('[data-replay-cursor-ms]').first().getAttribute('data-replay-cursor-ms').then(Number);
const ready=()=>q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:45000});
async function facts(label,count){
  const historyStarted=Date.now();
  const charts=await q.until(async()=>{const rows=await capture(q);return rows.length===count&&rows.every(c=>c.bars.length>10)?rows:false;},100000);
  const time=await cursor(), m=await manager();
  assert.equal(charts.length,count);assert.equal(m.activeSequences,count);
  const rows=[];
  for(const chart of charts){
    assert.ok(chart.bars.length>10);
    assert.ok(chart.bars.every(b=>b.time*1000<=time),'unrevealed bar timestamp');
    let checked=0;
    if(chart.interval==='1m')for(const bar of chart.bars.filter(b=>b.is_closed)){
      const i=(bar.time*1000-1700000040000)/60000,base=30000+i%80*2+Math.floor(i/80)*.25;
      assert.ok(Number.isInteger(i)&&i>=0&&i<4000);
      const expected={open:base,high:base+12,low:base-12,close:base+(i%2===0?4:-3),volume:10+i%7};
      for(const key of Object.keys(expected))assert.equal(bar[key],expected[key],`${label}:${key}:${i}`);
      assert.ok(bar.time*1000+59999<=time);checked++;
    }
    rows.push({cellId:chart.cellId,interval:chart.interval,bars:chart.bars.length,first:chart.bars[0].time,last:chart.bars.at(-1).time,closedOHLCVCompared:checked});
  }
  assert.equal(new Set(m.sequences.map(s=>s.owner)).size,count);
  assert.ok([...m.sequences,...m.operations].every(x=>x.cleanupErrors===0));
  await q.record(label,{time,historyWaitMs:Date.now()-historyStarted,charts:rows,manager:m});return charts;
}
try{
  await q.record('launch',await q.launch());
  await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();
  await q.s.page.waitForLoadState('load');
  await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);
  await q.s.page.locator('.training-hub-card').first().getByRole('button',{name:'继续训练',exact:true}).click();
  await ready();await facts('resumed-single',1);
  const runId=new URL(q.s.page.url()).searchParams.get('run');
  const initial=await cursor();
  await q.s.page.locator('[data-replay-action="play"]').click();
  await q.s.page.waitForFunction(old=>Number(document.querySelector('[data-replay-cursor-ms]')?.getAttribute('data-replay-cursor-ms'))>old+120000,initial);
  await q.s.page.locator('[data-replay-action="pause"]').click();await ready();
  await facts('play-pause',1);
  await q.s.page.getByRole('button',{name:'图 1 布局操作',exact:true}).click();
  await q.s.page.getByRole('button',{name:'向右拆分',exact:true}).click();
  await q.until(async()=> (await manager()).activeSequences===2);
  await facts('two-private-sequences',2);
  await q.s.page.locator('[data-chart-cell-id="cell-2"]').focus();
  await q.s.page.getByRole('button',{name:'5m',exact:true}).click();
  await q.until(async()=> (await capture(q)).some(c=>c.cellId==='cell-2'&&c.interval==='5m'&&c.bars.length>10));
  const split=await facts('independent-intervals',2);
  assert.equal(split.find(c=>c.cellId==='cell-1').interval,'1m');
  await q.screenshot('split-intervals');
  const before=await cursor(),cdp=await q.s.page.context().newCDPSession(q.s.page);
  await cdp.send('Network.enable');await cdp.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  const proto=await cdp.send('Runtime.evaluate',{expression:'WebSocket.prototype'});
  const sockets=await cdp.send('Runtime.queryObjects',{prototypeObjectId:proto.result.objectId});
  const closed=await cdp.send('Runtime.callFunctionOn',{objectId:sockets.objects.objectId,returnByValue:true,functionDeclaration:'function(){return this.map(socket=>{const url=socket.url;socket.close(4001);return url;});}'});
  assert.ok(closed.result.value.some(url=>url.includes('replay')));
  await q.delay(5000);
  const offline=await q.s.page.evaluate(async url=>{try{await fetch(url);return false;}catch{return true;}},q.s.backend+'/health');assert.equal(offline,true);
  await q.record('offline-observed',{urls:closed.result.value,time:await cursor(),networkFailure:offline});
  const started=Date.now();await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await ready();
  const advance=q.s.page.locator('[data-replay-action="advance-base"]'), acquire=q.s.page.getByRole('button',{name:'获取控制权',exact:true});
  await q.until(async()=>await advance.isEnabled()||await acquire.isVisible(),30000);
  if(await acquire.isVisible()){await acquire.click();await q.record('controller-reacquired',{});}
  await advance.click();
  await q.s.page.waitForFunction(old=>Number(document.querySelector('[data-replay-cursor-ms]')?.getAttribute('data-replay-cursor-ms'))>old,before,{timeout:45000});
  await ready();await facts('reconnected-advanced',2);
  await q.record('recovery-duration',{elapsedMs:Date.now()-started});
  await q.s.page.getByRole('button',{name:'复盘与完整性',exact:true}).click();
  await q.s.page.locator('.replay-portfolio-curve > summary').click();
  await q.s.page.getByRole('button',{name:'加载 / 刷新组合曲线',exact:true}).click();
  await q.s.page.getByText('暂无组合区间记录',{exact:true}).waitFor();
  assert.equal(await q.s.page.getByRole('link',{name:'导出全部已记录组合曲线',exact:true}).count(),0);
  await q.record('portfolio-empty-scope',{reason:'Single-market fixture has no multi-market portfolio interval export link.'});
  await q.s.page.locator('[data-replay-action="close-integrity"]').click();
  await q.s.page.getByRole('button',{name:'图 2 布局操作',exact:true}).click();
  await q.s.page.getByRole('button',{name:'关闭此图表',exact:true}).click();
  await q.until(async()=> (await manager()).activeSequences===1);
  await facts('closed-one-chart',1);
  await q.s.page.getByRole('button',{name:'存档大厅',exact:true}).click();
  await q.s.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();
  const released=await q.until(async()=>{const m=await manager();return m.activeSequences===0&&m.streams===0&&m.requests===0&&m.operations.every(o=>o.identity.runId==='hub')?m:false;});
  await q.record('run-resources-released',{runId,manager:released});
  assert.deepEqual(q.s.receipt.errors,[]);
  const startedExit=Date.now();await q.record('full-exit',{owned:await q.quit(),allExited:await q.exited(),elapsedMs:Date.now()-startedExit});
  q.s.receipt.passed=true;await q.save();console.log('NATIVE LIFECYCLE PASS');
}catch(error){
  console.error(error);q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();
  try{await fs.writeFile(q.s.root+'/lifecycle-failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('lifecycle-failure');}catch{}
  try{await q.quit();await q.exited();}catch{}process.exitCode=1;
}
