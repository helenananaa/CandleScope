import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';

q.s.receipt.schema = 'candlescope.history-study-native/1';
q.s.receipt.sourceCommit = cp.execFileSync('git', ['rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
q.s.receipt.scope = 'Packaged macOS arm64: account-free fixed-input current-interval studies, real manager history, revealed-prefix MA, independent chart/cursor, versioned review annotation, ordinary full exit/restart. Not finer-timeframe reconstruction, original-note sources, optional cursor linking, formal replay, arbitrary script causality or Windows acceptance.';
let running = false;
const studyRequests = [];
// Chromium normalizes an exact minute in datetime-local to omit :00 seconds.
const stamp = ms => new Date(ms).toISOString().slice(0,19).replace(/:00$/, '');
const cell = id => q.s.page.locator(`[data-chart-cell-id="${id}"]`);
const region = id => q.s.page.locator(`[data-study-id="${id}"]`);
const owner = (workspace, id) => Buffer.from(JSON.stringify([workspace,id])).toString('base64url');
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
async function capture(id, sourceRows, count, cutIndex) {
  await activate(id);
  const rows=sourceRows.filter(row=>row.is_closed!==false&&Number(row.time)*1000+60_000<=Date.now()).slice(-count);
  assert.equal(rows.length,count);
  const start=Number(rows[0].time)*1000,end=Number(rows.at(-1).time)*1000+60_000,cursor=Number(rows[cutIndex].time)*1000;
  await q.s.page.getByRole('button',{name:'历史研究',exact:true}).click();
  const dialog=q.s.page.getByRole('dialog',{name:'历史研究',exact:true});await dialog.waitFor();
  await dialog.getByLabel('区间开始（UTC）',{exact:true}).fill(stamp(start));
  await dialog.getByLabel('区间结束（UTC，不含）',{exact:true}).fill(stamp(end));
  await dialog.getByLabel('回放时刻（UTC）',{exact:true}).fill(stamp(cursor));
  await dialog.getByRole('button',{name:'开始研究',exact:true}).click();
  await q.until(async()=>(await cell(id).locator('[data-study-id]').count())>0,60_000);
  const studyId=await cell(id).locator('[data-study-id]').getAttribute('data-study-id');
  await q.until(async()=>Number(await region(studyId).getAttribute('data-study-cursor-ms'))===cursor);
  return {studyId,rows,start,end,cursor};
}
async function verify(study, cursor, label) {
  return q.until(async()=> {
    try {
      assert.equal(Number(await region(study.studyId).getAttribute('data-study-cursor-ms')),cursor);
      const chart=(await surfaces()).find(value=>value.dataset===study.studyId);assert.ok(chart);
      const expected=study.rows.filter(row=>Number(row.time)*1000+60_000<=cursor);
      assert.equal(chart.rows.length,expected.length);
      for(let i=0;i<expected.length;i++) for(const key of ['time','open','high','low','close','volume']) assert.equal(chart.rows[i][key],expected[i][key]);
      const points=chart.lines.flatMap(line=>line.data??[]);assert.equal(points.length,Math.max(0,expected.length-19));
      let maxError=0;
      for(let i=19;i<expected.length;i++) {
        const point=points.find(point=>Number(point.time)===Number(expected[i].time));assert.ok(point);
        const value=expected.slice(i-19,i+1).reduce((sum,row)=>sum+row.close,0)/20;
        const error=Math.abs(point.value-value);assert.ok(error<1e-7);maxError=Math.max(maxError,error);
      }
      assert.ok(points.every(point=>Number(point.time)*1000+60_000<=cursor));
      return {label,cursor,rows:expected.length,ma20Points:points.length,maxError,first:expected[0]?.time,last:expected.at(-1)?.time};
    } catch {return false;}
  },60_000);
}
function finances() {
  const python=q.s.root+'/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3';
  const database=q.s.root+'/profile/data/trading-accounts.sqlite3';
  return JSON.parse(cp.execFileSync(python,['-c',"import sqlite3,json,sys;db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(json.dumps({t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['accounts','orders','fills','cash_flows','journal_entries']}))",database],{encoding:'utf8'}));
}
try {
  await launch();
  const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[{name:'MA',period:20}]},
    {session:q.session('ETHUSDT'),indicators:[{name:'MA',period:20}]}],'split-vertical');
  await q.record('workspace-configured',configured);assert.equal(configured.result.state,'ready');
  await q.ready(2,90_000);
  const workspace=(await q.inspect()).workspaceId;
  const beforeFinances=finances();
  const live=await surfaces();const left=live.find(value=>value.cellId==='cell-1'),right=live.find(value=>value.cellId==='cell-2');assert.ok(left&&right);
  const last=Number(right.rows.at(-1).time)-3600;
  await q.execute('cell-2','visibleTimeRange',{from:last-1800,to:last});await q.delay(300);
  const siblingBefore=(await q.query('cell-2')).snapshot.visibleRange;
  const first=await capture('cell-1',left.rows,160,100);
  const saved=await read('/history-studies/views/'+owner(workspace,'cell-1'));
  assert.equal(saved.study.rows.length,160);assert.ok(saved.study.rows.at(-1).closeTimeMs>first.cursor);
  await q.record('frozen-prefetch-and-visible-prefix',await verify(first,first.cursor,'initial'));
  assert.equal(await q.s.page.locator('[data-study-context="true"]').count(),1);
  assert.equal(await q.s.page.locator('.alert-toggle-btn').count(),0);
  assert.equal(await q.s.page.getByRole('button',{name:'交易账户',exact:true}).count(),0);
  assert.equal(await region(first.studyId).getByText('共享历史已更新，本次研究仍保留已保存的输入。',{exact:true}).count(),0);
  const siblingAfter=(await q.query('cell-2')).snapshot.visibleRange;
  assert.deepEqual(siblingAfter.time,siblingBefore.time);assert.equal(siblingAfter.barSpacing,siblingBefore.barSpacing);
  await q.record('sibling-historical-window-preserved',{before:siblingBefore,after:siblingAfter});
  const text='Native historical review annotation v1';
  await region(first.studyId).getByRole('button',{name:'添加复盘补记',exact:true}).click();
  await region(first.studyId).getByLabel('补记内容',{exact:true}).fill(text);
  await region(first.studyId).getByRole('button',{name:'保存并关闭',exact:true}).click();
  await region(first.studyId).getByText(text,{exact:true}).waitFor();
  await region(first.studyId).getByRole('button',{name:'编辑补记',exact:true}).click();
  await region(first.studyId).getByLabel('补记内容',{exact:true}).fill(text+' updated v2');
  await region(first.studyId).getByRole('button',{name:'保存并关闭',exact:true}).click();
  await region(first.studyId).getByText(text+' updated v2',{exact:true}).waitFor();
  const notes=await read(`/history-studies/${first.studyId}/notes?cursorMs=${first.cursor}`);
  assert.equal(notes.notes.length,1);const note=notes.notes[0];assert.equal(note.reviewNote,true);assert.equal(note.marketTimeMs,first.cursor);
  assert.ok(note.updatedAtMs>note.marketTimeMs);assert.equal(note.revisions.length,2);assert.equal(note.revisions[0].fields.entryBasis,text);
  await q.record('review-annotation-versions-and-real-write-time',note);
  const rewind=Number(first.rows[50].time)*1000+30_000;
  await region(first.studyId).getByLabel('回放时刻（UTC）',{exact:true}).fill(stamp(rewind));
  await region(first.studyId).getByRole('button',{name:'改变回放时刻',exact:true}).click();
  await q.record('rewind-hides-forming-candle-and-recomputes-prefix',await verify(first,rewind,'rewind'));
  assert.equal(await region(first.studyId).getByText(text+' updated v2',{exact:true}).count(),0);
  assert.deepEqual((await read(`/history-studies/${first.studyId}/notes?cursorMs=${rewind}`)).notes,[]);
  await q.screenshot('history-study-rewind');await quit();

  await launch();await q.ready(2,90_000);await region(first.studyId).waitFor({timeout:60_000});
  await q.record('restart-restores-fixed-input-and-cut',await verify(first,rewind,'restart'));
  const restored=await read('/history-studies/views/'+owner(workspace,'cell-1'));
  assert.deepEqual(restored.study,saved.study);assert.equal(restored.cursorMs,rewind);assert.equal(restored.active,true);
  assert.equal(await region(first.studyId).getByText(text+' updated v2',{exact:true}).count(),0);
  const secondSource=(await surfaces()).find(value=>value.cellId==='cell-2'&&!value.dataset.startsWith('hs_'));assert.ok(secondSource);
  const second=await capture('cell-2',secondSource.rows,100,60);
  assert.notEqual(second.studyId,first.studyId);
  await q.record('second-independent-study',await verify(second,second.cursor,'second'));
  await region(second.studyId).getByRole('button',{name:'下次收盘',exact:true}).click();
  await q.record('second-cursor-advances-alone',await verify(second,second.cursor+60_000,'second-step'));
  await verify(first,rewind,'first-unchanged');
  await activate('cell-1');
  await region(first.studyId).getByLabel('回放时刻（UTC）',{exact:true}).fill(stamp(first.cursor));
  await region(first.studyId).getByRole('button',{name:'改变回放时刻',exact:true}).click();
  await verify(first,first.cursor,'forward');await region(first.studyId).getByText(text+' updated v2',{exact:true}).waitFor();
  await q.record('forward-reveals-supplement-without-changing-second',{first:await verify(first,first.cursor,'first-forward'),second:await verify(second,second.cursor+60_000,'second-unchanged')});
  await q.screenshot('two-independent-history-studies');
  await region(first.studyId).getByRole('button',{name:'保存并返回实时',exact:true}).click();await region(first.studyId).waitFor({state:'hidden'});
  await activate('cell-2');await region(second.studyId).getByRole('button',{name:'保存并返回实时',exact:true}).click();await region(second.studyId).waitFor({state:'hidden'});
  assert.deepEqual(finances(),beforeFinances);await q.record('no-account-order-fill-or-journal-side-effects',{before:beforeFinances,after:finances(),studyRequests});
  await q.screenshot('studies-return-to-live');await quit();
  assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
} catch(error) {
  q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
  if(q.s.page) {
    await q.screenshot('history-study-failure').catch(()=>{});
    q.s.receipt.diagnostics={surfaces:await surfaces().catch(String),body:await q.s.page.locator('body').innerText().catch(String)};
  }
} finally {
  if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error.stack||error);}
  await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
