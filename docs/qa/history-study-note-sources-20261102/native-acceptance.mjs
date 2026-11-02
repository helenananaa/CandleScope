import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema='candlescope.history-study-note-sources-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope='Packaged macOS arm64 original-note time projection on controlled persisted manual-account fixtures, real fixed public-market input, actual owning service/API and manager, per-chart sources, rewind, missing history, supplements and full exit/restart. Synthetic note save times are not real historical human-authorship evidence; no order or private exchange qualification.';
q.s.receipt.transport='Actual packaged app/bundled backend over loopback HTTP/WS; macOS process sandbox denies outbound remote sockets; warm committed real public-market DB; no response mocking or online-latest claim.';
const fixture=JSON.parse(await fs.readFile(q.s.root+'/fixture.json','utf8'));
const policy=await fs.readFile(fileURLToPath(new URL('./loopback-only.sb',import.meta.url)));
await fs.writeFile(q.s.root+'/loopback-only.sb',policy);
const shellQuote=value=>"'"+value.replaceAll("'","'\\''")+"'";
const executable=q.s.root+'/Installed App/CandleScope.app/Contents/MacOS/CandleScope';
const launcher=q.s.root+'/loopback-launcher.sh';
await fs.writeFile(launcher,'#!/bin/sh\nexec /usr/bin/sandbox-exec -f '+shellQuote(q.s.root+'/loopback-only.sb')+' '+shellQuote(executable)+' "$@"\n',{mode:0o700});
q.s.receipt.networkIsolation={policySha256:crypto.createHash('sha256').update(policy).digest('hex'),launcherSha256:crypto.createHash('sha256').update(await fs.readFile(launcher)).digest('hex'),launcher,executable};
let running=false;
const sourceReads=[];
const cell=id=>q.s.page.locator(`[data-chart-cell-id="${id}"]`);
const region=id=>q.s.page.locator(`[data-study-id="${id}"]`);
const stamp=ms=>new Date(ms).toISOString().slice(0,19).replace(/:00$/,'');
const owner=(workspace,id)=>Buffer.from(JSON.stringify([workspace,id])).toString('base64url');
async function launch(){
 try{await q.record('packaged-launch',await q.launch({executablePath:launcher}));running=true;}
 catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}
 q.s.page.on('request',request=>{if(request.url().includes('/journal-at-time'))sourceReads.push({at:Date.now(),url:request.url(),method:request.method()});});
 await q.until(async()=>await q.s.page.getByRole('button',{name:'设置',exact:true}).isVisible());
 if(await q.s.page.locator('.sym-modal-overlay').isVisible()){
  await q.s.page.keyboard.press('Escape');await q.s.page.locator('.sym-modal-overlay').waitFor({state:'hidden'});
  await q.record('closed-empty-online-symbol-picker',{action:'real Escape key; selected BTC cache unchanged; no online catalog claim'});
 }
 await q.enableControl();
 const probe=await q.s.app.evaluate(async()=>{
  const {spawnSync}=await import('node:child_process');
  const python=process.resourcesPath+'/python-runtime/python/bin/python3';
  const code="import errno,json,socket;s=socket.socket();s.settimeout(1)\ntry:s.connect(('192.0.2.1',443));raise AssertionError('Remote connection allowed')\nexcept OSError as e:assert e.errno in (errno.EPERM,errno.EACCES),(e.errno,str(e));print(json.dumps({'remoteErrno':e.errno,'remoteDeniedBeforeConnection':True}))\nfinally:s.close()";
  const result=spawnSync(python,['-B','-c',code],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  return{status:result.status,stdout:result.stdout,stderr:result.stderr};
 });
 assert.equal(probe.status,0,JSON.stringify(probe));assert.equal(JSON.parse(probe.stdout).remoteDeniedBeforeConnection,true);
 await q.record('actual-sandboxed-child-remote-denial',probe);
}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
const query=(id,command='inspect',args={})=>q.s.control.call('app.query',{windowId:'main-window',groupId:'study:'+id,command,args});
async function execute(id,command,args={}){
 const group=(await q.s.control.call('app.commands',{windowId:'main-window'})).groups.find(group=>group.id==='study:'+id);assert.ok(group);
 const requestId='source-notes-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command,args,requestId,expectedContext:group.contextToken});
 return q.until(async()=>{const result=await q.s.control.call('request.get',{requestId});return result.final?result:false;});
}
async function read(path){
 const result=await q.s.page.evaluate(async url=>{const response=await fetch(url);return{status:response.status,body:await response.json()};},q.s.backend+'/api/v1'+path);
 assert.equal(result.status,200);return result.body;
}
function counts(){
 const python=q.s.root+'/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3';
 return JSON.parse(cp.execFileSync(python,['-B','-c',"import sqlite3,json,sys;d=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(json.dumps({t:d.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['accounts','orders','fills','cash_flows','journal_entries','journal_revisions']}))",q.s.root+'/profile/data/trading-accounts.sqlite3'],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
}
async function pin(id,account){
 await cell(id).locator('.chart-account-overlay-trigger').click();
 const dialog=q.s.page.locator('.chart-account-overlay-menu');await dialog.waitFor();
 await dialog.getByRole('combobox').selectOption(account);
 await dialog.getByRole('checkbox').nth(0).uncheck();await dialog.getByRole('checkbox').nth(1).uncheck();await dialog.getByRole('checkbox').nth(2).check();
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();
}
async function capture(id){
 await cell(id).click({position:{x:5,y:5}});await q.until(async()=>(await q.inspect()).activeCellId===id);
 await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
 for(const [label,time] of [['区间开始（UTC）',fixture.fromMs],['区间结束（UTC，不含）',fixture.toMs],['回放时刻（UTC）',fixture.beforeMs]])await dialog.getByLabel(label,{exact:true}).fill(stamp(time));
 await dialog.getByRole('button',{name:'开始研究',exact:true}).click();await q.until(async()=>(await cell(id).locator('[data-study-id]').count())>0,90_000);
 return cell(id).locator('[data-study-id]').getAttribute('data-study-id');
}
async function verify(id,study,account,cursor,expected){
 return q.until(async()=>{
  try{
   const state=(await query(id)).snapshot;if(state?.cursorMs!==cursor)return false;
   const result=await query(id,'originalNotes',{limit:10});if(result.state!=='ready'||result.output.loading)return false;
   assert.equal(result.output.accountId,account);assert.equal(result.output.enabled,true);
   const notes=result.output.notes;assert.deepEqual(notes.map(note=>note.id).sort(),expected.map(note=>note.id).sort());
   const section=region(study).getByRole('region',{name:'来源账户笔记',exact:true});
   // Native HTML section has an accessible region role because it is named.
   await section.waitFor();
   for(const item of expected){const actual=notes.find(note=>note.id===item.id);assert.ok(actual);
    for(const [key,value] of Object.entries(item))assert.equal(actual[key],value);
    if(item.body)assert.equal(await section.getByText(item.body,{exact:true}).count(),1);
   }
   for(const hidden of ['Native future-created note','Native unavailable latest text',...(expected.some(note=>note.body==='Native original version one')?['Native original future version two']:[])]){
    assert.equal(await section.getByText(hidden,{exact:true}).count(),0);assert.ok(!JSON.stringify(result.output).includes(hidden));
   }
   return{cell:id,study,account,cursor,notes,barCount:state.barCount};
  }catch{return false;}
 },60_000);
}
const legacy={id:fixture.legacy,body:'',historyUnavailable:true,reviewNote:false};
const review={id:fixture.review,body:'Native later source review',historyUnavailable:false,reviewNote:true};
const first={id:fixture.original,body:'Native original version one',revision:1,historyUnavailable:false,reviewNote:false};
const second={...first,body:'Native original future version two',revision:2};
const other={id:fixture.other,body:'Native other account source',revision:1,historyUnavailable:false,reviewNote:false};
try{
 await launch();assert.deepEqual(counts(),fixture.counts);
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]},{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]}],'split-vertical');
 await q.record('configured-real-input-and-actual-latest-health',configured);assert.ok(configured.result.state==='ready'||(configured.result.state==='applied'&&configured.result.code==='READINESS_TIMEOUT'));
 await q.until(async()=>{const snap=await q.inspect();return snap.cells.length===2&&snap.cells.every(cell=>cell.runtime?.mode==='live'&&cell.runtime.barCount>=160);},90_000);
 const workspace=(await q.inspect()).workspaceId;
 await pin('cell-1',fixture.a);await pin('cell-2',fixture.b);
 const a=await capture('cell-1');assert.ok(a);const saved=await read('/history-studies/views/'+owner(workspace,'cell-1'));assert.equal(saved.study.rows.length,160);
 await q.record('original-history-not-latest-and-explicit-missing-version',await verify('cell-1',a,fixture.a,fixture.beforeMs,[legacy,first,review]));
 assert.equal(await region(a).getByText('此时的笔记历史不完整，无法还原。',{exact:true}).count(),1);
 const projected=(await query('cell-1','originalNotes',{limit:10})).output.notes;assert.ok(projected.find(note=>note.id===fixture.review).savedAtMs>fixture.beforeMs);
 assert.equal((await execute('cell-1','seekCursor',{timeMs:fixture.afterMs})).state,'applied');
 await q.record('forward-reveals-only-eligible-original-version',await verify('cell-1',a,fixture.a,fixture.afterMs,[legacy,second,review]));
 assert.equal((await execute('cell-1','seekCursor',{timeMs:fixture.beforeMs})).state,'applied');
 await q.record('rewind-removes-prefetched-future-text',await verify('cell-1',a,fixture.a,fixture.beforeMs,[legacy,first,review]));
 assert.equal((await execute('cell-1','seekCursor',{timeMs:fixture.earlyMs})).state,'applied');
 await q.record('future-created-and-future-anchor-both-hidden',await verify('cell-1',a,fixture.a,fixture.earlyMs,[legacy]));
 const b=await capture('cell-2');assert.ok(b&&b!==a);
 await q.record('same-market-independent-chart-source',await verify('cell-2',b,fixture.b,fixture.beforeMs,[other]));
 await verify('cell-1',a,fixture.a,fixture.earlyMs,[legacy]);
 await q.until(async()=>(await q.inspect()).persistence.state==='saved');await q.screenshot('original-notes-two-sources');await quit();
 await launch();await region(a).waitFor({timeout:90_000});await region(b).waitFor({timeout:90_000});
 await q.record('restart-restores-per-chart-source-and-note-time',{a:await verify('cell-1',a,fixture.a,fixture.earlyMs,[legacy]),b:await verify('cell-2',b,fixture.b,fixture.beforeMs,[other])});
 const restored=await read('/history-studies/views/'+owner(workspace,'cell-1'));assert.deepEqual(restored.study,saved.study);assert.equal(restored.cursorMs,fixture.earlyMs);
 assert.equal((await execute('cell-1','seekCursor',{timeMs:fixture.beforeMs})).state,'applied');
 await verify('cell-1',a,fixture.a,fixture.beforeMs,[legacy,first,review]);
 await pin('cell-1',fixture.b);await verify('cell-1',a,fixture.b,fixture.beforeMs,[other]);
 await verify('cell-2',b,fixture.b,fixture.beforeMs,[other]);
 await pin('cell-1',fixture.a);
 await q.record('source-switch-does-not-move-cursors-or-change-sibling',{a:await verify('cell-1',a,fixture.a,fixture.beforeMs,[legacy,first,review]),b:await verify('cell-2',b,fixture.b,fixture.beforeMs,[other])});
 await q.screenshot('original-note-version-restored');
 assert.deepEqual(counts(),fixture.counts);await q.record('no-source-ledger-or-journal-mutation',{before:fixture.counts,after:counts(),sourceReads});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){
 q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('original-note-sources-failure').catch(()=>{});q.s.receipt.diagnostics={body:await q.s.page.locator('body').innerText().catch(String),workspace:await q.inspect().catch(String)};}
}finally{
 if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
