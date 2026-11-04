import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './native-driver.mjs';
const root=q.s.root;
q.s.receipt.scope='Native macOS LOCAL_OFFLINE imported closed BAR / formal replay / simulated order / full owned exit and restart. Single dataset; not imported tape, multi-symbol financial qualification or #166 completion.';
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',REPLAY_ENABLED:'1',
 KLINES_DB_PATH:root+'/profile/data/market.db',REPLAY_DB_PATH:root+'/profile/data/replay.db',
 BACKTEST_DB_PATH:root+'/profile/data/backtest.db',BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1'};
try{await fs.stat(root+'/profile');throw new Error('Preserve existing profile; use a fresh candidate');}catch(e){if(e.code!=='ENOENT')throw e;}
await fs.mkdir(root+'/profile/data',{recursive:true});
const start=1700000040000,count=6000;
await fs.writeFile(root+'/imported-replay.csv','time,open,high,low,close,volume\n'+Array.from({length:count},(_,i)=>{
 const price=i>4500?1000000:100+i%20;return `${start+i*60000},${price},${price+2},${price-1},${price+1},100`;
}).join('\n'));
const requests=[];
async function json(path){const r=await fetch(q.s.backend+path);assert.ok(r.ok,await r.clone().text());return r.json();}
async function query(id){return (await q.s.control.call('app.query',{windowId:'main-window',groupId:id,command:'inspect',args:{}})).snapshot;}
async function group(id){return q.until(async()=>{const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});return groups.find(g=>g.id===id)||false;},30000);}
async function execute(id,command,args={}){
 const g=await group(id),requestId='imported-replay-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:id,command,args,requestId,expectedContext:g.contextToken});
 const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;},60000);
 assert.equal(result.state,'applied',JSON.stringify(result));return result;
}
async function launch(){
 await q.launch();q.s.page.on('request',r=>{if(r.url().includes('/api/'))requests.push({at:Date.now(),method:r.method(),path:new URL(r.url()).pathname,body:r.postData()});});
 const h=await json('/health');assert.equal(h.runtime_mode,'LOCAL_OFFLINE');assert.equal(h.local_offline.network.blocked_attempts,0);
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});await q.enableControl();
 await q.record('native-offline-launch',{identity:q.s.identity,health:h});
}
function verify(){return JSON.parse(cp.execFileSync('node',['docs/qa/replay-imported-bar-20261104/verify.mjs'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:root}}));}
try{
 await q.record('package-source-before',verify());await launch();
 await q.s.page.goto(new URL('/strategy.html',q.s.page.url()).href,{waitUntil:'domcontentloaded'});
 await q.s.page.getByTestId('research-data-source-bar').getByRole('button',{name:'打开本地资料库',exact:true}).click();
 const form=q.s.page.getByTestId('research-data-import-form');await form.waitFor();
 await form.locator('input[type=file]').setInputFiles(root+'/imported-replay.csv');
 await form.getByLabel('数据集名称',{exact:true}).fill('Native Imported BAR Replay');await form.getByLabel('商品',{exact:true}).fill('BTCUSDT');
 await form.getByRole('combobox',{name:'时间格式',exact:true}).selectOption('ms');
 await form.getByRole('button',{name:'导入到本地资料库',exact:true}).click();await form.waitFor({state:'hidden',timeout:30000});
 await q.record('imported-through-library-ui',{bars:count,start,source:'CSV closed OHLCV, future extreme after row4500'});
 await q.s.page.getByRole('navigation').getByRole('link',{name:'回放训练',exact:true}).waitFor({timeout:20000});
 await q.s.page.getByRole('navigation').getByRole('link',{name:'回放训练',exact:true}).click();await group('training-hub');
 await execute('training-hub','openCreate');
 await execute('training-hub','draft',{name:'Native Imported Replay',sourceKind:'BAR',startMode:'MANUAL',requestedStartMs:start+100*60000,
  indicatorWarmupBars:10,forwardCacheMs:60*60000,visibleHistoryMode:'ALL_AVAILABLE',displayInterval:'1m',baseInterval:'1m',
  timeDisclosurePolicy:'NONE',integrityMode:'PRACTICE',positionMode:'ONE_WAY',fundingMode:'OFF',bookMode:'OFF',accountDataMode:'APPROX_PROXY'});
 const setup=await q.until(async()=>{const s=await query('training-hub');return !s.operation&&s.evaluation?.canSubmit?s:false;},30000);
 assert.equal(setup.automaticPreparationAvailable,false);await q.record('offline-training-setup',setup);
 await execute('training-hub','createRun');await group('replay-initial-market');
 const picker=await q.until(async()=>{const p=await query('replay-initial-market');return p.catalog?.entries?.length?p:false;},30000);
 const entry=picker.catalog.entries.find(e=>e.identity.symbol==='BTCUSDT'&&e.identity.market_type==='local_bar');assert.ok(entry,JSON.stringify(picker));
 await execute('replay-initial-market','select',{marketKey:`${entry.identity.exchange}:${entry.identity.market_type}:${entry.identity.symbol}`});
 await group('replay');let view=await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading&&!v.controlPending&&!v.viewerPending?v:false;},60000);
 const runId=view.runId,tracks=await json(`/api/v1/replay/runs/${runId}/tracks`),track=tracks.tracks[0],session=track.adapter_session_id;
 assert.ok(session);let state=(await json(`/api/v1/replay/sessions/${session}`)).snapshot;
 assert.equal(state.config.exchange,entry.identity.exchange);assert.equal(state.config.source_kind,'BAR');
 await q.record('formal-replay-initialized',{runId,track,state});
 await execute('replay','control',{type:'acquire_controller'});
 await execute('replay','trade',{type:'place_order',payload:{client_order_id:'native-imported-buy',side:'BUY',order_type:'MARKET',quantity:'0.1',reduce_only:false,limit_price:null,stop_price:null}});
 await execute('replay','control',{type:'step_base'});
 state=(await json(`/api/v1/replay/sessions/${session}`)).snapshot;
 assert.ok(state.components.fills.length>0,JSON.stringify(state.components));
 const cursor=state.cursor;
 await execute('replay','displayInterval',{interval:'5m'});
 assert.deepEqual((await json(`/api/v1/replay/sessions/${session}`)).snapshot.cursor,cursor);
 await q.screenshot('formal-imported-bar');await q.record('trade-step-and-period-change',{state,cursor,viewer:await query('replay')});
 assert.ok(q.s.traffic.sockets.some(s=>s.url.includes('/stream/replay/')&&s.received>0),'Actual replay WS did not deliver frames');
 const h=await json('/health');assert.equal(h.local_offline.network.blocked_attempts,0);await q.record('offline-boundary',h);
 const before=(await json(`/api/v1/replay/sessions/${session}`)).snapshot;
 await q.record('first-full-exit',{owned:await q.quit(),allExited:await q.exited()});
 await launch();await q.s.page.goto(new URL(`/replay.html?run=${runId}`,q.s.page.url()).href,{waitUntil:'domcontentloaded'});await group('replay');
 await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading?v:false;},60000);
 const after=(await json(`/api/v1/replay/sessions/${session}`)).snapshot;
 assert.deepEqual(after.cursor,before.cursor);assert.deepEqual(after.components,before.components);assert.deepEqual(after.config,before.config);
 await q.screenshot('restored-imported-replay');await q.record('restored-source-account-and-cursor',{runId,before,after});
 assert.equal((await json('/health')).local_offline.network.blocked_attempts,0);assert.deepEqual(q.s.receipt.errors,[]);
 await q.record('second-full-exit',{owned:await q.quit(),allExited:await q.exited()});await q.record('package-source-after',verify());
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));q.s.receipt.passed=true;await q.save();console.log('IMPORTED BAR NATIVE PASS');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);
 try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}
 try{await q.quit();await q.exited();}catch{}
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));process.exitCode=1;
}
