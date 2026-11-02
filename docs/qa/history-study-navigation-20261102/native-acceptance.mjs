import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema='candlescope.history-study-navigation-recovery-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope='Packaged macOS arm64 bounded history viewport navigation, actual backend commits with deliberately dropped HTTP acknowledgements, authoritative recovery masking, independent chart notes and complete exit/restart. No online-latest, full replay engine, cross-window cursor or release qualification.';
q.s.receipt.transport='Actual bundled backend and owning API; Playwright route.fetch executes real writes then aborts only acknowledgements and temporarily holds the real authoritative GET. No substituted response bodies. OS sandbox permits loopback only.';
const fixture=JSON.parse(await fs.readFile(q.s.root+'/fixture.json','utf8'));
const policy=await fs.readFile(fileURLToPath(new URL('../history-study-note-sources-20261102/loopback-only.sb',import.meta.url)));
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
 const probe=await q.s.app.evaluate(()=>{
  const {spawnSync}=process.getBuiltinModule('node:child_process');
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
async function dropAcknowledgement(id, method, trigger){
 let releaseRead, sawRead, sawCommit;
 const held=new Promise(resolve=>{releaseRead=resolve;});
 const reading=new Promise(resolve=>{sawRead=resolve;});
 const committing=new Promise(resolve=>{sawCommit=resolve;});
 let dropped=false, observed;
 const pattern='**/api/v1/history-studies/views/**';
 const intercept=async route=>{
  if(route.request().method()===method&&!dropped){
   dropped=true;const response=await route.fetch();assert.equal(response.status(),200);
   observed=await response.json();sawCommit();await route.abort('connectionfailed');return;
  }
  if(route.request().method()==='GET'&&dropped){sawRead();await held;}
  await route.continue();
 };
 await q.s.page.route(pattern,intercept);
 let operation;
 try{
  operation=trigger();
  await Promise.race([Promise.all([committing,reading]),q.delay(30_000).then(()=>{throw new Error('No real commit/reconciliation read');})]);
  await cell(id).locator('.history-study-mask').waitFor();
  assert.equal(await cell(id).locator('[data-study-id]').count(),0);
  const snap=await q.inspect(), state=snap.cells.find(value=>value.cellId===id);
  assert.equal(state.runtime.mode,'restoring-study');assert.equal(state.runtime.barCount,0);
  const groups=(await q.s.control.call('app.commands',{windowId:'main-window'})).groups;
  assert.ok(!groups.some(group=>group.id==='study:'+id||group.id==='chart:'+id));
  await q.record('committed-response-dropped-and-authoritative-read-held',{method,observed,runtime:state.runtime,studyAndLiveCommandsAbsent:true});
 }finally{releaseRead();await q.s.page.unroute(pattern,intercept);}
 return{result:await operation,committed:observed};
}
try{
 await launch();assert.deepEqual(counts(),fixture.counts);
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]},{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]}],'split-vertical');
 await q.record('configured-bounded-real-history',configured);
 assert.ok(configured.result.state==='ready'||(configured.result.state==='applied'&&configured.result.code==='READINESS_TIMEOUT'));
 await q.until(async()=>{const snap=await q.inspect();return snap.cells.length===2&&snap.cells.every(cell=>cell.runtime?.mode==='live'&&cell.runtime.barCount>=160);},90_000);
 const workspace=(await q.inspect()).workspaceId;
 await pin('cell-1',fixture.a);await pin('cell-2',fixture.b);
 const captured=await dropAcknowledgement('cell-1','POST',()=>capture('cell-1'));
 const a=captured.result;assert.ok(a);
 const saved=await read('/history-studies/views/'+owner(workspace,'cell-1'));assert.equal(saved.study.id,a);assert.equal(saved.study.rows.length,160);
 const library=await read('/history-studies/saved/'+owner(workspace,'cell-1'));assert.equal(library.studies.length,1);
 await q.record('lost-capture-ack-recovered-with-one-immutable-input',{study:a,revision:saved.revision,libraryCount:library.studies.length});
 assert.equal((await execute('cell-1','seekCursor',{timeMs:fixture.afterMs})).state,'applied');
 const rewound=await dropAcknowledgement('cell-1','PATCH',()=>execute('cell-1','seekCursor',{timeMs:fixture.earlyMs}));
 // Unmounting the old control target may conservatively report TARGET_UNMOUNTED;
 // the authoritative service and new rendered target determine recovered state.
 await q.until(async()=>(await query('cell-1')).snapshot?.cursorMs===fixture.earlyMs);
 const confirmed=await read('/history-studies/views/'+owner(workspace,'cell-1'));
 assert.equal(confirmed.cursorMs,fixture.earlyMs);assert.equal(confirmed.revision,saved.revision+2);
 assert.equal(await region(a).getByText('Native original future version two',{exact:true}).count(),0);
 await q.record('lost-rewind-ack-recovers-committed-cut-without-future-text',{cursor:confirmed.cursorMs,revision:confirmed.revision,commandReceipt:rewound.result});
 const b=await capture('cell-2');assert.ok(b&&b!==a);
 const before=(await query('cell-1')).snapshot;
 await region(a).getByRole('button',{name:'定位视图日期',exact:true}).click();
 const dialog=q.s.page.locator('.chart-time-dialog');await dialog.waitFor();
 await dialog.locator('input').fill(stamp(fixture.fromMs+5*60_000));
 await dialog.locator('button[type=submit]').click();
 await q.until(async()=>/已定位/.test(await dialog.getByRole('status').innerText()));
 const after=(await query('cell-1')).snapshot;
 assert.equal(after.cursorMs,before.cursorMs);assert.equal(after.barCount,before.barCount);
 assert.equal((await read('/history-studies/views/'+owner(workspace,'cell-1'))).revision,confirmed.revision);
 await q.record('date-navigation-centers-only-revealed-prefix',{before,after,message:await dialog.getByRole('status').innerText()});
 await dialog.locator('input').fill(stamp(fixture.afterMs));await dialog.locator('button[type=submit]').click();
 await q.until(async()=>/未能/.test(await dialog.getByRole('status').innerText()));
 assert.equal((await query('cell-1')).snapshot.cursorMs,fixture.earlyMs);
 await q.record('future-view-date-rejected-without-advancing-study',{message:await dialog.getByRole('status').innerText()});
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();
 assert.equal((await query('cell-2')).snapshot.cursorMs,fixture.beforeMs);
 await q.until(async()=>(await q.inspect()).persistence.state==='saved');await q.screenshot('navigation-recovery');await quit();
 await launch();await region(a).waitFor({timeout:90_000});await region(b).waitFor({timeout:90_000});
 const restored=await read('/history-studies/views/'+owner(workspace,'cell-1'));
 assert.deepEqual(restored.study,saved.study);assert.equal(restored.cursorMs,fixture.earlyMs);
 assert.equal((await query('cell-2')).snapshot.cursorMs,fixture.beforeMs);
 assert.deepEqual(counts(),fixture.counts);
 await q.record('full-restart-restores-acknowledged-history-and-independent-sibling',{a:restored.study.id,cursor:restored.cursorMs,b,financialAndJournalCounts:counts()});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){
 q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('navigation-recovery-failure').catch(()=>{});q.s.receipt.diagnostics={body:await q.s.page.locator('body').innerText().catch(String),workspace:await q.inspect().catch(String)};}
}finally{
 if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
