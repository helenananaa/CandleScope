import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {assertPublicGate} from './public-gate.mjs';

await assertPublicGate(q.s.root);
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,e=>{if(e.code==='ENOENT')return false;throw e;}),false,'Preserve previous profiles');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.schema='candlescope.gate-indicator-native/1';
q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.driverCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope='Actual packaged macOS arm64 LIVE Gate spot1s/1m indicator UI, recomputation, new closes, viewport/resize and saved restart; real public HTTP/WS, no substituted responses. Binance spot1s is the independent sibling. Not Windows/full release qualification.';
const sessions=[q.session('BTCUSDT','1s'),{exchange:'gate',marketType:'spot',symbol:'BTC/USDT',interval:'1s'}];
const definitions=[{id:'sibling-ma5',period:5},{id:'gate-ma',period:5}];
const indicator=(id,period)=>({id,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period},visible:true});
const api=path=>q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+path);
let checkedCircuit=0,running=false;
async function circuit(){
 if(Date.now()-checkedCircuit<2000)return;checkedCircuit=Date.now();
 const health=await api('/api/v1/settings/storage/health');
 function find(value){if(!value||typeof value!=='object')return null;const c=value.global_circuit;
  if(c?.open&&c.last_status_code===418&&c.cooldown_remaining_seconds>0)return c;
  for(const child of Object.values(value)){const c=find(child);if(c)return c;}return null;}
 const value=find(health.body);if(!value)return;
 const deadline=Math.max(Date.now()+Math.ceil(value.cooldown_remaining_seconds*1000),value.opened_at_ms+Number(value.last_headers?.['retry-after']||0)*1000)+1000;
 const evidence={circuit:value,retry_not_before_ms:deadline,retry_not_before_utc:new Date(deadline).toISOString(),source:q.s.root+'/new-cooldown.json'};
 await fs.writeFile(evidence.source,JSON.stringify(evidence,null,2));
 for(const filename of ['/Users/ryanliang/CandleScope/output/backend-goal-20261102/STATE.json','/Users/ryanliang/CandleScope/output/development-goal-20261104/state.json']){
  const state=JSON.parse(await fs.readFile(filename,'utf8'));
  if((state.public_cooldown?.retry_not_before_ms??0)<deadline){state.public_cooldown=evidence;await fs.writeFile(filename,JSON.stringify(state,null,2)+'\n');}
 }
 q.s.receipt.publicCooldown=evidence;await q.record('public-circuit-stop',evidence);throw Error('PUBLIC_COOLDOWN_STOP '+evidence.retry_not_before_utc);
}
async function ready(expected=2){return q.until(async()=>{
 await circuit();const state=await q.inspect();await fs.writeFile(q.s.root+'/latest-workspace.json',JSON.stringify(state,null,2));
 for(const cell of state.cells)assert.ok(!cell.runtime.error?.includes('native_bar_basis_unknown'),cell.runtime.error);
 return state.cells.length===2&&state.persistence.state==='saved'&&state.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=30
  &&c.runtime.indicatorsReady&&!c.runtime.computing&&!c.runtime.indicatorErrors?.length&&c.runtime.indicatorOutputPoints?.length>0
  &&c.runtime.indicatorOutputPoints.every(n=>n>0))&&(await q.query('cell-2')).snapshot.indicators.length===expected?state:false;
 },180000);}
