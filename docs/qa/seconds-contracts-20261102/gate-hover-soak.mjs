import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {assertPublicGate} from './public-gate.mjs';
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
const provenance=JSON.parse(await fs.readFile(q.s.root+'/profile-provenance.json','utf8'));
assert.equal(JSON.parse(await fs.readFile(q.s.root+'/original-acceptance.json','utf8')).passed,true);
assert.ok(await fs.stat(provenance.snapshot));
q.s.receipt.schema='candlescope.seconds-native-hover/1';q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.scope='Warm reopen of previously qualified isolated four-source profile, actual Gate pointer hover during natural source updates (also while indicator output is pending); renderer diagnostic only; not a new cold-profile qualification.';
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+path);
async function circuit(){
 const health=await api('/api/v1/settings/storage/health');
 const find=value=>{if(!value||typeof value!=='object')return null;const c=value.global_circuit;if(c?.open&&c.last_status_code===418&&c.cooldown_remaining_seconds>0)return c;for(const child of Object.values(value)){const found=find(child);if(found)return found;}return null;};
 const c=find(health.body);if(!c)return;
 const deadline=Math.max(Date.now()+Math.ceil(c.cooldown_remaining_seconds*1000),c.opened_at_ms+Number(c.last_headers?.['retry-after']||0)*1000)+1000;
 const evidence={circuit:c,retry_not_before_ms:deadline,retry_not_before_utc:new Date(deadline).toISOString()};
 await fs.writeFile(q.s.root+'/new-cooldown.json',JSON.stringify(evidence,null,2));await q.record('public-ip-circuit-stop',evidence);throw new Error('PUBLIC_COOLDOWN_STOP '+evidence.retry_not_before_utc);
}
function verify(){cp.execFileSync('node',['docs/qa/seconds-contracts-20261102/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
let running=false;
try{
 await assertPublicGate(q.s.root);verify();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');
 try{await q.record('packaged-launch',await q.launch({executablePath:manifest.app+'/Contents/MacOS/CandleScope',profileRoot:provenance.profileRoot}));running=true;}catch(e){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw e;}
 await q.s.page.evaluate(()=>{Error.stackTraceLimit=50;});
 q.s.page.on('console',message=>{if(!['error','warning'].includes(message.type()))return;
  Promise.all(message.args().map(arg=>arg.evaluate(value=>value instanceof Error?{name:value.name,message:value.message,stack:value.stack}:value).catch(()=>null))).then(args=>fs.appendFile(q.s.root+'/renderer-console.ndjson',JSON.stringify({at:new Date().toISOString(),type:message.type(),text:message.text(),args})+'\n')).catch(()=>{});
 });
 await q.enableControl();await q.until(async()=>{await circuit();const s=await q.inspect();return s.cells.length===4&&s.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=10);},180000);
 await q.record('indicator-readiness-before-hover',await q.inspect());
 const before=await capture(q);assert.equal(before.length,4);await q.record('before-hover',before);
 const box=await q.s.page.locator('[data-chart-cell-id="cell-3"]').first().boundingBox();assert.ok(box);
 const started=Date.now();let frames=0;
 while(Date.now()-started<120000){
  await circuit();
  await q.s.page.mouse.move(box.x+box.width*(0.25+(frames%8)/20),box.y+box.height*0.48,{steps:3});
  const charts=await capture(q);await fs.appendFile(q.s.root+'/hover-frames.ndjson',JSON.stringify({at:new Date().toISOString(),frames,cells:charts.map(c=>({cellId:c.cellId,bars:c.bars.length,lastClosed:c.bars.filter(b=>b.is_closed).at(-1)?.time,lines:c.lines.map(l=>({id:l.id,last:l.data.at(-1)}))}))})+'\n');
  assert.equal(charts.length,4,'All four chart render surfaces must survive native pointer hover');
  frames++;await q.delay(500);
 }
 const after=await capture(q);for(const c of after){const prior=before.find(b=>b.cellId===c.cellId);assert.ok(c.bars.filter(b=>b.is_closed).at(-1)?.time>prior.bars.filter(b=>b.is_closed).at(-1)?.time);}
 await q.record('after-hover',{frames,elapsedMs:Date.now()-started,charts:after});await q.screenshot('hover-complete');assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(e){q.s.receipt.failure=String(e.stack||e);process.exitCode=1;if(running){await q.record('failure-renderer',await capture(q).catch(e=>({error:String(e)})));await q.record('failure-workspace',await q.inspect().catch(e=>({error:String(e)})));await q.record('failure-runtime',await api('/debug/snapshot').catch(e=>({error:String(e)})));await q.screenshot('failure').catch(()=>{});}}
finally{if(running)try{await q.quit();assert.equal(await q.exited(),true);await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt});verify();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));}catch(e){q.s.receipt.exitFailure=String(e);process.exitCode=1;}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure,exitFailure:q.s.receipt.exitFailure}));}
