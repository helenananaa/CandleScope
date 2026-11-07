import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './native-driver.mjs';

await q.assertPublicGate();
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve earlier native profiles; select a new isolated candidate root');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.driverCommit=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.scope='Native macOS arm64 LIVE Pine negative-offset time updates/deletions and saved source/full owned restart; no full152/Windows/release claim.';
const id='native-pine-output-ranges';
const source='//@version=6\nindicator("Native output ranges")\nvarip int executions = 0\nexecutions += 1\nplot(executions,"counter",offset=-1)\nplot(executions % 2 == 0 ? executions : na,"toggle",offset=-1)\nplotshape(executions % 2 == 0,style=shape.circle,location=location.abovebar,size=size.small,offset=-1)\nbgcolor(executions % 2 == 0 ? color.new(color.red,80) : na,offset=-1)';
function verifyPackage(){cp.execFileSync('node',['docs/qa/pine-output-main243-20261104/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
async function probe(){return q.s.page.evaluate(id=>{
 const element=document.querySelector('[data-chart-cell-id="cell-1"]');if(!element)return null;
 let fiber=element[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))];if(!fiber)return null;
 while(fiber.return)fiber=fiber.return;
 let result=null;
 function visit(node){
  if(!node||result)return;const p=node.memoizedProps;
  if(p?.seriesStore&&p.datasetKey){
   const bars=p.seriesStore.snapshot(),time=bars.at(-2)?.time;
   const lines=[...(p.mainOverlayLines??[]),...(p.subPanes??[]).flatMap(pane=>pane.lines??[])].filter(line=>line.indicatorId===id);
   if(lines.length){result={dataset:p.datasetKey,bars:bars.slice(-20),barCount:bars.length,targetTime:time,
    lines:lines.map(line=>({name:line.name,id:line.id,points:line.data.length,data:line.data.slice(-8)})),
    markers:(p.indicatorMarkers??[]).filter(row=>row.indicatorId===id).map(row=>({...row,data:row.data.filter(point=>point.time===time)})),
    bgcolors:(p.indicatorBgcolors??[]).filter(row=>row.indicatorId===id).map(row=>({...row,regions:(row.regions??[]).filter(point=>point.time===time)})),
    panes:(p.subPanes??[]).map(pane=>({id:pane.id,label:pane.label}))};return;}
  }
  visit(node.child);visit(node.sibling);
 }
 visit(fiber.stateNode.current);return result;
 },id);}
async function ready(){return q.until(async()=>{
 await q.checkCircuit();const snapshot=await q.inspect();const cell=snapshot.cells[0];
 return snapshot.cells.length===1&&cell.indicators.some(row=>row.id===id)&&snapshot.persistence.state==='saved'&&cell.runtime.marketReady&&!cell.runtime.loading&&cell.runtime.barCount>=500&&cell.runtime.indicatorsReady&&!cell.runtime.computing&&!cell.runtime.indicatorErrors?.length&&cell.runtime.indicatorOutputPoints.length>0&&cell.runtime.indicatorOutputPoints.every(count=>count>0)?snapshot:false;
 },180000);}
async function adopted(phase){
 const observations=[],seen=new Set(),pending=[];let lastCounter=-Infinity;const deadline=Date.now()+120000;
 while(Date.now()<deadline){
  await q.checkCircuit();const state=await probe();
  const counter=state?.lines.find(line=>line.name==='counter')?.data.at(-1);
  if(counter&&counter.time===state.targetTime&&Number.isInteger(counter.value)){
   const value=counter.value,even=value%2===0;
   const toggle=state.lines.find(line=>line.name==='toggle')?.data.find(point=>point.time===state.targetTime);
   const markers=state.markers.flatMap(row=>row.data),backgrounds=state.bgcolors.flatMap(row=>row.regions);
   const coherent=(even?toggle?.value===value:toggle===undefined)&&markers.length===(even?1:0)&&backgrounds.length===(even?1:0);
   await fs.appendFile(q.s.root+'/rendered-observations.ndjson',JSON.stringify({phase,at:Date.now(),counter,even,coherent,state})+'\n');
   if(coherent){
    if(value<lastCounter)await q.record(phase+'-counter-regression',{lastCounter,observations,pending,state});
    assert.ok(value>=lastCounter,'Counter regressed within this uninterrupted native session');lastCounter=value;
    assert.ok(counter.time<state.bars.at(-1).time,'Offset point must be before source bar');
    assert.ok(state.lines.every(line=>line.data.every(point=>point.time<state.bars.at(-1).time)),'Shifted plots must not acquire a current/future source-time point');
    assert.ok(markers.every(point=>point.size==='small'),'Native marker symbolic size must survive the frontend');
    const key=counter.time+':'+value;if(!seen.has(key)){seen.add(key);observations.push({at:new Date().toISOString(),counter,even,state});}
    if(observations.length>=6&&observations.some(row=>row.even)&&observations.some(row=>!row.even)){
     await q.record(phase,{observations,pending:pending.slice(-20)});return observations.at(-1).state;
    }
   }else if(pending.length<100)pending.push({at:Date.now(),counter,even,toggle,markers,backgrounds});
  }
  await q.delay([83,137,211,97][seen.size%4]);
 }
 await q.record(phase+'-incomplete',{observations,pending});throw new Error('Native displayed counter/toggle/marker/background did not adopt both parities at the shifted time');
}
async function canonical(state){
 const closed=state.bars.filter(bar=>bar.is_closed).slice(-3);assert.ok(closed.length>=2);
 const params=new URLSearchParams({exchange:'binance',market_type:'spot',symbol:'BTCUSDT',interval:'1m',start_ms:String(closed[0].time*1000),end_ms:String(closed.at(-1).time*1000),repair:'none',wait_ms:'0',strict:'false'});
 const response=await fetch(q.s.backend+'/api/v1/klines/range?'+params);const body=await response.json();assert.equal(response.status,200);assert.equal(body.complete,true);
 const rows=new Map(body.data.map(row=>[row.time,row]));for(const bar of closed)for(const field of ['open','high','low','close','volume'])assert.equal(rows.get(bar.time)?.[field],bar[field]);
 await q.record('real-source-canonical-rows',{closed,quality:{complete:body.complete,all_rows_final:body.all_rows_final}});
}
async function launch(){await q.record('launch',await q.launch());
 q.s.page.on('response',async response=>{if(!response.url().includes('/api/v1/indicators/'))return;
  try{await fs.appendFile(q.s.root+'/indicator-responses.ndjson',JSON.stringify({at:Date.now(),url:response.url(),status:response.status(),body:await response.json()})+'\n');}catch{}});
 await q.checkCircuit();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});await q.enableControl();}
