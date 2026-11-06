import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import * as q from './native-driver.mjs';
import {assertPublicGate} from '../seconds-contracts-20261102/public-gate.mjs';
await assertPublicGate(q.s.root);
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve previous profiles; select a fresh candidate');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
function verifyPackage(){cp.execFileSync('node',['docs/qa/alerts-main266-native-20261106/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
q.s.receipt.schema='candlescope.alert-numeric-native/1';
q.s.receipt.driverCommit=q.s.receipt.sourceCommit;
q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.transport='Packaged macOS arm64 numeric alerts with real public HTTP/WS; isolated local alert rules/history, no substituted responses or external notification channels.';
q.s.receipt.scope={aliases:['RSI14','MACD12/26/9 histogram','MA20'],source:'real public Binance BTCUSDT spot 1m',notCovered:['arbitrary indicator parameters','Pine/Python alerts','Windows','whole-application performance SLA','exactly-once external delivery','full157 acceptance']};
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+path);
let lastCircuitCheck=0;
async function checkCircuit(){
 if(Date.now()-lastCircuitCheck<2000)return;lastCircuitCheck=Date.now();
 const health=await api('/api/v1/settings/storage/health');assert.equal(health.status,200);await fs.writeFile(q.s.root+'/storage-health-latest.json',JSON.stringify({at:new Date().toISOString(),health:health.body},null,2));
 function visit(value){if(!value||typeof value!=='object')return null;const c=value.global_circuit;
  if(c?.open&&c.last_status_code===418&&c.cooldown_remaining_seconds>0)return c;
  for(const child of Object.values(value)){const found=visit(child);if(found)return found;}return null;}
 const circuit=visit(health.body);if(!circuit)return;
 const deadline=Math.max(Date.now()+Math.ceil(circuit.cooldown_remaining_seconds*1000),circuit.opened_at_ms+Number(circuit.last_headers?.['retry-after']||0)*1000)+1000;
 const evidence={circuit,retry_not_before_ms:deadline,retry_not_before_utc:new Date(deadline).toISOString()};
 await fs.writeFile(q.s.root+'/new-cooldown.json',JSON.stringify(evidence,null,2));
 for(const filename of ['/Users/ryanliang/CandleScope/output/backend-goal-20261102/STATE.json','/Users/ryanliang/CandleScope/output/development-goal-20261104/state.json']){
  const state=JSON.parse(await fs.readFile(filename,'utf8'));
  const prior=Date.parse(state.public_cooldown?.retry_not_before_utc??'');
  if(!Number.isFinite(prior)||prior<deadline){state.public_cooldown=evidence;await fs.writeFile(filename,JSON.stringify(state,null,2)+'\n');}
 }
await q.record('public-ip-circuit-stop',evidence);throw new Error('PUBLIC_COOLDOWN_STOP '+evidence.retry_not_before_utc);
}
const read=async path=>{await checkCircuit();const r=await api(path);assert.equal(r.status,200,path);return r.body;};
async function ready(){return q.until(async()=>{await checkCircuit();const snapshot=await q.inspect();return snapshot.cells.length===1&&snapshot.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=500)&&snapshot.persistence.state==='saved'?snapshot:false;},240000);}
async function group(prefix){return q.until(async()=>{const g=await q.s.control.call('app.commands',{windowId:'main-window'});return (g.groups??g).find(x=>x.id.startsWith(prefix));});}
async function command(prefix,command,args={}){const g=await group(prefix),requestId='alert-native-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId:g.id,command,args,requestId,expectedContext:g.contextToken});const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;},60000);assert.equal(result.state,'applied',JSON.stringify(result));return result;}
async function panel(){const g=await group('alerts:');return (await q.s.control.call('app.query',{windowId:'main-window',groupId:g.id,command:'inspect',args:{}})).snapshot;}
async function open(){await command('alert-notifications','openAlerts');await q.until(async()=>{const p=await panel();return !p.loading?p:false;});}
const history=()=>read('/api/v1/alerts/history?limit=1000');
const diagnostics=()=>read('/api/v1/indicators/diagnostics');
async function counts(n){return q.until(async()=>{const d=await diagnostics();await fs.writeFile(q.s.root+'/latest-diagnostics.json',JSON.stringify(d,null,2));return d.numericQueries?.subscriptions===n?d:false;},90000);}
async function captureState(){return {panel:await panel(),diagnostics:await diagnostics(),status:await read('/api/v1/alerts/status'),workspace:await q.inspect()};}
function unique(events){const keys=events.map(e=>JSON.stringify([e.ruleId,e.evaluationCursor]));assert.equal(new Set(keys).size,keys.length);}
async function verifyValues(events){const checked=[];for(const event of events){const end=event.evaluationCursor.barTime;assert.ok(end);const p=new URLSearchParams({symbol:'BTCUSDT',interval:'1m',exchange:'binance',market_type:'spot',start_ms:String(end-249*60000),end_ms:String(end),repair:'none',wait_ms:'0',strict:'false'});const result=await read('/api/v1/klines/range?'+p);assert.equal(result.complete,true);assert.equal(result.all_rows_final,true);assert.equal(result.data.length,250);
 const code="import json,sys\nfrom legacy_indicator_oracle import compute_alert_indicator_values\nfrom app.data_engine.data_manager.models import BarData\nrows=json.load(sys.stdin)\nprint(json.dumps(compute_alert_indicator_values([BarData(time=int(b['time']),open=b['open'],high=b['high'],low=b['low'],close=b['close'],volume=b['volume']) for b in rows])))";
 const resources=manifest.app+'/Contents/Resources';
 const expected=JSON.parse(cp.execFileSync(resources+'/python-runtime/python/bin/python3.12',['-B','-c',code],{input:JSON.stringify(result.data),encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONPATH:process.cwd()+'/backend:'+resources+'/python-runtime/site-packages:'+process.cwd()+'/docs/qa/alerts-main266-native-20261106',CANDLE_DATA_DIR:q.s.root+'/oracle-data'}}));
 for(const [key,value]of Object.entries(expected)){assert.equal(event.values.indicatorReady[key],true);assert.ok(Math.abs(event.values[key]-value)<Math.max(1e-9,Math.abs(value)*1e-10),key+': '+event.values[key]+' vs '+value);}
 const independent=JSON.parse(cp.execFileSync(resources+'/python-runtime/python/bin/python3.12',['-B','docs/qa/alerts-main266-native-20261106/numeric_oracle.py'],{input:JSON.stringify(result.data),encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));for(const[key,value]of Object.entries(independent)){assert.ok(Math.abs(event.values[key]-value)<Math.max(1e-9,Math.abs(value)*1e-10),'independent '+key+': '+event.values[key]+' vs '+value);}checked.push({event,expected,independent,canonicalRows:result.data});}return checked;}
let running=false;const ids=[];
async function launch(){await assertPublicGate(q.s.root);try{await q.record('packaged-launch',await q.launch());running=true;await checkCircuit();await q.enableControl();}catch(e){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw e;}}
async function quit(){const sidecarPid=q.s.bootstrap.sidecar.pid;await q.quit();assert.equal(await q.exited(),true);running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});const observed=JSON.parse(await fs.readFile(q.s.root+'/sidecar-exit-status.json','utf8'));const exit=observed.exits.find(x=>x.pid===sidecarPid);assert.ok(exit,'Missing exact sidecar exit');assert.equal(exit.code,0);assert.equal(exit.signal,null);assert.deepEqual(observed.killRequests,[]);await q.record('exact-sidecar-exit',{pid:sidecarPid,exit,killRequests:observed.killRequests});verifyPackage();await q.record('package-after-full-exit',JSON.parse(await fs.readFile(q.s.root+'/verified-after.json','utf8')));await q.record('cold-alert-store-after-exit',JSON.parse(await fs.readFile(q.s.root+'/profile/data/alerts.json','utf8')));}
try{
 verifyPackage();
 await launch();await q.record('configured',await q.configure([{session:q.session('BTCUSDT','1m'),indicators:[]}],'single'));await ready();await open();
 for(const suffix of ['A','B']){await command('alerts:','reset');const p=await panel();const product=p.products.find(p=>p.symbol==='BTCUSDT'&&p.exchange==='binance');assert.ok(product,JSON.stringify(p.products));await command('alerts:','target',{productKey:product.key,interval:'1m'});await command('alerts:','draft',{name:'Native numeric '+suffix,enabled:true,triggerOn:'bar_close',expression:{id:'root-'+suffix,type:'group',not:false,op:'AND',children:[['rsi','>=','0'],['ma20','>','0'],['macdHist','>','-1000000000']].map(([left,comparator,rightValue])=>({id:suffix+left,type:'condition',not:false,left,comparator,rightType:'number',rightValue,rangeMin:'',rangeMax:'',percentValue:''}))},maxTriggerMode:'custom',customMaxTriggers:'10',expiresMode:'never',afterTrigger:'keep',cooldownMode:'always',messageTemplate:'Native numeric '+suffix,channels:{in_app:true,history:true,browser:false,sound:false,webhook:false}});await q.record('draft-'+suffix,await panel());await command('alerts:','save');await command('alerts:','refresh');const saved=(await panel()).rules.find(r=>r.name==='Native numeric '+suffix);assert.ok(saved);ids.push(saved.id);}
 await counts(2);await q.record('two-rules-active',await captureState());
 const events=await q.until(async()=>{const h=await history();return ids.every(id=>h.some(e=>e.ruleId===id))?h:false;},180000);unique(events);await q.record('real-closes-match-legacy-values',await verifyValues(events));await command('alerts:','refresh');await command('alerts:','filters',{tab:'history'});await q.screenshot('real-close-alert-history');
 await command('alerts:','close');await q.record('btc-chart-closed',await q.configure([{session:q.session('ETHUSDT','1m'),indicators:[]}],'single'));await ready();await open();await counts(2);
 await command('alerts:','enabled',{ruleId:ids[0],enabled:false});await counts(1);const disabledHistory=await history(),aCount=disabledHistory.filter(e=>e.ruleId===ids[0]).length,bCount=disabledHistory.filter(e=>e.ruleId===ids[1]).length;
 const background=await q.until(async()=>{const h=await history();return h.filter(e=>e.ruleId===ids[1]).length>bCount?h:false;},180000);assert.equal(background.filter(e=>e.ruleId===ids[0]).length,aCount);unique(background);await command('alerts:','refresh');await q.record('paused-rule-stops-background-rule-continues',{state:await captureState(),values:await verifyValues(background.filter(e=>!disabledHistory.some(old=>old.id===e.id)))});await q.screenshot('background-alert-history');await quit();
 await launch();await ready();await open();await counts(1);let restored=await history();unique(restored);for(const e of background)assert.ok(restored.some(r=>r.id===e.id));assert.equal(restored.filter(e=>e.ruleId===ids[0]).length,aCount);await q.record('restart-preserves-rules-history-cursors',await captureState());
 await command('alerts:','enabled',{ruleId:ids[1],enabled:false});await counts(0);await command('alerts:','refresh');const event=(await history()).find(e=>e.ruleId===ids[1]);assert.ok(event);await command('alerts:','acknowledge',{eventId:event.id,acknowledged:true});await command('alerts:','refresh');const saved=await history();assert.ok(saved.find(e=>e.id===event.id).acknowledgedAt);await q.record('disabled-released-and-acknowledged',await captureState());await quit();
 await launch();await ready();await open();await counts(0);restored=await history();unique(restored);assert.deepEqual(restored,saved);await q.record('second-restart-disabled-history-stable',await captureState());await command('alerts:','filters',{tab:'history'});await q.screenshot('restored-alert-history');await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running){await q.screenshot('failure').catch(()=>{});await q.record('failure-state',await captureState().catch(e=>({error:String(e)}))).catch(()=>{});}}
finally{if(running)try{await quit();}catch(e){q.s.receipt.exitFailure=String(e);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
