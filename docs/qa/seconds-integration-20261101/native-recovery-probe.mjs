import fs from 'node:fs/promises';import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
q.s.receipt.schema='candlescope.seconds-recovery-diagnostic/1';q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope='Diagnostic only, reuses stopped attempt7 saved four-chart profile. Not a cold-start or acceptance pass.';
let running=false;
try {await q.record('launch',await q.launch());running=true;
for(let i=0;i<24;i++){const s=await q.s.page.evaluate(async url=>(await fetch(url)).json(),q.s.backend+'/debug/snapshot');await fs.writeFile(q.s.root+'/recovery-snapshot.json',JSON.stringify(s,null,2));const recent=s.event_bus?.recent_recoveries??[];await q.record('observation',{at:Date.now(),recent,delivery:s.bar_delivery,revision:s.storage_revisions,streams:s.coordinator?.streams});if(recent.length)break;await q.delay(5000);}await q.screenshot('recovery-diagnostic');}
catch(e){q.s.receipt.failure=String(e.stack||e);process.exitCode=1;}
finally {if(running){await q.quit();await q.exited();await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt});}await q.save();console.log(JSON.stringify({failure:q.s.receipt.failure,steps:q.s.receipt.steps.length}));}
