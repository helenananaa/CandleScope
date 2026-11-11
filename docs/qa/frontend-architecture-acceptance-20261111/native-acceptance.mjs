import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import path from 'node:path';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';

const durationMs=Number(process.env.CS_ACCEPTANCE_SOAK_MS??1_800_000);
assert.ok(durationMs>=1_800_000,'The acceptance soak must last at least 30 minutes');
q.s.receipt={schema:'candlescope.frontend-architecture-native/1',sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  platform:'macOS arm64',transport:'relocated current-source signed package, bundled backend/plugins, real public Binance and OKX',steps:[],errors:[],cold:[],warm:[],soak:[]};
q.s.env.PYTHONDONTWRITEBYTECODE='1';
let running=false;
const series=(symbol,interval='1m',exchange='binance')=>({exchange,marketType:'spot',symbol,interval});
const summary=chart=>({cellId:chart.cellId,symbol:chart.symbol,interval:chart.interval,bars:chart.bars.length,
  first:chart.bars[0]?.time,last:chart.bars.at(-1)?.time,closedLast:chart.bars.filter(b=>b.is_closed).at(-1)?.time,
  lines:chart.lines.map(line=>({id:line.id,points:line.data.length,first:line.data[0],last:line.data.at(-1)}))});
async function command(groupId,command,args={}){
 const groups=await q.s.control.call('app.commands',{windowId:'main-window'});
 const group=(groups.groups??groups).find(x=>x.id===groupId);assert.ok(group,'Missing command group '+groupId);
 const requestId='architecture-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId,command,args,requestId,expectedContext:group.contextToken});
 const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;},60_000);
 assert.equal(result.state,'applied',JSON.stringify(result));return result;
}
async function health(input){
 return q.s.page.evaluate(input=>{
  const el=document.querySelector('[data-chart-cell-id]');if(!el)return null;
  let root=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(root.return)root=root.return;
  let found;
  function visit(n){if(!n||found)return;const v=n.memoizedProps?.value;
   if(v?.dataManager?.cache&&v.indicatorDataManager)found=v;
   visit(n.child);visit(n.sibling);}
  visit(root.stateNode.current);if(!found)return null;
  const plan=found.dataManager.cache.planHistory(input,500);
  return {action:plan.action,health:plan.health,count:plan.snapshot.rows.length,version:plan.snapshot.version,
    diagnostics:found.dataManager.diagnostics(),indicators:found.indicatorDataManager.diagnostics()};
 },input);
}
async function readyFor(input,count=2,timeout=180_000){
 let last;
 return q.until(async()=>{
  last=await q.inspect();
  return last.cells.length===count&&last.cells[0].session.symbol===input.symbol&&last.cells[0].session.interval===input.interval
   &&last.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=500)&&last.persistence.state==='saved'?last:false;
 },timeout).catch(error=>{throw new Error(error.message+' '+JSON.stringify(last));});
}
async function begin(){
 const launch=await q.launch();running=true;
 assert.equal(q.s.identity.packaged,true);
 await q.record('launch',launch);
 const visible=await q.until(async()=>{try{const charts=await capture(q);return charts.length&&charts.every(c=>c.bars.length>=1)?charts.map(summary):false;}catch{return false;}},180_000);
 const visibleMs=Date.now()-q.s.startedAt;
 await q.enableControl();
 return {visibleMs,visible};
}
async function end(){
 const before=await q.inspect();assert.equal(before.persistence.state,'saved');
 const processes=await q.quit();await q.exited();running=false;
 await q.record('full-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes});
}
async function state(name,raw=false){
 const charts=await capture(q),workspace=await q.inspect(),broker=await q.broker();
 const metrics=await q.s.app.evaluate(({app})=>app.getAppMetrics());
 const heap=await q.s.page.evaluate(()=>({memory:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize,limit:performance.memory.jsHeapSizeLimit}:null,
  frames:document.querySelectorAll('iframe').length,observations:window.__architectureObservations??null,perf:window.__CANDLESCOPE_PERF__?.report()}));
 const rows=cp.execFileSync('ps',['-axo','pid=,ppid=,rss=,%cpu=,args='],{encoding:'utf8'}).trim().split('\n').map(line=>{const m=line.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(.*)$/);return m&&{pid:+m[1],ppid:+m[2],rssKb:+m[3],cpuPct:+m[4],args:m[5]};}).filter(Boolean);
 const pids=new Set([q.s.identity.pid]);for(let i=0;i<12;i++)for(const row of rows)if(pids.has(row.ppid))pids.add(row.pid);
 const processes=rows.filter(row=>pids.has(row.pid));
 const cache=broker?.marketDataManager?.cache;
 if(cache){assert.ok(cache.series<=cache.maxSeries);assert.ok(cache.bars<=cache.maxBars);assert.equal(cache.listenerErrors,0);}
 assert.ok((broker?.dataFlow?.indicators?.inputs?.subscriptions??0)<=workspace.cells.length,'closed charts retained JS input subscriptions');
 const evidence={workspace,broker,metrics,heap,processes,sumRssKb:processes.reduce((sum,p)=>sum+p.rssKb,0),charts:charts.map(summary)};
 if(raw){const filename=name+'.bars.json';await fs.writeFile(path.join(q.s.root,filename),JSON.stringify(charts));evidence.raw=filename;}
 await q.record(name,evidence);return evidence;
}
async function values(name){
 let failure;
 return q.until(async()=>{try{
  const charts=await capture(q),result=[];
  for(const chart of charts){
   const bars=chart.bars.filter(b=>b.is_closed),points=[];
   assert.ok(bars.length>=499);
   const view=(await q.query(chart.cellId)).snapshot.visibleRange;
   const range=view?.time??view;
   const visible=bars.filter(b=>Number(b.time)>=Number(range?.from??bars.at(-80).time)&&Number(b.time)<=Number(range?.to??bars.at(-1).time));
   assert.ok(visible.length>=20,'numerical oracle requires a visible chart range');
   for(const line of chart.lines){
    const values=new Map(line.data.map(p=>[Number(p.time),p.value]));assert.equal(values.size,line.data.length);
    let checked=0;
    for(let i=19;i<bars.length;i++){
     const actual=values.get(bars[i].time);
     const required=visible.some(b=>b.time===bars[i].time)&&(line.id!=='qa-python'||i>=bars.length-450);
     if(required)assert.notEqual(actual,undefined,`${name} ${line.id} missing visible ${bars[i].time}`);
     if(actual===undefined)continue;
     const expected=line.id==='qa-ma'?bars.slice(i-19,i+1).reduce((sum,b)=>sum+b.close,0)/20
      :bars[i].close*(line.id==='qa-pine'?3:line.id==='qa-python'?4:2);
     assert.ok(Math.abs(actual-expected)<=Math.max(1e-7,Math.abs(expected)*1e-10),`${name} ${line.id} ${bars[i].time} ${actual} != ${expected}`);checked++;
    }
    assert.ok(checked>=20,`${line.id} has insufficient comparable points`);points.push({id:line.id,checked});
   }
   assert.ok(chart.lines.length>=4,`${name} ${chart.cellId} lacks four runtime outputs: ${chart.lines.map(x=>x.id)}`);
   result.push({cellId:chart.cellId,points});
  }
  return result;
 }catch(error){failure=String(error);return false;}},180_000).catch(error=>{throw new Error(error.message+'; '+failure);});
}
const indicators=[
 {id:'qa-ma',name:'QA MA',engineName:'MA',kind:'builtin',params:{period:20},visible:true},
 {id:'qa-js',name:'QA JS',language:'frontend-js',script:'plot("JS close x2",bars.map(b=>b.close*2),{pane:"main",color:"#ffaa00"});',params:{},visible:true},
 {id:'qa-pine',name:'QA Pine',language:'pine',script:'//@version=6\nindicator("QA Pine",overlay=true)\nplot(close*3,title="Pine close x3")',params:{},visible:true},
 {id:'qa-python',name:'QA Python',language:'python',script:"INDICATOR={'name':'QA Python','overlay':True,'window':500}\ndef compute(bars, params):\n return {'lines':{'main':[v*4 for v in bars['close']]}}\n",params:{},visible:true},
];
try{
 await fs.mkdir(q.s.root,{recursive:true});
 // Same profile and machine; every restart recreates the frontend pool.
 // Persistent backend history is intentionally retained and separately named.
 for(let index=0;index<10;index++){
  const visible=await begin();
  const snap=await q.ready(1,180_000),input=snap.cells[0].session;
  const tail=await q.until(async()=>{const h=await health(input);return h?.action==='reuse'?h:false;},180_000);
  q.s.receipt.cold.push({index,scope:'cold frontend pool / persistent backend history',input,...visible,tailReadyMs:Date.now()-q.s.startedAt,tail,
    http:q.s.traffic.requests.filter(r=>r.at>=q.s.startedAt).length});await q.save();
  const next=[series('BTCUSDT'),series('ETHUSDT'),series('BTCUSDT','5m'),series('ETHUSDT','5m')][(index+1)%4];
  await q.execute(snap.cells[0].cellId,'session',next);await q.ready(1,180_000);await end();
 }
 await begin();
 let configured=await q.configure([{session:series('BTCUSDT'),indicators:[]},{session:series('BTCUSDT'),indicators:[]}],'split-vertical');
 assert.equal(configured.result.state,'ready');await q.ready(2,180_000);
 await command('workspace','setLinkGroup',{cellIds:['cell-1','cell-2'],groupId:null});
 await state('initial-shared-two-chart',true);
 // A public full-tier consumer keeps ETH current while the sibling retains BTC.
 await command('watchlist','setTier',{symbolKey:'spot:ETHUSDT',tier:'full'});
 await q.until(async()=>{const h=await health(series('ETHUSDT'));return h?.action==='reuse'?h:false;},180_000);
 for(let index=0;index<10;index++){
  const input=series(index%2?'BTCUSDT':'ETHUSDT');
  const before=await health(input),requests=q.s.traffic.requests.length,sockets=q.s.traffic.sockets.length,at=Date.now();assert.equal(before.action,'reuse');
  const sibling=await q.query('cell-2');
  await q.execute('cell-1','session',input);await readyFor(input);
  const elapsedMs=Date.now()-at,after=await health(input);
  const traffic=q.s.traffic.requests.slice(requests);
  const targetReads=traffic.filter(r=>{const u=new URL(r.url);return u.pathname.includes('/klines/')&&u.searchParams.get('symbol')===input.symbol&&u.searchParams.get('interval')===input.interval;});
  const newMarketSockets=q.s.traffic.sockets.slice(sockets).filter(r=>r.url.includes('/stream/klines'));
  assert.equal(targetReads.length,0,'healthy target switch repeated its history/latest request');
  assert.equal(newMarketSockets.length,0,'healthy target switch opened another physical market socket');
  const bars=await capture(q);assert.equal(bars.find(c=>c.cellId==='cell-2').symbol,'BTCUSDT');
  q.s.receipt.warm.push({index,input,elapsedMs,before,after,requests:traffic,targetReads,newMarketSockets,sibling});await q.save();
 }
 await command('watchlist','setTier',{symbolKey:'spot:ETHUSDT',tier:'none'});
 await q.execute('cell-1','session',series('BTCUSDT'));await readyFor(series('BTCUSDT'));
 // The actual chart pagination action must preserve the other navigation owner.
 const siblingBefore=await capture(q);const siblingFirst=siblingBefore.find(c=>c.cellId==='cell-2').bars[0].time;
 let trimmed=false;
 for(let index=0;index<24;index++){
  const left=(await capture(q)).find(c=>c.cellId==='cell-1');if(trimmed)break;
  const old=left.bars[0].time;
  await q.execute('cell-1','loadMoreLeft',{});
  await q.until(async()=>{const c=(await capture(q)).find(c=>c.cellId==='cell-1');return c.bars[0].time<old?c:false;},120_000);
  if(left.bars.length>=10_000)trimmed=true;
 }
 assert.equal(trimmed,true,'deep navigation must exercise capacity trimming');
 const deep=await capture(q);assert.equal(deep.find(c=>c.cellId==='cell-1').bars.length,10_000);
 assert.equal(deep.find(c=>c.cellId==='cell-2').bars[0].time,siblingFirst);
 await state('deep-history-live-isolation',true);await q.screenshot('deep-history-live-isolation');
 await q.execute('cell-1','restoreLatestWindow',{});await readyFor(series('BTCUSDT'));
 await q.until(async()=>{const charts=await capture(q),a=charts.find(c=>c.cellId==='cell-1'),b=charts.find(c=>c.cellId==='cell-2');return a.bars.length<10_000&&a.bars.at(-1).time>=b.bars.at(-1).time-60;},120_000);await state('deep-history-back-to-live',true);
 for(const cell of ['cell-1','cell-2'])for(const indicator of indicators)await q.execute(cell,'addIndicator',indicator);
 const retired=await q.execute('cell-1','addIndicator',{id:'qa-retired',name:'Unsupported legacy fixture',language:'pyne',script:'legacy fixture'});
 assert.equal(retired.state,'failed');assert.ok(JSON.stringify(retired).includes('PYNE_RETIRED'));await q.record('retired-entry-rejected',retired);
 await q.indicatorsReady(2,180_000);await q.record('four-runtime-numerical-oracle',await values('initial'));await state('four-runtime-saved',true);await q.screenshot('four-runtime-saved');
 // Real renderer network disconnect, preserving bundled provider ownership.
 const session=await q.s.app.context().newCDPSession(q.s.page);
 await session.send('Network.enable');await session.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
 const prototype=await session.send('Runtime.evaluate',{expression:'WebSocket.prototype'});
 const sockets=await session.send('Runtime.queryObjects',{prototypeObjectId:prototype.result.objectId});
 const closed=await session.send('Runtime.callFunctionOn',{objectId:sockets.objects.objectId,functionDeclaration:`function(){const closed=[];for(const socket of this){if(socket.url.includes('/api/v1/stream/')&&socket.readyState<2){closed.push(socket.url);socket.close(4000,'QA controlled renderer disconnect');}}return closed;}`,returnByValue:true});
 await q.record('renderer-disconnect',{closed:closed.result.value});
 await session.send('Runtime.releaseObject',{objectId:sockets.objects.objectId});
 await session.send('Runtime.releaseObject',{objectId:prototype.result.objectId});
 await q.s.app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].minimize());
 await q.delay(75_000);
 const offline=await state('offline-minimized');
 assert.equal(offline.broker.scheduler?.windowVisible,false,'Native minimize was not observed');
 assert.equal(offline.broker.scheduler?.runnableFrames,0,'Hidden rendering kept runnable frames');
 assert.notEqual((await health(series('BTCUSDT'))).action,'reuse','Disconnected source was still reported healthy');
 await session.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 await q.s.app.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows()[0];window.restore();window.show();});
 await q.ready(2,180_000);await q.indicatorsReady(2,180_000);await q.record('four-runtime-reconnect-oracle',await values('reconnect'));await state('reconnect-restored',true);
 await q.s.page.evaluate(()=>{
  const observations={counts:{},longtasks:[],maxLongTask:0};window.__architectureObservations=observations;
  const observer=new PerformanceObserver(list=>{for(const entry of list.getEntries()){if(entry.entryType==='mark')observations.counts[entry.name]=(observations.counts[entry.name]??0)+1;else{observations.maxLongTask=Math.max(observations.maxLongTask,entry.duration);if(observations.longtasks.length<2048)observations.longtasks.push(entry.duration);}}});
  observer.observe({entryTypes:['mark','longtask']});window.__architectureObserver=observer;
 });
 // This run's duration is measured on the actual app, without compressing time.
 const started=Date.now();let nextCycle=0;
 while(Date.now()-started<durationMs){
  const elapsedMs=Date.now()-started;
  if(nextCycle<10&&elapsedMs>=nextCycle*(durationMs/10)){
   const cells=(await q.inspect()).cells;
   await q.execute(cells[0].cellId,'interval',{interval:nextCycle%2?'1m':'5m'});await q.ready(2,180_000);
   await command('workspace','closeCell',{cellId:cells[0].cellId});await q.ready(1,180_000);
   await command('workspace','splitCell',{cellId:cells[1].cellId,direction:'columns',creationMode:'copy'});await q.ready(2,180_000);
   await q.indicatorsReady(2,180_000);await q.record('soak-cycle-oracle-'+nextCycle,await values('soak-cycle-'+nextCycle));
   nextCycle++;
  }
  const sample=await state('soak-'+q.s.receipt.soak.length);
  q.s.receipt.soak.push({elapsedMs:Date.now()-started,cycle:nextCycle,broker:sample.broker,metrics:sample.metrics,heap:sample.heap,sumRssKb:sample.sumRssKb,processes:sample.processes});await q.save();
  await q.delay(Math.min(30_000,Math.max(1,durationMs-(Date.now()-started))));
 }
 assert.ok(Date.now()-started>=durationMs);assert.equal(nextCycle,10);
 await q.record('soak-completed',{durationMs:Date.now()-started,cycles:nextCycle});
 const saved=await q.inspect();assert.equal(saved.persistence.state,'saved');await end();
 await begin();await q.ready(2,180_000);await q.indicatorsReady(2,180_000);await q.record('saved-exit-restart-oracle',await values('restart'));await state('restart-restored',true);await q.screenshot('restart-restored');
 // Second supported source has its own receipt, no claimed Cartesian coverage.
 const okx=series('BTC-USDT','1m','okx');
 await q.execute((await q.inspect()).cells[0].cellId,'session',okx);await q.ready(2,180_000);await q.indicatorsReady(2,180_000);
 await q.record('okx-four-runtime-oracle',await values('okx'));await state('okx-source',true);await q.screenshot('okx-source');
 await end();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});}
finally{if(running)try{await end();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure,steps:q.s.receipt.steps.length}));}
