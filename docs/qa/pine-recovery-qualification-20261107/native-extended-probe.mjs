import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../indicator-domain-native-20261106/native-driver.mjs';

await q.assertPublicGate();
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve earlier native profiles; select a new isolated candidate root');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.driverCommit=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.scope='Packaged Pine live admission, controlled correction, source reset notice, save and restart. Stable-generation counters remain monotonic.';
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LIVE',PYTHONDONTWRITEBYTECODE:'1'};
const received=[];
let terminalOriginError=null;
let correction=null;
const id='native-pine-output-ranges';
const source='//@version=6\nindicator("Native output ranges")\nvarip int executions = 0\nexecutions += 1\nplot(executions,"counter",offset=-1)\nplot(executions % 2 == 0 ? executions : na,"toggle",offset=-1)\nplotshape(executions % 2 == 0,style=shape.circle,location=location.abovebar,size=size.small,offset=-1)\nbgcolor(executions % 2 == 0 ? color.new(color.red,80) : na,offset=-1)\nplot(close,"source close",offset=-1)';
function verifyPackage(){cp.execFileSync('node',['docs/qa/indicator-domain-native-20261106/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
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
 const observations=[],seen=new Set(),pending=[];let lastCounter=-Infinity,lastPosition=null,boundaryOpen=null;const restart=phase.startsWith('restart-');const deadline=Date.now()+(restart?280000:120000);
 while(Date.now()<deadline){
  await q.checkCircuit();assert.equal(terminalOriginError,null,JSON.stringify(terminalOriginError));const state=await probe();
  const counter=state?.lines.find(line=>line.name==='counter')?.data.at(-1);
  if(counter&&counter.time===state.targetTime&&Number.isInteger(counter.value)){
   const value=counter.value,even=value%2===0;
   if(boundaryOpen===null){boundaryOpen=(Math.floor(Date.now()/60000)+1)*60;await q.record(phase+"-boundary-target",{boundaryOpen,firstSourceOpen:state.bars.at(-1)?.time});}
   const toggle=state.lines.find(line=>line.name==='toggle')?.data.find(point=>point.time===state.targetTime);
   const markers=state.markers.flatMap(row=>row.data),backgrounds=state.bgcolors.flatMap(row=>row.regions);
   const coherent=(even?toggle?.value===value:toggle===undefined)&&markers.length===(even?1:0)&&backgrounds.length===(even?1:0);
   await fs.appendFile(q.s.root+'/rendered-observations.ndjson',JSON.stringify({phase,at:Date.now(),counter,even,coherent,state})+'\n');
   if(coherent){
    const match=received.findLast(frame=>frame.counter?.time===counter.time&&frame.counter.value===value);
    if(value<lastCounter){
     const reset=match&&lastPosition&&received.find(frame=>
      frame.calculation?.domainId===match.calculation.domainId&&
      frame.calculation.generation===match.calculation.generation&&frame.meta?.sessionReset===true&&
      frame.meta.sessionResetReason==='sourceRebuild'&&frame.meta.sessionRecovered===false);
     assert.ok(reset&&match.calculation.domainId===lastPosition.domainId&&
       match.calculation.generation>lastPosition.generation,
       'Counter regressed without an independently observed source rebuild');
     await q.record(phase+'-qualified-generation-reset',{lastCounter,lastPosition,counter,reset});
    }
    if(match)lastPosition=match.calculation;
    lastCounter=value;
    assert.ok(counter.time<state.bars.at(-1).time,'Offset point must be before source bar');
    assert.ok(state.lines.every(line=>line.data.every(point=>point.time<state.bars.at(-1).time)),'Shifted plots must not acquire a current/future source-time point');
    assert.ok(markers.every(point=>point.size==='small'),'Native marker symbolic size must survive the frontend');
    const key=counter.time+':'+value;if(!seen.has(key)){seen.add(key);observations.push({at:new Date().toISOString(),counter,even,state});}
    if(observations.length>=6&&observations.some(row=>row.even)&&observations.some(row=>!row.even)&&Number(state.bars.at(-1)?.time)>=boundaryOpen+(restart?120:0)){
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
function receive(payload,via){
 if(payload.type==='error'&&payload.error==='INDICATOR_CALCULATION_ORIGIN_REQUIRED'){terminalOriginError=payload;return;}
 if(!payload.calculation||!Array.isArray(payload.lines))return;
 const line=(name)=>payload.lines.find(item=>(item.name??item.title)===name);
 const frame={via,type:payload.type,at:Date.now(),calculation:payload.calculation,meta:payload.meta,
  counter:line('counter')?.data?.at(-1),
  amended:correction&&line('source close')?.data?.find(point=>point.time===correction.openMs/1000-60)};
 received.push(frame);
}
async function launch(){
 if(received.length)await fs.writeFile(q.s.root+'/initial-projection-observations.json',JSON.stringify(received,null,2)+'\n');
 received.length=0;terminalOriginError=null;await q.record('launch',await q.launch());
 q.s.page.on('websocket',socket=>{
  if(!socket.url().includes('/stream/indicators'))return;
  socket.on('framereceived',event=>{try{receive(JSON.parse(String(event.payload)),'ws');}catch{}});
 });
 q.s.page.on('response',async response=>{if(!response.url().includes('/api/v1/indicators/'))return;
  try{receive(await response.json(),'http');}catch{}});
 await q.checkCircuit();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});await q.enableControl();}
async function close(){
 await q.quit();const allExited=await q.exited();running=false;assert.equal(allExited,true);
 await q.record('full-owned-exit',{allExited:true});
 const status=JSON.parse(await fs.readFile(q.s.root+'/sidecar-exit-status.json','utf8'));
 const pid=q.s.bootstrap.sidecar.pid,exit=status.exits.find(row=>row.pid===pid);
 assert.equal(status.killRequests.some(row=>row.pid===pid&&row.signal==='SIGKILL'),false,'Desktop forced the owned sidecar to exit');
 assert.ok(exit,'Exact owned sidecar exit status must be recorded');assert.equal(exit.code,0);assert.equal(exit.signal,null);
 verifyPackage();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));
}

async function verifyCorrection(state){
 const current=state.lines.find(line=>line.name==='counter').data.at(-1);
 const before=received.findLast(frame=>frame.counter?.time===current.time&&frame.counter.value===current.value);
 assert.ok(before,'No actual wire projection corresponds to the displayed pre-correction counter');
 const times=state.bars.filter(bar=>bar.is_closed).slice(-17,-7).map(bar=>bar.time*1000);
 assert.ok(times.length>=4);
 const profile=q.s.root+'/profile', resources=q.s.identity.resources;
 correction=JSON.parse(cp.execFileSync(resources+'/python-runtime/python/bin/python3.12',
  ['-B','docs/qa/pine-recovery-qualification-20261107/amend_market.py',profile,...times.map(String)],{
   encoding:'utf8',env:{...process.env,DATA_DIR:profile+'/data',CANDLE_DATA_DIR:profile+'/data',
    KLINES_DB_PATH:profile+'/data/candlescope.db',PYTHONPATH:resources+'/backend:'+resources+'/python-runtime/site-packages',
    PYTHONDONTWRITEBYTECODE:'1'}
  }));
 await q.record('controlled-source-correction',{before,correction});
 const rebuilt=await q.until(async()=>{
  await q.checkCircuit();
  return received.find(frame=>frame.at>=correction.startedMs&&frame.type==='indicator.snapshot'&&
   frame.calculation.domainId===before.calculation.domainId&&frame.calculation.generation>before.calculation.generation&&
   frame.calculation.sequence>before.calculation.sequence&&frame.meta?.sessionReset===true&&
   frame.meta.sessionResetReason==='sourceRebuild'&&frame.meta.sessionRecovered===false&&
   frame.amended?.value===correction.newClose);
 },45000);
 await q.record('source-rebuild-admitted',{rebuilt,correction});
 await q.s.page.getByRole('button',{name:/^指标 [0-9]+$/}).click();
 await q.s.page.getByRole('button',{name:/^已添加/}).click();
 const notice=q.s.page.getByText('输入或历史发生变化，Pine 已重新开始，之前的盘中状态已清除。',{exact:true});
 await notice.waitFor({timeout:10000});
 await q.record('source-rebuild-notice-rendered',{text:await notice.textContent(),generation:rebuilt.calculation.generation});
 await q.screenshot('source-rebuild-notice');
 await q.s.page.getByRole('button',{name:'关闭指标侧栏',exact:true}).click();
}

let running=false;
try{
 verifyPackage();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');
 running=true;await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT','1m'),indicators:[]}],'single');
 await q.record('configured-single-chart',configured);assert.ok(['applied','ready'].includes(configured.result.state),JSON.stringify(configured.result));
 await q.until(async()=>{await q.checkCircuit();const snapshot=await q.inspect();return snapshot.cells[0]?.runtime.marketReady&&!snapshot.cells[0]?.runtime.loading?snapshot:false;},180000);
 assert.equal((await q.execute('cell-1','addIndicator',{id,name:'Native output ranges',kind:'script',executionTarget:'hosted',language:'pine',securityMode:'safe',script:source,visible:true})).state,'applied');
 await ready();await q.record('installed-plugin-source',JSON.parse(cp.execFileSync(q.s.identity.resources+'/python-runtime/python/bin/python3.12',['-B','docs/qa/indicator-domain-native-20261106/verify_installed_plugins.py'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}})));const before=await adopted('old-time-updates-and-deletions');await canonical(before);await verifyCorrection(before);
 const saved=await ready();const savedDefinition=(await q.query('cell-1')).snapshot.indicators.find(row=>row.id===id);assert.equal(savedDefinition?.script,source);await q.record('saved-source',{workspace:saved,definition:savedDefinition});await q.screenshot('saved-pine-output-ranges');
 await close();running=false;
 running=true;await launch();await ready();const restored=await q.inspect();const restoredDefinition=(await q.query('cell-1')).snapshot.indicators.find(row=>row.id===id);assert.equal(restoredDefinition?.script,source);
 await adopted('restart-old-time-updates-and-deletions');await q.record('restored-source',{workspace:restored,definition:restoredDefinition});await q.screenshot('restored-pine-output-ranges');
 assert.deepEqual(q.s.receipt.errors,[]);await close();q.s.receipt.passed=true;
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(q.s.page)await q.screenshot('failure').catch(()=>{});}
finally{if(running&&q.s.app){q.s.identity??={pid:q.s.app.process()?.pid};try{await close();}catch(error){q.s.receipt.exitFailure=String(error);}}await fs.mkdir(q.s.root,{recursive:true});await fs.writeFile(q.s.root+'/projection-observations.json',JSON.stringify(received,null,2)+'\n');await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
