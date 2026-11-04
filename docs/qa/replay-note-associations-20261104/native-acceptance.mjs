import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../replay-imported-bar-20261104/native-driver.mjs';
const root=q.s.root;
q.s.receipt.scope='Native macOS LOCAL_OFFLINE formal replay version-bound fill/trade links: actual create/edit/historical version API and history UI, retained draft/full owned exit/restart on imported BAR; not screenshot attachments or whole166.';
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
async function group(id){return q.until(async()=>{
 try{const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});return groups.find(g=>g.id===id)||false;}
 catch(error){if(error.code==='WINDOW_UNAVAILABLE')return false;throw error;}
},30000);}
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
async function chartProjection(runId,track,session,state){
 const params=new URLSearchParams({track_id:track.track_id, revealed_boundary_ms:String(state.cursor.virtual_time_ms),
   limit:'100', data_epoch:state.data_epoch, display_interval:'5m'});
 await q.until(async()=>{
  const body=await q.s.page.locator('body').innerText(),count=Number(body.match(/显示\s*(\d+)\s*根\s*K\s*线/)?.[1]??0);
  return await q.s.page.locator('canvas').count()>0 && count>=10 && !body.includes('source-aligned display projection');
 },30000);
 const p=await json(`/api/v1/replay/runs/session/${session}/display-projection?${params}`);
 assert.ok(p.bars.length>0,JSON.stringify(p));
 assert.ok(p.bars.every(b=>Number(b.high)<200 && b.last_base_open_ms+59999<=state.cursor.virtual_time_ms),JSON.stringify(p));
 return {...p,visibleFooter:await q.s.page.locator('#status-bar').innerText()};
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
  timeDisclosurePolicy:'NONE',integrityMode:'PRACTICE',allowedMutations:['deposit'],positionMode:'ONE_WAY',fundingMode:'OFF',bookMode:'OFF',accountDataMode:'APPROX_PROXY'});
 const setup=await q.until(async()=>{const s=await query('training-hub');return !s.operation&&s.evaluation?.canSubmit?s:false;},30000);
 assert.equal(setup.automaticPreparationAvailable,false);await q.record('offline-training-setup',setup);
 await execute('training-hub','createRun');await group('replay-initial-market');
 const picker=await q.until(async()=>{const p=await query('replay-initial-market');return p.catalog?.entries?.length?p:false;},30000);
 const entry=picker.catalog.entries.find(e=>e.identity.symbol==='BTCUSDT'&&e.identity.market_type==='local_bar');assert.ok(entry,JSON.stringify(picker));
 await execute('replay-initial-market','select',{marketKey:`${entry.identity.exchange}:${entry.identity.market_type}:${entry.identity.symbol}`});
 await group('replay');let view=await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading&&!v.controlPending&&!v.viewerPending?v:false;},60000);
 const runId=view.runId,tracks=await json(`/api/v1/replay/runs/${runId}/tracks`),track=tracks.tracks[0],session=track.adapter_session_id;
 assert.ok(session);let state=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 assert.equal(state.config.exchange,entry.identity.exchange);assert.equal(state.config.source_kind,'bar');
 await q.record('formal-replay-initialized',{runId,track,state});
 await execute('replay','control',{type:'acquire_controller',payload:{takeover:false}});
 const notesPath=`/api/v1/replay/runs/${runId}/tracks/${track.track_id}/notes`;
 const notePanel=()=>q.s.page.getByTestId('replay-notes-panel');
 async function saveNote(){
  const response=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===notesPath && r.request().method()==='POST',{timeout:30000});
  await notePanel().getByRole('button',{name:'保存并关闭',exact:true}).click();
  const saved=await response;assert.equal(saved.status(),200,await saved.text());
  const value=await saved.json();await notePanel().locator('textarea').waitFor({state:'hidden'});return value;
 }
 const financialBeforePlan=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 await q.s.page.locator('button[data-rail-view="replay-notes"]').click();
 await notePanel().getByRole('button',{name:'新增笔记',exact:true}).click();
 await notePanel().locator('textarea').fill('原生事前计划：保持回放时钟和账户不变');
 const originalNote=await saveNote();
 assert.deepEqual((await json(`/api/v1/replay/runs/session/${session}`)).snapshot,financialBeforePlan);
 await q.record('native-original-plan',{note:originalNote,unchangedFinancialSnapshot:true});
 await execute('replay','trade',{type:'place_order',payload:{client_order_id:'native-imported-buy',side:'BUY',order_type:'MARKET',quantity:'0.1',reduce_only:false,limit_price:null,stop_price:null}});
 await execute('replay','control',{type:'step_base',payload:{count:1}});
 state=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 assert.ok(state.components.fills.length>0,JSON.stringify(state.components));
 const financialBeforeEdit=state;
 await notePanel().getByRole('button',{name:'编辑',exact:true}).click();
 await notePanel().locator('textarea').fill('原生推进后的修改：版本随市场时间生效');
 await notePanel().getByRole('button',{name:'选择成交',exact:true}).click();
 await notePanel().getByTestId('replay-note-link-options').getByRole('checkbox').first().check();
 let laterNote=await saveNote();assert.equal(laterNote.id,originalNote.id);assert.equal(laterNote.revisionCount,2);
 assert.ok(laterNote.effectiveTimeMs>originalNote.effectiveTimeMs);
 const historical=await json(notesPath+'?at_time_ms='+originalNote.effectiveTimeMs);
 assert.equal(historical.notes.length,1);assert.equal(historical.notes[0].fields.entryBasis,originalNote.fields.entryBasis);
 assert.equal(historical.notes[0].revisionCount,1);
 assert.deepEqual((await json(`/api/v1/replay/runs/session/${session}`)).snapshot,financialBeforeEdit);
 assert.equal(laterNote.links.length,1);assert.equal(laterNote.links[0].kind,'FILL');
 await q.record('native-time-versioned-edit',{laterNote,historical,unchangedFinancialSnapshot:true});
 const fillNote=laterNote;
 await execute('replay','trade',{type:'place_order',payload:{client_order_id:'native-linked-close',side:'SELL',order_type:'MARKET',quantity:'0.1',reduce_only:true,limit_price:null,stop_price:null}});
 state=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 assert.equal(state.components.closed_trades.length,1);
 await notePanel().getByRole('button',{name:'编辑',exact:true}).click();
 await notePanel().getByRole('button',{name:'选择交易',exact:true}).click();
 await notePanel().getByTestId('replay-note-link-options').getByRole('checkbox').first().check();
 const financeBeforeTradeLink=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 laterNote=await saveNote();assert.equal(laterNote.revisionCount,3);
 assert.deepEqual(laterNote.links.map(link=>link.kind),['FILL','TRADE']);
 assert.deepEqual((await json(`/api/v1/replay/runs/session/${session}`)).snapshot,financeBeforeTradeLink);
 await q.record('native-trade-link',{laterNote,fillNote,unchangedFinancialSnapshot:true});
 async function inspectHistory(stage){
  const article=notePanel().locator(`article[data-note-id="${originalNote.id}"]`);
  await article.getByRole('button',{name:'版本历史',exact:true}).click();
  await q.until(async()=>await article.locator('[data-note-version]').count()===3,30000);
  assert.equal(await article.locator('[data-note-version="1"] .replay-note-text').innerText(),originalNote.fields.entryBasis);
  assert.equal(await article.locator('[data-note-version="2"] .replay-note-text').innerText(),fillNote.fields.entryBasis);
  assert.equal(await article.locator('[data-note-version="1"] [data-testid="replay-note-links"]').count(),0);
  assert.equal(await article.locator('[data-note-version="2"] [data-testid="replay-note-links"] li').count(),1);
  assert.equal(await article.locator('[data-note-version="3"] [data-testid="replay-note-links"] li').count(),2);
  assert.equal(await article.getByRole('button',{name:'加载更早版本',exact:true}).count(),0);
  const versions=await json(notesPath+'/'+originalNote.id+'/versions');
  assert.deepEqual(versions.versions,[laterNote,fillNote,originalNote]);
  await q.screenshot('note-version-history-'+stage);await q.record('native-note-history-'+stage,{versions,uiVersionRows:3});
  await article.getByRole('button',{name:'版本历史',exact:true}).click();
 }
 await inspectHistory('before-exit');
 const cursor=state.cursor;
 await execute('replay','displayInterval',{interval:'5m'});
 await q.until(async()=>{const v=await json(`/api/v1/replay/runs/${runId}/viewer`);return v.viewer_state.display_interval==='5m';},30000);
 await q.delay(750);
 assert.equal((await json(`/api/v1/replay/runs/${runId}/viewer`)).viewer_state.display_interval,'5m');
 assert.equal(await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).inputValue(),'5m');
 await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).selectOption('15m');
 await q.until(async()=> (await json(`/api/v1/replay/runs/${runId}/viewer`)).viewer_state.display_interval==='15m',30000);
 await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).selectOption('5m');
 await q.until(async()=> (await json(`/api/v1/replay/runs/${runId}/viewer`)).viewer_state.display_interval==='5m',30000);
 await q.delay(750);
 assert.equal(await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).inputValue(),'5m');
 assert.deepEqual((await json(`/api/v1/replay/runs/session/${session}`)).snapshot.cursor,cursor);
 await q.record('rendered-source-prefix-5m',await chartProjection(runId,track,session,state));
 await q.screenshot('formal-imported-bar');await q.record('trade-step-and-period-change',{state,cursor,viewer:await query('replay')});
 assert.ok(q.s.traffic.sockets.some(s=>s.url.includes('/stream/replay/')&&s.received>0),'Actual replay WS did not deliver frames');
 const h=await json('/health');assert.equal(h.local_offline.network.blocked_attempts,0);await q.record('offline-boundary',h);
 const before=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 await notePanel().getByRole('button',{name:'编辑',exact:true}).click();
 await notePanel().locator('textarea').fill('原生完整退出后保留的未保存草稿');
 await q.screenshot('note-draft-before-exit');
 await q.record('native-unsaved-draft',{marketTimeMs:before.cursor.virtual_time_ms,expectedRevision:3,text:'原生完整退出后保留的未保存草稿'});
 await q.record('first-full-exit',{owned:await q.quit(),allExited:await q.exited()});
 await launch();await q.s.page.goto(new URL(`/replay.html?run=${runId}`,q.s.page.url()).href,{waitUntil:'domcontentloaded'});await group('replay');
 await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading?v:false;},60000);
 const after=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 assert.equal((await json(`/api/v1/replay/runs/${runId}/viewer`)).viewer_state.display_interval,'5m');
 assert.equal(await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).inputValue(),'5m');
 assert.deepEqual(after.cursor,before.cursor);assert.deepEqual(after.components,before.components);assert.deepEqual(after.config,before.config);
 await notePanel().getByText('原生推进后的修改：版本随市场时间生效',{exact:true}).waitFor({timeout:30000});
 const restoredNotes=await json(notesPath);assert.deepEqual(restoredNotes.notes,[laterNote]);
 await notePanel().getByRole('button',{name:/^恢复草稿/}).click();
 assert.equal(await notePanel().locator('textarea').inputValue(),'原生完整退出后保留的未保存草稿');
 const financialBeforeRecovery=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 const rejected=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===notesPath&&r.request().method()==='POST',{timeout:30000});
 await notePanel().getByRole('button',{name:'保存',exact:true}).click();
 const stale=await rejected;assert.equal(stale.status(),409);assert.equal((await stale.json()).error.code,'REPLAY_NOTE_CONTEXT_CHANGED');
 assert.equal(await notePanel().locator('textarea').inputValue(),'原生完整退出后保留的未保存草稿');
 await notePanel().getByRole('button',{name:'另存为当前时刻的新笔记',exact:true}).click();
 const recoveredNote=await saveNote();assert.notEqual(recoveredNote.id,originalNote.id);assert.equal(recoveredNote.revisionCount,1);
 assert.equal(recoveredNote.fields.entryBasis,'原生完整退出后保留的未保存草稿');
 const recoveryRetained=await q.s.page.evaluate(()=>Object.keys(localStorage).some(key=>key.startsWith('candlescope.replay-note-draft.v1:')
  &&localStorage.getItem(key)?.includes('原生完整退出后保留的未保存草稿')));
 assert.ok(recoveryRetained,'Explicit new note erased the original stale recovery draft');
 const finalNotes=await json(notesPath);assert.deepEqual(finalNotes.notes.find(n=>n.id===originalNote.id),laterNote);
 await q.record('stale-context-explicit-copy',{rejectedCode:'REPLAY_NOTE_CONTEXT_CHANGED',recoveryRetained,oldSavedVersionPreserved:true});
 await inspectHistory('restored');
 assert.deepEqual((await json(`/api/v1/replay/runs/session/${session}`)).snapshot,financialBeforeRecovery);
 await q.screenshot('restored-saved-note-and-draft');
 await q.record('native-note-and-draft-restored',{restoredNotes,recoveredNote,unchangedFinancialSnapshot:true});
 await q.record('restored-rendered-source-prefix-5m',await chartProjection(runId,track,session,after));
 await q.screenshot('restored-imported-replay');await q.record('restored-source-account-and-cursor',{runId,before,after});
 assert.equal((await json('/health')).local_offline.network.blocked_attempts,0);assert.deepEqual(q.s.receipt.errors,[]);
 await q.record('second-full-exit',{owned:await q.quit(),allExited:await q.exited()});await q.record('package-source-after',verify());
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));q.s.receipt.passed=true;await q.save();console.log('FORMAL REPLAY NOTES NATIVE PASS');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);
 try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}
 try{await q.quit();await q.exited();}catch{}
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));process.exitCode=1;
}
