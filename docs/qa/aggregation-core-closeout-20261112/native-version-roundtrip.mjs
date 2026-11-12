import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
q.s.root=process.env.CANDLESCOPE_K130_ROUNDTRIP_OUTPUT ?? path.join(repo,'output/aggregation-core-closeout-20261112/native-version');
await fs.mkdir(q.s.root,{recursive:true});
q.s.profileRoot=q.s.root+'/profile';
await assert.rejects(fs.stat(q.s.profileRoot),{code:'ENOENT'});
const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));
const resources=path.join(repo,'frontend/desktop-dist/mac-arm64/CandleScope.app/Contents/Resources');
const python=resources+'/python-runtime/python/bin/python3';
const selection=q.s.root+'/selection';await fs.writeFile(selection,'candidate');
const config={port,selection,requests:q.s.root+'/physical-kline-requests.jsonl',generations:q.s.root+'/generations.jsonl',
 backends:{candidate:resources+'/backend',baseline:process.env.CANDLESCOPE_K130_BASELINE_BACKEND}};
assert.ok(config.backends.baseline);
await fs.writeFile(q.s.root+'/wrapper.json',JSON.stringify(config,null,2));
q.s.receipt={schema:'candlescope.k130.active-version-roundtrip/1',
 scope:'packaged frontend held open; controlled sidecar replacement on one endpoint and SQLite profile; real public OKX transport; no response substitution',
 candidate:execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(),baseline:'83778381611f67b0835a7dce8a1bde08f48b9837',
 input:'fresh profile with no seeded market database',steps:[],errors:[]};
