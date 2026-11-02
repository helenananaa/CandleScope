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
q.s.receipt.schema='candlescope.study-linked-indicator-math-native/1';
q.s.receipt.scope='Additional actual-package causal OHLCV/SMA20 oracle across linked 1m/5m studies in two native windows while a linked live sibling remains live. Controlled warm public input; bounded selected qualification only.';
const base=JSON.parse(await fs.readFile(q.s.root+'/basic-acceptance.json','utf8'));
assert.equal(base.passed,true);
const topology=base.steps.find(step=>step.name==='actual-desktop-window-follows-without-entering-live-sibling').evidence;
function reference(input,cursor){
 const rows=input.rows.filter(row=>row.closeTimeMs<=cursor);
 if(input.series.interval==='1m')return rows;
 assert.equal(input.series.interval,'5m');assert.equal(input.sourceSeries.interval,'1m');
 const groups=new Map();for(const row of rows){const key=Math.floor(row.time/300)*300;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 return [...groups].flatMap(([time,part])=>{
  if(part[0].time!==time||part.some((row,index)=>row.time!==time+index*60))return[];
  return[{time,open:part[0].open,high:Math.max(...part.map(row=>row.high)),low:Math.min(...part.map(row=>row.low)),close:part.at(-1).close,volume:part.reduce((sum,row)=>sum+row.volume,0),is_closed:part.at(-1).closeTimeMs===(time+300)*1000}];
 });
}
async function verify(id,windowId,input,cursor){
 return q.until(async()=>{
  try{
   const snap=await state(id,windowId);if(snap.cursorMs!==cursor||snap.busy||snap.computing)return false;
   const bars=await q.s.control.call('app.query',{windowId,groupId:'study:'+id,command:'bars',args:{limit:500}});
   const outputs=await q.s.control.call('app.query',{windowId,groupId:'study:'+id,command:'indicatorOutputs',args:{limit:500}});
   const after=await state(id,windowId);if(after.cursorMs!==cursor||after.revision!==snap.revision||bars.state!=='ready'||outputs.state!=='ready')return false;
   const expected=reference(input,cursor);assert.equal(bars.output.length,expected.length);
   for(let i=0;i<expected.length;i++)for(const key of ['time','open','high','low','close','volume','is_closed'])assert.equal(bars.output[i][key],expected[i][key]);
   assert.equal(outputs.output.length,1);assert.ok(!outputs.output[0].error);
   const points=outputs.output[0].lines.flatMap(line=>line.data);assert.equal(points.length,Math.max(0,expected.length-19));
   let maxError=0;for(let i=19;i<expected.length;i++){
    const point=points.find(point=>point.time===expected[i].time);assert.ok(point);
    const mean=expected.slice(i-19,i+1).reduce((sum,row)=>sum+row.close,0)/20;
    maxError=Math.max(maxError,Math.abs(point.value-mean));assert.ok(Math.abs(point.value-mean)<1e-7);
   }
   return{cellId:id,windowId,studyId:input.id,cursor,displayInterval:input.series.interval,indicatorId:outputs.output[0].id,revealedSourceRows:input.rows.filter(row=>row.closeTimeMs<=cursor).length,displayBars:expected.length,ma20Points:points.length,maxError};
  }catch(error){q.s.receipt.lastMathError=String(error);return false;}
 },30_000);
}
try{
 await launch();secondPage=await pageFor(topology.secondId);secondPage.on('pageerror',error=>q.s.receipt.errors.push({windowId:topology.secondId,message:error.message}));await at('cell-1',fixture.earlyMs);await at('cell-2',fixture.earlyMs);await at(topology.targetId,fixture.earlyMs,topology.secondId);
 const workspace=(await q.inspect()).workspaceId;
 const a=(await read('/history-studies/views/'+owner(workspace,'cell-1'))).study;
 const b=(await read('/history-studies/views/'+owner(workspace,'cell-2'))).study;
 const c=(await read('/history-studies/views/'+owner(workspace,topology.targetId))).study;
 assert.ok(new Set([a.id,b.id,c.id]).size===3);
 await execute('cell-1','seekCursor',{timeMs:fixture.afterMs});
 await at('cell-2',fixture.afterMs);await at(topology.targetId,fixture.afterMs,topology.secondId);
 const forward={a:await verify('cell-1','main-window',a,fixture.afterMs),b:await verify('cell-2','main-window',b,fixture.afterMs),c:await verify(topology.targetId,topology.secondId,c,fixture.afterMs)};
 assert.equal(forward.a.indicatorId,forward.c.indicatorId);
 await q.record('shared-definition-independent-causal-ohlcv-and-sma20',forward);
 await execute('cell-1','seekCursor',{timeMs:fixture.earlyMs});await at('cell-2',fixture.earlyMs);await at(topology.targetId,fixture.earlyMs,topology.secondId);
 await q.record('linked-rewind-recomputes-each-display-prefix',{a:await verify('cell-1','main-window',a,fixture.earlyMs),b:await verify('cell-2','main-window',b,fixture.earlyMs),c:await verify(topology.targetId,topology.secondId,c,fixture.earlyMs)});
 const doc=await q.until(document);const liveIds=Object.keys(doc.cells).filter(id=>doc.cells[id].linkGroupId===doc.cells['cell-1'].linkGroupId&&![ 'cell-1','cell-2',topology.targetId].includes(id));
 const second=(await q.s.control.call('workspace.inspect',{windowId:topology.secondId})).snapshot;
 assert.ok(second.cells.some(cell=>liveIds.includes(cell.cellId)&&cell.runtime.mode==='live'));
 assert.deepEqual(counts(),fixture.counts);await q.record('live-sibling-and-original-source-records-unchanged',{live:second.cells.filter(cell=>liveIds.includes(cell.cellId)),counts:counts()});
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('cursor-math-failure').catch(()=>{});q.s.receipt.diagnostics={body:await q.s.page.locator('body').innerText().catch(String),workspace:await q.inspect().catch(String)};}
}finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure,lastMathError:q.s.receipt.lastMathError}));}
