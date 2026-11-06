import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../replay-imported-multimarket-20261106/native-driver.mjs';
const root=q.s.root;
q.s.receipt.driverCheckout=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=JSON.parse(await fs.readFile(root+'/source-package-manifest.json','utf8')).sourceCommit;
q.s.receipt.scope='Additional actual MA5 inputs/output and rendered legend/review boundary qualification. Packaged macOS LOCAL_OFFLINE imported BAR two-market/two-chart source isolation, independent periods/notes/screenshots/fill links, global step, actual Review history, and full owned quit/restart; no public feed, AGG_TRADE or Windows qualification.';
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',REPLAY_ENABLED:'1',
 KLINES_DB_PATH:root+'/profile/data/market.db',REPLAY_DB_PATH:root+'/profile/data/replay.db',
 BACKTEST_DB_PATH:root+'/profile/data/backtest.db',BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1'};
try{await fs.stat(root+'/profile');throw new Error('Preserve existing profile; use a fresh candidate');}catch(e){if(e.code!=='ENOENT')throw e;}
await fs.mkdir(root+'/profile/data',{recursive:true});
const start=1700000040000,count=6000;
await fs.writeFile(root+'/imported-replay.csv','time,open,high,low,close,volume\n'+Array.from({length:count},(_,i)=>{
 const price=i>4500?1000000:100+i%20;return `${start+i*60000},${price},${price+2},${price-1},${price+1},100`;
}).join('\n'));
const requests=[],allUrls=[],indicatorComputations=[];const responseWork=new Set();
async function json(path){const r=await fetch(q.s.backend+path);assert.ok(r.ok,await r.clone().text());return r.json();}
async function query(id){return (await q.s.control.call('app.query',{windowId:'main-window',groupId:id,command:'inspect',args:{}})).snapshot;}
async function group(id){return q.until(async()=>{
 try{const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});return groups.find(g=>g.id===id)||false;}
 catch(error){if(error.code==='WINDOW_UNAVAILABLE')return false;throw error;}
},30000);}
async function stableReplayIdle(){
 let key=null,since=0;
 return q.until(async()=>{
  const value=await query('replay');
  const active=q.s.page.locator('section.replay-chart-cell.active');
  const activeId=await active.count()?await active.getAttribute('data-replay-track-id'):null;
  const ready=value.viewer&&!value.loading&&!value.viewerPending&&!value.controlPending&&(!activeId||value.viewer.selected_track_id===activeId);
  const next=ready?JSON.stringify([value.viewer,activeId]):null;
  if(!next||next!==key){key=next;since=Date.now();return false;}
  return Date.now()-since>=600?value:false;
 },30000);
}
async function execute(id,command,args={}){
 if(id==='replay')await stableReplayIdle();
 const g=await group(id),requestId='imported-replay-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:id,command,args,requestId,expectedContext:g.contextToken});
 const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;},60000);
 assert.equal(result.state,'applied',JSON.stringify(result));return result;
}
async function launch(){
 await q.launch();q.s.page.on('response',r=>{if(!new URL(r.url()).pathname.endsWith('/indicator-compute'))return;const work=(async()=>{try{indicatorComputations.push({at:Date.now(),url:r.url(),status:r.status(),request:r.request().postDataJSON(),response:await r.json()});}catch(error){indicatorComputations.push({url:r.url(),observationError:String(error)});}})();responseWork.add(work);work.finally(()=>responseWork.delete(work));});q.s.page.on('request',r=>{if(r.url().includes('/api/'))requests.push({at:Date.now(),method:r.method(),path:new URL(r.url()).pathname,body:r.postData()});});
 q.s.page.on('request',r=>{const u=new URL(r.url());if(['http:','https:','ws:','wss:'].includes(u.protocol))allUrls.push(u.href);});
 q.s.page.on('websocket',ws=>allUrls.push(ws.url()));
 const h=await json('/health');assert.equal(h.local_offline.network.installed,true);assert.equal(h.runtime_mode,'LOCAL_OFFLINE');assert.equal(h.local_offline.network.blocked_attempts,0);
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
function verify(){return JSON.parse(cp.execFileSync('node',['docs/qa/replay-multichart-indicator-boundary-20261106/verify.mjs'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:root}}));}
try{
 await q.record('package-source-before',verify());await launch();
 await q.s.page.goto(new URL('/strategy.html',q.s.page.url()).href,{waitUntil:'domcontentloaded'});
 await q.s.page.getByTestId('research-data-source-bar').getByRole('button',{name:'打开本地资料库',exact:true}).click();
 const form=q.s.page.getByTestId('research-data-import-form');await form.waitFor();
 await form.locator('input[type=file]').setInputFiles(root+'/imported-replay.csv');
 await form.getByLabel('数据集名称',{exact:true}).fill('Native Imported BAR Replay');await form.getByLabel('商品',{exact:true}).fill('BTCUSDT');
 await form.getByRole('combobox',{name:'时间格式',exact:true}).selectOption('ms');
 await form.getByLabel('数量资产（成交量单位）',{exact:true}).fill('BTC');await form.getByLabel('价格计价资产',{exact:true}).fill('USDT');
 await form.getByRole('button',{name:'导入到本地资料库',exact:true}).click();await form.waitFor({state:'hidden',timeout:30000});
 await q.record('imported-through-library-ui',{bars:count,start,source:'CSV closed OHLCV, future extreme after row4500'});
 await q.s.page.getByTestId('research-data-source-bar').getByRole('button',{name:'打开本地资料库',exact:true}).click();
 await q.s.page.getByRole('tab',{name:'导入 CSV',exact:true}).click();
 const secondForm=q.s.page.getByTestId('research-data-import-form');await secondForm.waitFor();
 await fs.writeFile(root+'/second-replay.csv','time,open,high,low,close,volume\n'+Array.from({length:count},(_,i)=>{const price=i>4500?2000000:500+i%20;return `${start+i*60000},${price},${price+2},${price-1},${price+1},100`;}).join('\n'));
 await secondForm.locator('input[type=file]').setInputFiles(root+'/second-replay.csv');
 await secondForm.getByLabel('数据集名称',{exact:true}).fill('Native Imported ETH');await secondForm.getByLabel('商品',{exact:true}).fill('ETHUSDT');
 await secondForm.getByRole('combobox',{name:'时间格式',exact:true}).selectOption('ms');
 await secondForm.getByLabel('数量资产（成交量单位）',{exact:true}).fill('ETH');await secondForm.getByLabel('价格计价资产',{exact:true}).fill('USDT');
 await secondForm.getByRole('button',{name:'导入到本地资料库',exact:true}).click();await secondForm.waitFor({state:'hidden',timeout:30000});
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
 const runId=view.runId,initialTracks=await json(`/api/v1/replay/runs/${runId}/tracks`),track=initialTracks.tracks[0],session=track.adapter_session_id;
 assert.ok(session);let state=(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 assert.equal(state.config.exchange,entry.identity.exchange);assert.equal(state.config.source_kind,'bar');
 await q.record('formal-replay-initialized',{runId,track,state});
 await execute('replay','control',{type:'acquire_controller',payload:{takeover:false}});
 let notesPath=`/api/v1/replay/runs/${runId}/tracks/${track.track_id}/notes`;
 const notePanel=()=>q.s.page.getByTestId('replay-notes-panel');
 async function saveNote(){
  const response=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===notesPath && r.request().method()==='POST',{timeout:30000});
  await notePanel().getByRole('button',{name:'保存并关闭',exact:true}).click();
  const saved=await response;assert.equal(saved.status(),200,await saved.text());
  const value=await saved.json();await notePanel().locator('textarea').waitFor({state:'hidden'});return value;
 }
 async function captureImage(label){
  const response=q.s.page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/note-captures')&&r.request().method()==='POST',{timeout:30000});
  await notePanel().getByRole('button',{name:'截取当前图表',exact:true}).click();
  const uploaded=await response;assert.equal(uploaded.status(),200,await uploaded.text());
  const receipt=await uploaded.json(),request=uploaded.request().postDataJSON();
  await q.until(async()=>await notePanel().getByRole('button',{name:'保存并关闭',exact:true}).isEnabled(),30000);
  await q.record('native-png-upload-'+label,{receipt,encodedBytes:request.image.length});
  return {receipt,image:request.image};
 }
 async function inspectImage(note,capture,label,expected){
  const result=await json(notesPath+'/'+note.id+'/versions/'+note.revisionCount+'/screenshots/'+capture.id);
  assert.equal(result.image,expected);assert.equal(result.capture.id,capture.id);
  await fs.writeFile(root+'/actual-note-image-'+label+'.png',Buffer.from(result.image.slice(22),'base64'));
  const article=notePanel().locator(`article[data-note-id="${note.id}"]`);
  await article.getByRole('button',{name:/^查看截图 1/}).first().click();
  const dialog=q.s.page.getByRole('dialog',{name:'回放笔记截图',exact:true});
  await q.until(async()=>await dialog.locator('img').evaluate(image=>image.complete&&image.naturalWidth>0),30000);
  assert.equal(await dialog.locator('img').evaluate(image=>image.naturalWidth),capture.width);
  await q.screenshot('native-note-image-view-'+label);await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await q.record('native-png-view-'+label,{noteId:note.id,revision:note.revisionCount,capture,pixelsUnchanged:true});
 }
 const getTracks=async()=>(await json(`/api/v1/replay/runs/${runId}/tracks`)).tracks;
 async function snapshots(){const result={};for(const t of await getTracks())if(t.adapter_session_id)result[t.track_id]=(await json(`/api/v1/replay/runs/session/${t.adapter_session_id}`)).snapshot;return result;}
 const cell=id=>q.s.page.locator(`section.replay-chart-cell[data-replay-track-id="${id}"]`);
 async function focus(t){await cell(t.track_id).locator('header').first().getByText(t.symbol,{exact:true}).click();
  await q.until(async()=>{const v=await json(`/api/v1/replay/runs/${runId}/viewer`);return v.viewer_state.selected_track_id===t.track_id;},30000);
  await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading&&!v.viewerPending&&!v.controlPending;},30000);
  notesPath=`/api/v1/replay/runs/${runId}/tracks/${t.track_id}/notes`;
 }
 async function openNotes(){if(!await notePanel().isVisible())await q.s.page.locator('button[data-rail-view="replay-notes"]').click();
  const toggle=notePanel().getByRole('button',{name:'回放笔记',exact:true});if(await toggle.count()&&await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
 }
 const integrity=()=>q.s.page.locator('[data-replay-panel="integrity"]');
 async function openIntegrity(){if(!await integrity().isVisible())await q.s.page.locator('[data-replay-action="toggle-integrity"]').click();await integrity().getByRole('heading',{name:'只读复盘',exact:true}).waitFor();}
 async function closeIntegrity(){await integrity().locator('[data-replay-action="close-integrity"]').click();}
 async function marker(text){await openIntegrity();await integrity().getByLabel('手工复盘标记',{exact:true}).fill(text);const pending=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/replay/runs/${runId}/markers`&&r.request().method()==='POST');await integrity().getByRole('button',{name:'记录到不可变时间线',exact:true}).click();const r=await pending;assert.equal(r.status(),200,await r.text());const mark=await r.json();await closeIntegrity();await q.record('marker-'+text,mark);return mark;}
 const initial=await snapshots();
 await q.s.page.locator('button[data-rail-view="replay-watchlist"]').click();
 await q.s.page.getByRole('searchbox',{name:'搜索本次训练可用商品',exact:true}).fill('ETHUSDT');
 await q.s.page.getByRole('button',{name:'ETHUSDT · 在新图表打开',exact:true}).click();
 const all=await q.until(async()=>{const tracks=await getTracks();return tracks.length===2&&tracks.every(t=>t.adapter_session_id&&t.subscription_tier==='FULL')?tracks:false;},60000);
 const btc=all.find(t=>t.symbol==='BTCUSDT'),eth=all.find(t=>t.symbol==='ETHUSDT');assert.ok(btc&&eth);assert.notEqual(btc.exchange,eth.exchange);
 await q.until(async()=>await q.s.page.locator('section.replay-chart-cell').count()===2&&await cell(btc.track_id).locator('canvas').count()>0&&await cell(eth.track_id).locator('canvas').count()>0,30000);
 const afterAdd=await snapshots();assert.notEqual(afterAdd[btc.track_id].data_epoch,afterAdd[eth.track_id].data_epoch);assert.deepEqual(afterAdd[btc.track_id].cursor,initial[btc.track_id].cursor);
 for(const t of all)assert.equal(afterAdd[t.track_id].config.exchange,t.exchange);
 await q.record('two-imported-markets-added-through-native-ui',{tracks:all,afterAdd});
 async function assertCharts(){const result=[];for(const t of all){const ohlc=await q.until(async()=>{const group=cell(t.track_id).getByRole('group',{name:/^主图信息：/});return await group.count()?await group.getAttribute('aria-label'):false;},30000);const high=Number(ohlc.match(/最高\s*([\d,.]+)/)?.[1]?.replaceAll(',',''));assert.ok(high>(t.symbol==='BTCUSDT'?90:490)&&high<(t.symbol==='BTCUSDT'?200:600),ohlc);result.push({track:t.track_id,symbol:t.symbol,ohlc});}await q.record('independently-rendered-market-prices',result);}

 async function chartGroup(t){const cellId=await cell(t.track_id).getAttribute('data-chart-cell-id');return q.until(async()=>{const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});return groups.find(g=>g.id.startsWith('chart:replay:')&&g.id.endsWith(':'+cellId))||false;},30000);}
 async function legend(t){return cell(t.track_id).locator('.chart-main-legend').getAttribute('aria-label');}
 async function assertIndicators(label){
  const states=[];
  // Each rendered legend must contain a settled MA, rather than only a command receipt.
  for(const t of all){const g=await chartGroup(t);const current=await q.until(async()=>{const snap=await query(g.id);return !snap.computing&&snap.indicators.length===1&&snap.indicators[0].id==='boundary-ma-'+t.track_id&&!snap.indicators[0].error&&snap.indicators[0].outputPointCount>0?snap:false;},30000);
   const text=await q.until(async()=>{const value=await legend(t);return value&&/MA[^，]*[0-9]/.test(value)?value:false;},30000);
   const numbers=await cell(t.track_id).locator('.chart-main-indicator-row .chart-legend-number').allTextContents();assert.equal(numbers.length,1);const numeric=Number(numbers[0].replaceAll(',',''));assert.ok(numeric>(t.symbol==='BTCUSDT'?90:490)&&numeric<(t.symbol==='BTCUSDT'?200:600),text);
   states.push({track:t.track_id,symbol:t.symbol,cellId:await cell(t.track_id).getAttribute('data-chart-cell-id'),legend:text,numbers,controlSnapshot:current});
  }
  await q.record('actual-indicator-legends-'+label,states);
 }
 await assertCharts();
 const beforeIndicators=await snapshots();
 for(const t of all){await focus(t);const g=await chartGroup(t);await execute(g.id,'addIndicator',{id:'boundary-ma-'+t.track_id,name:'MA',engineName:'MA',kind:'builtin',params:{period:5},visible:true});}
 await assertIndicators('initial');assert.deepEqual(await snapshots(),beforeIndicators);
 await focus(btc);const early=await marker('before-any-notes');
 const originals={},later={},images={},oldMarks={},lateMarks={};
 for(const t of all){await focus(t);await openNotes();await notePanel().getByRole('button',{name:'新增笔记',exact:true}).click();
  const before=await snapshots();await notePanel().locator('textarea').fill(t.symbol+' original plan');const image=await captureImage(t.symbol+'-original');const note=await saveNote();
  assert.equal(note.trackId,t.track_id);assert.equal(note.screenshots[0].id,image.receipt.capture.id);assert.deepEqual(await snapshots(),before);
  originals[t.track_id]=note;images[t.track_id]=image;oldMarks[t.track_id]=await marker(t.symbol+'-original-time');
 }
 await execute('replay','control',{type:'step_base',payload:{count:2}});const stepped=await snapshots();assert.equal(stepped[btc.track_id].cursor.virtual_time_ms,stepped[eth.track_id].cursor.virtual_time_ms);assert.ok(stepped[btc.track_id].cursor.virtual_time_ms>afterAdd[btc.track_id].cursor.virtual_time_ms);
 for(const t of all){await focus(t);await openNotes();const other=all.find(x=>x.track_id!==t.track_id);assert.equal(await notePanel().locator(`article[data-note-id="${originals[other.track_id].id}"]`).count(),0);
  await execute('replay','trade',{type:'place_order',payload:{client_order_id:'multi-buy-'+t.track_id,side:'BUY',order_type:'MARKET',quantity:'0.1',reduce_only:false,limit_price:null,stop_price:null}});
  const before=await snapshots(),fills=before[t.track_id].components.fills;assert.equal(fills.length,1);
  await notePanel().getByRole('button',{name:'编辑',exact:true}).click();await notePanel().locator('textarea').fill(t.symbol+' later plan');await notePanel().getByRole('button',{name:'选择成交',exact:true}).click();
  const choices=notePanel().getByTestId('replay-note-link-options').getByRole('checkbox');await q.until(async()=>await choices.count()===1,30000);await choices.first().check();
  const note=await saveNote();assert.equal(note.id,originals[t.track_id].id);assert.equal(note.revisionCount,2);assert.equal(note.links.length,1);assert.equal(note.links[0].kind,'FILL');assert.equal(note.links[0].id,fills[0].fill_id??fills[0].id);
  assert.deepEqual(await snapshots(),before);later[t.track_id]=note;
  if(t.symbol==='BTCUSDT'){await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).selectOption('5m');await q.until(async()=>await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).inputValue()==='5m',30000);}
  else assert.equal(await q.s.page.getByRole('combobox',{name:'展示 K',exact:true}).inputValue(),'1m');
  lateMarks[t.track_id]=await marker(t.symbol+'-later-time');
 }
 await assertCharts();await assertIndicators('different-periods');await q.screenshot('two-market-live-notes');let parentBeforeReview=await snapshots();let review;
 async function startReview(){await openIntegrity();const pending=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/replay/runs/${runId}/review`&&r.request().method()==='POST');await integrity().getByRole('button',{name:'开始只读复盘',exact:true}).click();const r=await pending;assert.equal(r.status(),200,await r.text());review=await r.json();assert.equal(review.read_only,true);await q.record('review-start',review);}
 async function jump(mark,t,revision){await openIntegrity();const event=review.events.find(e=>e.timeline_sequence===mark.timeline_sequence);assert.ok(event);await integrity().getByRole('combobox',{name:'持久事件',exact:true}).selectOption(event.event_id);const pending=q.s.page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(`/reviews/${review.review_id}/cursor`)&&r.request().method()==='POST');await integrity().getByRole('button',{name:'跳转',exact:true}).click();const r=await pending;assert.equal(r.status(),200,await r.text());review={...review,...await r.json()};assert.equal(review.immutability_proof.verified,true);await closeIntegrity();await cell(t.track_id).locator('header').first().getByText(t.symbol,{exact:true}).click();if(await integrity().isVisible())await closeIntegrity();notesPath=`/api/v1/replay/runs/${runId}/tracks/${t.track_id}/notes`;await openNotes();await q.until(async()=>await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).isEnabled(),30000);
  assert.equal(review.projection.viewer_state.selected_track_id,t.track_id);const note=originals[t.track_id],article=notePanel().locator(`article[data-note-id="${note.id}"]`);await article.getByText(t.symbol+(revision===1?' original plan':' later plan'),{exact:true}).waitFor();
  const other=all.find(x=>x.track_id!==t.track_id);assert.equal(await notePanel().locator(`article[data-note-id="${originals[other.track_id].id}"]`).count(),0);
  await article.getByRole('button',{name:'版本历史',exact:true}).click();await q.until(async()=>await article.locator('[data-note-version]').count()===revision,30000);assert.equal(await article.getByTestId('replay-note-links').count(),revision===1?0:2);await article.getByRole('button',{name:'版本历史',exact:true}).click();
  await article.getByRole('button',{name:/^查看截图 1/}).click();const dialog=q.s.page.getByRole('dialog',{name:'回放笔记截图',exact:true});await q.until(async()=>await dialog.locator('img').evaluate(i=>i.complete&&i.naturalWidth>0),30000);assert.equal(await dialog.locator('img').getAttribute('src'),images[t.track_id].image);await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await assertCharts();await assertIndicators('review-'+t.track_id+'-v'+revision);assert.deepEqual(await snapshots(),parentBeforeReview);await q.record('native-review-track-and-version',{track:t.track_id,revision,review});
 }
 await startReview();for(const t of all){await jump(oldMarks[t.track_id],t,1);await jump(lateMarks[t.track_id],t,2);}
 async function boundary(){const health=await json('/health');assert.equal(health.runtime_mode,'LOCAL_OFFLINE');assert.equal(health.local_offline.network.installed,true);assert.equal(health.local_offline.network.blocked_attempts,0);assert.deepEqual(allUrls.filter(u=>!['127.0.0.1','localhost','[::1]'].includes(new URL(u).hostname)),[]);await q.record('offline-network-boundary',{health,urls:allUrls});}
 async function fullExit(label){const owned=await q.quit();await q.exited();const present=cp.execFileSync('ps',['-axo','pid='],{encoding:'utf8'}).trim().split(/\s+/).map(Number);assert.deepEqual(owned.filter(p=>present.includes(p.pid)),[]);await q.record(label,{owned,independentlyAbsent:true});}
 await boundary();await q.screenshot('two-market-review-before-exit');await fs.writeFile(root+'/multimarket-identities.json',JSON.stringify({runId,tracks:all,originals,later,oldMarks,lateMarks,early},null,2));await fullExit('first-full-owned-exit');
 await launch();await q.s.page.goto(new URL(`/replay.html?run=${runId}`,q.s.page.url()).href,{waitUntil:'domcontentloaded'});await group('replay');await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading&&!v.viewerPending;},60000);
 const restored=await snapshots();for(const t of all){assert.deepEqual(restored[t.track_id].cursor,parentBeforeReview[t.track_id].cursor);assert.deepEqual(restored[t.track_id].components,parentBeforeReview[t.track_id].components);assert.equal(restored[t.track_id].data_epoch,parentBeforeReview[t.track_id].data_epoch);}
 parentBeforeReview=restored;await assertCharts();await assertIndicators('after-restart');await startReview();for(const t of all){await jump(oldMarks[t.track_id],t,1);await jump(lateMarks[t.track_id],t,2);}
 await boundary();assert.deepEqual(q.s.receipt.errors,[]);await fullExit('second-full-owned-exit');await q.record('package-source-after',verify());await Promise.all([...responseWork]);await fs.writeFile(root+'/indicator-computations.json',JSON.stringify(indicatorComputations,null,2));await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));q.s.receipt.passed=true;await q.save();console.log('NATIVE MULTICHART INDICATOR OBSERVATIONS PASS; independent CSV oracle still required');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}try{await q.quit();await q.exited();}catch{}await Promise.all([...responseWork]);await fs.writeFile(root+'/indicator-computations.json',JSON.stringify(indicatorComputations,null,2));await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));process.exitCode=1;}
