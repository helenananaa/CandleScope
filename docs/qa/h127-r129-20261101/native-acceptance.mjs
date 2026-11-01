import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';

// Choose a real UTC bucket with enough already elapsed1m slots to exercise
// the measured default admission, while leaving time for save/restart.
const minute=Math.floor(Date.now()/60000);
// Nonmultiples of2/3/5 retain the native1m route; this width also leaves
// several target bars under the unchanged20k source-row viewport budget.
const width=Array.from({length:400},(_,i)=>2201+i*2).find(n=>n%3&&n%5&&minute%n>=2112&&n-minute%n>=60);
assert.ok(width,'No qualified native acceptance bucket in this clock window');
const interval=width+'m';
q.s.receipt.schema='candlescope.h127-r129-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope={platform:'macOS arm64',provider:'Binance public',interval,
 source:'canonical native1m',minimumPrefixSlots:2048,admission:'Existing20000source-row UI budget remains; long chart has a finite small number of target bars',
 notCovered:['Windows native','all129/127 scope','all157 release acceptance','native destructive source faults','all-source mixed history']};
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);if(!r.ok)throw new Error(r.status+' '+await r.text());return r.json();},q.s.backend+path);
const diag=async()=>(await api('/api/v1/settings/cache-diagnostics')).data_manager;
const indicators=()=>api('/api/v1/indicators/diagnostics');
let running=false;
async function ready(withIndicators=false){
 return q.until(async()=>{const s=await q.inspect();return s.cells.length===2&&s.persistence.state==='saved'
  &&s.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=(c.cellId==='cell-1'?500:3)
    &&(!withIndicators||(c.runtime.indicatorsReady&&!c.runtime.computing&&!c.runtime.indicatorErrors?.length&&c.runtime.indicatorOutputPoints?.some(n=>n>0))))?s:false;},600000);
}
async function prefix(){
 return q.until(async()=>{const d=await diag(),p=d.history_prefix,l=p.last_adoption;return p.adoptions>0&&l?.interval===interval&&l.source==='BTCUSDT@1m'&&l.complete&&l.accepted_slots>=2048&&l.pages>=8?d:false;},300000);
}
async function verify(){
 let failure;
 return q.until(async()=>{try{
  assert.deepEqual(q.s.receipt.errors,[]);const charts=await capture(q);assert.equal(charts.length,2);const evidence=[];
  for(const chart of charts){
   const period=chart.interval==='1m'?20:3,bars=chart.bars.filter(b=>b.is_closed);
   assert.ok(bars.length>=(period===20?499:3));assert.equal(chart.lines.length,1);
   const points=new Map(chart.lines[0].data.map(p=>[Number(p.time),p.value]));assert.equal(points.size,chart.lines[0].data.length);
   let checked=0,maxError=0;
   for(let i=period-1;i<bars.length;i++){
    const expected=bars.slice(i-period+1,i+1).reduce((n,b)=>n+b.close,0)/period,actual=points.get(bars[i].time);
    assert.ok(actual!==undefined,`${chart.interval} missing ${bars[i].time}`);const error=Math.abs(actual-expected);assert.ok(error<1e-7);maxError=Math.max(maxError,error);checked++;
   }
   evidence.push({cellId:chart.cellId,interval:chart.interval,period,bars:chart.bars.length,closed:bars.length,checked,maxError,lastClosed:bars.at(-1).time});
  }return evidence;
 }catch(error){failure=String(error);return false;}},90000).catch(error=>{throw new Error(error.message+'; '+failure);});
}
async function launch(){try{await q.record('packaged-launch',await q.launch());running=true;await q.enableControl();}catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
try{
 await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT',interval),indicators:[]}],'split-vertical');
 assert.ok(['applied','ready'].includes(configured.result.state));await q.record('workspace-configured',configured);
 await ready();
 for(const [cell,id,period] of [['cell-1','prefix-ma-native',20],['cell-2','prefix-ma-derived',3]])assert.equal((await q.execute(cell,'addIndicator',{id,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period},visible:true})).state,'applied');
 await ready(true);const initial=await prefix();assert.equal(initial.bar_delivery.acknowledgement_batch_size,16);
 await q.record('qualified-multipage-prefix-and-live-values',{diagnostics:initial,values:await verify(),workspace:await q.inspect()});
 const before=(await indicators()).engine.instances.find(i=>i.refcount>0&&i.interval==='1m').last_committed;
 await q.until(async()=>{const d=await indicators();return d.engine.instances.some(i=>i.refcount>0&&i.interval==='1m'&&i.last_committed>before)?d:false;},120000);
 // The native indicator commit and derived-prefix refresh are independent
 // delivery consumers. Wait for both acknowledgements, without assuming an
 // ordering between them or accepting an old complete-prefix diagnostic.
 await q.until(async()=>{const d=await diag();return d.history_prefix.refreshes>0?d:false;},120000);
 const advanced=await prefix();assert.ok(advanced.history_prefix.refreshes>0);
 await q.record('new-native-close-with-prefix-refresh',{diagnostics:advanced,values:await verify()});
 await ready(true);await q.record('saved-workspace',await q.inspect());await q.screenshot('saved-prefix-handoff');await quit();
 await launch();await ready(true);
 await q.record('restart-restores-handoff-and-values',{diagnostics:await prefix(),values:await verify(),workspace:await q.inspect()});
 await quit();
 q.s.env.HISTORY_PREFIX_ENABLED='0';
 await launch();await ready(true);const rollback=await diag();assert.deepEqual(rollback.history_prefix,{enabled:false});
 await q.record('restart-rollback-preserves-values',{diagnostics:rollback,values:await verify(),workspace:await q.inspect()});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