async function close(){await q.quit();assert.equal(await q.exited(),true);running=false;await q.record('full-owned-exit',{allExited:true});verifyPackage();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));}
let running=false;
try{
 verifyPackage();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');
 running=true;await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT','1m'),indicators:[]}],'single');
 await q.record('configured-single-chart',configured);assert.ok(['applied','ready'].includes(configured.result.state),JSON.stringify(configured.result));
 await q.until(async()=>{await q.checkCircuit();const snapshot=await q.inspect();return snapshot.cells[0]?.runtime.marketReady&&!snapshot.cells[0]?.runtime.loading?snapshot:false;},180000);
 assert.equal((await q.execute('cell-1','addIndicator',{id,name:'Native output ranges',kind:'script',executionTarget:'hosted',language:'pine',securityMode:'safe',script:source,visible:true})).state,'applied');
 await ready();const before=await adopted('old-time-updates-and-deletions');await canonical(before);
 const saved=await ready();const savedDefinition=(await q.query('cell-1')).snapshot.indicators.find(row=>row.id===id);assert.equal(savedDefinition?.script,source);await q.record('saved-source',{workspace:saved,definition:savedDefinition});await q.screenshot('saved-pine-output-ranges');
 await close();running=false;
 running=true;await launch();await ready();const restored=await q.inspect();const restoredDefinition=(await q.query('cell-1')).snapshot.indicators.find(row=>row.id===id);assert.equal(restoredDefinition?.script,source);
 await adopted('restart-old-time-updates-and-deletions');await q.record('restored-source',{workspace:restored,definition:restoredDefinition});await q.screenshot('restored-pine-output-ranges');
 assert.deepEqual(q.s.receipt.errors,[]);await close();q.s.receipt.passed=true;
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(q.s.page)await q.screenshot('failure').catch(()=>{});}
finally{if(running&&q.s.app){q.s.identity??={pid:q.s.app.process()?.pid};try{await close();}catch(error){q.s.receipt.exitFailure=String(error);}}await fs.mkdir(q.s.root,{recursive:true});await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
