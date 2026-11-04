import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import * as q from '../backend-batch1-20261101/driver.mjs';
const root=q.s.root,data=root+'/profile/data';
const fixture=JSON.parse(await fs.readFile(root+'/fixture.json','utf8'));assert.equal(fixture.rowsPerSymbol,15000);
q.s.env={...q.s.env,MULTI_WINDOW_ENABLED:'1',KLINES_DB_PATH:data+'/candlescope.db',REPLAY_DB_PATH:data+'/replay.db',REPLAY_HISTORY_ARCHIVE_DIR:data+'/replay-history',REPLAY_HISTORY_ORIGIN_URI:' ',REPLAY_ENABLED:'1',SYMBOL_CATALOG_SNAPSHOT_PATH:data+'/fixture-symbol-catalog.json'};
q.s.receipt.schema='candlescope.replay-manager-service-native/1';q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.applicationSourceCommit=JSON.parse(await fs.readFile(root+'/assembly.json','utf8')).sourceCommit;
q.s.receipt.transport='Actual packaged app/bundled backend, two native app-page windows through the trusted openAppPage bridge, finite synthetic BTC/ETH archive, loopback-only OS sandbox, no response substitution.';
const policy=await fs.readFile(new URL('../history-study-note-sources-20261102/loopback-only.sb',import.meta.url));await fs.writeFile(root+'/loopback-only.sb',policy);
const quote=s=>"'"+s.replaceAll("'","'\\''")+"'",launcher=root+'/loopback-launcher.sh';
await fs.writeFile(launcher,'#!/bin/sh\nexec /usr/bin/sandbox-exec -f '+quote(root+'/loopback-only.sb')+' '+quote(root+'/Installed App/CandleScope.app/Contents/MacOS/CandleScope')+' "$@"\n',{mode:0o700});
q.s.receipt.networkPolicySha256=crypto.createHash('sha256').update(policy).digest('hex');
let running=false,mainPage,a,b;
const requests=[],sockets=[];q.s.receipt.replayRequests=requests;q.s.receipt.replaySockets=sockets;
function observe(page){
 page.on('pageerror',e=>q.s.receipt.errors.push({url:page.url(),message:e.message}));
 page.on('request',r=>{if(r.url().includes('/api/v1/replay/'))requests.push({method:r.method(),url:r.url()});});
 page.on('websocket',ws=>{if(ws.url().includes('/stream/replay/')){const row={url:ws.url()};sockets.push(row);ws.on('close',()=>row.closedAt=Date.now());}});
}
async function launch(){try{await q.record('packaged-launch',await q.launch({executablePath:launcher}));running=true;}catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}
 mainPage=q.s.page;await mainPage.getByRole('button',{name:'设置',exact:true}).waitFor();await mainPage.waitForLoadState('load');
 const probe=await q.s.app.evaluate(()=>{const {spawnSync}=process.getBuiltinModule('node:child_process');return spawnSync(process.resourcesPath+'/python-runtime/python/bin/python3',['-B','-c',"import errno,socket;s=socket.socket();s.settimeout(1)\ntry:s.connect(('192.0.2.1',443));raise AssertionError('remote allowed')\nexcept OSError as e:assert e.errno in (errno.EPERM,errno.EACCES);print(e.errno)\nfinally:s.close()"],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}).status;});assert.equal(probe,0);
}
async function read(page,path){const r=await page.evaluate(async url=>{const response=await fetch(url);return{status:response.status,body:await response.json()};},q.s.backend+path);assert.equal(r.status,200,JSON.stringify(r));return r.body;}
async function stats(){const body=await read(mainPage,'/debug/snapshot');assert.ok(body.replay?.data_manager,JSON.stringify(body));return body.replay.data_manager;}
async function waitStreams(count){return q.until(async()=>{const s=await stats();return s.streams===count?s:false;},30000);}
async function pageFor(id){return q.until(async()=>{for(const page of q.s.app.windows())try{if(await page.evaluate(async()=> (await window.candlescopeDesktop.getBootstrap()).windowId)===id)return page;}catch{}return false;},60000);}
async function openHub(){
 const opened=await mainPage.evaluate(()=>window.candlescopeDesktop.openAppPage('/replay.html'));
 const page=await pageFor(opened.windowId);observe(page);q.s.page=page;
 const bootstrap=await page.evaluate(()=>window.candlescopeDesktop.getBootstrap());assert.equal(bootstrap.sidecar.pid,q.s.bootstrap.sidecar.pid);
 await page.getByRole('button',{name:'新建训练',exact:true}).waitFor();return{page,windowId:opened.windowId,bootstrap};
}
async function ready(page){await page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:90000});}
async function createRun(name){const window=await openHub(),page=window.page;
 await page.getByRole('button',{name:'新建训练',exact:true}).click();await page.getByRole('textbox',{name:'商品',exact:true}).fill('BTCUSDT');await page.getByRole('textbox',{name:'存档名称',exact:true}).fill(name);
 await page.getByRole('textbox',{name:'开始时间（UTC）',exact:true}).fill('2023-11-15T12:00');await page.locator('[data-training-field="time-disclosure-policy"]').selectOption('NONE');
 await page.locator('#training-hub-create-advanced > summary').click();await page.getByRole('spinbutton',{name:'指标预热 BAR 只保证指标计算所需数据，不决定图表可向前滚动多远。',exact:true}).fill('20');
 await page.locator('[data-training-field="forward-cache-ms"]').fill('3600000');await page.getByRole('combobox',{name:'可见历史',exact:true}).selectOption('DURATION');await page.getByRole('spinbutton',{name:'可见历史时长（ms）',exact:false}).fill('21600000');
 await page.getByRole('button',{name:'确认时间并创建训练',exact:true}).click();await ready(page);
 const runId=new URL(page.url()).searchParams.get('run');assert.ok(runId);return{...window,runId,name};
}
async function facts(window,reader=window.page){const body=await read(reader,'/api/v1/replay/runs/'+window.runId+'/tracks');return{cursors:body.tracks.map(t=>({trackId:t.track_id,sessionId:t.adapter_session_id,timeMs:t.cursor.virtual_time_ms,sourceSequence:t.cursor.source_sequence})),portfolio:body.portfolio};}
async function manager(page){return page.evaluate(()=>window.__CANDLESCOPE_REPLAY_DATA__?.snapshot().replay);}
async function sequenceCount(page,count){return q.until(async()=>{const m=await manager(page);return m?.activeSequences===count?m:false;});}
async function advance(window){q.s.page=window.page;const before=await facts(window);await window.page.locator('[data-replay-action="advance-base"]').click();
 await q.until(async()=>{const after=await facts(window);return after.cursors[0].timeMs>before.cursors[0].timeMs?after:false;});await ready(window.page);return facts(window);
}
async function selectPeriod(page,interval){await page.getByRole('button',{name:'打开周期选择与自定义周期管理',exact:true}).click();const picker=page.getByRole('dialog',{name:'周期选择器',exact:true});await picker.waitFor();await picker.locator('[data-interval-chip="'+interval+'"]').click();await picker.waitFor({state:'hidden'});await ready(page);}
async function quit(){q.s.page=mainPage;await q.quit();await q.exited();running=false;await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
async function restore(window){const opened=await openHub();await opened.page.locator('.training-hub-card').filter({hasText:window.name}).getByRole('button',{name:'继续训练',exact:true}).click();await ready(opened.page);assert.equal(new URL(opened.page.url()).searchParams.get('run'),window.runId);return{...window,...opened};}
try{
 await launch();assert.equal((await stats()).streams,0);
 a=await createRun('Native manager A');const initialA=await facts(a);
 b=await createRun('Native manager B');const initialB=await facts(b);
 assert.notEqual(a.runId,b.runId);assert.notEqual(initialA.cursors[0].sessionId,initialB.cursors[0].sessionId);
 const four=await waitStreams(4);assert.deepEqual(four.consumers,{adapter:2,run:2});assert.equal(four.scopes,4);
 await q.record('two-native-run-windows-share-one-backend-and-manager-own-four-streams',{a:{runId:a.runId,windowId:a.windowId,pid:a.bootstrap.sidecar.pid,state:initialA},b:{runId:b.runId,windowId:b.windowId,pid:b.bootstrap.sidecar.pid,state:initialB},manager:four});
 const advancedA=await advance(a);assert.deepEqual(await facts(b),initialB);await q.record('advancing-run-a-does-not-advance-run-b-or-change-its-account',{a:advancedA,b:await facts(b),manager:await stats()});
 q.s.page=a.page;await a.page.getByRole('button',{name:'图 1 布局操作',exact:true}).click();await a.page.getByRole('button',{name:'向右拆分',exact:true}).click();await sequenceCount(a.page,2);
 await a.page.locator('[data-chart-cell-id="cell-2"]').focus();await selectPeriod(a.page,'5m');await q.until(async()=>await a.page.locator('[data-replay-cell-interval="5m"]').count()>0);
 assert.deepEqual(await facts(a),advancedA);assert.deepEqual(await facts(b),initialB);assert.equal((await stats()).streams,4);
 await q.record('extra-period-chart-has-private-sequence-without-duplicating-shared-adapter-stream',{aFrontend:await manager(a.page),bFrontend:await manager(b.page),backend:await stats()});
 await a.page.getByRole('button',{name:'图 2 布局操作',exact:true}).click();await a.page.getByRole('button',{name:'关闭此图表',exact:true}).click();await sequenceCount(a.page,1);assert.equal((await stats()).streams,4);assert.deepEqual(await facts(b),initialB);
 await q.record('closing-one-chart-releases-only-its-display-sequence',{aFrontend:await manager(a.page),backend:await stats()});
 await q.screenshot('manager-run-a');q.s.page=b.page;await q.screenshot('manager-run-b');await a.page.close();const two=await waitStreams(2);assert.deepEqual(two.consumers,{adapter:1,run:1});
 const advancedB=await advance(b);assert.deepEqual(await facts(a,b.page),advancedA);await q.record('closing-native-window-a-releases-its-streams-while-b-continues',{a:await facts(a,b.page),b:advancedB,manager:await stats()});
 await b.page.getByRole('button',{name:'存档大厅',exact:true}).click();await b.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();const empty=await waitStreams(0);assert.ok(empty.control_accesses>0);
 await q.record('returning-run-b-to-hub-releases-all-manager-streams',{backend:empty,frontend:await manager(b.page)});await quit();
 await launch();assert.equal((await stats()).streams,0);a=await restore(a);b=await restore(b);await waitStreams(4);
 assert.deepEqual(await facts(a),advancedA);assert.deepEqual(await facts(b),advancedB);await q.record('complete-restart-restores-two-independent-run-clocks-and-portfolios',{a:await facts(a),b:await facts(b),manager:await stats()});
 q.s.page=a.page;await q.screenshot('manager-restored-a');q.s.page=b.page;await q.screenshot('manager-restored-b');await a.page.close();await waitStreams(2);await b.page.close();await waitStreams(0);await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){process.exitCode=1;q.s.receipt.failure=String(error.stack||error);if(q.s.page){await q.screenshot('manager-failure').catch(()=>{});q.s.receipt.body=await q.s.page.locator('body').innerText().catch(String);q.s.receipt.manager=await stats().catch(String);}}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
