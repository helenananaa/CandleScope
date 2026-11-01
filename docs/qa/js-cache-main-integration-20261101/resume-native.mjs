import fs from 'node:fs/promises';
import cp from 'node:child_process';
import assert from 'node:assert/strict';
import * as q from './acceptance-driver.mjs';
import * as vp from './value-probe.mjs';
import * as checks from './acceptance-checks.mjs';
import * as scenario from './native-scenarios.mjs';

const prior=JSON.parse(await fs.readFile(q.s.root+'/acceptance.json','utf8'));
await fs.mkdir(q.s.root+'/attempt-04',{recursive:true});
for(const file of ['acceptance.json','traffic.json','native.log']) await fs.copyFile(q.s.root+'/'+file,q.s.root+'/attempt-04/'+file);
const saved=prior.steps.find(step=>step.name==='saved-before-exit').evidence.charts;
q.s.receipt=prior;
q.s.receipt.previousHarnessFailure=prior.failure;
delete q.s.receipt.failure;
q.s.receipt.passed=false;
try {
  const processRows=cp.execFileSync('ps',['-axo','pid=,args='],{encoding:'utf8'});
  assert.ok(!processRows.split('\n').some(line=>line.includes(q.s.root+'/Installed App/')));
  await q.record('previous-processes-absent',{allAbsent:true,priorExitDuration:'not qualified: 30s timeout with manually retained Playwright debugger'});
  for(let cycle=0;cycle<2;cycle++) {
    await q.record('restart-launch-'+cycle,await q.launch());
    await q.enableControl();
    await scenario.healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'});
    const restored=await Promise.all(['cell-1','cell-2'].map(id=>q.query(id)));
    for(let i=0;i<2;i++) {
      assert.deepEqual(checks.comparable(restored[i].snapshot),checks.comparable(saved[i].snapshot));
      const a=saved[i].snapshot.visibleRange.logical,b=restored[i].snapshot.visibleRange.logical;
      assert.ok(Math.abs((a.to-a.from)-(b.to-b.from))<0.1,'saved zoom changed');
    }
    await q.record('restart-restored-'+cycle,{charts:restored,values:await vp.verify(q,scenario.transforms),coverage:await checks.visibleCoverage(q),viewportPolicy:'latest bar on reopening, saved zoom retained'});
    await q.screenshot('restart-'+cycle);
    if(cycle===1) {
      await q.execute('cell-1','removeIndicator',{indicatorId:'qa-js-left'});
      await q.until(async()=> (await q.broker()).dataFlow.indicators.inputs.subscriptions===1);
      await q.execute('cell-2','removeIndicator',{indicatorId:'qa-js-right'});
      await q.until(async()=> (await q.broker()).dataFlow.indicators.inputs.subscriptions===0);
      await q.until(async()=>q.s.page.workers().every(worker=>!worker.url().startsWith('blob:')));
      await q.record('final-input-release',{broker:await q.broker(),workers:q.s.page.workers().map(worker=>worker.url())});
    }
    const origin=q.s.backend,started=Date.now();
    const owned=await q.quit();
    const allExited=await q.exited();
    const portClosed=await fetch(origin+'/health').then(()=>false,()=>true);
    assert.equal(portClosed,true);
    await q.record('full-exit-'+cycle,{owned,allExited,portClosed,elapsedMs:Date.now()-started,method:'Playwright app.close: app.quit followed by debugger detach; no signals'});
  }
  assert.deepEqual(q.s.receipt.errors,[]);
  q.s.receipt.passed=true;await q.save();console.log('NATIVE ACCEPTANCE PASS');
}catch(error){
  console.error(error);q.s.receipt.failure=String(error.stack??error);await q.save();
  try{await q.screenshot('resume-failure');await q.quit();await q.exited();}catch{}
  process.exitCode=1;
}
