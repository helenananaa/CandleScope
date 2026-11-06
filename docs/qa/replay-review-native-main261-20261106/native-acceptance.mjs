import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './native-driver.mjs';
const root=q.s.root;
q.s.receipt.originalSetupScope='Native macOS LOCAL_OFFLINE formal replay version-bound actual chart PNGs and fill/trade links: actual create/edit/historical version API and history UI, retained draft/full owned exit/restart on imported BAR; not full graphical Review/multitrack/Windows or whole166.';
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',REPLAY_ENABLED:'1',
 KLINES_DB_PATH:root+'/profile/data/market.db',REPLAY_DB_PATH:root+'/profile/data/replay.db',
 BACKTEST_DB_PATH:root+'/profile/data/backtest.db',BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1'};
try{await fs.stat(root+'/profile');throw new Error('Preserve existing profile; use a fresh candidate');}catch(e){if(e.code!=='ENOENT')throw e;}
await fs.mkdir(root+'/profile/data',{recursive:true});
const start=1700000040000,count=6000;
await fs.writeFile(root+'/imported-replay.csv','time,open,high,low,close,volume\n'+Array.from({length:count},(_,i)=>{
 const price=i>4500?1000000:100+i%20;return `${start+i*60000},${price},${price+2},${price-1},${price+1},100`;
}).join('\n'));
const requests=[],allUrls=[];
q.s.receipt.scope='Current main packaged macOS, LOCAL_OFFLINE imported BAR: actual graphical Review JUMP/PREVIOUS/NEXT, historical note versions, screenshots and fill links, retrospective supplements, parent isolation and full owned exit/restart. Not public feed, Windows, multitrack or whole166.';
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
function verify(){return JSON.parse(cp.execFileSync('node',['docs/qa/replay-review-native-main261-20261106/verify.mjs'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:root}}));}
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
 const snap=async()=>(await json(`/api/v1/replay/runs/session/${session}`)).snapshot;
 const integrity=()=>q.s.page.locator('[data-replay-panel="integrity"]');
 async function openIntegrity(){if(!await integrity().isVisible())await q.s.page.locator('[data-replay-action="toggle-integrity"]').click();await integrity().getByRole('heading',{name:'只读复盘',exact:true}).waitFor();}
 async function closeIntegrity(){await integrity().locator('[data-replay-action="close-integrity"]').click();}
 async function marker(text){
  await openIntegrity();await integrity().getByLabel('手工复盘标记',{exact:true}).fill(text);
  const r=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/replay/runs/${runId}/markers`&&r.request().method()==='POST');
  await integrity().getByRole('button',{name:'记录到不可变时间线',exact:true}).click();const response=await r;assert.equal(response.status(),200,await response.text());
  const result=await response.json();await q.record('immutable-marker-'+text,result);await closeIntegrity();return result;
 }
 // Move away from initial events before creating the plan, so the earlier marker has no note.
 const early=await marker('before-plan');await execute('replay','control',{type:'step_base',payload:{count:1}});
 await q.s.page.locator('button[data-rail-view="replay-notes"]').click();
 const v1text='Review native original plan v1',v2text='Review native later edit v2',supplementText='Review retrospective supplement';
 const beforePlan=await snap();await notePanel().getByRole('button',{name:'新增笔记',exact:true}).click();
 await notePanel().locator('textarea').fill(v1text);const imageA=await captureImage('v1');const v1=await saveNote();
 assert.deepEqual(await snap(),beforePlan);const first=await marker('original-plan-time');
 await execute('replay','trade',{type:'place_order',payload:{client_order_id:'review-native-buy',side:'BUY',order_type:'MARKET',quantity:'0.1',reduce_only:false,limit_price:null,stop_price:null}});
 await execute('replay','control',{type:'step_base',payload:{count:2}});
 await execute('replay','trade',{type:'place_order',payload:{client_order_id:'review-native-close',side:'SELL',order_type:'MARKET',quantity:'0.1',reduce_only:true,limit_price:null,stop_price:null}});
 const beforeEdit=await snap();assert.equal(beforeEdit.components.fills.length,2);assert.equal(beforeEdit.components.closed_trades.length,1);
 await notePanel().getByRole('button',{name:'编辑',exact:true}).click();await notePanel().locator('textarea').fill(v2text);
 await notePanel().getByRole('button',{name:'选择成交',exact:true}).click();await notePanel().getByTestId('replay-note-link-options').getByRole('checkbox').first().check();
 await notePanel().getByRole('button',{name:'选择交易',exact:true}).click();await notePanel().getByTestId('replay-note-link-options').getByRole('checkbox').first().check();
 const imageB=await captureImage('v2');await notePanel().getByRole('button',{name:'移除截图 1',exact:true}).click();const v2=await saveNote();
 assert.equal(v2.id,v1.id);assert.equal(v2.revisionCount,2);assert.equal(v2.links.length,2);assert.deepEqual(v2.links.map(l=>l.kind).sort(),['FILL','TRADE']);assert.ok(v2.effectiveTimeMs>v1.effectiveTimeMs);assert.deepEqual(await snap(),beforeEdit);
 const late=await marker('later-edit-time');
 let parentBeforeReview=await snap();await fs.writeFile(root+'/review-identities.json',JSON.stringify({runId,track,session,early,first,late,v1,v2},null,2));
 let review;
 async function startReview(){await openIntegrity();const response=q.s.page.waitForResponse(r=>new URL(r.url()).pathname===`/api/v1/replay/runs/${runId}/review`&&r.request().method()==='POST');await integrity().getByRole('button',{name:'开始只读复盘',exact:true}).click();const r=await response;assert.equal(r.status(),200,await r.text());review=await r.json();assert.equal(review.read_only,true);assert.equal(review.immutability_proof.verified,true);await q.record('review-start',review);}
 function eventId(mark){const event=review.events.find(e=>e.timeline_sequence===mark.timeline_sequence);assert.ok(event,JSON.stringify(mark));return event.event_id;}
 async function navigate(action,event=null){
  await openIntegrity();
  if(event)await integrity().getByRole('combobox',{name:'持久事件',exact:true}).selectOption(event);
  const response=q.s.page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(`/reviews/${review.review_id}/cursor`)&&r.request().method()==='POST');
  await integrity().getByRole('button',{name:action,exact:true}).click();const r=await response;assert.equal(r.status(),200,await r.text());const result=await r.json();
  review=result.review??result;assert.equal(review.read_only,true);assert.equal(review.immutability_proof.verified,true);
  await q.until(async()=>await q.s.page.locator('[data-review-verified="true"]').count()===1,20000);
  await q.record('graphical-review-'+action,review);await closeIntegrity();
  const toggle=notePanel().getByRole('button',{name:'回放笔记',exact:true});
  if(await toggle.count() && await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
  return review;
 }
 async function notesAt(text,expected){
  await q.until(async()=>await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).isEnabled(),30000);
  const body=await notePanel().innerText();assert.ok(body.includes(text),body);assert.ok(!body.includes(text===v1text?v2text:v1text),body);
  const article=notePanel().locator(`article[data-note-id="${v1.id}"]`);assert.equal(await article.getByRole('button',{name:'编辑',exact:true}).isDisabled(),true);
  // The screenshot is fetched by the actual Review viewer with its current context.
  await article.getByRole('button',{name:/^查看截图 1/}).click();const dialog=q.s.page.getByRole('dialog',{name:'回放笔记截图',exact:true});
  await q.until(async()=>await dialog.locator('img').evaluate(i=>i.complete&&i.naturalWidth>0),30000);
  const src=await dialog.locator('img').getAttribute('src');assert.equal(src,expected.image);await q.screenshot('review-'+text.replaceAll(' ','-'));await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  const expectedRevision=text===v1text?1:2;
  const historyButton=article.getByRole('button',{name:'版本历史',exact:true});await historyButton.click();
  await q.until(async()=>await article.locator('[data-note-version]').count()===expectedRevision,30000);
  assert.equal(await article.locator('[data-note-version="2"]').count(),expectedRevision===2?1:0);
  assert.equal(await article.getByTestId('replay-note-links').count(),expectedRevision===2?2:0);
  if(expectedRevision===2)assert.equal(await article.locator('[data-note-version="2"] [data-testid="replay-note-links"] li').count(),2);
  await q.record('graphical-history-version-'+expectedRevision,{text:await article.innerText(),selectedEvent:review.selected_event_id});await historyButton.click();
  await q.until(async()=>Number(await q.s.page.locator('#status-bar').getAttribute('data-replay-cursor-ms'))===review.projection.cursor.virtual_time_ms && Number(await q.s.page.locator('#status-bar').getAttribute('data-replay-max-bar-ms'))+59999<=review.projection.cursor.virtual_time_ms,30000);
  const chart=q.s.page.getByRole('group',{name:/^主图信息：/}).first(),ohlc=await chart.getAttribute('aria-label');assert.ok(ohlc&&!ohlc.includes('1000000'),ohlc);
  const high=Number(ohlc.match(/最高\s*([\d,.]+)/)?.[1]?.replaceAll(',',''));assert.ok(high>0&&high<200,ohlc);
  await q.record('rendered-review-prefix',{selectedEvent:review.selected_event_id,cursor:review.projection.cursor,footer:await q.s.page.locator('#status-bar').innerText(),maxBarMs:await q.s.page.locator('#status-bar').getAttribute('data-replay-max-bar-ms'),ohlc});
  assert.deepEqual(await snap(),parentBeforeReview);return body;
 }
 await startReview();const earlyId=eventId(early),firstId=eventId(first),lateId=eventId(late);
 await navigate('跳转',firstId);await notesAt(v1text,imageA);
 await navigate('下一事件');await navigate('上一事件');assert.equal(review.selected_event_id,firstId);await notesAt(v1text,imageA);
 await navigate('跳转',lateId);await notesAt(v2text,imageB);
 await navigate('跳转',earlyId);await q.until(async()=>await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).isEnabled(),30000);
 assert.equal(await notePanel().locator('article[data-note-id]').count(),0);assert.ok(!(await notePanel().innerText()).includes(v1text));
 assert.deepEqual(await snap(),parentBeforeReview);await q.record('future-note-hidden',{selectedEvent:earlyId,reviewTime:review.projection.cursor.virtual_time_ms});
 await navigate('跳转',firstId);await notesAt(v1text,imageA);
 await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).click();await notePanel().locator('textarea').fill(supplementText);
 const writtenAfter=Date.now(),supplement=await saveNote();assert.equal(supplement.reviewNote,true);assert.equal(supplement.marketTimeMs,review.projection.cursor.virtual_time_ms);assert.ok(supplement.updatedAtMs>=writtenAfter-1000);assert.notEqual(supplement.id,v1.id);
 await notePanel().locator(`article[data-note-id="${supplement.id}"]`).getByText('复盘补记',{exact:true}).waitFor();assert.deepEqual(await snap(),parentBeforeReview);
 await q.record('retrospective-native-supplement',{supplement,parentUnchanged:true});
 await navigate('跳转',earlyId);await q.until(async()=>await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).isEnabled(),30000);assert.equal(await notePanel().locator('article[data-note-id]').count(),0);
 await navigate('跳转',lateId);await notesAt(v2text,imageB);await notePanel().getByText(supplementText,{exact:true}).waitFor();
 async function boundary(){const health=await json('/health');assert.equal(health.runtime_mode,'LOCAL_OFFLINE');assert.equal(health.local_offline.network.installed,true);assert.equal(health.local_offline.network.blocked_attempts,0);assert.ok(allUrls.length>0);assert.deepEqual(allUrls.filter(value=>!['127.0.0.1','localhost','[::1]'].includes(new URL(value).hostname)),[]);await q.record('offline-network-boundary',{health,urls:allUrls});}
 async function fullExit(label){const owned=await q.quit();await q.exited();const rows=cp.execFileSync('ps',['-axo','pid='],{encoding:'utf8'}).trim().split(/\s+/).map(Number);assert.deepEqual(owned.filter(p=>rows.includes(p.pid)),[]);await q.record(label,{owned,independentlyAbsent:true});}
 await boundary();await q.screenshot('review-before-full-exit');await fullExit('first-full-owned-exit');
 await launch();await q.s.page.goto(new URL(`/replay.html?run=${runId}`,q.s.page.url()).href,{waitUntil:'domcontentloaded'});await group('replay');await q.until(async()=>{const v=await query('replay');return v.viewer&&!v.loading?v:false;},60000);
 const restored=await snap();assert.deepEqual(restored.cursor,parentBeforeReview.cursor);assert.deepEqual(restored.components,parentBeforeReview.components);assert.deepEqual(restored.config,parentBeforeReview.config);
 await q.record('restart-parent-semantic-invariance',{before:parentBeforeReview,after:restored,controllerReacquired:true});parentBeforeReview=restored;
 // Review mode may itself restore, otherwise enter it using the real button.
 await openIntegrity();if(await integrity().getByRole('button',{name:'开始只读复盘',exact:true}).count())await startReview();else {throw new Error('Restored active Review requires explicit captured response, preserve evidence');}
 await navigate('跳转',firstId);await notesAt(v1text,imageA);await notePanel().getByText(supplementText,{exact:true}).waitFor();
 await navigate('跳转',lateId);await notesAt(v2text,imageB);await navigate('跳转',earlyId);
 await q.until(async()=>await notePanel().getByRole('button',{name:'新增复盘补记',exact:true}).isEnabled(),30000);assert.equal(await notePanel().locator('article[data-note-id]').count(),0);
 await q.record('native-review-history-restored',{original:v1.id,laterRevision:v2.revisionCount,supplement:supplement.id,parentCursor:restored.cursor,parentAccount:restored.components});
 await boundary();assert.deepEqual(q.s.receipt.errors,[]);await fullExit('second-full-owned-exit');await q.record('package-source-after',verify());
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));q.s.receipt.passed=true;await q.save();console.log('NATIVE GRAPHICAL REVIEW PASS');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);
 try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}
 try{await q.quit();await q.exited();}catch{}
 await fs.writeFile(root+'/replay-requests.json',JSON.stringify(requests,null,2));process.exitCode=1;
}
