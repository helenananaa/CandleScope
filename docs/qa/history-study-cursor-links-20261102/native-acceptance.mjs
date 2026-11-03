import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema='candlescope.history-study-cursor-links-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.applicationSourceCommit=JSON.parse(await fs.readFile(q.s.root+'/assembly.json','utf8')).sourceCommit;
q.s.receipt.buildFlags={VITE_DESKTOP_BUILD:'1',VITE_MULTI_WINDOW_ENABLED:'1',VITE_MULTI_CHART_16_ENABLED:false,VITE_MULTI_CHART_64_ENABLED:false};
q.s.receipt.scope='Actual packaged macOS arm64 optional study clock links: default off, independent input/periods, source notes, target editing/availability, absolute cursor, playback leadership, two actual windows and full exit/restart. Explicit multi-window build/runtime flag; no formal replay or order qualification.';
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
let secondPage;
try{
 await launch();assert.deepEqual(counts(),fixture.counts);assert.equal(q.s.bootstrap.multiWindowEnabled,true);
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]},{session:q.session('BTCUSDT','5m'),indicators:[{name:'MA',period:20}]}],'split-vertical');
 await q.record('configured-real-source-different-display-periods',configured);
 assert.ok(configured.result.state==='ready'||(configured.result.state==='applied'&&configured.result.code==='READINESS_TIMEOUT'));
 // Warm bounded history is intentionally independent of today's live tail.
 // The capture service below must prove the selected historical range itself.
 await q.until(async()=>{const snap=await q.inspect();return snap.cells.length===2&&snap.cells.every(cell=>cell.runtime?.mode==='live');},90_000);
 const workspace=(await q.inspect()).workspaceId;
 await pin('cell-1',fixture.a);await pin('cell-2',fixture.a);
 const a=await capture('cell-1'),b=await capture('cell-2','1m');assert.ok(a&&b&&a!==b);
 const independent=await q.until(async()=>{
  const left=await state('cell-1'),right=await state('cell-2');
  return left?.indicators.length===1&&right?.indicators.length===1&&!left.computing&&!right.computing?{left,right}:false;
 });
 assert.equal(independent.left.indicators[0].outputPoints,independent.left.barCount-19);
 await q.record('independent-study-indicators-preserved',independent);
 const doc=await q.until(document),oldGroups=new Set(Object.keys(doc.linkGroups));
 await command('workspace','createLinkGroup',{cellIds:['cell-1','cell-2']});
 const grouped=await q.until(async()=>{const value=await document();return value&&Object.keys(value.linkGroups).some(id=>!oldGroups.has(id))?value:false;});
 const groupId=Object.keys(grouped.linkGroups).find(id=>!oldGroups.has(id));assert.ok(groupId);
 assert.equal(grouped.linkGroups[groupId].peerPolicy.studyCursor,false);
 await execute('cell-1','seekCursor',{timeMs:fixture.afterMs});await at('cell-1',fixture.afterMs);
 assert.equal((await state('cell-2')).cursorMs,fixture.beforeMs);
 await region(a).getByText('Native original future version two',{exact:true}).waitFor();
 await q.record('default-off-retains-independent-cursors',{a:await state('cell-1'),b:await state('cell-2')});
 await command('workspace','updateLinkPolicy',{groupId,relationship:'peers',patch:{studyCursor:true}});
 await execute('cell-1','seekCursor',{timeMs:fixture.earlyMs});await at('cell-1',fixture.earlyMs);await at('cell-2',fixture.earlyMs);
 assert.equal((await state('cell-2')).series.interval,'5m');
 assert.equal((await state('cell-1')).indicators.length,1);assert.equal((await state('cell-2')).indicators.length,1);
 await q.record('same-window-follows-absolute-cut-with-own-period',{a:await state('cell-1'),b:await state('cell-2')});
 await region(b).getByRole('button',{name:'添加复盘补记',exact:true}).click();
 await execute('cell-1','seekCursor',{timeMs:fixture.beforeMs});await at('cell-1',fixture.beforeMs);
 await region(a).getByRole('button',{name:'重试游标联动',exact:true}).waitFor();
 assert.equal((await state('cell-2')).cursorMs,fixture.earlyMs);
 await q.record('note-editor-refuses-linked-time-change',{a:await state('cell-1'),b:await state('cell-2')});
 await region(b).getByRole('button',{name:'保存并关闭',exact:true}).click();
 await region(a).getByRole('button',{name:'重试游标联动',exact:true}).click();await at('cell-2',fixture.beforeMs);
 await command('workspace','createWindow');
 const topology=await q.until(async()=>{const value=await document();return value&&Object.keys(value.windows).length===2?value:false;});
 const secondId=Object.keys(topology.windows).find(id=>id!=='main-window');assert.ok(secondId);
 secondPage=await pageFor(secondId);secondPage.on('pageerror',error=>q.s.receipt.errors.push({windowId:secondId,message:error.message}));
 const otherSnap=await q.until(async()=>{try{const value=(await q.s.control.call('workspace.inspect',{windowId:secondId})).snapshot;return value.ready&&value.cells.length===2&&value.cells.every(cell=>cell.runtime?.mode==='live')?value:false;}catch{return false;}},90_000);
 const targetId=otherSnap.cells[0].cellId,otherId=otherSnap.cells[1].cellId;
 // A new window duplicates chart configuration, but owner ids do not copy saved studies.
 assert.equal(otherSnap.cells[0].runtime.mode,'live');
 await withPage(secondPage,async()=>{
  if(await secondPage.locator('.sym-modal-overlay').isVisible()){await secondPage.keyboard.press('Escape');}
  await pin(targetId,fixture.a);
 });
 // Capture through the actual owner action. This helper's active-cell assertion
 // uses main-window inspect, so use the same visible dialog directly here.
 const c=await withPage(secondPage,async()=>{
  await cell(targetId).click({position:{x:5,y:5}});
  await secondPage.getByRole('button',{name:'历史研究',exact:true}).click();
  const dialog=secondPage.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
  for(const [label,time] of [['区间开始（UTC）',fixture.fromMs],['区间结束（UTC，不含）',fixture.toMs],['回放时刻（UTC）',fixture.beforeMs]])await dialog.getByLabel(label,{exact:true}).fill(stamp(time));
  await dialog.getByRole('button',{name:'开始研究',exact:true}).click();
  await cell(targetId).locator('[data-study-id]').waitFor({timeout:90_000});return cell(targetId).locator('[data-study-id]').getAttribute('data-study-id');
 });assert.ok(c&&c!==a&&c!==b);
 // The duplicated live sibling stays linked: cursor policy must skip it without entering a study.
 await command('workspace','setLinkGroup',{cellIds:[targetId],groupId},secondId);
 await execute('cell-1','seekCursor',{timeMs:fixture.afterMs});await at('cell-2',fixture.afterMs);await at(targetId,fixture.afterMs,secondId);
 await secondPage.locator(`[data-study-id="${c}"]`).getByText('Native original future version two',{exact:true}).waitFor();
 const live=(await q.s.control.call('workspace.inspect',{windowId:secondId})).snapshot.cells.find(cell=>cell.cellId===otherId);
 assert.equal(live.runtime.mode,'live');
 await q.record('actual-desktop-window-follows-without-entering-live-sibling',{secondId,targetId,source:await state('cell-1'),target:await state(targetId,secondId),liveSibling:live.runtime});
 await execute('cell-1','seekCursor',{timeMs:fixture.beforeMs});await at(targetId,fixture.beforeMs,secondId);
 await execute('cell-1','play');await q.until(async()=>(await state('cell-1')).playing===true);
 await q.until(async()=>!(await state(targetId,secondId)).busy);
 await command('study:'+targetId,'play',{},secondId);
 await q.until(async()=>(await state('cell-1')).playing===false&&(await state(targetId,secondId)).playing===true);
 await q.until(async()=>(await state(targetId,secondId)).cursorMs>fixture.beforeMs);
 await command('study:'+targetId,'pause',{},secondId);
 await q.until(async()=>{const left=await state('cell-1'),right=await state(targetId,secondId);return left.cursorMs===right.cursorMs&&right.playing===false?{left,right}:false;});
 await q.record('playback-start-takes-lead-without-feedback',{source:await state(targetId,secondId),follower:await state('cell-1')});
 await execute('cell-1','seekCursor',{timeMs:fixture.earlyMs});await at(targetId,fixture.earlyMs,secondId);await at('cell-2',fixture.earlyMs);
 assert.equal(await region(a).getByText('Native original future version two',{exact:true}).count(),0);
 assert.equal(await secondPage.locator(`[data-study-id="${c}"]`).getByText('Native original future version two',{exact:true}).count(),0);
 await q.until(async()=>(await q.inspect()).persistence.state==='saved');await q.screenshot('cursor-links-main');await secondPage.screenshot({path:q.s.root+'/cursor-links-second.png'});
 assert.deepEqual(counts(),fixture.counts);await quit();
 await launch();secondPage=await pageFor(secondId);secondPage.on('pageerror',error=>q.s.receipt.errors.push({windowId:secondId,message:error.message}));
 await at('cell-1',fixture.earlyMs);await at('cell-2',fixture.earlyMs);await at(targetId,fixture.earlyMs,secondId);
 assert.equal((await document()).linkGroups[groupId].peerPolicy.studyCursor,true);
 const restored=await read('/history-studies/views/'+owner(workspace,targetId));assert.equal(restored.study.id,c);
 assert.deepEqual(counts(),fixture.counts);
 await q.record('full-restart-restores-options-independent-inputs-and-cross-window-cut',{main:await state('cell-1'),second:await state(targetId,secondId),group:(await document()).linkGroups[groupId],sourceRecordCounts:counts()});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('cursor-links-failure').catch(()=>{});q.s.receipt.diagnostics={body:await q.s.page.locator('body').innerText().catch(String),workspace:await q.inspect().catch(String)};}
}finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
