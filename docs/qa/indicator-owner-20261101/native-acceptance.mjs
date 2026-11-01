import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';

q.s.receipt.schema='candlescope.indicator-owner-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope={issue:120,platform:'macOS arm64',provider:'Binance public',indicators:'hosted builtin MA',
  notCovered:['Windows installed acceptance','full 157-item acceptance','Pine/Python execution','all builtin formulas','finite-provider H127/R129 integration']};
let running=false;
const periods={'owner-ma-one':20,'owner-ma-two':20};
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);if(!r.ok)throw new Error(r.status+' '+await r.text());return r.json();},q.s.backend+path);
const diag=()=>api('/api/v1/indicators/diagnostics');
const definition=id=>({id,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period:20},visible:true});
const active=d=>d.engine.instances.filter(x=>x.refcount>0);
async function verify(){
 let failure;
 return q.until(async()=>{
  try{
   assert.deepEqual(q.s.receipt.errors,[]);
   const charts=await capture(q);assert.equal(charts.length,2);
   const evidence=[];
   for(const chart of charts){
    const bars=chart.bars.filter(b=>b.is_closed);assert.ok(bars.length>=499);assert.equal(chart.lines.length,1);
    const line=chart.lines[0], period=periods[line.id];assert.ok(period);
    const points=new Map(line.data.map(p=>[Number(p.time),p.value]));assert.equal(points.size,line.data.length);
    let checked=0,maxError=0;
    for(let i=period-1;i<bars.length;i++){
     const expected=bars.slice(i-period+1,i+1).reduce((n,b)=>n+b.close,0)/period,actual=points.get(bars[i].time);
     assert.ok(actual!==undefined,`${line.id} missing ${bars[i].time}`);
     const error=Math.abs(actual-expected);assert.ok(error<1e-7,`${line.id} ${bars[i].time}: ${actual} != ${expected}`);
     maxError=Math.max(maxError,error);checked++;
    }
    evidence.push({cellId:chart.cellId,id:line.id,period,checked,maxError,first:bars[0].time,last:bars.at(-1).time});
   }
   return evidence;
  }catch(error){failure=String(error);return false;}
 },90000).catch(error=>{throw new Error(error.message+'; '+failure);});
}
async function launch(){const e=await q.launch();running=true;await q.record('packaged-launch',e);await q.enableControl();}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
function checkProcesses(d){
 assert.equal(d.engine.serial_owner.execution_mode,'process');assert.equal(d.engine.serial_owner.failure,null);
 const p=d.engine.worker.pid,h=d.executors.indicator_history_process.worker.pid;
 assert.ok(p&&h);assert.notEqual(p,h);assert.notEqual(p,q.s.bootstrap.sidecar.pid);assert.notEqual(h,q.s.bootstrap.sidecar.pid);
 return {backend:q.s.bootstrap.sidecar.pid,realtime:p,history:h,generation:d.engine.serial_owner.generation};
}
try{
 await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');assert.equal(configured.result.state,'ready');
 await q.ready(2,180000);
 for(const [cell,id] of [['cell-1','owner-ma-one'],['cell-2','owner-ma-two']])assert.equal((await q.execute(cell,'addIndicator',definition(id))).state,'applied');
 await q.indicatorsReady(2,90000);await q.record('hosted-MA-values',await verify());
 const initial=await diag(),processes=checkProcesses(initial);assert.equal(active(initial).length,1);assert.equal(initial.engine.serial_owner.generation,0);
 await q.record('deduplicated-owned-processes',{processes,diagnostics:initial});
 const closed=active(initial)[0].last_committed;
 const advanced=await q.until(async()=>{const d=await diag();return active(d).some(i=>i.last_committed>closed)?d:false;},90000);
 assert.equal(advanced.engine.serial_owner.generation,0,'normal shared/warm subscriptions must not require recovery');
 await q.record('real-provider-new-close',{before:closed,diagnostics:advanced,values:await verify()});
 assert.equal((await q.execute('cell-2','indicatorParams',{indicatorId:'owner-ma-two',params:{period:5}})).state,'applied');periods['owner-ma-two']=5;
 await q.indicatorsReady(2,60000);await q.record('independent-parameters',await verify());
 const before=await diag(),old=checkProcesses(before);assert.equal(active(before).length,2);
 const owned=cp.execFileSync('ps',['-p',String(old.realtime),'-o','pid=,ppid=,args='],{encoding:'utf8'}).trim();
 const match=owned.match(/^(\d+)\s+(\d+)\s+(.*)$/);assert.ok(match);assert.equal(+match[1],old.realtime);assert.equal(+match[2],old.backend);assert.ok(match[3].includes(q.s.identity.resources+'/python-runtime/'));
 process.kill(old.realtime,'SIGKILL');
 const recovered=await q.until(async()=>{const d=await diag();return d.engine.worker.pid!==old.realtime&&d.engine.serial_owner.generation>old.generation&&!d.engine.serial_owner.failure&&!d.engine.serial_owner.recovering&&active(d).length===2?d:false;},120000);
 await q.indicatorsReady(2,60000);await q.record('owned-compute-child-recovery',{old,owned,after:checkProcesses(recovered),diagnostics:recovered,values:await verify()});
 await q.ready(2,60000);await q.record('saved-workspace',await q.inspect());await q.screenshot('saved-hosted-indicators');
 const firstProcesses=checkProcesses(await diag());await quit();
 for(const pid of [firstProcesses.realtime,firstProcesses.history])assert.ok(q.s.quitPids.some(p=>p.pid===pid));
 await launch();await q.ready(2,180000);await q.indicatorsReady(2,90000);
 const restarted=await diag(),newProcesses=checkProcesses(restarted);assert.notEqual(firstProcesses.realtime,newProcesses.realtime);assert.notEqual(firstProcesses.history,newProcesses.history);
 await q.record('restart-restored-values',{processes:newProcesses,values:await verify(),workspace:await q.inspect()});
 for(const [cell,id] of [['cell-1','owner-ma-one'],['cell-2','owner-ma-two']])assert.equal((await q.execute(cell,'removeIndicator',{indicatorId:id})).state,'applied');
 const released=await q.until(async()=>{const d=await diag();return active(d).length===0&&d.engine.serial_owner.release_targets===0?d:false;},30000);
 await q.record('last-unsubscribe-releases-owner',released);await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
