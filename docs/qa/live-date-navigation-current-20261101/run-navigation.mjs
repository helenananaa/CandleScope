import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';
setup(q);q.s.receipt.schema='candlescope.live-date-navigation-native/1';
const state=async()=> (await q.s.control.call('app.query',{windowId:'main-window',groupId:'workspace',command:'inspect',args:{}})).snapshot;
async function command(name,args){const groups=await q.s.control.call('app.commands',{windowId:'main-window'});const g=(groups.groups??groups).find(x=>x.id==='workspace');assert.ok(g);const requestId='native186-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId:g.id,command:name,args,requestId,expectedContext:g.contextToken});const r=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false});assert.equal(r.state,'applied');}
async function launch(){await q.launch();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.s.page.waitForLoadState('load');await q.enableControl();}
async function surface(){return q.s.page.evaluate(()=>{const el=document.querySelector('[data-chart-cell-id]');let n=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(n.return)n=n.return;const seen=new Set(),charts=[];function visit(n){if(!n)return;const p=n.memoizedProps;if(p?.seriesStore&&p.datasetKey&&n.memoizedState&&!seen.has(p.seriesStore)){seen.add(p.seriesStore);let a=n,cellId;while(a){cellId??=a.memoizedProps?.['data-chart-cell-id'];a=a.return;}let h=n.memoizedState,canvas;while(h){const api=h.memoizedState?.current;if(api&&typeof api.options==='function'&&typeof api.timeScale==='function'){canvas={options:api.options().timeScale,logical:api.timeScale().getVisibleLogicalRange(),time:api.timeScale().getVisibleRange()};}h=h.next;}charts.push({cellId,interval:p.interval,dataMeta:p.dataMeta,rows:p.seriesStore.snapshot(),rightTruncated:p.seriesStore.rightTruncated,canvas});}visit(n.child);visit(n.sibling);}visit(n.stateNode.current);return charts;});}
async function jump(timeMs,{shortcut=false,keepOpen=false}={}){if(shortcut)await q.s.page.keyboard.press('Alt+g');else await q.s.page.getByRole('button',{name:'跳转到日期',exact:true}).click();const dialog=q.s.page.getByRole('dialog',{name:'跳转到日期',exact:true});await dialog.getByLabel('日期和时间（UTC）',{exact:true}).fill(new Date(timeMs).toISOString().slice(0,16));await dialog.getByRole('button',{name:'跳转',exact:true}).click();await q.until(async()=>{const text=await dialog.getByRole('status').innerText();return /已定位|未能定位|未找到/.test(text)?text:false;},60000);const text=await dialog.getByRole('status').innerText();if(!keepOpen)await dialog.getByRole('button',{name:'关闭',exact:true}).click();return text;}
function centered(chart,timeMs,span){const index=chart.rows.findIndex(r=>r.time===timeMs/1000);assert.ok(index>=0,'target row absent');const r=chart.canvas.logical;assert.ok(Math.abs((r.from+r.to)/2-index)<0.15,'target not centered: '+JSON.stringify({index,r}));if(span!==undefined)assert.ok(Math.abs(r.to-r.from-span)<0.15,'zoom changed');}
function oracle(chart){for(const r of chart.rows){const i=(r.time*1000-1700000040000)/60000;assert.ok(Number.isInteger(i)&&i>=0&&i<4000);const base=30000+(i%80)*2+Math.floor(i/80)/4;assert.equal(r.open,base);assert.equal(r.close,base+(i%2===0?4:-3));}}
try{
 const seeded=JSON.parse(cp.execFileSync('/Users/ryanliang/CandleScope/backend/.venv/bin/python',['-c',"import json,sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(json.dumps(c.execute('select interval,count(*) from klines group by interval').fetchall()))",q.s.root+'/profile/data/candlescope.db'],{encoding:'utf8'}));
 assert.ok(seeded.every(([interval])=>interval==='1m'));await q.record('initial-data-has-no-5m-bars',{seeded});
 await launch();const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');assert.equal(configured.result.state,'ready');await q.ready(2,60000);
 const groupId=Object.keys((await state()).document.linkGroups)[0];await command('setLinkGroup',{cellIds:['cell-1','cell-2'],groupId});await command('updateLinkPolicy',{groupId,relationship:'peers',patch:{timeAnchor:false,dateRange:false}});await command('setActiveCell',{cellId:'cell-1'});
 for(const c of await surface()){const end=c.rows.at(-1).time;assert.equal((await q.execute(c.cellId,'visibleTimeRange',{from:end-3600,to:end})).state,'applied');}await q.delay(500);
 const before=await surface(),span=before.find(c=>c.cellId==='cell-1').canvas.logical.to-before.find(c=>c.cellId==='cell-1').canvas.logical.from;
 const target=1700000040000+1000*60000;const message=await jump(target,{shortcut:true});assert.match(message,/已定位/);await q.delay(500);const independent=await surface();const own=independent.find(c=>c.cellId==='cell-1'),sibling=independent.find(c=>c.cellId==='cell-2');centered(own,target,span);oracle(own);assert.equal(own.rightTruncated,true);await q.record('sibling-absolute-viewport',{before:before.find(c=>c.cellId==='cell-2'),after:sibling});assert.deepEqual(sibling.canvas.time,before.find(c=>c.cellId==='cell-2').canvas.time);assert.equal(sibling.canvas.options.barSpacing,before.find(c=>c.cellId==='cell-2').canvas.options.barSpacing);assert.ok(sibling.rows.at(-1).time>1700000040+4000*60);await q.record('independent-date-seek',{message,before,after:independent});await q.screenshot('independent-date');
 await q.delay(3000);const retained=(await surface()).find(c=>c.cellId==='cell-1');assert.equal(retained.rows.at(-1).time,own.rows.at(-1).time);centered(retained,target,span);await q.record('live-traffic-does-not-pull-history',{first:retained.rows[0].time,last:retained.rows.at(-1).time,rightTruncated:retained.rightTruncated});
 await command('setActiveCell',{cellId:'cell-2'});await q.s.page.getByRole('button',{name:'5m',exact:true}).click();await q.until(async()=>{const c=(await surface()).find(c=>c.cellId==='cell-2');if(Date.now()-(q.s.lastColdSnapshot??0)>=1000){q.s.lastColdSnapshot=Date.now();const health=await (await fetch(q.s.backend+'/api/v1/settings/storage/health')).json();await fs.appendFile(q.s.root+'/cold-5m-health.jsonl',JSON.stringify({at:Date.now(),interval:c.interval,rows:c.rows.length,health})+'\n');}return c.interval==='5m'&&c.rows.length>0;},60000);await command('setActiveCell',{cellId:'cell-1'});await command('updateLinkPolicy',{groupId,relationship:'peers',patch:{timeAnchor:true,dateRange:false}});
 const linkedTarget=1700000040000+1500*60000;
 let linkedMessage,linked;
 for(let attempt=0;attempt<20;attempt++){
  linkedMessage=await jump(linkedTarget);assert.match(linkedMessage,/已定位/);await q.delay(500);linked=await surface();
  centered(linked.find(c=>c.cellId==='cell-1'),linkedTarget,span);
  const partial=/部分联动图表未能/.test(linkedMessage);
  await q.record('linked-attempt-'+attempt,{message:linkedMessage,partial,charts:linked});
  if(!partial)break;
  // An unavailable peer must keep its prior live window and disclose the
  // partial result. Retry through the same user command after preparation.
  const peer=linked.find(c=>c.cellId==='cell-2');assert.equal(peer.rightTruncated,false);
  assert.ok(peer.rows.at(-1).time>1700000040+4000*60);
  await q.delay(2500);
 }
 assert.ok(!/部分联动图表未能/.test(linkedMessage),'5m target never became available after explicit retries');
 for(const c of linked){const actual=c.interval==='5m'?Math.floor(linkedTarget/300000)*300000:linkedTarget;centered(c,actual);assert.equal(c.rightTruncated,true);}
 const coarse=linked.find(c=>c.interval==='5m');
 const rangeUrl=new URL(q.s.backend+'/api/v1/klines/range');
 Object.entries({symbol:'BTCUSDT',interval:'5m',exchange:'binance',market_type:'spot',start_ms:coarse.rows[0].time*1000,end_ms:coarse.rows.at(-1).time*1000,repair:'none',wait_ms:0,strict:true}).forEach(([key,value])=>rangeUrl.searchParams.set(key,String(value)));
 const rangeResponse=await fetch(rangeUrl),range=await rangeResponse.json();assert.equal(rangeResponse.status,200);assert.equal(range.complete,true);assert.equal(range.data.length,coarse.rows.length);
 for(let index=0;index<coarse.rows.length;index++)for(const key of ['time','open','high','low','close','volume'])assert.equal(coarse.rows[index][key],range.data[index][key]);
 await q.record('cold-5m-chart-matches-backend',{rows:range.data.length,complete:range.complete,historyState:range.history_state,first:coarse.rows[0].time,last:coarse.rows.at(-1).time});
 await q.record('linked-independent-intervals',{message:linkedMessage,charts:linked});await q.screenshot('linked-date');

 assert.deepEqual(q.s.receipt.errors,[]);await q.record('normal-exit',{owned:await q.quit(),allExited:await q.exited()});q.s.receipt.passed=true;await q.save();console.log('NATIVE DATE NAVIGATION BASIC PASS');
}catch(e){try{const health=await (await fetch(q.s.backend+'/api/v1/settings/storage/health')).json();await fs.writeFile(q.s.root+'/failure-storage-health.json',JSON.stringify(health,null,2)+'\n');}catch{}q.s.receipt.passed=false;q.s.receipt.failure=String(e.stack??e);await q.save();console.error(e);try{await fs.writeFile(q.s.root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}try{await q.quit();await q.exited();}catch{}process.exitCode=1;}
