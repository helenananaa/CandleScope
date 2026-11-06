import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './native-driver.mjs';

// This driver is deliberately unqualified until a real source run completes.
// Never launch Electron to test this file while the public cooldown is active.
await q.assertPublicGate();
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve earlier native profiles; select a new isolated candidate root');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.driverCommit=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.env={...q.s.env,KLINES_DB_PATH:q.s.root+'/profile/data/market.db'};
q.s.receipt.scope='Bounded native Binance futures 5m OI query receipts, real pane persistence and full owned restart; not all149 sources or whole product.';
const end=Math.floor((Date.now()-36*3600000)/300000)*300000-1;
const start=end-4*3600000+1;
const params={exchange:'binance',market_type:'futures',symbol:'BTCUSDT',channel:'open_interest',period:'5m',start_ms:String(start),end_ms:String(end),limit:'1000'};
async function history(mode){
 await q.checkCircuit();
 const response=await fetch(q.s.backend+'/api/v1/market/history?'+new URLSearchParams({...params,mode}));
 const body=await response.json();await q.record('history-'+mode,{status:response.status,body});
 await q.checkCircuit();assert.equal(response.status,200,JSON.stringify(body));return body;
}
function covered(page){assert.equal(page.complete,true);assert.equal(page.retryable,false);assert.equal(page.has_more,false);assert.deepEqual(page.coverage.missing_ranges,[]);assert.ok(page.coverage.ranges.length>0);}
function receipts(){
 const python=process.env.CANDLESCOPE_QA_PYTHON??'/Users/ryanliang/CandleScope/backend/.venv/bin/python';
 return JSON.parse(cp.execFileSync(python,['-B','-c',
  'import sqlite3,json,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); c.row_factory=sqlite3.Row; print(json.dumps([dict(r) for r in c.execute("SELECT * FROM open_interest_query_receipts WHERE exchange=? AND market_type=? AND symbol=? AND period=? AND start_ms<=? AND end_ms>=? ORDER BY start_ms,end_ms",("binance","futures","BTCUSDT","5m",int(sys.argv[3]),int(sys.argv[2])))])); c.close()',
  q.s.root+'/profile/data/market.db',String(start),String(end)],{encoding:'utf8'}));
}
function coldWitness(){
 const python=process.env.CANDLESCOPE_QA_PYTHON??'/Users/ryanliang/CandleScope/backend/.venv/bin/python';
 return JSON.parse(cp.execFileSync(python,['-B','-c',
  'import sqlite3,json,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); c.row_factory=sqlite3.Row; c.execute("BEGIN"); print(json.dumps({"rows":[dict(r) for r in c.execute("SELECT * FROM open_interest_history WHERE exchange=? AND market_type=? AND symbol=? AND period=? AND event_time_ms BETWEEN ? AND ? ORDER BY event_time_ms",("binance","futures","BTCUSDT","5m",int(sys.argv[2]),int(sys.argv[3])))],"receipts":[dict(r) for r in c.execute("SELECT * FROM open_interest_query_receipts WHERE exchange=? AND market_type=? AND symbol=? AND period=? AND start_ms<=? AND end_ms>=? ORDER BY start_ms,end_ms,policy_revision",("binance","futures","BTCUSDT","5m",int(sys.argv[3]),int(sys.argv[2])))]})); c.close()',
  q.s.root+'/profile/data/market.db',String(start),String(end)],{encoding:'utf8'}));
}
async function launched(){
 await q.record('launch',await q.launch());
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});
 await q.checkCircuit();await q.enableControl();
}
function verifyPackage(){cp.execFileSync('node',['docs/qa/oi-main266-native-20261106/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
async function closed(){await q.quit();assert.equal(await q.exited(),true);running=false;await q.record('full-owned-exit',{allExited:true});const status=JSON.parse(await fs.readFile(q.s.root+'/sidecar-exit-status.json','utf8'));const pid=q.s.bootstrap.sidecar.pid,exit=status.exits.find(row=>row.pid===pid);assert.ok(exit,'Exact owned sidecar exit required');assert.equal(exit.code,0);assert.equal(exit.signal,null);assert.equal(status.killRequests.some(row=>row.pid===pid),false);await q.record('exact-sidecar-exit',{pid,exit,killRequests:status.killRequests});verifyPackage();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));}
async function ready(){return q.until(async()=>{await q.checkCircuit();const snapshot=await q.inspect();return snapshot.cells.length===1&&snapshot.cells[0].runtime.marketReady&&!snapshot.cells[0].runtime.loading&&snapshot.persistence.state==='saved'?snapshot:false;},180000);}
async function catalog(){
 await q.s.page.getByRole('button',{name:/^指标 \d+$/}).click();
 const group=await q.until(async()=>{const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});return groups.find(row=>row.id.startsWith('indicator-catalog:'))??false;});
 return group;
}
async function catalogCommand(group,command,args){
 const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});
 group=groups.find(row=>row.id===group.id);assert.ok(group,'Catalog group disappeared');
 const requestId='oi149-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command,args,requestId,expectedContext:group.contextToken});
 const result=await q.until(async()=>{const row=await q.s.control.call('request.get',{requestId});return row.final?row:false;});assert.equal(result.state,'applied',JSON.stringify(result));
}
let running=false;
try{
 verifyPackage();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');
 running=true;await launched();
 const configured=await q.configure([{session:{exchange:'binance',marketType:'futures',symbol:'BTCUSDT',interval:'5m'},indicators:[]}],'single');assert.ok(['applied','ready'].includes(configured.result.state));await ready();
 await q.record('futures-market-ready-before-receipts',await q.inspect());
 const cold=await history('local_only');assert.equal(cold.count,0);assert.equal(cold.complete,false);assert.ok(cold.coverage.missing_ranges.length>0);
 const acquired=await history('fill_missing');covered(acquired);assert.ok(acquired.count>0,'No real BTCUSDT OI records acquired');
 const before=receipts();assert.ok(before.length>0);
 const hot=await history('fill_missing');covered(hot);assert.deepEqual(hot.data,acquired.data);assert.deepEqual(receipts(),before,'Hot bounded request must preserve receipt observation timestamps');
 const local=await history('local_only');covered(local);assert.deepEqual(local.data,acquired.data);assert.deepEqual(receipts(),before,'Local-only must not rewrite receipts');
 const refreshed=await history('refresh');covered(refreshed);const stable=await history('local_only');assert.deepEqual(stable.data,refreshed.data);
 const savedReceipts=receipts();assert.ok(savedReceipts.some(row=>row.observed_at_ms>Math.max(...before.map(item=>item.observed_at_ms))),'Explicit refresh must record a new source observation');

 let group=await catalog();await catalogCommand(group,'marketStudy',{studyId:'market:open-interest',action:'add'});await catalogCommand(group,'close',{});
 const pane=q.s.page.locator('[data-market-pane="open-interest"]');await pane.waitFor({timeout:90000});assert.ok((await pane.innerText()).includes('Open Interest'));await ready();await q.screenshot('saved-oi-pane');
 await q.record('saved-oi-pane',{text:await pane.innerText(),receipts:savedReceipts,range:{start,end}});
 await closed();running=false;
 // The pane may legitimately acquire overlapping history after the explicit
 // refresh reference was read. Freeze the actual saved disk only after its
 // complete owned exit; retain every audit field in the restart comparison.
 const coldSaved=coldWitness();await q.record('cold-storage-before-restart',coldSaved);
 const expectedData=coldSaved.rows.map(row=>({key:stable.data[0].key,topic:stable.data[0].topic,channel:'open_interest',
  event_time_ms:row.event_time_ms,received_at_ms:row.received_at_ms,source:row.source,sequence:row.event_time_ms,
  data:{open_interest:row.open_interest,is_final:Boolean(row.is_final),sample_kind:row.is_final?'final':'provisional',
   ...(row.open_interest_value===null?{}:{open_interest_value:row.open_interest_value})}}));
 assert.equal(expectedData.length,stable.data.length);
 for(let i=0;i<expectedData.length;i++)assert.deepEqual({...expectedData[i],received_at_ms:stable.data[i].received_at_ms},stable.data[i],
  'Pane hydration changed a persisted source value/identity, not just its acquisition timestamp');
 running=true;await launched();await ready();
 const restored=await history('local_only');covered(restored);assert.deepEqual(restored.data,expectedData);
 const after=receipts();for(const receipt of savedReceipts)assert.ok(after.some(row=>JSON.stringify(row)===JSON.stringify(receipt)),'Durable query receipt missing or silently rewritten');
 await q.s.page.locator('[data-market-pane="open-interest"]').waitFor({timeout:90000});
 group=await catalog();const snapshot=await q.s.control.call('app.query',{windowId:'main-window',groupId:group.id,command:'inspect',args:{}});
 const study=snapshot.snapshot.marketStudies.find(row=>row.id==='market:open-interest');assert.ok(study?.added&&study.visible,JSON.stringify(study));await catalogCommand(group,'close',{});
 await q.screenshot('restored-oi-pane');await q.record('restart-restored',{receipts:after,study,range:{start,end},count:restored.count});
 assert.deepEqual(q.s.receipt.errors,[]);await closed();running=false;
 const afterCold=coldWitness();await q.record('cold-storage-after-restart',afterCold);
 assert.deepEqual(afterCold.rows,coldSaved.rows,'Every saved SQLite row field must remain unchanged');
 for(const receipt of coldSaved.receipts)assert.ok(afterCold.receipts.some(row=>JSON.stringify(row)===JSON.stringify(receipt)),
  'Cold saved query receipt was rewritten or removed');
 q.s.receipt.passed=true;
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(q.s.page)await q.screenshot('failure').catch(()=>{});}
finally{if(running&&q.s.app){q.s.identity??={pid:q.s.app.process()?.pid};try{await closed();}catch(error){q.s.receipt.exitFailure=String(error);}}await fs.mkdir(q.s.root,{recursive:true});await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
