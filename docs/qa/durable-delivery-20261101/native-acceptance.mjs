import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';

q.s.receipt.schema='candlescope.durable-delivery-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope={issue:121,platform:'macOS arm64',provider:'Binance public',
 controlled:'64 committed-publication recovery receipts based on already stored real candles; no canonical writes',
 notCovered:['Windows native','power loss','all-writer fairness','full issue121','full157 release acceptance']};
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);if(!r.ok)throw new Error(r.status+' '+await r.text());return r.json();},q.s.backend+path);
const diag=async()=>(await api('/api/v1/settings/cache-diagnostics')).data_manager.bar_delivery;
const indicators=()=>api('/api/v1/indicators/diagnostics');
let running=false;
async function verify(){
 let failure;
 return q.until(async()=>{try{
  assert.deepEqual(q.s.receipt.errors,[]);const charts=await capture(q);assert.equal(charts.length,2);const evidence=[];
  for(const chart of charts){
   const bars=chart.bars.filter(b=>b.is_closed);assert.ok(bars.length>=499);assert.equal(chart.lines.length,1);
   const points=new Map(chart.lines[0].data.map(p=>[Number(p.time),p.value]));assert.equal(points.size,chart.lines[0].data.length);
   let checked=0,maxError=0;
   for(let i=19;i<bars.length;i++){
    const expected=bars.slice(i-19,i+1).reduce((n,b)=>n+b.close,0)/20,actual=points.get(bars[i].time);
    assert.ok(actual!==undefined);const error=Math.abs(actual-expected);assert.ok(error<1e-7,`${chart.cellId}: ${actual} != ${expected}`);maxError=Math.max(maxError,error);checked++;
   }
   evidence.push({cellId:chart.cellId,id:chart.lines[0].id,checked,maxError,last:bars.at(-1).time});
  }return evidence;
 }catch(error){failure=String(error);return false;}},90000).catch(error=>{throw new Error(error.message+'; '+failure);});
}
async function fixture(operation){
 const python=q.s.identity.resources+'/python-runtime/python/bin/python3';
 const result=await new Promise((resolve,reject)=>cp.execFile(python,['docs/qa/durable-delivery-20261101/native-receipts.py',q.s.root,operation],
  {env:{...q.s.env,PYTHONPATH:q.s.identity.resources+'/backend:'+q.s.identity.resources+'/python-runtime/site-packages',CANDLE_DATA_DIR:q.s.root+'/profile/data'},timeout:30000},
  (error,stdout,stderr)=>error?reject(new Error(String(error)+' '+stderr)):resolve(JSON.parse(stdout))));
 return result;
}
async function launch(){try{await q.record('packaged-launch',await q.launch());running=true;await q.enableControl();}catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
try{
 await launch();
 assert.equal((await q.configure(['BTCUSDT','ETHUSDT'].map(symbol=>({session:q.session(symbol),indicators:[]})),'split-vertical')).result.state,'ready');
 await q.ready(2,180000);
 for(const [cell,id] of [['cell-1','ack-ma-btc'],['cell-2','ack-ma-eth']])assert.equal((await q.execute(cell,'addIndicator',{id,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period:20},visible:true})).state,'applied');
 await q.indicatorsReady(2,90000);await q.record('real-provider-hosted-values',await verify());
 const first=await indicators();const closed=Math.min(...first.engine.instances.filter(i=>i.refcount>0).map(i=>i.last_committed));
 await q.until(async()=>{const d=await indicators();return d.engine.instances.filter(i=>i.refcount>0).every(i=>i.last_committed>closed)?d:false;},90000);
 await q.record('real-provider-new-close',{values:await verify(),delivery:await diag()});
 const before=await diag();assert.equal(before.acknowledgement_batch_size,16);assert.equal(before.degraded,false);
 const inserted=await fixture('insert');await q.record('controlled-receipt-insertion',inserted);
 const recovered=await q.until(async()=>{const state=await fixture('check');return state.passed?state:false;},60000);
 const after=await diag();assert.equal(after.degraded,false);assert.ok(after.acknowledgement_records-before.acknowledgement_records>=64);
 assert.ok(after.acknowledgement_batches-before.acknowledgement_batches<after.acknowledgement_records-before.acknowledgement_records);
 await q.record('native-batch-recovery',{before,after,recovered,values:await verify()});
 await q.ready(2,60000);await q.record('saved-workspace',await q.inspect());await q.screenshot('saved-durable-delivery');await quit();
 await launch();await q.ready(2,180000);await q.indicatorsReady(2,90000);
 const restarted=await diag();assert.equal(restarted.acknowledgement_batch_size,16);assert.equal(restarted.degraded,false);
 const persisted=await fixture('check');assert.equal(persisted.passed,true);
 await q.record('restart-restores-values-and-published-receipts',{delivery:restarted,persisted,values:await verify(),workspace:await q.inspect()});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