const {_electron}=createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const sockets=[];let stage='candidate-initial', running=false, navigations=0;
async function generation(name){const lines=(await fs.readFile(config.generations,'utf8')).trim().split('\n').map(JSON.parse);return lines.filter(x=>x.event==='started').findLast(x=>x.variant===name);}
async function checkStage(name,after,anchors){
 await q.until(()=>sockets.some(s=>s.events.filter(e=>e.at>after&&e.type==='bar.updated'&&e.interval==='2m').length>=2)
   &&sockets.some(s=>s.events.filter(e=>e.at>after&&e.type==='bar.updated'&&e.interval==='4m').length>=2),150000);
 await q.until(async()=>{const x=await q.inspect();return x.cells.length===2&&x.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=128);},150000);
 assert.equal(await q.s.page.evaluate(()=>window.__k130MountRefs.every((node,i)=>node===document.querySelector('[data-chart-cell-id="cell-'+(i+1)+'"]'))),true);
 const charts=await capture(q), values=[];
 for(const [index,chart] of charts.entries()){
   const closed=chart.bars.filter(b=>b.is_closed);assert.ok(closed.length>=127);
   const anchor=anchors?.[index] ?? closed[0];
   const params=new URLSearchParams({symbol:'BTC-USDT',exchange:'okx',market_type:'spot',interval:chart.interval,
    start_ms:String(anchor.time*1000),end_ms:String(anchor.time*1000),repair:'none',wait_ms:'0',strict:'true'});
   let body;await q.until(async()=>{const response=await fetch(q.s.backend+'/api/v1/klines/range?'+params);assert.equal(response.status,200);body=await response.json();return body.complete&&body.data?.length===1;},60000);
   for(const field of ['open','high','low','close','volume'])assert.equal(body.data[0][field],anchor[field]);
   values.push(anchor);
 }
 await q.delay(8000);
 const attempts=sockets.filter(s=>s.stage===name);
 const fresh=attempts.filter(s=>s.sent.some(m=>m.action==='subscribe')); 
 const sent=fresh.flatMap(s=>s.sent).filter(m=>m.action==='subscribe');
 if(name!=='candidate-initial'){
  assert.equal(fresh.length,1,'one replacement physical K-line socket per generation');
  assert.equal(sent.length,1,'one recovery subscribe per generation');
  for(const interval of ['2m','4m'])assert.equal(sent.flatMap(m=>m.items??[]).filter(item=>item.intervals?.includes(interval)).length,1);
 }
 await q.record(name,{generation:await generation(name==='baseline'?'baseline':'candidate'),anchors:values,
   connectionAttempts:attempts.length,failedHandshakeAttempts:attempts.filter(s=>!s.sent.length).length,
   sockets:fresh.map(s=>({stage:s.stage,received:s.events.length,closedAt:s.closedAt,sent:s.sent})),subscribeMessages:sent.length,
   workspace:await q.inspect()});
 return values;
}
try{
 q.s.app=await _electron.launch({executablePath:resources.replace('/Contents/Resources','/Contents/MacOS/CandleScope'),args:['--no-sandbox'],timeout:240000,
  env:{...q.s.env,PYTHONUNBUFFERED:'1',CANDLESCOPE_DESKTOP_USER_DATA:q.s.profileRoot,CANDLE_DATA_DIR:q.s.profileRoot+'/data',
   CANDLESCOPE_DESKTOP_UI_PORT:'0',CANDLESCOPE_DESKTOP_BACKEND_PORT:String(port),CANDLESCOPE_DESKTOP_SIDECAR_TIMEOUT_MS:'210000',
   CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT:q.s.profileRoot+'/plugins',CANDLESCOPE_LOCAL_DATA_DIR:q.s.profileRoot+'/local-data',
   CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON:JSON.stringify([python,path.join(repo,'docs/qa/aggregation-core-closeout-20261112/version-sidecar.py'),q.s.root+'/wrapper.json'])}});
 running=true;q.s.page=await q.s.app.firstWindow({timeout:240000});
 q.s.page.on('pageerror',e=>q.s.receipt.errors.push({message:e.message}));
 q.s.page.on('framenavigated',frame=>{if(frame===q.s.page.mainFrame())navigations++;});
 q.s.page.on('websocket',ws=>{if(!new URL(ws.url()).pathname.includes('/stream/klines'))return;
  const record={stage,at:Date.now(),sent:[],events:[]};sockets.push(record);
  ws.on('framesent',event=>{try{record.sent.push(JSON.parse(String(event.payload)));}catch{}});
  ws.on('framereceived',event=>{try{const j=JSON.parse(String(event.payload));if(j.type==='kline'&&record.events.length<4000)record.events.push({at:Date.now(),type:j.event_type,interval:j.interval,data:j.data});}catch{}});
  ws.on('close',()=>record.closedAt=Date.now());});
 await q.s.page.waitForFunction(()=>Boolean(window.candlescopeDesktop),null,{timeout:30000});
 q.s.identity=await q.s.app.evaluate(({app})=>({packaged:app.isPackaged,pid:process.pid,userData:app.getPath('userData'),resources:process.resourcesPath}));assert.equal(q.s.identity.packaged,true);
 q.s.bootstrap=await q.s.page.evaluate(()=>window.candlescopeDesktop.getBootstrap());q.s.backend=new URL(q.s.bootstrap.sidecar.healthUrl).origin;
 await q.s.page.evaluate(()=>window.candlescopeDesktop.aiControlSetMode('control',true));
 q.s.control=new ControlClient(q.s.profileRoot+'/control/connection.json');await q.s.control.connect();
 await q.record('packaged-launch',{identity:q.s.identity,bootstrap:q.s.bootstrap});
 const beginning=Date.now();
 await q.configure(['2m','4m'].map(interval=>({session:{exchange:'okx',marketType:'spot',symbol:'BTC-USDT',interval},indicators:[]})),'split-vertical');
 await q.s.page.evaluate(()=>window.__k130MountRefs=['cell-1','cell-2'].map(id=>document.querySelector('[data-chart-cell-id="'+id+'"]')));
 const anchors=await checkStage(stage,beginning);
 for(const variant of ['baseline','candidate']){
   stage=variant==='baseline'?'baseline':'candidate-restored';const after=Date.now();
   await fs.writeFile(selection,variant);
   await q.until(async()=>{const value=await generation(variant);return value?.at*1000>=after-1000;},40000);
   await checkStage(stage,after,anchors);
 }
 assert.equal(navigations,0,'frontend must stay in the same active document');assert.deepEqual(q.s.receipt.errors,[]);
 await q.quit();await q.exited();running=false;
 await q.record('full-process-exit',{processes:q.s.quitPids,elapsedMs:Date.now()-q.s.quitStartedAt});
 const requests=(await fs.readFile(config.requests,'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);
 const duplicates=[];const baselineDuplicates=[];const seen=new Set();
 for(const request of requests.filter(x=>x.success)){
   const params=new Map(request.query);
   if(params.get('bar')!=='1m'||!request.returned?.length)continue;
   const lower=Math.ceil((Number(params.get('before'))+1)/60000)*60000;
   const upper=Math.floor((Number(params.get('after'))-1)/60000)*60000;
   const confirmed=new Set(request.returned.filter(row=>row.confirmed).map(row=>row.open_ms));
   if(!Number.isFinite(lower)||!Number.isFinite(upper)||upper<lower||((upper-lower)/60000+1)>300)continue;
   let complete=true;for(let opened=lower;opened<=upper;opened+=60000)if(!confirmed.has(opened))complete=false;
   if(!complete)continue; // Exchange confirmation, not local elapsed time, grants closure.
   const key=JSON.stringify([request.generation,request.host,request.path,request.query]);
   if(seen.has(key))(request.variant==='baseline'?baselineDuplicates:duplicates).push(request);seen.add(key);
 }
 await q.record('physical-request-audit',{requests:requests.length,completed:requests.filter(x=>x.success).length,
   rule:'Identical successful complete OKX 1m windows already carrying upstream confirm=1; incomplete/provisional responses do not qualify',
   duplicateCandidateClosedWindows:duplicates,duplicateBaselineClosedWindows:baselineDuplicates});
 assert.deepEqual(duplicates,[],'candidate duplicates an already confirmed complete REST window');
 q.s.receipt.passed=true;
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});
}finally{if(running){await q.quit().catch(()=>{});await q.exited().catch(()=>{});}await q.save();await fs.writeFile(q.s.root+'/sockets.json',JSON.stringify(sockets,null,2));console.log(JSON.stringify({passed:q.s.receipt.passed,failure:q.s.receipt.failure}));}
