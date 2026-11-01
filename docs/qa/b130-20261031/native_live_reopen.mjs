import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn, execFileSync} from 'node:child_process';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
const scriptRoot=path.dirname(new URL(import.meta.url).pathname);
const repo=path.resolve(process.env.CANDLE_NATIVE_REPO || path.join(scriptRoot,'../../..'));
const root=path.resolve(process.env.CANDLE_JOINT_NATIVE_OUTPUT || path.join(repo,'output/b130-reproduction/native'));
assert.ok(fs.existsSync(path.join(root,'profile')) && fs.existsSync(path.join(root,'data')), 'Reopen the validated profile');fs.mkdirSync(root,{recursive:true});
const executable=path.join(repo,'frontend/desktop-dist/mac-arm64/CandleScope.app/Contents/MacOS/CandleScope');
const report={scope:'Actual packaged macOS app, bundled Python/backend, live public market data, isolated profile; no response stubs',phases:[],errors:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const save=()=>fs.writeFileSync(path.join(root,'live-reopen-report.json'),JSON.stringify(report,null,2));
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
 const value=await until(name+' durable delivery settled',async()=>{const d=await(await fetch(url)).json();fs.writeFileSync(path.join(root,name+'-inflight.json'),JSON.stringify(d,null,2));return d;},d=>!d.bar_delivery.degraded&&d.bar_delivery.pending===0&&d.bar_delivery.recovery_pending===0,30000);
 const snapshot={memory_budget:value.memory_budget,revision_adoption:value.revision_adoption,cache:value.cache,bar_delivery:value.bar_delivery,source_continuity:value.source_continuity,event_bus:value.event_bus,runtime:value.runtime};
 fs.writeFileSync(path.join(root,name+'-diagnostics.json'),JSON.stringify(snapshot,null,2));
 assert.equal(snapshot.memory_budget.over_budget_bytes,0);assert.equal(snapshot.revision_adoption.last_error,null);assert.equal(snapshot.bar_delivery.degraded,false,JSON.stringify(snapshot.bar_delivery));assert.equal(snapshot.bar_delivery.pending,0,JSON.stringify(snapshot.bar_delivery));
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
const book=async()=>{const r=await page.send('Runtime.evaluate',{expression:'JSON.stringify({live:!!document.querySelector(".ob-status-live"),title:document.querySelector(".ob-status")?.title,levels:document.querySelectorAll(".ob-level-row").length,mid:document.querySelector(".ob-mid-price")?.textContent})',returnByValue:true});return JSON.parse(r.result.value);};
const tails=async()=>Promise.all((await charts()).map(async row=>({interval:row.session.interval,bar:(await query(row.id,'bars',{limit:1})).output[0]})));
try{
 await launch('live-reopen');await ready('restored live charts');
 const firstBook=await until('fresh order book',book,b=>b.live&&b.levels>0,120000);record('book-first',firstBook);
 const first=await tails();record('live-first',first);
 const changed=await until('all four live tails update',tails,rows=>rows.length===4&&rows.every((r,i)=>r.bar&&!r.bar.is_closed&&(r.bar.close!==first[i].bar.close||r.bar.volume!==first[i].bar.volume)),120000);
 const nextBook=await until('order book receives another snapshot',book,b=>b.live&&b.levels>0&&b.title!==firstBook.title,30000);
 record('live-updated',changed);record('book-updated',nextBook);await diagnose('live-reopen');await quit('live-restored');report.passed=true;
}catch(error){report.passed=false;report.error=String(error);console.error(error);process.exitCode=1;try{if(page)await capture('live-failure');}catch{}}
finally{clearInterval(sampler);if(child){try{await quit('live-failed');}catch(error){report.cleanupError=String(error);child.kill('SIGTERM');}}save();}
