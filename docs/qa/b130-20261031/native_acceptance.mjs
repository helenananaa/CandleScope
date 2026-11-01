import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn, execFileSync} from 'node:child_process';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
const scriptRoot=path.dirname(new URL(import.meta.url).pathname);
const repo=path.resolve(process.env.CANDLE_NATIVE_REPO || path.join(scriptRoot,'../../..'));
const root=path.resolve(process.env.CANDLE_JOINT_NATIVE_OUTPUT || path.join(repo,'output/b130-reproduction/native'));
assert.ok(!fs.existsSync(path.join(root,'profile')) && !fs.existsSync(path.join(root,'data')), 'Use a fresh output directory');fs.mkdirSync(root,{recursive:true});
const executable=path.join(repo,'frontend/desktop-dist/mac-arm64/CandleScope.app/Contents/MacOS/CandleScope');
const report={scope:'Actual packaged macOS app, bundled Python/backend, live public market data, isolated profile; no response stubs',phases:[],errors:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const save=()=>fs.writeFileSync(path.join(root,'report.json'),JSON.stringify(report,null,2));
const record=(name,value)=>{report.phases.push({name,at:new Date().toISOString(),value});save();console.log(name);};
async function until(label,fn,accept,timeout=120000){let last;const start=Date.now();while(Date.now()-start<timeout){last=await fn();if(accept(last))return last;await sleep(500);}fs.writeFileSync(path.join(root,'last-wait.json'),JSON.stringify({label,last},null,2));throw Error('Timed out: '+label);}
class CDP{
 static async open(url){const c=new CDP();c.id=0;c.pending=new Map();c.events=[];c.ws=new WebSocket(url);c.ws.onmessage=e=>{const m=JSON.parse(e.data);if(!m.id){c.events.push(m);return;}const p=c.pending.get(m.id);if(!p)return;c.pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);};await new Promise((resolve,reject)=>{c.ws.onopen=resolve;c.ws.onerror=reject;});return c;}
 send(method,params={}){return new Promise((resolve,reject)=>{const id=++this.id;const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('CDP timeout '+method));},20000);this.pending.set(id,{resolve,reject,timer});this.ws.send(JSON.stringify({id,method,params}));});}
}
let child,page,browser,client,sampler;
const env={...process.env,CANDLESCOPE_DESKTOP_USER_DATA:path.join(root,'profile'),CANDLE_DATA_DIR:path.join(root,'data'),CANDLESCOPE_DESKTOP_UI_PORT:'19679'};
for(const key of ['ELECTRON_RUN_AS_NODE','CANDLESCOPE_DESKTOP_SKIP_SIDECAR','CANDLESCOPE_DESKTOP_URL','CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON','CANDLESCOPE_PYTHON'])delete env[key];
async function launch(phase){
 const fd=fs.openSync(path.join(root,phase+'.log'),'a');child=spawn(executable,['--remote-debugging-port=19692'],{env,stdio:['ignore',fd,fd]});fs.closeSync(fd);
 const tabs=await until('native window',async()=>{assert.equal(child.exitCode,null);try{return await(await fetch('http://127.0.0.1:19692/json/list')).json();}catch{return[];}},v=>v.some(x=>x.type==='page'&&x.url.startsWith('http:')));
 page=await CDP.open(tabs.find(x=>x.type==='page'&&x.url.startsWith('http:')).webSocketDebuggerUrl);
 await page.send('Runtime.enable'); await page.send('Network.enable');
 const version=await(await fetch('http://127.0.0.1:19692/json/version')).json();browser=await CDP.open(version.webSocketDebuggerUrl);
 await until('preload',()=>page.send('Runtime.evaluate',{expression:'typeof window.candlescopeDesktop?.aiControlSetMode === "function"',returnByValue:true}),r=>r.result?.value===true);
 const enabled=await page.send('Runtime.evaluate',{expression:'window.candlescopeDesktop.aiControlSetMode("control",true)',awaitPromise:true,returnByValue:true});assert.ok(!enabled.exceptionDetails);
 client=new ControlClient(path.join(root,'profile/control/connection.json'));
 sampler=setInterval(()=>{try{const rows=execFileSync(path.join(repo,'.venv/bin/python'),['-c','import psutil,json,sys; p=psutil.Process(int(sys.argv[1])); print(json.dumps([{\"pid\":c.pid,\"name\":c.name(),\"rss\":c.memory_info().rss} for c in [p]+p.children(recursive=True)]))',String(child.pid)],{encoding:'utf8'});fs.appendFileSync(path.join(root,'resources.jsonl'),JSON.stringify({at:Date.now(),phase,processes:JSON.parse(rows)})+'\n');}catch{}},2000);
 const caps=await until('control ready',async()=>{try{return await client.connect();}catch{return{};}},r=>r.windows?.some(w=>w.ready));
 record(phase+'-launch',{pid:child.pid,instanceId:caps.instanceId,browser:version.Browser});
}
const inspect=async()=> (await client.call('workspace.inspect',{windowId:'main-window'})).snapshot;
const groups=async()=> (await client.call('app.commands',{windowId:'main-window'})).groups;
const query=async(groupId,command='inspect',args={})=>client.call('app.query',{windowId:'main-window',groupId,command,args});
let sequence=0;
async function execute(groupId,command,args={}){const group=(await groups()).find(g=>g.id===groupId);assert.ok(group,groupId);const requestId='native-'+(++sequence);await client.call('app.execute',{windowId:'main-window',groupId,command,args,requestId,expectedContext:group.contextToken});return until(command,()=>client.call('request.get',{requestId}),r=>{if(r.final)assert.equal(r.state,'applied',JSON.stringify(r));return r.final;});}
async function charts(){return Promise.all((await groups()).filter(g=>g.id.startsWith('chart:')).map(async g=>({id:g.id,...(await query(g.id)).snapshot})));}
function assertViewport(row){
 const range=row.visibleRange;assert.ok(range?.logical,JSON.stringify({interval:row.session.interval,range}));
 const span=range.logical.to-range.logical.from;
 assert.ok(range.rightOffset <= Math.max(8,span*.2),JSON.stringify({error:'viewport mostly future whitespace',interval:row.session.interval,range}));
 assert.ok(range.logical.from < row.barCount-1, 'viewport must include market bars');
}
async function ready(name){await until(name,charts,rows=>rows.length===4&&rows.every(r=>r.barCount>=128&&!r.status.initialHistoryPending&&r.status.activeChartReady&&!r.loading&&!r.error&&!r.computing&&r.indicators.every(i=>i.outputPointCount>0)),240000);await sleep(1200);const settled=await charts();settled.forEach(assertViewport);return settled;}
async function diagnose(name){
 const result=await page.send('Runtime.evaluate',{expression:'window.candlescopeDesktop.apiBase',returnByValue:true});
 const url=result.result.value.replace('/api/v1','')+'/debug/snapshot';
 const value=await until(name+' durable delivery settled',async()=>{const d=await(await fetch(url)).json();fs.writeFileSync(path.join(root,name+'-inflight.json'),JSON.stringify(d,null,2));return d;},d=>!d.bar_delivery.degraded&&d.bar_delivery.pending===0&&d.bar_delivery.recovery_pending===0&&d.query_engine.shared_aggregation_blocks.views===0&&d.query_engine.shared_aggregation_blocks.inflight===0&&d.query_engine.shared_aggregation_blocks.leases===0,30000);
 const snapshot={shared_blocks:value.query_engine.shared_aggregation_blocks,memory_budget:value.memory_budget,revision_adoption:value.revision_adoption,cache:value.cache,bar_delivery:value.bar_delivery,source_continuity:value.source_continuity,event_bus:value.event_bus,runtime:value.runtime};
 fs.writeFileSync(path.join(root,name+'-diagnostics.json'),JSON.stringify(snapshot,null,2));
 const blocks=snapshot.shared_blocks;assert.ok(blocks.entries+blocks.retired_entries<=blocks.limits.entries);assert.ok(blocks.estimated_bytes<=blocks.limits.bytes);assert.equal(blocks.last_error,null);assert.equal(snapshot.memory_budget.owners['aggregation-blocks'].reserved_bytes,0);if(name==='verified')assert.ok(blocks.hits>0,'native target switch must reuse B130 blocks');record(name+'-blocks',blocks);assert.equal(snapshot.memory_budget.over_budget_bytes,0);assert.equal(snapshot.revision_adoption.last_error,null);assert.equal(snapshot.bar_delivery.degraded,false,JSON.stringify(snapshot.bar_delivery));assert.equal(snapshot.bar_delivery.pending,0,JSON.stringify(snapshot.bar_delivery));
}
async function proveSharedReads(rows){
 const api=(await page.send('Runtime.evaluate',{expression:'window.candlescopeDesktop.apiBase',returnByValue:true})).result.value;
 const bars=(await query(rows.find(r=>r.session.interval==='2d').id,'bars',{limit:128})).output;
 // Cold backfill may materialize the displayed targets without a shared-block read.
 // New targets over already loaded, closed 1d history exercise the actual packaged API.
 const start=bars[bars.length-40].time*1000,end=bars[bars.length-4].time*1000;
 const before=await(await fetch(api.replace('/api/v1','')+'/debug/snapshot')).json();
 const receipts=[];
 for(const interval of ['6d','8d']){
  const params=new URLSearchParams({symbol:'BTC-USDT-SWAP',exchange:'okx',market_type:'futures',interval,start_ms:String(start),end_ms:String(end),repair:'none'});
  const response=await fetch(api+'/klines/range?'+params);assert.equal(response.status,200);
  const value=await response.json();fs.writeFileSync(path.join(root,'shared-range-'+interval+'.json'),JSON.stringify(value,null,2));
  assert.ok(value.count>=6,JSON.stringify(value));receipts.push({interval,count:value.count,source:value.source});
 }
 const after=await until('packaged shared reads released',async()=>await(await fetch(api.replace('/api/v1','')+'/debug/snapshot')).json(),d=>d.query_engine.shared_aggregation_blocks.views===0&&d.query_engine.shared_aggregation_blocks.leases===0&&d.query_engine.shared_aggregation_blocks.inflight===0,30000);
 const blocks=after.query_engine.shared_aggregation_blocks;
 assert.ok(blocks.builds>0,'packaged API must build B130 blocks');
 assert.ok(blocks.hits>before.query_engine.shared_aggregation_blocks.hits,'packaged cross-target API must reuse B130 blocks');
 record('packaged-shared-reads',{start,end,receipts,before:before.query_engine.shared_aggregation_blocks,after:blocks});
}
async function capture(name){const shot=await page.send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(root,name+'.png'),Buffer.from(shot.data,'base64'));}
async function quit(phase){
 clearInterval(sampler);
 report.errors.push(...page.events.filter(e=>e.method==='Runtime.exceptionThrown'));
 const tree=JSON.parse(execFileSync(path.join(repo,'.venv/bin/python'),['-c','import psutil,json,sys; p=psutil.Process(int(sys.argv[1])); print(json.dumps([p.pid]+[c.pid for c in p.children(recursive=True)]))',String(child.pid)],{encoding:'utf8'}));
 fs.writeFileSync(path.join(root,phase+'-console.json'),JSON.stringify(page.events.filter(e=>e.method==='Runtime.consoleAPICalled'),null,2));fs.writeFileSync(path.join(root,phase+'-history-requests.json'),JSON.stringify(page.events.filter(e=>e.method==='Network.requestWillBeSent'&&e.params.request.url.includes('/klines/history')).map(e=>({url:e.params.request.url,body:e.params.request.postData})),null,2));await capture(phase);page.ws.close();try{await browser.send('Browser.close');}catch{}browser.ws.close();
 await until('full exit',async()=>JSON.parse(execFileSync(path.join(repo,'.venv/bin/python'),['-c','import psutil,json,sys; print(json.dumps([p for p in json.loads(sys.argv[1]) if psutil.pid_exists(p)]))',JSON.stringify(tree)],{encoding:'utf8'})),v=>v.length===0,45000);
 record(phase+'-full-exit',{pids:tree,remaining:[]});child=null;assert.equal(report.errors.length,0);
}
try{
 await launch('cold');
 const initial=await until('initial workspace persistence',inspect,r=>r.ready&&r.persistence.state==='saved');record('initial',initial);
 const requestId='native-custom-history';
 const periods=['45m','90m','2d','3d'];
 const started=Date.now();await client.call('workspace.configure',{windowId:'main-window',workspaceId:initial.workspaceId,expectedRevision:initial.revision,requestId,layout:'quad',charts:periods.map(interval=>({session:{exchange:'okx',marketType:'futures',symbol:'BTC-USDT-SWAP',interval},indicators:[{name:'EMA',period:20}]}))});
 const receipt=await until('configuration receipt',()=>client.call('request.get',{requestId}),r=>r.final,240000);record('configuration-receipt',receipt);
 assert.ok(['ready','applied'].includes(receipt.state),JSON.stringify(receipt));
 const loaded=await ready('four custom histories');record('custom-cold',{elapsedMs:Date.now()-started,charts:loaded});await diagnose('cold');
 for(const row of loaded){const bars=(await query(row.id,'bars',{limit:500})).output;fs.writeFileSync(path.join(root,'cold-bars-'+row.session.interval+'.json'),JSON.stringify(bars));assert.ok(bars.length>=128);assert.ok(bars.every((b,i)=>Number.isFinite(b.close)&&(!i||b.time>bars[i-1].time)));}
 const saved=await until('saved four charts',inspect,r=>r.persistence.state==='saved');record('saved',saved);
 await quit('saved');
 await launch('restart');
 const restored=await ready('restored custom histories');assert.deepEqual(restored.map(r=>r.session.interval),periods);record('restored',restored);await diagnose('restart');await proveSharedReads(restored);
 await execute(restored[1].id,'addIndicator',{id:'qa-b130-pine-local',name:'Pine SMA',kind:'script',executionTarget:'local',script:'//@version=5\nindicator("B130 Pine SMA")\nplot(ta.sma(close,20))',language:'pine',securityMode:'safe',visible:true});
 const pine=await until('bundled current-main Pine',()=>query(restored[1].id),r=>r.snapshot.indicators.some(i=>i.id==='qa-b130-pine-local'&&i.outputPointCount>0&&!i.error),60000);record('pine',pine.snapshot.indicators.find(i=>i.id==='qa-b130-pine-local'));
 const fourthStart=Date.now();const other=restored[0];await execute(other.id,'customIntervalCreate',{interval:'4d'});await execute(other.id,'interval',{interval:'4d'});
 const fourth=await until('4d real history',()=>query(other.id),r=>r.snapshot?.session.interval==='4d'&&r.snapshot.barCount>=128&&!r.snapshot.status.initialHistoryPending&&r.snapshot.status.activeChartReady&&!r.snapshot.loading&&!r.snapshot.computing,180000);await sleep(1200);fourth.snapshot=(await query(other.id)).snapshot;assertViewport(fourth.snapshot);record('4d',{...fourth.snapshot,elapsedMs:Date.now()-fourthStart});
 const fifthStart=Date.now();await execute(other.id,'customIntervalCreate',{interval:'5d'});await execute(other.id,'interval',{interval:'5d'});
 const fifth=await until('5d real history',()=>query(other.id),r=>r.snapshot?.session.interval==='5d'&&r.snapshot.barCount>=128&&!r.snapshot.status.initialHistoryPending&&r.snapshot.status.activeChartReady&&!r.snapshot.loading&&!r.snapshot.computing,180000);await sleep(1200);fifth.snapshot=(await query(other.id)).snapshot;assertViewport(fifth.snapshot);record('5d',{...fifth.snapshot,elapsedMs:Date.now()-fifthStart});
 await until('final save',inspect,r=>r.persistence.state==='saved');await diagnose('verified');await quit('verified');await launch('final-restart');const finalRestored=await ready('final saved 5d');assert.deepEqual(finalRestored.map(r=>r.session.interval),['5d','90m','2d','3d']);assert.ok(finalRestored[1].indicators.some(i=>i.id==='qa-b130-pine-local'&&i.outputPointCount>0&&!i.error));record('final-restored',finalRestored);for(const row of finalRestored){const bars=(await query(row.id,'bars',{limit:500})).output;fs.writeFileSync(path.join(root,'restored-bars-'+row.session.interval+'.json'),JSON.stringify(bars));}await diagnose('final-restart');await quit('final-restored');report.passed=true;
}catch(error){report.passed=false;report.error=String(error);console.error(error);process.exitCode=1;try{if(page)await capture('failure');}catch{}}
finally{clearInterval(sampler);if(child){try{await quit('failed');}catch(error){report.cleanupError=String(error);child.kill('SIGTERM');}}save();}
