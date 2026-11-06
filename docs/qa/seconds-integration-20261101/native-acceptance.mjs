import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {assertPublicGate} from '../seconds-contracts-20261102/public-gate.mjs';
await assertPublicGate(q.s.root);
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve earlier native profiles; select a new isolated candidate root');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.schema='candlescope.seconds-native/1';
q.s.receipt.driverCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.transport='Packaged bundled backend, real public Binance/Gate/Upbit HTTP and WebSocket; no substituted responses.';
q.s.receipt.scope={platform:'macOS arm64',sources:['Binance spot1s','Binance custom7s','Gate spot1s','Upbit spot1s'],notCovered:['Windows','1s replay archives','ordinary USD-M1s','full157 release acceptance','all exchanges']};
const sessions=[q.session('BTCUSDT','1s'),q.session('BTCUSDT','7s'),{exchange:'gate',marketType:'spot',symbol:'BTC/USDT',interval:'1s'},{exchange:'upbit',marketType:'spot',symbol:'BTC/KRW',interval:'1s'}];
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+path);
let lastCircuitCheck=0,lastContinuityCheck=0;
async function checkCircuit(){
 if(Date.now()-lastCircuitCheck<2000)return;
 lastCircuitCheck=Date.now();
 const response=await api('/api/v1/settings/storage/health');
 function visit(value){
  if(!value||typeof value!=='object')return null;
  const circuit=value.global_circuit;
  if(circuit?.open&&circuit.last_status_code===418&&circuit.cooldown_remaining_seconds>0)return circuit;
  for(const child of Object.values(value)){const found=visit(child);if(found)return found;}
  return null;
 }
 const circuit=visit(response.body);
 if(Date.now()-lastContinuityCheck>=5000){
  lastContinuityCheck=Date.now();
  const snapshot=await api('/debug/snapshot');
  await fs.appendFile(q.s.root+'/source-continuity.ndjson',JSON.stringify({at:new Date().toISOString(),continuity:snapshot.body?.market_data_control?.source_continuity})+'\n');
 }
 if(circuit){
  const deadline=Math.max(Date.now()+Math.ceil(circuit.cooldown_remaining_seconds*1000),circuit.opened_at_ms+Number(circuit.last_headers?.['retry-after']||0)*1000)+1000;
  const evidence={circuit,retry_not_before_ms:deadline,retry_not_before_utc:new Date(deadline).toISOString()};
  q.s.receipt.publicCooldown=evidence;
  await fs.writeFile(q.s.root+'/new-cooldown.json',JSON.stringify(evidence,null,2));
  await q.record('public-ip-circuit-stop',evidence);
  throw new Error('PUBLIC_COOLDOWN_STOP: '+evidence.retry_not_before_utc);
 }
}
async function ready(indicators=false){return q.until(async()=>{await checkCircuit();const s=await q.inspect();await fs.writeFile(q.s.root+'/latest-workspace.next.json',JSON.stringify(s,null,2));await fs.rename(q.s.root+'/latest-workspace.next.json',q.s.root+'/latest-workspace.json');return s.cells.length===4&&s.persistence.state==='saved'&&s.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=10&&(!indicators||(c.runtime.indicatorsReady&&!c.runtime.computing&&!c.runtime.indicatorErrors?.length&&c.runtime.indicatorOutputPoints?.some(n=>n>0))))?s:(await q.delay(1000),false);},360000);}
async function range(session,first,last){const p=new URLSearchParams({exchange:session.exchange,market_type:session.marketType,symbol:session.symbol,interval:session.interval,start_ms:String(first*1000),end_ms:String(last*1000),repair:'none',wait_ms:'0',strict:'false'});const started=Date.now();let attempts=0;while(true){await checkCircuit();const r=await api('/api/v1/klines/range?'+p);attempts++;const clipped=r.body.complete&&Number.isFinite(r.body.effective_end_ms)&&r.body.effective_end_ms<last*1000;if(r.status!==200||(r.body.complete&&!clipped)||(!r.body.retryable&&!clipped)||Date.now()-started>=180000){q.s.receipt.rangeReads??=[];q.s.receipt.rangeReads.push({session,first,last,attempts,elapsedMs:Date.now()-started,status:r.status,historyState:r.body.history_state,effectiveEndMs:r.body.effective_end_ms,complete:r.body.complete,retryable:r.body.retryable,missingRanges:r.body.missing_ranges,cache:r.body.cache});return r;}await q.delay(200);}}
async function verify(){
 const initial=await capture(q);assert.equal(initial.length,4);const out=[];
 for(let i=0;i<4;i++){
  const cellId='cell-'+(i+1),seed=initial.find(c=>c.cellId===cellId);
  assert.ok(seed);const sample=seed.bars.filter(b=>b.is_closed).slice(-100);
  assert.ok(sample.length>=9,cellId);
  const first=sample[0].time,last=sample.at(-1).time,started=Date.now();let attempts=0;
  let response=await range(sessions[i],first,last);
  assert.equal(response.status,200);assert.equal(response.body.complete,true,JSON.stringify(response.body).slice(0,600));
  assert.equal(response.body.all_rows_final,true);
  while(true){
   await checkCircuit();attempts++;
   // History may be amended while range() waits. Compare a fresh renderer
   // view of this fixed interval, and require complete natural convergence.
   // These reads never schedule repairs or overwrite renderer state.
   const chart=(await capture(q)).find(c=>c.cellId===cellId);assert.ok(chart);
   const bars=chart.bars.filter(b=>b.is_closed&&b.time>=first&&b.time<=last);
   const canonical=response.body.data.filter(b=>b.time>=first&&b.time<=last);
   const rows=new Map(canonical.map(b=>[b.time,b]));
   const mismatches=[];
   if(bars.length!==canonical.length)mismatches.push({field:'count',renderer:bars.length,canonical:canonical.length});
   for(const bar of bars){const row=rows.get(bar.time);
    if(!row){mismatches.push({time:bar.time,field:'missing-canonical-row'});continue;}
    for(const field of ['open','high','low','close','volume'])if(bar[field]!==row[field])mismatches.push({time:bar.time,field,renderer:bar[field],canonical:row[field]});
    assert.equal(bar.time%(i===1?7:1),0);
   }
   const evidence={at:new Date().toISOString(),cellId,session:sessions[i],first,last,attempts,elapsedMs:Date.now()-started,mismatches};
   await fs.appendFile(q.s.root+'/canonical-comparisons.ndjson',JSON.stringify(evidence)+'\n');
   await fs.writeFile(q.s.root+'/canonical-last-'+cellId+'.json',JSON.stringify({...evidence,chart,response},null,2));
   if(!mismatches.length){
    assert.ok(bars.length>=9);
    out.push({session:sessions[i],cellId,bars:chart.bars.length,checked:bars.length,first,last,convergenceAttempts:attempts,quality:{complete:response.body.complete,all_rows_final:response.body.all_rows_final,history_state:response.body.history_state,excluded_ranges:response.body.excluded_ranges},rows:bars});break;
   }
   assert.ok(Date.now()-started<60000,JSON.stringify(evidence));
   await q.delay(500);response=await range(sessions[i],first,last);
   assert.equal(response.status,200);assert.equal(response.body.complete,true);assert.equal(response.body.all_rows_final,true);
  }
 }
 return out;
}
async function values(){
 const initial=await capture(q);assert.equal(initial.length,4);
 const targets=new Map();
 for(const chart of initial){const view=(await q.query(chart.cellId)).snapshot.visibleRange?.time;assert.ok(view);
  targets.set(chart.cellId,{...view,closedThrough:chart.bars.filter(b=>b.is_closed).at(-1)?.time});}
 const started=Date.now();let attempts=0;
 while(true){
  await checkCircuit();attempts++;const charts=await capture(q);assert.equal(charts.length,4,'Four render surfaces must stay mounted during indicator convergence');
  const out=[],mismatches=[];
  for(const chart of charts){
   const bars=chart.bars.filter(b=>b.is_closed),view=targets.get(chart.cellId);assert.ok(view);assert.equal(chart.lines.length,1);
   const points=new Map(chart.lines[0].data.map(p=>[Number(p.time),p.value]));let checked=0,maxError=0;
   for(let i=4;i<bars.length;i++){
    if(bars[i].time<view.from||bars[i].time>view.to||bars[i].time>view.closedThrough)continue;
    const actual=points.get(bars[i].time),expected=bars.slice(i-4,i+1).reduce((n,b)=>n+b.close,0)/5;
    if(actual===undefined){mismatches.push({cellId:chart.cellId,time:bars[i].time,kind:'missing-visible-MA5'});continue;}
    const error=Math.abs(actual-expected);
    if(error>=Math.max(1e-7,Math.abs(expected)*1e-10))mismatches.push({cellId:chart.cellId,time:bars[i].time,actual,expected});
    maxError=Math.max(maxError,error);checked++;
   }
   if(checked<3)mismatches.push({cellId:chart.cellId,kind:'too-few-checked-values',checked});
   out.push({cellId:chart.cellId,checked,maxError,target:view,attempts,elapsedMs:Date.now()-started});
  }
  await fs.appendFile(q.s.root+'/indicator-comparisons.ndjson',JSON.stringify({at:new Date().toISOString(),attempts,elapsedMs:Date.now()-started,mismatches})+'\n');
  if(!mismatches.length)return out;
  assert.ok(Date.now()-started<90000,JSON.stringify({attempts,mismatches}).slice(0,2500));
  await q.delay(500);
 }
}
let running=false;
function verifyPackage(){cp.execFileSync('node',['docs/qa/seconds-contracts-20261102/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
async function persistenceCheckpoint(name,quality){
 const expected=q.s.root+'/'+name+'-expected.json',output=q.s.root+'/'+name+'.json';
 await fs.writeFile(expected,JSON.stringify(quality));
 const python=manifest.app+'/Contents/Resources/python-runtime/python/bin/python3';
 const report=JSON.parse(cp.execFileSync(python,['-B','docs/qa/seconds-contracts-20261102/persistence_probe.py','--database',q.s.root+'/profile/data/candlescope.db','--quality',expected,'--output',output],{encoding:'utf8',maxBuffer:4*1024*1024}));
 await q.record(name,{...report,artifact:output});return report;
}
async function launch(){await assertPublicGate(q.s.root);try{await q.record('packaged-launch',await q.launch());running=true;
 await q.s.page.evaluate(()=>{Error.stackTraceLimit=50;});
 q.s.page.on('console',message=>{if(!['error','warning'].includes(message.type()))return;
  Promise.all(message.args().map(arg=>arg.evaluate(value=>value instanceof Error?{name:value.name,message:value.message,stack:value.stack}:value).catch(()=>null)))
   .then(args=>fs.appendFile(q.s.root+'/renderer-console.ndjson',JSON.stringify({at:new Date().toISOString(),type:message.type(),text:message.text(),args})+'\n')).catch(()=>{});
 });
 await q.enableControl();}catch(e){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw e;}}
async function quit(){await q.quit();assert.equal(await q.exited(),true);running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});verifyPackage();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));}
try{
 verifyPackage();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');
 await launch();
 for(const exchange of ['binance','gate','upbit']){
  const caps=await api('/api/v1/exchanges/'+exchange+'/capabilities');assert.equal(caps.status,200);
  const symbols=await q.until(async()=>{
   const result=await api('/api/v1/symbols/exchange-info?exchange='+exchange+'&market_type=spot&search=BTC');await checkCircuit();
   if(result.status===200)return result;
   await q.record('catalog-pending-'+exchange,result);
   assert.equal(result.status,503);assert.equal(result.body.detail?.retryable,true);
   await q.delay(3000);return false;
  },180000);
  for(const session of sessions.filter(s=>s.exchange===exchange))assert.ok(symbols.body.symbols.some(s=>s.symbol===session.symbol),'Catalog lacks '+session.symbol);
  await q.record('source-catalog-'+exchange,{caps,symbols});
 }
 // The bulk configuration control deliberately supports only Binance/OKX.
 // Use the registered chart-session command for other advertised providers.
 const configured=await q.configure(sessions.map((session,i)=>({session:i<2?session:q.session('BTCUSDT','1s'),indicators:[]})),'quad');
 await q.record('workspace-layout-configured',configured);assert.ok(['applied','ready'].includes(configured.result.state));
 for(const i of [2,3]){const changed=await q.execute('cell-'+(i+1),'session',sessions[i]);await q.record('source-session-selected-'+sessions[i].exchange,changed);assert.equal(changed.state,'applied');}
 await ready();
 await q.record('canonical-seconds-quality',await verify());
 for(let i=1;i<=4;i++)assert.equal((await q.execute('cell-'+i,'addIndicator',{id:'seconds-ma-'+i,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period:5},visible:true})).state,'applied');
 await ready(true);await q.record('visible-indicator-values',await values());const before=await verify();
 await q.until(async()=>{await checkCircuit();const charts=await capture(q);
  await fs.appendFile(q.s.root+'/new-closes.ndjson',JSON.stringify({at:new Date().toISOString(),cells:charts.map(c=>({cellId:c.cellId,lastClosed:c.bars.filter(b=>b.is_closed).at(-1)?.time,lines:c.lines.map(l=>({id:l.id,last:l.data.at(-1)}))}))})+'\n');
  assert.equal(charts.length,4,'All four chart render surfaces must remain mounted');
  return charts.every(c=>c.bars.filter(b=>b.is_closed).at(-1)?.time>before.find(x=>x.cellId===c.cellId).last)?true:false;},90000);
 const saved=await verify();await q.record('new-closes-and-saved-workspace',{quality:saved,values:await values(),workspace:await ready(true)});await q.screenshot('saved-seconds');await quit();
 const cold=await persistenceCheckpoint('cold-storage-before-restart',saved);assert.equal(cold.matchesSaved,true,JSON.stringify(cold.mismatches).slice(0,1500));
 await launch();await ready(true);const restored=await verify();await persistenceCheckpoint('storage-after-live-restart',saved);for(const item of saved){const r=await range(item.session,item.first,item.last);assert.equal(r.status,200);assert.equal(r.body.complete,true);const rows=new Map(r.body.data.map(b=>[b.time,b]));for(const b of item.rows)for(const key of ['open','high','low','close','volume'])assert.equal(rows.get(b.time)?.[key],b[key],JSON.stringify({session:item.session,time:b.time,field:key,before:b[key],after:rows.get(b.time)?.[key]}));}await q.record('restart-restores-persisted-seconds',{quality:restored,values:await values(),workspace:await q.inspect()});await q.screenshot('restored-seconds');await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running){
 await q.record('failure-renderer-charts',await capture(q).catch(e=>({error:String(e)})));
 await q.record('failure-workspace',await q.inspect().catch(e=>({error:String(e)})));
await q.screenshot('failure').catch(()=>{});for(const [name,path]of [['storage-health','/api/v1/settings/storage/health'],['support','/api/v1/support/diagnostics'],['runtime-snapshot','/debug/snapshot']])await q.record('failure-'+name,await api(path).catch(e=>({error:String(e)}))).catch(()=>{});}}
finally{if(running)try{await quit();}catch(e){q.s.receipt.exitFailure=String(e);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
