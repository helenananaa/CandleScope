import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';
setup(q);q.s.receipt.schema='candlescope.chart-style-native/1';
const state=async()=> (await q.s.control.call('app.query',{windowId:'main-window',groupId:'workspace',command:'inspect',args:{}})).snapshot;
async function command(name,args){
 const groups=await q.s.control.call('app.commands',{windowId:'main-window'});const g=(groups.groups??groups).find(x=>x.id==='workspace');assert.ok(g);
 const requestId='native181-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId:'workspace',command:name,args,requestId,expectedContext:g.contextToken});
 const result=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false});assert.equal(result.state,'applied');return result;
}
const globalSettings=()=>q.s.page.evaluate(()=>localStorage.getItem('candlescope-settings'));
async function launch(){await q.launch();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.s.page.waitForLoadState('load');await q.enableControl();}
async function replay(){await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);await q.s.page.locator('.training-hub-card').first().getByRole('button',{name:'继续训练',exact:true}).click();await q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:60000});}
async function financial(){const id=new URL(q.s.page.url()).searchParams.get('run');const r=await fetch(q.s.backend+'/api/v1/replay/runs/'+id+'/tracks');assert.equal(r.status,200);const d=await r.json();return {clock:d.global_clock,portfolio:d.portfolio};}
async function surface(){return q.s.page.evaluate(()=>{
 const el=document.querySelector('[data-chart-cell-id]');let node=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(node.return)node=node.return;const seen=new Set(),charts=[];
 function visit(n){if(!n)return;const p=n.memoizedProps;if(p?.seriesStore&&p.datasetKey&&n.memoizedState&&!seen.has(p.seriesStore)){seen.add(p.seriesStore);let a=n,cellId;while(a){cellId??=a.memoizedProps?.['data-chart-cell-id'];a=a.return}let hook=n.memoizedState,canvas;while(hook){const api=hook.memoizedState?.current;if(api&&typeof api.options==='function'&&typeof api.timeScale==='function'){canvas={layout:api.options().layout,range:api.timeScale().getVisibleLogicalRange()};}hook=hook.next;}charts.push({cellId,canvas,theme:p.theme,inheritApplicationTheme:p.inheritApplicationTheme,customBg:p.customBg,upColor:p.upColor,downColor:p.downColor,bars:p.seriesStore.barCount,first:p.seriesStore.first()?.time,last:p.seriesStore.last()?.time});}visit(n.child);visit(n.sibling)}visit(node.stateNode.current);for(const c of charts){const pane=document.querySelector('[data-chart-cell-id="'+c.cellId+'"] .multi-pane-chart');if(pane){const css=getComputedStyle(pane);c.css=Object.fromEntries(['--text-primary','--text-up','--text-down','--bg-primary'].map(k=>[k,css.getPropertyValue(k).trim()]));}}return charts;
});}
async function edit(cellId,theme,{red=false,bg}={}){
 await command('setActiveCell',{cellId});await q.s.page.getByRole('button',{name:'设置',exact:true}).click();
 const dialog=q.s.page.getByRole('dialog');await dialog.getByRole('button',{name:theme,exact:true}).click();
 if(red)await dialog.getByRole('button',{name:/红涨.*绿跌/}).click();
 if(bg)await dialog.locator('input[type=color]').first().fill(bg);
 await q.s.page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
}
async function link(label){if(label==='formal'){await q.s.page.getByRole('button',{name:/^工作区 ·/}).click();}else{await q.s.page.getByRole('button',{name:/^当前窗口布局:/}).click();await q.s.page.getByRole('button',{name:'图表工作区管理',exact:true}).click();}await q.s.page.getByRole('tab',{name:'联动',exact:true}).click();const b=q.s.page.getByRole('button',{name:/^图表样式/});await b.click();assert.equal(await b.getAttribute('aria-pressed'),'true');await q.s.page.getByRole('button',{name:'关闭图表工作区侧栏',exact:true}).click();}
async function exercise(label){
 const original=await state();const groupId=Object.keys(original.document.linkGroups)[0];await command('setLinkGroup',{cellIds:['cell-1','cell-2'],groupId});await command('updateLinkPolicy',{groupId,relationship:'peers',patch:{chartStyle:false}});
 const appBefore=await globalSettings();const siblingColorBefore=(await surface()).find(c=>c.cellId==='cell-2').upColor;const siblingBefore=(await state()).document.cells['cell-2'].chartSettings;
 await edit('cell-1','亮色',{red:true});const independent=await state();assert.equal(independent.document.cells['cell-1'].chartSettings.theme,'light');assert.deepEqual(independent.document.cells['cell-2'].chartSettings,siblingBefore);assert.equal(await globalSettings(),appBefore);
 let charts=await surface();await q.record(label+'-canvas-before-assertion',{charts});assert.equal(charts.find(c=>c.cellId==='cell-1').canvas.layout.background.color,'#ffffff');assert.equal(charts.find(c=>c.cellId==='cell-1').theme,'light');assert.equal(charts.find(c=>c.cellId==='cell-1').inheritApplicationTheme,false);assert.equal(charts.find(c=>c.cellId==='cell-2').upColor,siblingColorBefore);for(const c of charts){assert.equal(c.css['--text-up'],c.upColor);assert.equal(c.css['--text-down'],c.downColor);}assert.notEqual(charts.find(c=>c.cellId==='cell-1').css['--text-primary'],charts.find(c=>c.cellId==='cell-1').css['--bg-primary']);await q.screenshot(label+'-independent');await q.record(label+'-independent',{charts,workspace:independent});
 await link(label);await edit('cell-1','自定义',{bg:'#223344'});const linked=await state();for(const id of ['cell-1','cell-2']){assert.equal(linked.document.cells[id].chartSettings.theme,'custom');assert.equal(linked.document.cells[id].chartSettings.customBg,'#223344');}
 const linkedCharts=await surface();for(const c of linkedCharts)assert.equal(c.canvas.layout.background.color,'#223344');assert.equal(linked.document.cells['cell-2'].chartSettings.upColor,siblingBefore.upColor);assert.equal(await globalSettings(),appBefore);await q.record(label+'-linked',{workspace:linked,charts:await surface()});
 await command('updateLinkPolicy',{groupId,relationship:'peers',patch:{chartStyle:false}});await edit('cell-2','亮色');const final=await state();assert.equal(final.document.cells['cell-1'].chartSettings.theme,'custom');assert.equal(final.document.cells['cell-2'].chartSettings.theme,'light');await q.screenshot(label+'-final');return {settings:Object.fromEntries(['cell-1','cell-2'].map(id=>[id,final.document.cells[id].chartSettings])),groups:final.document.linkGroups};
}
async function restored(expected,label){const current=await state();for(const id of ['cell-1','cell-2'])assert.deepEqual(current.document.cells[id].chartSettings,expected.settings[id]);assert.deepEqual(current.document.linkGroups,expected.groups);await q.record(label,{workspace:current,charts:await surface()});}
async function checkViewport(label){
 const found=await q.s.control.call('app.commands',{windowId:'main-window'});const groups=(found.groups??found).filter(g=>g.id.startsWith('chart:'));const before=await surface();
 assert.equal(groups.length,before.length);const end=Math.min(...before.map(c=>c.last));for(const group of groups){assert.equal((await q.execute(group.id.slice('chart:'.length),'visibleTimeRange',{from:end-3600,to:end})).state,'applied');}
 await q.delay(600);const positioned=await surface();for(const c of positioned){assert.ok(c.canvas.range.from<c.bars&&c.canvas.range.to>0,'viewport excludes all bars');}
 for(const c of positioned){await edit(c.cellId,'亮色');const changed=(await surface()).find(x=>x.cellId===c.cellId);assert.equal(changed.canvas.layout.background.color,'#ffffff');for(const edge of ['from','to'])assert.ok(Math.abs(changed.canvas.range[edge]-c.canvas.range[edge])<0.1,'style moved viewport');}
 await q.record(label+'-visible-style',{before:positioned,after:await surface()});await q.screenshot(label+'-visible-style');
}
try{await launch();await q.ready(2,60000);await checkViewport('live');await replay();const before=await financial();await checkViewport('formal');assert.deepEqual(await financial(),before);await q.record('final-exit',{owned:await q.quit(),allExited:await q.exited()});q.s.receipt.passed=true;await q.save();console.log('NATIVE STYLE VISIBLE VIEWPORT PASS');}catch(e){q.s.receipt.passed=false;q.s.receipt.failure=String(e.stack??e);await q.save();console.error(e);try{await q.screenshot('viewport-failure');await q.quit();await q.exited();}catch{}process.exitCode=1;}
