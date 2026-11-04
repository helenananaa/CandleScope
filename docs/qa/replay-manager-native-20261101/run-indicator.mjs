import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';
import {capture} from './value-probe.mjs';
setup(q);
q.s.receipt.schema='candlescope.replay-manager-native-indicator/1';
const ready=()=>q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:45000});
async function resume(){
 await q.launch();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.s.page.waitForLoadState('load');
 await q.enableControl();await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);
 await q.s.page.locator('.training-hub-card').first().getByRole('button',{name:'继续训练',exact:true}).click();await ready();
 const groups=await q.s.control.call('app.commands',{windowId:'main-window'});
 const group=(groups.groups??groups).find(g=>g.title==='Imported/replay chart indicators and navigation');assert.ok(group);
 q.s.chartId=group.id.slice('chart:'.length);return {identity:q.s.identity,group:group.id};
}
async function positionVisibleCharts(){const cursor=Number(await q.s.page.locator('[data-replay-cursor-ms]').first().getAttribute('data-replay-cursor-ms'))/1000;const found=await q.s.control.call('app.commands',{windowId:'main-window'});for(const g of (found.groups??found).filter(g=>g.title==='Imported/replay chart indicators and navigation'))assert.equal((await q.execute(g.id.slice('chart:'.length),'visibleTimeRange',{from:cursor-14400,to:cursor})).state,'applied');await q.delay(500);}
function closeAt(i){const base=30000+i%80*2+Math.floor(i/80)*.25;return base+(i%2===0?4:-3);}
async function check(label,count=1){
 const charts=await q.until(async()=>{const rows=await capture(q);return rows.length===count&&rows.every(c=>{const last=c.bars.filter(b=>b.is_closed).at(-1);return c.lines.some(l=>l.data.length>20&&l.data.some(p=>Number(p.time)===last?.time))})?rows:false;},90000);
 const cursor=Number(await q.s.page.locator('[data-replay-cursor-ms]').first().getAttribute('data-replay-cursor-ms'));
 const evidence=[];
 for(const chart of charts){
  const line=chart.lines[0],points=new Map(line.data.map(p=>[Number(p.time),p.value]));assert.ok(line.data.every(p=>Number(p.time)*1000<=cursor));let compared=0,aggregateCompared=0,visibleCompared=0;
  for(let n=19;n<chart.bars.length;n++){
   const bar=chart.bars[n];if(!bar.is_closed)continue;
   let expected;
   if(chart.interval==='1m'){const i=(bar.time*1000-1700000040000)/60000;let sum=0;for(let j=i-19;j<=i;j++)sum+=closeAt(j);expected=sum/20;}
   else {expected=chart.bars.slice(n-19,n+1).reduce((sum,b)=>sum+b.close,0)/20;}
   const visible=chart.visible;assert.ok(visible&&Number.isFinite(Number(visible.from))&&Number.isFinite(Number(visible.to)),'missing actual visible range');if(bar.time>=Number(visible.from)&&bar.time<=Number(visible.to)){assert.ok(points.has(bar.time),`missing visible MA point ${chart.cellId} ${bar.time}`);visibleCompared++;}if(!points.has(bar.time))continue;assert.ok(Math.abs(points.get(bar.time)-expected)<1e-7,`MA mismatch ${chart.cellId} ${bar.time}: ${points.get(bar.time)} != ${expected}`);compared++;
   if(chart.interval==='5m'&&bar.time*1000>=1700049600000){
    const first=(bar.time*1000-1700000040000)/60000,rows=Array.from({length:5},(_,k)=>{const i=first+k,base=30000+i%80*2+Math.floor(i/80)*.25;return {open:base,high:base+12,low:base-12,close:closeAt(i),volume:10+i%7}});
    assert.ok(bar.time*1000+299999<=cursor);
    const expectedBar={open:rows[0].open,high:Math.max(...rows.map(b=>b.high)),low:Math.min(...rows.map(b=>b.low)),close:rows.at(-1).close,volume:rows.reduce((n,b)=>n+b.volume,0)};
    for(const key of Object.keys(expectedBar))assert.equal(bar[key],expectedBar[key],`5m ${key} ${bar.time}`);aggregateCompared++;
   }
  }
  assert.ok(compared>=50);assert.ok(visibleCompared>=30,`vacuous visible coverage: ${chart.cellId} ${visibleCompared}`);if(chart.interval==='5m')assert.ok(aggregateCompared>=2);evidence.push({cellId:chart.cellId,interval:chart.interval,compared,visibleCompared,aggregateCompared,points:line.data.length,visible:chart.visible,first:line.data[0],last:line.data.at(-1)});
 }
 await q.record(label,{cursor,charts:evidence});return {cursor,points:charts.map(c=>({cellId:c.cellId,lines:c.lines})).sort((a,b)=>a.cellId.localeCompare(b.cellId))};
}

try{
 await q.record('launch',await resume());if(await q.s.page.getByRole('button',{name:'图 2 布局操作',exact:true}).isVisible()){await q.s.page.getByRole('button',{name:'图 2 布局操作',exact:true}).click();await q.s.page.getByRole('button',{name:'关闭此图表',exact:true}).click();await q.until(async()=>(await capture(q)).length===1);}assert.equal((await q.execute(q.s.chartId,'removeIndicator',{indicatorId:'native180-ma20'})).state,'applied');
 await q.execute(q.s.chartId,'addIndicator',{id:'native180-ma20',name:'MA',engineName:'MA',kind:'builtin',params:{period:20,source:'close'},visible:true,paneTarget:'main'});
 await positionVisibleCharts();await check('initial-ma20');
 await q.s.page.getByRole('button',{name:'图 1 布局操作',exact:true}).click();await q.s.page.getByRole('button',{name:'向右拆分',exact:true}).click();await q.until(async()=>(await capture(q)).length===2);await q.s.page.locator('[data-chart-cell-id="cell-2"]').focus();await q.s.page.getByRole('button',{name:'5m',exact:true}).click();await q.until(async()=>(await capture(q)).some(c=>c.interval==='5m'));await positionVisibleCharts();await check('independent-period-ma20',2);
 const old=Number(await q.s.page.locator('[data-replay-cursor-ms]').first().getAttribute('data-replay-cursor-ms'));
 await q.s.page.locator('[data-replay-action="advance-base"]').click();
 await q.s.page.waitForFunction(t=>Number(document.querySelector('[data-replay-cursor-ms]')?.getAttribute('data-replay-cursor-ms'))>t,old);await ready();
 await positionVisibleCharts();await q.delay(2000);const saved=await check('advanced-ma20',2);await q.screenshot('ma20');
 await q.s.page.getByRole('button',{name:'存档大厅',exact:true}).click();await q.s.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();
 await q.record('full-exit',{owned:await q.quit(),allExited:await q.exited()});
 await q.record('restart',await resume());const restored=await check('restored-ma20',2);assert.equal(restored.cursor,saved.cursor);assert.deepEqual(restored.points,saved.points);
 assert.deepEqual(q.s.receipt.errors,[]);await q.record('final-exit',{owned:await q.quit(),allExited:await q.exited()});q.s.receipt.passed=true;await q.save();console.log('NATIVE INDICATOR PASS');
}catch(error){console.error(error);q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();try{await fs.writeFile(q.s.root+'/indicator-failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('indicator-failure');}catch{}try{await q.quit();await q.exited();}catch{}process.exitCode=1;}