async function values(periods){
 const start=Date.now();let last;
 return q.until(async()=>{
  await circuit();const charts=await capture(q);assert.equal(charts.length,2);
  const result=[],errors=[];
  for(const chart of charts){
   const snapshot=(await q.query(chart.cellId)).snapshot,view=snapshot.visibleRange?.time;
   assert.ok(view);const bars=chart.bars.filter(b=>b.is_closed),wanted=periods[chart.cellId];
   assert.equal(chart.lines.length,Object.keys(wanted).length);
   for(const line of chart.lines){const period=wanted[line.id];assert.ok(period,'Unexpected rendered indicator '+line.id);
    const points=new Map(line.data.map(p=>[Number(p.time),p.value]));let checked=0,maxError=0;
    for(let i=period-1;i<bars.length;i++){
     const bar=bars[i];if(bar.time<view.from||bar.time>view.to)continue;
     const expected=bars.slice(i-period+1,i+1).reduce((sum,b)=>sum+b.close,0)/period,actual=points.get(bar.time);
     const error=actual===undefined?Infinity:Math.abs(actual-expected);
     if(error>=Math.max(1e-7,Math.abs(expected)*1e-10))errors.push({cellId:chart.cellId,id:line.id,period,time:bar.time,expected,actual});
     maxError=Math.max(maxError,error);checked++;
    }
    if(checked<3)errors.push({cellId:chart.cellId,id:line.id,checked});
    result.push({cellId:chart.cellId,id:line.id,period,checked,maxError,interval:chart.interval,visible:view,lastClosed:bars.at(-1)?.time});
   }
  }
  last={at:new Date().toISOString(),elapsedMs:Date.now()-start,errors,result};
  await fs.appendFile(q.s.root+'/value-comparisons.ndjson',JSON.stringify(last)+'\n');
  assert.ok(Date.now()-start<90000,JSON.stringify(last));return errors.length?false:result;
 },95000);
}
async function canonical(){
 const result=[];
 for(let i=0;i<2;i++){
  const id='cell-'+(i+1),session={...sessions[i],interval:(await q.query(id)).snapshot.session.interval};
  const seed=(await capture(q)).find(c=>c.cellId===id),sample=seed.bars.filter(b=>b.is_closed).slice(-60);
  assert.ok(sample.length>=30);const first=sample[0].time,last=sample.at(-1).time;
  const params=new URLSearchParams({exchange:session.exchange,market_type:session.marketType,symbol:session.symbol,interval:session.interval,
   start_ms:String(first*1000),end_ms:String(last*1000),repair:'none',wait_ms:'0',strict:'false'});
  const start=Date.now();await q.until(async()=>{
   await circuit();const response=await api('/api/v1/klines/range?'+params);
   assert.equal(response.status,200);if(!response.body.complete)return false;
   assert.equal(response.body.all_rows_final,true);
   const chart=(await capture(q)).find(c=>c.cellId===id),bars=chart.bars.filter(b=>b.is_closed&&b.time>=first&&b.time<=last);
   const rows=response.body.data.filter(b=>b.time>=first&&b.time<=last),lookup=new Map(rows.map(b=>[b.time,b]));
   const differences=[];if(bars.length!==rows.length)differences.push({field:'count',renderer:bars.length,canonical:rows.length});
   for(const bar of bars)for(const field of ['open','high','low','close','volume'])if(bar[field]!==lookup.get(bar.time)?.[field])differences.push({time:bar.time,field,renderer:bar[field],canonical:lookup.get(bar.time)?.[field]});
   const evidence={id,session,first,last,checked:bars.length,elapsedMs:Date.now()-start,differences};
   await fs.appendFile(q.s.root+'/canonical-comparisons.ndjson',JSON.stringify(evidence)+'\n');
   if(differences.length)return false;assert.ok(bars.length>=30);result.push(evidence);return true;
  },90000);
 }
 return result;
}
function verifyPackage(){cp.execFileSync('node',['docs/qa/seconds-contracts-20261102/verify.mjs'],{env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root},stdio:'inherit'});}
async function launch(){await assertPublicGate(q.s.root);try{await q.record('packaged-launch',await q.launch());running=true;await q.enableControl();}
 catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}}
async function quit(){await q.quit();assert.equal(await q.exited(),true);running=false;
 await q.record('full-owned-exit',{allExited:true,ms:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});verifyPackage();}
