import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema='candlescope.history-study-mode-links-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.applicationSourceCommit=JSON.parse(await fs.readFile(q.s.root+'/assembly.json','utf8')).sourceCommit;
q.s.receipt.buildFlags={VITE_DESKTOP_BUILD:'1',VITE_MULTI_WINDOW_ENABLED:'1',VITE_MULTI_CHART_16_ENABLED:false,VITE_MULTI_CHART_64_ENABLED:false};
q.s.receipt.scope='Actual packaged macOS arm64 optional study mode/cursor policies across two windows: resume own input/cut, unprepared target and editor refusal, visible live-source retry, real lost-exit acknowledgement recovery, causal OHLCV/SMA and full exit/restart. Warm controlled history only; no formal replay or financial qualification.';
q.s.receipt.transport='Real packaged app/bundled backend on warm actual public-market DB; macOS sandbox loopback only; no response substitution.';
q.s.env.MULTI_WINDOW_ENABLED='1';
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
async function capture(id,sourceInterval){
 await cell(id).click({position:{x:5,y:5}});await q.until(async()=>(await q.inspect()).activeCellId===id);
 await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
 for(const [label,time] of [['区间开始（UTC）',fixture.fromMs],['区间结束（UTC，不含）',fixture.toMs],['回放时刻（UTC）',fixture.beforeMs]])await dialog.getByLabel(label,{exact:true}).fill(stamp(time));
 if(sourceInterval)await dialog.getByLabel('细数据周期',{exact:true}).selectOption(sourceInterval);
 await dialog.getByRole('button',{name:'开始研究',exact:true}).click();await q.until(async()=>(await cell(id).locator('[data-study-id]').count())>0,90_000);
 return cell(id).locator('[data-study-id]').getAttribute('data-study-id');
}

