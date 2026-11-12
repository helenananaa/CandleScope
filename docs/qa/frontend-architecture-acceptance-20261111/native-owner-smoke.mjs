import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {captureRendered} from './rendered-probe.mjs';
import {captureOwners} from './owner-probe.mjs';
q.s.receipt={schema:'candlescope.initial-backfill-owner-native/1',sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),steps:[],errors:[],
 scope:'Targeted current installed-app ETH/BTC 1m restart and initial-backfill ownership regression; separate from the complete matrix'};
q.s.env.INGESTION_HTTP_TIMEOUT='120';q.s.receipt.configuration={ingestionHttpTimeoutSeconds:120};
let active=false,timer;const ownershipSamples=[];let lastOracleError;
try{
 await fs.mkdir(q.s.root,{recursive:true});
 await q.record('launch',await q.launch({executablePath:process.env.CS_ACCEPTANCE_APP,profileRoot:process.env.CS_ACCEPTANCE_PROFILE}));active=true;
 await q.enableControl();
 timer=setInterval(()=>{void captureOwners(q).then(async owners=>{ownershipSamples.push({at:Date.now(),owners});if(ownershipSamples.length>48)ownershipSamples.shift();await fs.writeFile(q.s.root+'/ownership-samples.json',JSON.stringify(ownershipSamples,null,2));}).catch(()=>{});},5000);
 await q.ready(2,300_000);await q.indicatorsReady(2,180_000);
 const initial=await q.inspect();assert.deepEqual(initial.cells.map(c=>c.session.symbol),['ETHUSDT','BTCUSDT']);
 for(const chart of await capture(q)){
  await q.execute(chart.cellId,'visibleTimeRange',{from:chart.bars.at(-80).time,to:chart.bars.at(-1).time+120});
 }
 const values=await q.until(async()=>{try{
  const windows=await capture(q),display=await captureRendered(q),checked=[];
  for(const chart of windows){
   const rendered=display.find(c=>c.cellId===chart.cellId);assert.ok(rendered);
   assert.deepEqual(rendered.lines.map(l=>l.id).sort(),['qa-ma','qa-js','qa-pine','qa-python'].sort());
   const bars=chart.bars.filter(b=>b.is_closed),points=[];
   for(const line of rendered.lines){const data=new Map(line.data.map(p=>[Number(p.time),p.value]));let count=0;
    for(let i=Math.max(19,bars.length-60);i<bars.length;i++){
     const expected=line.id==='qa-ma'?bars.slice(i-19,i+1).reduce((s,b)=>s+b.close,0)/20:bars[i].close*(line.id==='qa-js'?2:line.id==='qa-pine'?3:4);
     assert.ok(Math.abs(data.get(bars[i].time)-expected)<=Math.max(1e-7,Math.abs(expected)*1e-10));count++;
    }
    assert.ok(count>=20);points.push({id:line.id,checked:count});
   }checked.push({cellId:chart.cellId,symbol:chart.symbol,points});
  }return checked;
 }catch(error){lastOracleError=String(error);return false;}},180_000).catch(error=>{throw new Error(String(error)+"; "+lastOracleError);});
 const gates=await q.s.page.evaluate(()=>window.__CANDLESCOPE_INDICATOR_MONITOR__.snapshot().runtimes.map(r=>({runtimeId:r.runtimeId,gates:r.gates,state:r.state,chart:r.chart})));
 assert.ok(gates.every(r=>r.gates.length===0));await q.record('four-runtime-values-and-released-gates',{values,gates});await q.screenshot('four-runtime-owner-released');
 assert.equal((await q.inspect()).persistence.state,'saved');await q.record('full-exit',{processes:await q.quit()});await q.exited();active=false;
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(active){
 await q.screenshot('failure').catch(()=>{});
 await captureOwners(q).then(owners=>fs.writeFile(q.s.root+'/failure-owners.json',JSON.stringify(owners,null,2))).catch(()=>{});
 await q.s.page.evaluate(()=>window.__CANDLESCOPE_INDICATOR_MONITOR__?.snapshot()).then(monitor=>fs.writeFile(q.s.root+'/failure-indicator-monitor.json',JSON.stringify(monitor,null,2))).catch(()=>{});
}}
finally{clearInterval(timer);if(active)try{await q.quit();await q.exited();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