const expected={'cell-1':{'sibling-ma5':5},'cell-2':{'gate-ma':7,'gate-new-ma11':11}};
try{
 verifyPackage();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');await launch();
 const configured=await q.configure(sessions.map((session,i)=>({session:i? q.session('BTCUSDT','1s'):session,indicators:[]})),'split-vertical');
 await q.record('workspace-layout-configured',configured);assert.ok(['applied','ready'].includes(configured.result.state),JSON.stringify(configured.result));
 assert.equal((await q.execute('cell-2','session',sessions[1])).state,'applied');
 for(let i=0;i<2;i++)assert.equal((await q.execute('cell-'+(i+1),'addIndicator',indicator(definitions[i].id,5))).state,'applied');
 await ready(1);await q.record('baseline-values',await values({'cell-1':{'sibling-ma5':5},'cell-2':{'gate-ma':5}}));
 // Focus the actual Gate chart, then edit its existing MA through the real drawer.
 await q.s.page.locator('[data-chart-cell-id="cell-2"]').click({position:{x:100,y:160}});
 assert.equal((await q.inspect()).activeCellId,'cell-2');
 await q.s.page.getByRole('button',{name:/^指标 \d+$/}).click();
 await q.s.page.getByRole('button',{name:'已添加 (1)',exact:true}).click();
 const parameter=q.s.page.locator('.indicator-active-item .indicator-param-input').first();
 await parameter.fill('7');await parameter.press('Enter');
 await q.until(async()=>{const s=(await q.query('cell-2')).snapshot;return s.indicators.find(x=>x.id==='gate-ma')?.params?.period===7?s:false;});
 await q.s.page.getByRole('button',{name:'重新计算全部',exact:true}).click();
 await q.s.page.getByRole('button',{name:'关闭指标侧栏',exact:true}).click();
 await ready(1);await q.record('actual-ui-param-and-recompute',await values({'cell-1':{'sibling-ma5':5},'cell-2':{'gate-ma':7}}));
 assert.equal((await q.execute('cell-2','addIndicator',indicator('gate-new-ma11',11))).state,'applied');await ready();
 await q.record('new-indicator-values',await values(expected));await q.record('canonical-after-ui',await canonical());
 const before=(await capture(q)).find(c=>c.cellId==='cell-2').bars.filter(b=>b.is_closed).at(-1).time;
 await q.until(async()=>{await circuit();return (await capture(q)).find(c=>c.cellId==='cell-2').bars.filter(b=>b.is_closed).at(-1).time>before;},90000);
 await ready();await q.record('later-close-values',await values(expected));
 const bars=(await capture(q)).find(c=>c.cellId==='cell-2').bars.filter(b=>b.is_closed);
 assert.equal((await q.execute('cell-2','visibleTimeRange',{from:bars.at(-45).time,to:bars.at(-5).time})).state,'applied');
 await ready();await q.record('navigated-visible-values',await values(expected));
 for(const [width,height] of [[1400,900],[1060,780]]){
  const bounds=await q.s.app.evaluate(({BrowserWindow},size)=>{const w=BrowserWindow.getAllWindows().find(w=>!w.isDestroyed());w.setContentSize(size.width,size.height);return w.getContentBounds();},{width,height});
  await ready();await q.record('resized-'+width,{bounds,values:await values(expected)});await q.screenshot('resized-'+width);
 }
 assert.equal((await q.execute('cell-2','interval',{interval:'1m'})).state,'applied');await ready();
 await q.record('gate-one-minute-values',await values(expected));
 assert.equal((await q.execute('cell-2','interval',{interval:'1s'})).state,'applied');await ready();
 await q.record('gate-returned-second-values',await values(expected));
 assert.equal((await q.execute('cell-2','refresh',{})).state,'applied');await ready();await q.record('refresh-values',await values(expected));
 await q.record('saved-interaction',{workspace:await q.inspect(),values:await values(expected),canonical:await canonical()});await q.screenshot('saved-interaction');await quit();
 await launch();await ready();
 for(const [cellId,ids] of Object.entries(expected)){
  const state=(await q.query(cellId)).snapshot;assert.equal(state.session.exchange,cellId==='cell-1'?'binance':'gate');assert.equal(state.session.interval,'1s');
  assert.deepEqual(Object.fromEntries(state.indicators.map(x=>[x.id,x.params.period])),ids);
 }
 await q.record('restored-interaction',{workspace:await q.inspect(),values:await values(expected),canonical:await canonical()});await q.screenshot('restored-interaction');await quit();
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(running){await q.record('failure-state',{workspace:await q.inspect().catch(e=>String(e)),charts:await capture(q).catch(e=>String(e)),health:await api('/api/v1/settings/storage/health').catch(e=>String(e))}).catch(()=>{});
  await q.screenshot('failure').catch(()=>{});await fs.writeFile(q.s.root+'/failure-ui.txt',await q.s.page.locator('body').ariaSnapshot().catch(()=>''));}}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure,exitFailure:q.s.receipt.exitFailure}));}
