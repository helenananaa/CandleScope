import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../replay-imported-multimarket-20261106/native-driver.mjs';

const root=q.s.root;
const manifest=JSON.parse(await fs.readFile(root+'/source-package-manifest.json','utf8'));
const seed=JSON.parse(await fs.readFile(root+'/multimarket-identities.json','utf8'));
q.s.receipt.driverCheckout=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.scope='Actual packaged LOCAL_OFFLINE replay chart closure, shared-adapter consumer lifetime, hidden FULL-track advancement and same-profile restart; synthetic copy, original preserved.';
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',REPLAY_ENABLED:'1',
 KLINES_DB_PATH:root+'/profile/data/market.db',REPLAY_DB_PATH:root+'/profile/data/replay.db',
 BACKTEST_DB_PATH:root+'/profile/data/backtest.db',BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1'};
try{await fs.stat(root+'/acceptance.json');throw new Error('Preserve previous attempts');}catch(error){if(error.code!=='ENOENT')throw error;}
const runId=seed.runId,btc=seed.tracks.find(t=>t.symbol==='BTCUSDT'),eth=seed.tracks.find(t=>t.symbol==='ETHUSDT');
assert.ok(btc&&eth);
const requests=[],urls=[];
const verify=()=>JSON.parse(cp.execFileSync('node',['docs/qa/replay-imported-multimarket-20261106/verify.mjs'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:root}}));
async function json(path){const r=await fetch(q.s.backend+path);assert.ok(r.ok,await r.clone().text());return r.json();}
async function query(id){return (await q.s.control.call('app.query',{windowId:'main-window',groupId:id,command:'inspect',args:{}})).snapshot;}
async function groups(){return (await q.s.control.call('app.commands',{windowId:'main-window'})).groups;}
async function idle(){return q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading&&!v.viewerPending&&!v.controlPending?v:false;},30000);}
async function execute(id,command,args={}){
 if(id==='replay')await idle();
 const g=(await groups()).find(g=>g.id===id);assert.ok(g,id);
 const requestId='native-lifecycle-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:id,command,args,requestId,expectedContext:g.contextToken});
 const r=await q.until(async()=>{const value=await q.s.control.call('request.get',{requestId});return value.final?value:false;},60000);
 assert.equal(r.state,'applied',JSON.stringify(r));return r;
}
const cells=()=>q.s.page.locator('section.replay-chart-cell');
const cell=id=>q.s.page.locator(`section.replay-chart-cell[data-chart-cell-id="${id}"]`);
const trackCells=t=>q.s.page.locator(`section.replay-chart-cell[data-replay-track-id="${t.track_id}"]`);
// Electron's detached inspector need not deliver a socket close callback during
// full application quit. Earlier-process observations remain in traffic.json;
// only this launch's actual backend endpoint defines its current consumers.
function sockets(t){return q.s.traffic.sockets.filter(s=>new URL(s.url).host===new URL(q.s.backend).host&&s.url.includes('/stream/replay/'+t.adapter_session_id+'?'));}
function openSockets(t){return sockets(t).filter(s=>!s.closedAt);}
async function current(){const result={};for(const t of seed.tracks)result[t.track_id]=(await json('/api/v1/replay/runs/session/'+t.adapter_session_id)).snapshot;return result;}
function financial(state){return Object.fromEntries(Object.entries(state).map(([id,s])=>[id,{cursor:s.cursor,components:s.components,data_epoch:s.data_epoch}]));}
async function view(label){
 await idle();
 const state=await current(),readinessStarted=Date.now(),observations=[];
 // A command acknowledgement precedes receipt/rendering of its committed run
 // projection. Observe that real projection becoming current; never replace it.
 const viewer=await q.until(async()=>{
  const value=await query('replay');const portfolio=value.tracks?.portfolio;
  observations.push({at:Date.now(),equity:portfolio?.equity,marks:portfolio?.positions?.map(p=>({track:p.track_id,mark:p.position.mark_price}))});
  await fs.writeFile(root+'/portfolio-readiness.json',JSON.stringify({label,observations},null,2));
  return portfolio&&seed.tracks.every(t=>portfolio.positions.some(p=>p.track_id===t.track_id&&p.position.mark_price===state[t.track_id].components.position.mark_price))?value:false;
 },30000);
 const dom=[];for(const id of await cells().evaluateAll(rows=>rows.map(r=>r.dataset.chartCellId))){
  const c=cell(id);
  const indicatorReadiness=await q.until(async()=>{const g=(await groups()).find(g=>g.id.startsWith('chart:replay:')&&g.id.endsWith(':'+id));if(!g)return false;const snapshot=await query(g.id);return !snapshot.computing&&snapshot.indicators.every(i=>!i.error&&i.outputPointCount>0)?snapshot:false;},30000);
  await c.locator('.chart-main-legend').waitFor();
  dom.push({id,track:await c.getAttribute('data-replay-track-id'),header:await c.locator('header').innerText(),legend:await c.locator('.chart-main-legend').getAttribute('aria-label'),indicatorReadiness});
 }
 const row={state,viewer,dom,backend:q.s.backend,projectionReadiness:{elapsedMs:Date.now()-readinessStarted,observations},groups:(await groups()).map(g=>g.id),sockets:structuredClone({btc:sockets(btc),eth:sockets(eth)})};
 await q.record(label,row);return row;
}
async function launch(){
 await q.launch();
 q.s.page.on('request',r=>{const u=new URL(r.url());if(['http:','https:','ws:','wss:'].includes(u.protocol))urls.push(u.href);if(u.pathname.includes('/api/'))requests.push({at:Date.now(),method:r.method(),path:u.pathname,body:r.postData()});});
 q.s.page.on('websocket',s=>urls.push(s.url()));
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});await q.enableControl();
 await q.s.page.goto(new URL('/replay.html?run='+runId,q.s.page.url()).href,{waitUntil:'domcontentloaded'});
 await q.until(async()=>{try{return (await groups()).some(g=>g.id==='replay');}catch{return false;}},30000);
 await idle();await q.record('packaged-launch',{identity:q.s.identity,bootstrap:q.s.bootstrap});
}
async function boundary(){const h=await json('/health');assert.equal(h.runtime_mode,'LOCAL_OFFLINE');assert.equal(h.local_offline.network.installed,true);assert.equal(h.local_offline.network.blocked_attempts,0);assert.deepEqual(urls.filter(u=>!['127.0.0.1','localhost','[::1]'].includes(new URL(u).hostname)),[]);await q.record('offline-boundary',{health:h,urls});}
async function closeCell(id){
 await cell(id).locator('.multi-chart-cell-layout-trigger').click();
 await q.s.page.getByRole('dialog').filter({has:q.s.page.getByRole('button',{name:'关闭此图表',exact:true})}).getByRole('button',{name:'关闭此图表',exact:true}).click();
 await cell(id).waitFor({state:'detached'});await idle();
}
async function reopenEth(){
 const search=q.s.page.getByRole('searchbox',{name:'搜索本次训练可用商品',exact:true});
 if(!await search.isVisible())await q.s.page.locator('button[data-rail-view="replay-watchlist"]').click();
 await search.fill('ETHUSDT');
 const row=q.s.page.locator(`.replay-watchlist-row[data-replay-track-id="${eth.track_id}"]`);
 await row.getByRole('button',{name:'ETHUSDT · 在新图表打开',exact:true}).click();
 await q.until(async()=>await trackCells(eth).count()===1&&openSockets(eth).length===1,30000);await idle();
 const id=await trackCells(eth).getAttribute('data-chart-cell-id');await trackCells(eth).locator('canvas').first().waitFor();return id;
}
async function quit(label){const owned=await q.quit();await q.exited();const present=cp.execFileSync('ps',['-axo','pid='],{encoding:'utf8'}).trim().split(/\s+/).map(Number);assert.deepEqual(owned.filter(p=>present.includes(p.pid)),[]);await q.record(label,{owned,independentlyAbsent:true});}

