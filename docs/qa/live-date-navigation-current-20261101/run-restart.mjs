import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './restart-driver.mjs';
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
 await launch();await q.ready(2,90000);
 const workspace=await state();const restored=await surface();
 assert.deepEqual(restored.map(c=>c.interval).sort(),['1m','5m']);
 await q.record('restarted-workspace',{cells:restored.map(c=>({cellId:c.cellId,interval:c.interval,rows:c.rows.length,first:c.rows[0].time,last:c.rows.at(-1).time,rightTruncated:c.rightTruncated,canvas:c.canvas})),linkGroups:workspace.document.linkGroups});
 await command('setActiveCell',{cellId:'cell-1'});
 const target=1700000040000+1500*60000;const message=await jump(target);assert.match(message,/已定位/);assert.ok(!/部分联动图表未能/.test(message));await q.delay(500);
 const charts=await surface();for(const c of charts)centered(c,c.interval==='5m'?Math.floor(target/300000)*300000:target);
 await q.record('historical-navigation-after-restart',{message,charts:charts.map(c=>({cellId:c.cellId,interval:c.interval,rows:c.rows.length,rightTruncated:c.rightTruncated,canvas:c.canvas}))});await q.screenshot('date-after-restart');
 await q.s.page.locator('[data-chart-cell-id="cell-1"]').getByRole('button',{name:'回到实时',exact:true}).click();
 const latest=await q.until(async()=>{const c=(await surface()).find(c=>c.cellId==='cell-1');return !c.rightTruncated&&c.rows.at(-1).time>1700000040+4000*60?c:false},90000);
 await q.record('return-to-live',{last:latest.rows.at(-1).time,rightTruncated:latest.rightTruncated,canvas:latest.canvas});
 assert.deepEqual(q.s.receipt.errors,[]);await q.record('normal-exit',{owned:await q.quit(),allExited:await q.exited()});q.s.receipt.passed=true;await q.save();console.log('NATIVE DATE RESTART PASS');
}catch(e){q.s.receipt.passed=false;q.s.receipt.failure=String(e.stack??e);await q.save();console.error(e);try{await q.screenshot('restart-failure');}catch{}try{await q.quit();await q.exited();}catch{}process.exitCode=1;}
