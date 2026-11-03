import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../replay-manager-native-20261101/value-probe.mjs';
const root=q.s.root,data=root+'/profile/data';
q.s.env={...q.s.env,KLINES_DB_PATH:data+'/candlescope.db',REPLAY_DB_PATH:data+'/replay.db',REPLAY_HISTORY_ARCHIVE_DIR:data+'/replay-history',REPLAY_HISTORY_ORIGIN_URI:' ',REPLAY_ENABLED:'1',SYMBOL_CATALOG_SNAPSHOT_PATH:data+'/fixture-symbol-catalog.json'};
q.s.receipt.schema='candlescope.replay-view-date-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.applicationSourceCommit=JSON.parse(await fs.readFile(root+'/assembly.json','utf8')).sourceCommit;
q.s.receipt.transport='Actual packaged macOS arm64 app and bundled backend; finite synthetic BTC/ETH 1m/5m archive; loopback-only OS sandbox; no response substitution.';
const policy=await fs.readFile(new URL('../history-study-note-sources-20261102/loopback-only.sb',import.meta.url));
await fs.writeFile(root+'/loopback-only.sb',policy);
const quote=value=>"'"+value.replaceAll("'","'\\''")+"'",executable=root+'/Installed App/CandleScope.app/Contents/MacOS/CandleScope',launcher=root+'/loopback-launcher.sh';
await fs.writeFile(launcher,'#!/bin/sh\nexec /usr/bin/sandbox-exec -f '+quote(root+'/loopback-only.sb')+' '+quote(executable)+' "$@"\n',{mode:0o700});
q.s.receipt.networkPolicySha256=crypto.createHash('sha256').update(policy).digest('hex');
const history=[];let running=false,runId;
async function launch(){
 try{await q.record('packaged-launch',await q.launch({executablePath:launcher}));running=true;}catch(error){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw error;}
 q.s.page.on('request',r=>{if(/\/replay\/.*\/history\?/.test(r.url()))history.push({url:r.url(),method:r.method(),at:Date.now()});});
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.s.page.waitForLoadState('load');
 const probe=await q.s.app.evaluate(()=>{const {spawnSync}=process.getBuiltinModule('node:child_process');return spawnSync(process.resourcesPath+'/python-runtime/python/bin/python3',['-B','-c',"import errno,socket;s=socket.socket();s.settimeout(1)\ntry:s.connect(('192.0.2.1',443));raise AssertionError('remote allowed')\nexcept OSError as e:assert e.errno in (errno.EPERM,errno.EACCES);print(e.errno)\nfinally:s.close()"],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}).status;});assert.equal(probe,0);
}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
async function read(path){const result=await q.s.page.evaluate(async url=>{const r=await fetch(url);return{status:r.status,body:await r.json()};},q.s.backend+'/api/v1/replay'+path);assert.equal(result.status,200);return result.body;}
async function facts(){const tracks=await read('/runs/'+runId+'/tracks');return{clock:tracks.global_clock?{state:tracks.global_clock.state,basis:tracks.global_clock.basis,rate:tracks.global_clock.rate,speed:tracks.global_clock.speed,tick:tracks.global_clock.tick}:null,cursors:tracks.tracks.map(t=>({track_id:t.track_id,virtual_time_ms:t.cursor.virtual_time_ms,source_sequence:t.cursor.source_sequence})),portfolio:tracks.portfolio};}
async function command(groupId,name,args={}){
 const group=(await q.s.control.call('app.commands',{windowId:'main-window'})).groups.find(g=>g.id===groupId);assert.ok(group,groupId);
 const requestId='replay-date-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId,command:name,args,requestId,expectedContext:group.contextToken});
 const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;});assert.equal(result.state,'applied',JSON.stringify(result));return result;
}
async function document(){return(await q.s.control.call('app.query',{windowId:'main-window',groupId:'workspace',command:'inspect',args:{}})).snapshot.document;}
async function viewport(id){const groups=(await q.s.control.call('app.commands',{windowId:'main-window'})).groups;const group=groups.find(g=>g.id.startsWith('chart:replay:')&&g.id.endsWith(':'+id));assert.ok(group);return(await q.s.control.call('app.query',{windowId:'main-window',groupId:group.id,command:'viewport',args:{}})).snapshot;}
const ready=()=>q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:90000});
async function create(policy,name){
 await q.s.page.getByRole('button',{name:'新建训练',exact:true}).click();
 await q.s.page.getByRole('textbox',{name:'商品',exact:true}).fill('BTCUSDT');
 await q.s.page.getByRole('textbox',{name:'存档名称',exact:true}).fill(name);
 await q.s.page.getByRole('textbox',{name:'开始时间（UTC）',exact:true}).fill('2023-11-15T12:00');
 await q.s.page.locator('[data-training-field="time-disclosure-policy"]').selectOption(policy);
 await q.s.page.locator('#training-hub-create-advanced > summary').click();
 await q.s.page.getByRole('spinbutton',{name:'指标预热 BAR 只保证指标计算所需数据，不决定图表可向前滚动多远。',exact:true}).fill('20');
 await q.s.page.locator('[data-training-field="forward-cache-ms"]').fill('3600000');
 await q.s.page.getByRole('combobox',{name:'可见历史',exact:true}).selectOption('DURATION');
 await q.s.page.getByRole('spinbutton',{name:'可见历史时长（ms）',exact:false}).fill('43200000');
 await q.s.page.getByRole('button',{name:'确认时间并创建训练',exact:true}).click();await ready();
 runId=new URL(q.s.page.url()).searchParams.get('run');assert.ok(runId);
}
async function navigate(time,{shortcut=false,located=true}={}){
 if(shortcut)await q.s.page.keyboard.press('Alt+g');else await q.s.page.getByRole('button',{name:'定位视图日期',exact:true}).click();
 const dialog=q.s.page.getByRole('dialog',{name:'跳转到日期',exact:true});await dialog.waitFor();
 await dialog.getByLabel('日期和时间（UTC）',{exact:true}).fill(time);await dialog.getByRole('button',{name:'跳转',exact:true}).click();
 await q.until(async()=>{const status=dialog.getByRole('status');return await status.getAttribute('aria-busy')==='false'&&Boolean(await status.innerText());});
 const message=await dialog.getByRole('status').innerText();if(located)assert.match(message,/已定位|最近/);else assert.doesNotMatch(message,/已定位/);
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();return message;
}
async function barsEvidence(){return(await capture(q)).map(c=>({cellId:c.cellId,interval:c.interval,bars:c.bars.length,first:c.bars[0]?.time,last:c.bars.at(-1)?.time,visible:c.visible}));}
try{
 await launch();await q.enableControl();await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);await create('NONE','Native date shown');
 await q.until(async()=>(await capture(q)).some(c=>c.bars.length>20));const original=await facts();
 const target=Date.parse('2023-11-15T00:30:00Z');assert.ok((await capture(q))[0].bars[0].time*1000>target,'Target must require real bounded history, not only a loaded row');
 const readsBefore=history.length,message=await navigate('2023-11-15T00:30:00',{shortcut:true});
 assert.ok(history.length>readsBefore);assert.deepEqual(await facts(),original);
 const chart=(await capture(q))[0];assert.ok(chart.bars.some(b=>b.time*1000===target));
 assert.ok(chart.visible&&Number(chart.visible.from)<=target/1000&&Number(chart.visible.to)>=target/1000);
 await q.record('date-shortcut-loads-real-bounded-history-without-clock-or-account-change',{message,history:history.slice(readsBefore),before:original,charts:await barsEvidence()});
 await q.s.page.getByRole('button',{name:'图 1 布局操作',exact:true}).click();await q.s.page.getByRole('button',{name:'向右拆分',exact:true}).click();
 await q.until(async()=>(await capture(q)).length===2);
 await command('workspace','setLinkGroup',{cellIds:['cell-1','cell-2'],groupId:null});
 await command('workspace','setActiveCell',{cellId:'cell-2'});await q.s.page.getByRole('button',{name:'5m',exact:true}).click();await ready();
 await q.until(async()=>(await capture(q)).some(c=>c.cellId==='cell-2'&&c.interval==='5m'&&c.bars.length>20));
 await command('workspace','setActiveCell',{cellId:'cell-1'});const peerBefore=await viewport('cell-2');assert.ok(peerBefore?.logical,'Peer viewport must be observable');
 await navigate('2023-11-15T05:00:00');assert.deepEqual(await viewport('cell-2'),peerBefore);assert.deepEqual(await facts(),original);
 await q.record('independent-date-navigation-keeps-other-period-viewport-and-run-clock',{charts:await barsEvidence(),peerBefore});
 await command('workspace','createLinkGroup',{cellIds:['cell-1','cell-2']});const doc=await document(),groupId=doc.cells['cell-1'].linkGroupId;assert.ok(groupId);
 await command('workspace','updateLinkPolicy',{groupId,relationship:'peers',patch:{timeAnchor:true,dateRange:false}});
 const linkedTarget=Date.parse('2023-11-15T04:00:00Z');await navigate('2023-11-15T04:00:00');
 const linked=await capture(q);for(const c of linked){assert.ok(c.visible&&Number(c.visible.from)<=linkedTarget/1000&&Number(c.visible.to)>=linkedTarget/1000);assert.ok(c.bars.every(b=>b.time*1000<=original.cursors[0].virtual_time_ms));}
 assert.deepEqual(await facts(),original);await q.record('linked-periods-locate-one-time-without-advancing-authoritative-run',{charts:await barsEvidence(),state:await facts()});
 const readCount=history.length;await navigate('2023-11-15T12:01:00',{located:false});assert.equal(history.length,readCount);assert.deepEqual(await facts(),original);await q.record('unrevealed-date-cannot-read-or-advance-run',{historyRequests:readCount});
 await q.screenshot('replay-date-linked');const savedRunId=runId;await q.s.page.getByRole('button',{name:'存档大厅',exact:true}).click();await q.s.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();await quit();
 await launch();await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);await q.s.page.locator('.training-hub-card').filter({hasText:'Native date shown'}).getByRole('button',{name:'继续训练',exact:true}).click();await ready();
 runId=new URL(q.s.page.url()).searchParams.get('run');assert.equal(runId,savedRunId);assert.deepEqual(await facts(),original);await navigate('2023-11-15T05:00:00');assert.deepEqual(await facts(),original);await q.record('complete-restart-restores-clock-account-and-view-only-navigation',{runId,state:await facts(),charts:await barsEvidence()});
 await q.s.page.getByRole('button',{name:'存档大厅',exact:true}).click();await q.s.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();await create('HIDE_ALL','Native date hidden');
 assert.notEqual(runId,savedRunId);assert.equal(await q.s.page.getByRole('button',{name:'定位视图日期',exact:true}).count(),0);await q.s.page.keyboard.press('Alt+g');assert.equal(await q.s.page.getByRole('dialog',{name:'跳转到日期',exact:true}).count(),0);
 await q.record('hidden-calendar-training-has-no-absolute-date-input-or-shortcut',{runId,policy:'HIDE_ALL'});await q.screenshot('replay-date-hidden');await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){process.exitCode=1;q.s.receipt.failure=String(error.stack||error);if(q.s.page){await q.screenshot('replay-date-failure').catch(()=>{});q.s.receipt.body=await q.s.page.locator('body').innerText().catch(String);}}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}q.s.receipt.historyRequests=history;await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