try{
 await q.record('package-before',verify());await launch();
 await q.until(async()=>await cells().count()===2&&openSockets(btc).length===1&&openSockets(eth).length===1,30000);
 const initial=await view('initial-two-restored-charts');assert.equal(initial.dom.filter(d=>d.track===btc.track_id).length,1);assert.equal(initial.dom.filter(d=>d.track===eth.track_id).length,1);
 const oldEth=await trackCells(eth).getAttribute('data-chart-cell-id');
 await closeCell(oldEth);await q.until(async()=>openSockets(eth).length===0&&openSockets(btc).length===1,30000);
 const closed=await view('secondary-chart-last-consumer-closed');assert.deepEqual(financial(closed.state),financial(initial.state));assert.equal(closed.dom.length,1);assert.ok(closed.dom[0].header.includes('BTCUSDT'));assert.ok(closed.groups.every(g=>!g.endsWith(':'+oldEth)));
 const firstEth=await reopenEth();
 // Opening a new chart copies the active chart's period. Establish the two
 // intended periods through actual UI actions, rather than assuming a default.
 await cell(firstEth).locator('header strong').click();await idle();await execute('replay','displayInterval',{interval:'1m'});
 await q.until(async()=> (await cell(firstEth).locator('header').innerText()).includes('1m'),30000);
 const reopened=await view('secondary-chart-reopened');assert.deepEqual(financial(reopened.state),financial(closed.state));assert.equal(openSockets(eth).length,1);
 const streamBeforeSplit=openSockets(eth)[0];
 await cell(firstEth).locator('.multi-chart-cell-layout-trigger').click();await q.s.page.getByRole('button',{name:'向右拆分',exact:true}).click();
 await q.until(async()=>await cells().count()===3&&await trackCells(eth).count()===2,30000);
 const ethIds=await trackCells(eth).evaluateAll(rows=>rows.map(r=>r.dataset.chartCellId));const duplicate=ethIds.find(id=>id!==firstEth);assert.ok(duplicate);
 await cell(duplicate).locator('header strong').click();await idle();await execute('replay','displayInterval',{interval:'5m'});
 await q.until(async()=> (await cell(duplicate).locator('header').innerText()).includes('5m'),30000);
 const split=await view('same-adapter-two-period-consumers');assert.deepEqual(financial(split.state),financial(reopened.state));assert.equal(openSockets(eth).length,1);assert.equal(openSockets(eth)[0],streamBeforeSplit);assert.equal(streamBeforeSplit.closedAt,undefined);
 assert.ok(split.dom.find(d=>d.id===firstEth).header.includes('1m'));assert.ok(split.dom.find(d=>d.id===duplicate).header.includes('5m'));
 const geometry=[];
 for(const id of await cells().evaluateAll(rows=>rows.map(r=>r.dataset.chartCellId))){
  const measured=await cell(id).locator('.chart-main-legend').evaluate(legend=>{
   const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
   const close=Array.from(legend.querySelectorAll('.chart-main-ohlcv > span')).find(s=>s.querySelector('.chart-legend-key')?.textContent.trim()==='C')?.querySelector('strong');
   return {legend:rect(legend),close:close?{text:close.textContent,...rect(close)}:null,numbers:Array.from(legend.querySelectorAll('.chart-main-indicator-row .chart-legend-number')).map(e=>({text:e.textContent,...rect(e)}))};
  });
  assert.ok(measured.legend.width>0&&measured.legend.height>0);assert.ok(measured.close);assert.equal(measured.numbers.length,1);
  for(const value of [measured.close,...measured.numbers])assert.ok(value.width>0&&value.left>=measured.legend.left-1&&value.right<=measured.legend.right+1&&value.top>=measured.legend.top-1&&value.bottom<=measured.legend.bottom+1,JSON.stringify({id,measured}));
  geometry.push({id,...measured});
 }
 await q.screenshot('three-horizontal-charts-after-fix');await q.record('three-horizontal-legends-unclipped',geometry);
 await closeCell(duplicate);const oneEth=await view('one-of-two-consumers-closed');assert.deepEqual(financial(oneEth.state),financial(split.state));assert.equal(openSockets(eth).length,1);assert.equal(openSockets(eth)[0],streamBeforeSplit);assert.equal(streamBeforeSplit.closedAt,undefined);
 await q.until(async()=>await cell(firstEth).locator('.chart-main-legend').isVisible(),30000);
 await closeCell(firstEth);await q.until(async()=>openSockets(eth).length===0&&openSockets(btc).length===1,30000);
 const onlyBtc=await view('last-secondary-consumer-closed-again');assert.deepEqual(financial(onlyBtc.state),financial(oneEth.state));assert.equal(onlyBtc.dom.length,1);
 // The secondary FULL track still belongs to the run/account even without a chart.
 await execute('replay','control',{type:'step_base',payload:{count:3}});
 const advanced=await view('hidden-full-track-global-advance');
 for(const t of seed.tracks){const before=onlyBtc.state[t.track_id],after=advanced.state[t.track_id];assert.ok(after.cursor.virtual_time_ms>before.cursor.virtual_time_ms);assert.equal(after.data_epoch,before.data_epoch);assert.equal(after.components.fills.length,before.components.fills.length);}
 assert.equal(advanced.state[btc.track_id].cursor.virtual_time_ms,advanced.state[eth.track_id].cursor.virtual_time_ms);
 assert.equal(openSockets(eth).length,0);await boundary();await q.screenshot('one-chart-before-restart');await quit('first-full-owned-exit');
 await launch();await q.until(async()=>await cells().count()===1&&openSockets(btc).length===1,30000);
 const restored=await view('single-chart-layout-restored');assert.equal(restored.dom.length,1);assert.deepEqual(financial(restored.state),financial(advanced.state));assert.equal(openSockets(eth).length,0);
 await reopenEth();const final=await view('hidden-track-reopened-after-restart');assert.deepEqual(financial(final.state),financial(restored.state));assert.equal(openSockets(eth).length,1);assert.equal(final.dom.length,2);
 await boundary();assert.deepEqual(q.s.receipt.errors,[]);await q.screenshot('two-charts-reopened-after-restart');await quit('second-full-owned-exit');await q.record('package-after',verify());
 const orders=requests.filter(r=>r.method==='POST'&&r.body&&JSON.parse(r.body).type==='place_order');assert.deepEqual(orders,[]);await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));q.s.receipt.passed=true;await q.save();console.log('NATIVE MULTICHART LIFECYCLE PASS; independent hidden-track financial audit still required');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}try{await q.quit();await q.exited();}catch{}await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));process.exitCode=1;}
