import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';


q.s.receipt.schema='candlescope.history-study-fine-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope='Packaged macOS arm64 fixed 1m input reconstructed into 5m closed/forming display, causal OHLCV and independent SMA, durable controls/rewind/restart, sibling viewport and financial isolation. Warm known public history, no current-latest/cold, tick path, arbitrary scripts, full product or Windows claim.';
let running=false;
const studyRequests=[];
const cell=id=>q.s.page.locator(`[data-chart-cell-id="${id}"]`);
const region=id=>q.s.page.locator(`[data-study-id="${id}"]`);
const stamp=ms=>new Date(ms).toISOString().slice(0,19).replace(/:00$/,'');
const owner=(workspace,id)=>Buffer.from(JSON.stringify([workspace,id])).toString('base64url');
const query=(command='inspect',args={})=>q.s.control.call('app.query',{windowId:'main-window',groupId:'study:cell-1',command,args});
async function execute(command,args={}) {
 const group=(await q.s.control.call('app.commands',{windowId:'main-window'})).groups.find(group=>group.id==='study:cell-1');assert.ok(group);
 const requestId='fine-study-'+crypto.randomUUID();
 await q.s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command,args,requestId,expectedContext:group.contextToken});
 return q.until(async()=>{const result=await q.s.control.call('request.get',{requestId});return result.final?result:false;});
}
// Independent fixed 5m oracle; intentionally does not import production aggregation.
function reference(input,cursor) {
 const revealed=input.rows.filter(row=>row.closeTimeMs<=cursor),buckets=new Map();
 for(const row of revealed){const start=Math.floor(row.time/300)*300;const rows=buckets.get(start)??[];rows.push(row);buckets.set(start,rows);}
 return [...buckets].flatMap(([time,rows])=>{
  if(rows[0].time!==time||rows.some((row,index)=>index&&row.time!==rows[index-1].time+60))return [];
  return [{time,open:rows[0].open,high:Math.max(...rows.map(row=>row.high)),low:Math.min(...rows.map(row=>row.low)),
   close:rows.at(-1).close,volume:rows.reduce((sum,row)=>sum+row.volume,0),is_closed:rows.length===5}];
 });
}
async function verify(input,cursor,label) {
 return q.until(async()=>{
  try {
  const result=await query(),snap=result.snapshot;if(snap?.cursorMs!==cursor||snap.computing)return false;
  const chart=(await surfaces()).find(surface=>surface.dataset===input.id);if(!chart)return false;
  const expected=reference(input,cursor);assert.equal(chart.rows.length,expected.length);
  for(let i=0;i<expected.length;i++)for(const key of ['time','open','high','low','close','volume','is_closed'])assert.equal(chart.rows[i][key],expected[i][key],label+':'+key);
  const bars=await query('bars',{limit:500});assert.equal(bars.output.length,expected.length);
  for(let i=0;i<expected.length;i++)for(const key of ['time','open','high','low','close','volume','is_closed'])assert.equal(bars.output[i][key],expected[i][key]);
  const output=await query('indicatorOutputs',{limit:500});if(output.state!=='ready')return false;
  const points=output.output.flatMap(item=>item.lines.flatMap(line=>line.data));if(points.length!==expected.length-19)return false;
  let maxError=0;for(let i=19;i<expected.length;i++){const point=points.find(point=>point.time===expected[i].time);assert.ok(point);const sma=expected.slice(i-19,i+1).reduce((sum,row)=>sum+row.close,0)/20;const error=Math.abs(sma-point.value);assert.ok(error<1e-7);maxError=Math.max(error,maxError);}
  const runtime=(await q.inspect()).cells.find(cell=>cell.cellId==='cell-1').runtime;
  assert.equal(runtime.mode,'history-study');assert.equal(runtime.barCount,expected.length);assert.equal(runtime.study.cursorMs,cursor);
  assert.equal(snap.sourceSeries.interval,'1m');assert.equal(snap.series.interval,'5m');assert.deepEqual(snap.missingBuckets,[]);
  return {label,cursor,sourceRowsRevealed:input.rows.filter(row=>row.closeTimeMs<=cursor).length,displayRows:expected.length,forming:expected.at(-1),ma20Points:points.length,maxError,sourceSeries:snap.sourceSeries,series:snap.series};
  } catch {return false;}
 },60_000);
}
async function launch() {
  try { await q.record('packaged-launch', await q.launch()); running = true; }
  catch (error) { running=Boolean(q.s.app); q.s.identity??={pid:q.s.app?.process()?.pid}; throw error; }
  q.s.page.on('request', request => { if (request.url().includes('/history-studies/')) studyRequests.push({at:Date.now(),path:new URL(request.url()).pathname,method:request.method()}); });
  await q.enableControl();
}
async function quit() {
  await q.quit(); await q.exited(); running = false;
  await q.record('full-owned-exit', {elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});
}
async function read(path) {
  const result = await q.s.page.evaluate(async url => { const response = await fetch(url); return {status:response.status,body:await response.json()}; }, q.s.backend+'/api/v1'+path);
  assert.equal(result.status,200); return result.body;
}
async function surfaces() {
  return q.s.page.evaluate(() => {
    const element=document.querySelector('[data-chart-cell-id]');
    let node=element?.[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))];
    while(node?.return) node=node.return;
    const seen=new Set(), found=[];
    function visit(n) {
      if(!n) return;
      const p=n.memoizedProps;
      if(p?.seriesStore && p.datasetKey && !seen.has(p.seriesStore)) {
        seen.add(p.seriesStore); let parent=n,cellId;
        while(parent) {cellId??=parent.memoizedProps?.['data-chart-cell-id']??parent.memoizedProps?.cell?.id;parent=parent.return;}
        found.push({cellId,dataset:p.datasetKey,rows:p.seriesStore.snapshot(),lines:p.mainOverlayLines??[]});
      }
      visit(n.child);visit(n.sibling);
    }
    visit(node?.stateNode?.current);return found;
  });
}
async function activate(id) {
  await cell(id).click({position:{x:5,y:5}});
  await q.until(async()=> (await q.inspect()).activeCellId===id);
}
function finances() {
  const python=q.s.root+'/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3';
  const database=q.s.root+'/profile/data/trading-accounts.sqlite3';
  return JSON.parse(cp.execFileSync(python,['-c',"import sqlite3,json,sys;db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(json.dumps({t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['accounts','orders','fills','cash_flows','journal_entries']}))",database],{encoding:'utf8'}));
}
try {
 await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT','5m'),indicators:[{name:'MA',period:20}]},{session:q.session('ETHUSDT'),indicators:[{name:'MA',period:20}]}],'split-vertical');
 await q.record('configuration-and-actual-latest-health',configured);
 assert.ok(configured.result.state==='ready'||(configured.result.state==='applied'&&configured.result.code==='READINESS_TIMEOUT'));
 await q.until(async()=>{const snap=await q.inspect();return snap.cells.length===2&&snap.cells.every(cell=>cell.runtime?.mode==='live'&&cell.runtime.barCount>=120&&!cell.runtime.computing&&cell.runtime.indicatorsReady);},90_000);
 const workspace=(await q.inspect()).workspaceId,before=finances(),live=await surfaces();
 const left=live.find(surface=>surface.cellId==='cell-1'),right=live.find(surface=>surface.cellId==='cell-2');assert.ok(left&&right);
 const closed=left.rows.filter(row=>row.is_closed!==false&&row.time*1000+300_000<=Date.now());
 const runs=[];let run=[];for(const row of closed){if(run.length&&row.time!==run.at(-1).time+300){runs.push(run);run=[];}run.push(row);}runs.push(run);
 const selected=runs.sort((a,b)=>b.length-a.length)[0].filter(row=>row.time*1000+300_000<=Date.now()-3_600_000).slice(-100);assert.equal(selected.length,100);
 const start=selected[0].time*1000,end=selected.at(-1).time*1000+300_000,cursor=selected[60].time*1000+150_000;
 const last=right.rows.at(-1).time-3600;await q.execute('cell-2','visibleTimeRange',{from:last-1800,to:last});await q.delay(200);
 const siblingBefore=(await q.query('cell-2')).snapshot.visibleRange;
 await activate('cell-1');await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();
 const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
 await dialog.getByLabel('细数据周期',{exact:true}).selectOption('1m');
 for(const [label,time] of [['区间开始（UTC）',start],['区间结束（UTC，不含）',end],['回放时刻（UTC）',cursor]])await dialog.getByLabel(label,{exact:true}).fill(stamp(time));
 await dialog.getByRole('button',{name:'开始研究',exact:true}).click();
 await q.until(async()=>(await cell('cell-1').locator('[data-study-id]').count())>0,90_000);
 const studyId=await cell('cell-1').locator('[data-study-id]').getAttribute('data-study-id');
 const saved=await read('/history-studies/views/'+owner(workspace,'cell-1')),input=saved.study;
 assert.equal(input.sourceSeries.interval,'1m');assert.equal(input.series.interval,'5m');assert.equal(input.rows.length,500);
 await q.record('captured-fine-input-and-partial-display',await verify(input,cursor,'initial'));
 assert.ok(input.rows.at(-1).closeTimeMs>cursor);const futureIndex=input.rows.findIndex(row=>row.closeTimeMs>cursor);assert.ok(futureIndex>0);
 const stepped=await execute('step',{direction:'forward'});assert.equal(stepped.state,'applied');const next=input.rows[futureIndex].closeTimeMs;
 await q.record('one-source-close-updates-only-forming-tail',await verify(input,next,'step'));
 const rewind=input.rows[207].time*1000+30_000;assert.equal((await execute('seekCursor',{timeMs:rewind})).state,'applied');
 await q.record('rewind-recomputes-smaller-forming-input-and-ma',await verify(input,rewind,'rewind'));
 const siblingAfter=(await q.query('cell-2')).snapshot.visibleRange;assert.deepEqual(siblingAfter.time,siblingBefore.time);assert.equal(siblingAfter.barSpacing,siblingBefore.barSpacing);
 await q.record('sibling-viewport-preserved',{before:siblingBefore,after:siblingAfter});await q.screenshot('fine-study-rewind');await quit();
 await launch();await region(studyId).waitFor({timeout:90_000});
 await q.record('restart-restores-fine-input-and-cursor',await verify(input,rewind,'restart'));
 const restored=await read('/history-studies/views/'+owner(workspace,'cell-1'));assert.deepEqual(restored.study,input);assert.equal(restored.cursorMs,rewind);
 assert.equal((await query()).snapshot.playing,false);
 assert.equal((await execute('seekCursor',{timeMs:cursor})).state,'applied');await q.record('forward-after-restart-reproduces-forming-reference',await verify(input,cursor,'forward'));
 await q.screenshot('fine-study-forward');assert.equal((await execute('exit')).state,'applied');await region(studyId).waitFor({state:'hidden'});
 assert.deepEqual(finances(),before);await q.record('no-financial-side-effects',{before,after:finances(),studyRequests});await quit();
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
} catch(error) {
 q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(q.s.page){await q.screenshot('fine-study-failure').catch(()=>{});q.s.receipt.diagnostics={surfaces:await surfaces().catch(String),body:await q.s.page.locator('body').innerText().catch(String)};}
} finally {
 if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
 await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
