import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';
setup(q);
const query=async(id='cell-1')=>(await q.s.control.call('app.query',{windowId:'main-window',groupId:'drawings:'+id,command:'inspect',args:{}})).snapshot;
const pane=async()=> (await query()).panes.find(p=>p.paneId==='main');
const payload=p=>p.zOrder.map(id=>{const entity=p.entities.find(e=>e.id===id);assert.ok(entity);const {kind,geometry,style}=entity;return {id,kind,geometry,style};});
async function command(name,args,id='cell-1'){
 const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});const group=groups.find(g=>g.id==='drawings:'+id);assert.ok(group);
 const requestId='native184-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command:name,args,requestId,expectedContext:group.contextToken});
 const r=await q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;});assert.equal(r.state,'applied',JSON.stringify(r));return r;
}
async function launch(){await q.launch();await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.s.page.waitForLoadState('load');await q.enableControl();}
async function tool(value){
 await q.s.page.locator('[data-chart-cell-id="cell-1"] .chart-pane').first().hover();
 await q.s.page.locator('.drawing-tool-btn[data-drawing-tool^="line-"],.drawing-tool-btn[data-drawing-tool^="measure-"],.drawing-tool-btn[data-drawing-tool="angle-measure"]').click({button:'right'});
 await q.s.page.locator('[data-tool-variant="'+value+'"]').click();
 return q.until(async()=>{const p=await pane();return p?.ready?p:false;});
}
async function create(value,index){
 await tool(value);await command('preferences',{snap:false,continuous:false});
 const chart=q.s.page.locator('[data-chart-cell-id="cell-1"] .chart-pane').first();const box=await chart.boundingBox();assert.ok(box);
 const a={x:box.width*.20,y:box.height*(.78-index*.23)},b={x:box.width*.62,y:box.height*(.66-index*.23)};
 const before=(await pane()).entities.length;
 await chart.click({position:a});await q.s.page.mouse.move(box.x+b.x,box.y+b.y);await chart.click({position:b});
 const after=await q.until(async()=>{const p=await pane();return p?.entities.length===before+1?p:false;});
 const e=after.entities.at(-1);assert.equal(e.kind,'range-measure');assert.equal(e.geometry.measureType,value.slice(8));assert.equal(e.geometry.dataPoints.length,2);
 const [first,last]=e.geometry.dataPoints;assert.ok(Number.isFinite(first.time)&&Number.isFinite(last.time)&&last.time>first.time);assert.ok(last.price>first.price);
 await q.record('created-'+value,{pane:after,measured:{priceDelta:last.price-first.price,percentDelta:(last.price-first.price)/Math.abs(first.price)*100,elapsedSeconds:last.time-first.time}});
 return {id:e.id,a,b,box};
}
try{
 await launch();const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');assert.equal(configured.result.state,'ready');await q.ready(2,90000);
 const created=[];for(const [i,type]of ['measure-price','measure-time','measure-price-time'].entries())created.push(await create(type,i));
 const header=await q.s.page.locator('[data-chart-cell-id="cell-1"] .multi-chart-cell-header .drawing-object-trigger').boundingBox();const plot=await q.s.page.locator('[data-chart-cell-id="cell-1"] .chart-pane').first().boundingBox();assert.ok(header&&plot&&header.y+header.height<=plot.y);await q.record('objects-control-outside-plot',{header,plot});const original=payload(await pane());assert.equal(original.length,3);assert.ok((await query('cell-2')).panes.every(p=>p.entities.length===0));await q.screenshot('three-measurements');
 await command('undo',{paneId:'main'});assert.equal((await pane()).entities.length,2);await command('redo',{paneId:'main'});assert.deepEqual(payload(await pane()),original);
 let p=await pane();await command('apply',{paneId:'main',scopeKey:p.scopeKey,expectedRevision:p.revision,commands:[{type:'update-style',id:created[2].id,patch:{locked:true,color:'#33aaee'}}]});
 const locked=payload(await pane());assert.equal(locked[2].style.locked,true);
 await tool('measure-price-time');const c=created[2];await q.s.page.mouse.move(c.box.x+c.a.x,c.box.y+c.a.y);await q.s.page.mouse.down();await q.s.page.mouse.move(c.box.x+c.a.x+20,c.box.y+c.a.y+20);await q.s.page.mouse.up();await q.delay(400);assert.deepEqual(payload(await pane()),locked);
 await command('tool',{tool:'cursor-default'});await q.record('history-style-lock',{pane:await pane()});
 assert.equal((await q.execute('cell-1','interval',{interval:'5m'})).state,'applied');await q.ready(2,90000);await q.until(async()=>!!(await pane())?.ready);assert.deepEqual(payload(await pane()),locked);await q.screenshot('five-minute-measurements');await q.record('interval-preserved',{pane:await pane(),workspace:await q.inspect()});
 await q.delay(1000);await q.record('full-exit',{owned:await q.quit(),allExited:await q.exited()});await launch();await q.ready(2,90000);await q.until(async()=>!!(await pane())?.ready);assert.deepEqual(payload(await pane()),locked);assert.ok((await query('cell-2')).panes.every(p=>p.entities.length===0));await q.screenshot('restored-measurements');await q.record('restart-persistence',{pane:await pane()});
 p=await pane();await command('apply',{paneId:'main',scopeKey:p.scopeKey,expectedRevision:p.revision,commands:[{type:'delete',id:created[1].id}]});assert.equal((await pane()).entities.length,2);await command('undo',{paneId:'main'});assert.deepEqual(payload(await pane()),locked);await q.record('delete-undo',{pane:await pane()});
 assert.deepEqual(q.s.receipt.errors,[]);await q.record('final-exit',{owned:await q.quit(),allExited:await q.exited()});q.s.receipt.passed=true;await q.save();console.log('NATIVE RANGE MEASUREMENTS PASS');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);try{await fs.writeFile(q.s.root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}try{await q.quit();await q.exited();}catch{}process.exitCode=1;}