async function command(groupId,name,args={},windowId='main-window'){
 const group=(await q.s.control.call('app.commands',{windowId})).groups.find(value=>value.id===groupId);assert.ok(group,groupId);
 const requestId='study-links-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId,groupId,command:name,args,requestId,expectedContext:group.contextToken});
 const result=await q.until(async()=>{const value=await q.s.control.call('request.get',{requestId});return value.final?value:false;});
 assert.equal(result.state,'applied',JSON.stringify(result));return result;
}
const document=async()=> (await q.s.control.call('app.query',{windowId:'main-window',groupId:'workspace',command:'inspect',args:{}})).snapshot?.document??null;
const state=(id,windowId='main-window')=>q.until(async()=>{const value=await q.s.control.call('app.query',{windowId,groupId:'study:'+id,command:'inspect',args:{}});return value.snapshot??false;});
const at=async(id,time,windowId='main-window')=>q.until(async()=>{const value=await state(id,windowId);return value?.cursorMs===time&&!value.busy&&!value.computing?value:false;});
async function pageFor(windowId){
 return q.until(async()=>{
  for(const page of q.s.app.windows())try{
   if(await page.evaluate(async()=> (await window.candlescopeDesktop.getBootstrap()).windowId)===windowId)return page;
  }catch{}return false;
 },90_000);
}
async function withPage(page,run){const previous=q.s.page;q.s.page=page;try{return await run();}finally{q.s.page=previous;}}
const base=JSON.parse(await fs.readFile(q.s.root+'/cursor-base-acceptance.json','utf8'));
assert.equal(base.passed,true);
const topology=base.steps.find(step=>step.name==='actual-desktop-window-follows-without-entering-live-sibling').evidence;
const secondId=topology.secondId,targetId=topology.targetId;
let secondPage,workspace,groupId,liveId;
const modeButton=()=>cell('cell-1').getByRole('button',{name:'重试模式联动',exact:true});
const view=id=>read('/history-studies/views/'+owner(workspace,id));
const layout=async windowId=>(await q.s.control.call('workspace.inspect',{windowId})).snapshot;
async function live(id,windowId='main-window'){
 return q.until(async()=>{const value=(await layout(windowId)).cells.find(row=>row.cellId===id);return value?.runtime?.mode==='live'?value:false;});
}
async function activateCell(id,windowId){
 await cell(id).click({position:{x:5,y:5}});
 await q.until(async()=>(await layout(windowId)).activeCellId===id);
}
async function resume(id,windowId='main-window'){
 const page=windowId==='main-window'?q.s.page:secondPage;
 return withPage(page,async()=>{
  await activateCell(id,windowId);
  await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();
  const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
  const choices=dialog.getByRole('button',{name:'继续已保存的研究',exact:true});await choices.waitFor();assert.equal(await choices.count(),1);
  await choices.click();await cell(id).locator('[data-study-id]').waitFor();
 });
}
async function captureOther(){
 return withPage(secondPage,async()=>{
  await activateCell(liveId,secondId);
  await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();
  const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
  for(const [label,time] of [['区间开始（UTC）',fixture.fromMs],['区间结束（UTC，不含）',fixture.toMs],['回放时刻（UTC）',fixture.beforeMs]])await dialog.getByLabel(label,{exact:true}).fill(stamp(time));
  const source=dialog.getByLabel('细数据周期',{exact:true});await source.selectOption('1m');
  await dialog.getByRole('button',{name:'开始研究',exact:true}).click();await cell(liveId).locator('[data-study-id]').waitFor({timeout:90_000});
  return cell(liveId).locator('[data-study-id]').getAttribute('data-study-id');
 });
}
function reference(input,cursor){
 const rows=input.rows.filter(row=>row.closeTimeMs<=cursor);
 if(input.series.interval==='1m')return rows;
 assert.equal(input.series.interval,'5m');assert.equal(input.sourceSeries.interval,'1m');
 const buckets=new Map();for(const row of rows){const key=Math.floor(row.time/300)*300;if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(row);}
 return [...buckets].flatMap(([time,part])=>part[0].time!==time||part.some((row,i)=>row.time!==time+i*60)?[]:[{time,open:part[0].open,high:Math.max(...part.map(row=>row.high)),low:Math.min(...part.map(row=>row.low)),close:part.at(-1).close,volume:part.reduce((sum,row)=>sum+row.volume,0),is_closed:part.at(-1).closeTimeMs===(time+300)*1000}]);
}
async function verify(id,windowId,input,cursor){
 return q.until(async()=>{
  const snap=await state(id,windowId);if(snap.cursorMs!==cursor||snap.busy||snap.computing)return false;
  const bars=await q.s.control.call('app.query',{windowId,groupId:'study:'+id,command:'bars',args:{limit:500}});
  const outputs=await q.s.control.call('app.query',{windowId,groupId:'study:'+id,command:'indicatorOutputs',args:{limit:500}});
  const after=await state(id,windowId);if(after.revision!==snap.revision||after.cursorMs!==cursor||bars.state!=='ready'||outputs.state!=='ready')return false;
  const expected=reference(input,cursor);assert.equal(bars.output.length,expected.length);
  for(let i=0;i<expected.length;i++)for(const key of ['time','open','high','low','close','volume','is_closed'])assert.equal(bars.output[i][key],expected[i][key]);
  assert.equal(outputs.output.length,1);assert.ok(!outputs.output[0].error);
  const points=outputs.output[0].lines.flatMap(line=>line.data);assert.equal(points.length,Math.max(0,expected.length-19));
  let maxError=0;for(let i=19;i<expected.length;i++){
   const point=points.find(point=>point.time===expected[i].time);assert.ok(point);
   const mean=expected.slice(i-19,i+1).reduce((sum,row)=>sum+row.close,0)/20;
   maxError=Math.max(maxError,Math.abs(point.value-mean));assert.ok(Math.abs(point.value-mean)<1e-7);
  }
  return{cellId:id,windowId,studyId:input.id,cursor,displayBars:expected.length,ma20Points:points.length,maxError};
 });
}
async function lostExit(){
 let committed,heldRead=false,dropped=false,release;
 const held=new Promise(resolve=>{release=resolve;});const pattern='**/api/v1/history-studies/views/**';
 const intercept=async route=>{
  if(route.request().method()==='PATCH'&&!dropped){dropped=true;const response=await route.fetch();assert.equal(response.status(),200);committed=await response.json();await route.abort('connectionfailed');return;}
  if(route.request().method()==='GET'&&dropped){heldRead=true;await held;}
  await route.continue();
 };
 await q.s.page.route(pattern,intercept);let operation;
 try{
  operation=execute('cell-1','exit');await q.until(()=>committed&&heldRead);
  await cell('cell-1').locator('.history-study-mask').waitFor();assert.equal(await cell('cell-1').locator('[data-study-id]').count(),0);
  const source=(await layout('main-window')).cells.find(row=>row.cellId==='cell-1');assert.equal(source.runtime.mode,'restoring-study');assert.equal(source.runtime.barCount,0);
  await at('cell-2',fixture.earlyMs);await at(targetId,fixture.earlyMs,secondId);await at(liveId,fixture.earlyMs,secondId);
  await q.record('real-exit-commit-unknown-acknowledgement-keeps-source-masked-and-peer-modes-unchanged',{committed,source:source.runtime});
 }finally{release();}
 try{const receipt=await operation;await live('cell-1');await live('cell-2');await live(targetId,secondId);await live(liveId,secondId);await q.record('authoritative-exit-recovery-publishes-mode-to-all-owning-windows',{receipt,committed});}
 finally{await q.s.page.unroute(pattern,intercept);}
}
async function resumeWithPeerCommitHeld(){
 let committed,release;
 const held=new Promise(resolve=>{release=resolve;});
 const pattern='**/api/v1/history-studies/views/'+owner(workspace,'cell-2');
 const intercept=async route=>{
  if(route.request().method()==='PATCH'&&!committed){
   const response=await route.fetch();assert.equal(response.status(),200);committed=await response.json();
   await held;await route.abort('connectionfailed');return;
  }
  await route.continue();
 };
 await q.s.page.route(pattern,intercept);let operation;
 try{
  operation=resume('cell-1');await q.until(()=>committed);
  await cell('cell-2').locator('.history-study-mask').waitFor();
  const target=(await layout('main-window')).cells.find(row=>row.cellId==='cell-2');
  assert.equal(committed.active,true);assert.equal(target.runtime.mode,'restoring-study');assert.equal(target.runtime.barCount,0);
  assert.equal(await cell('cell-2').locator('[data-study-id]').count(),0);
  await q.record('peer-mode-activation-masks-live-before-real-committed-response-is-released',{committed,target:target.runtime,acknowledgement:'Actual PATCH committed, response held before abort; no substituted body'});
 }finally{release();}
 try{await operation;await at('cell-2',fixture.beforeMs);}finally{await q.s.page.unroute(pattern,intercept);}
}
try{
 await launch();secondPage=await pageFor(secondId);secondPage.on('pageerror',error=>q.s.receipt.errors.push({windowId:secondId,message:error.message}));
 workspace=(await q.inspect()).workspaceId;const initial=await q.until(document);groupId=initial.cells['cell-1'].linkGroupId;assert.ok(groupId);
 assert.equal(initial.linkGroups[groupId].peerPolicy.studyMode,false);
 liveId=(await layout(secondId)).cells.find(row=>row.cellId!==targetId).cellId;
 await at('cell-1',fixture.earlyMs);await at('cell-2',fixture.earlyMs);await at(targetId,fixture.earlyMs,secondId);await live(liveId,secondId);
 const a=(await view('cell-1')).study,b=(await view('cell-2')).study,c=(await view(targetId)).study;assert.equal(new Set([a.id,b.id,c.id]).size,3);
 await command('workspace','updateLinkPolicy',{groupId,relationship:'peers',patch:{studyCursor:false}});
 await execute('cell-2','seekCursor',{timeMs:fixture.beforeMs});await command('study:'+targetId,'seekCursor',{timeMs:fixture.afterMs},secondId);
 await execute('cell-1','exit');await live('cell-1');await at('cell-2',fixture.beforeMs);await at(targetId,fixture.afterMs,secondId);
 await resume('cell-1');await at('cell-1',fixture.earlyMs);
 await q.record('default-off-mode-retains-independent-other-studies',{a:await state('cell-1'),b:await state('cell-2'),c:await state(targetId,secondId)});
 await command('workspace','updateLinkPolicy',{groupId,relationship:'peers',patch:{studyMode:true}});
 await execute('cell-1','exit');await live('cell-1');await live('cell-2');await live(targetId,secondId);await live(liveId,secondId);
 await resumeWithPeerCommitHeld();await at('cell-1',fixture.earlyMs);await at('cell-2',fixture.beforeMs);await at(targetId,fixture.afterMs,secondId);await live(liveId,secondId);
 assert.equal((await view('cell-1')).study.id,a.id);assert.equal((await view('cell-2')).study.id,b.id);assert.equal((await view(targetId)).study.id,c.id);
 await region(b.id).getByText('Native original version one',{exact:true}).waitFor();
 assert.equal(await region(b.id).getByText('Native original future version two',{exact:true}).count(),0);
 await secondPage.locator(`[data-study-id="${c.id}"]`).getByText('Native original future version two',{exact:true}).waitFor();
 assert.equal(await region(a.id).getByText('Native original version one',{exact:true}).count(),0);
 assert.equal(await region(a.id).getByText('Native original future version two',{exact:true}).count(),0);
 await modeButton().waitFor();assert.equal((await view(liveId)).study,null);
 await q.record('mode-only-resumes-own-inputs-and-own-cuts-unprepared-chart-explicit',{a:await state('cell-1'),b:await state('cell-2'),c:await state(targetId,secondId),unprepared:await view(liveId)});
 await execute('cell-1','seekCursor',{timeMs:fixture.earlyMs});await modeButton().waitFor();
 await q.record('cursor-success-does-not-hide-unconfirmed-mode',{unprepared:liveId});
 await command('workspace','setLinkGroup',{cellIds:[liveId],groupId:null},secondId);
 const d=await captureOther();assert.ok(d&&![a.id,b.id,c.id].includes(d));
 await command('workspace','setLinkGroup',{cellIds:[liveId],groupId},secondId);
 await modeButton().click();await q.until(async()=>await modeButton().count()===0);
 await region(b.id).getByRole('button',{name:'添加复盘补记',exact:true}).click();
 await execute('cell-1','exit');await live('cell-1');
 const modeExit=await q.until(async()=>{
  const cells=(await layout(secondId)).cells;const peersLive=[targetId,liveId].every(id=>cells.find(row=>row.cellId===id)?.runtime?.mode==='live');
  return peersLive?{peersLive:true}:await modeButton().isVisible()?{peersLive:false}:false;
 });
 if(!modeExit.peersLive){
  await q.record('concurrent-group-change-keeps-unconfirmed-mode-visible',{source:await view('cell-1'),peers:(await layout(secondId)).cells});
  await q.until(async()=>{const doc=await document();return doc?.cells[liveId]?.linkGroupId===groupId&&(await q.inspect()).persistence.state==='saved';});
  await modeButton().click();
 }
 await live(targetId,secondId);await live(liveId,secondId);await at('cell-2',fixture.beforeMs);
 await modeButton().waitFor();await q.record('editor-refuses-mode-exit-and-live-source-retains-visible-retry',{source:await view('cell-1'),editingTarget:await state('cell-2')});
 await region(b.id).getByRole('button',{name:'保存并关闭',exact:true}).click();
 await q.until(async()=>await region(b.id).getByRole('button',{name:'保存并关闭',exact:true}).count()===0);
 await modeButton().click();await live('cell-2');await q.until(async()=>await modeButton().count()===0);
 await command('workspace','updateLinkPolicy',{groupId,relationship:'peers',patch:{studyCursor:true}});
 await resume('cell-1');for(const [id,windowId] of [['cell-1','main-window'],['cell-2','main-window'],[targetId,secondId],[liveId,secondId]])await at(id,fixture.earlyMs,windowId);
 const dInput=(await view(liveId)).study;
 const math=async()=>({a:await verify('cell-1','main-window',a,fixture.earlyMs),b:await verify('cell-2','main-window',b,fixture.earlyMs),c:await verify(targetId,secondId,c,fixture.earlyMs),d:await verify(liveId,secondId,dInput,fixture.earlyMs)});
 await q.record('mode-and-cursor-enter-own-inputs-at-one-causal-cut',await math());
 for(const [page,id] of [[q.s.page,a.id],[q.s.page,b.id],[secondPage,c.id],[secondPage,d]])for(const text of ['Native original version one','Native original future version two','Native future-created note'])assert.equal(await page.locator(`[data-study-id="${id}"]`).getByText(text,{exact:true}).count(),0);
 await lostExit();assert.deepEqual(counts(),fixture.counts);
 await q.until(async()=>(await q.inspect()).persistence.state==='saved');await q.screenshot('mode-links-live-recovered');await quit();
 await launch();secondPage=await pageFor(secondId);secondPage.on('pageerror',error=>q.s.receipt.errors.push({windowId:secondId,message:error.message}));
 for(const [id,windowId] of [['cell-1','main-window'],['cell-2','main-window'],[targetId,secondId],[liveId,secondId]]){await live(id,windowId);const saved=await view(id);assert.equal(saved.active,false);assert.equal(saved.cursorMs,fixture.earlyMs);}
 const restored=await q.until(document);assert.equal(restored.linkGroups[groupId].peerPolicy.studyMode,true);assert.equal(restored.linkGroups[groupId].peerPolicy.studyCursor,true);
 await resume('cell-1');for(const [id,windowId] of [['cell-1','main-window'],['cell-2','main-window'],[targetId,secondId],[liveId,secondId]])await at(id,fixture.earlyMs,windowId);
 await q.record('complete-restart-keeps-inactive-inputs-options-and-causal-resumption',await math());
 for(const id of ['cell-1','cell-2',targetId,liveId])assert.equal((await read('/history-studies/saved/'+owner(workspace,id))).studies.length,1);
 assert.deepEqual(counts(),fixture.counts);await q.screenshot('mode-links-restored');await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('mode-links-failure').catch(()=>{});q.s.receipt.diagnostics={body:await q.s.page.locator('body').innerText().catch(String),workspace:await q.inspect().catch(String)};}
}finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
