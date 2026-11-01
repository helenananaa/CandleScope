import assert from 'node:assert/strict';
export const transforms = {'qa-js-right':{scale:2,offset:5}};
export const script='plot("close",bars.map(bar=>bar.close*Number(params.scale??1)),{pane:"main",color:"#f59e0b"});';
export const definition=id=>({id,name:'JS Close '+id,kind:'script',executionTarget:'local',language:'frontend-js',securityMode:'safe',script,params:{scale:1},visible:true});
export async function healthy(q,vp,expected,transform=transforms) {
  let failure;
  const result=await q.until(async()=>{
    assert.deepEqual(q.s.receipt.errors,[],'renderer error');
    const snap=await q.inspect();
    if(snap.persistence.state!=='saved'||snap.cells.some(c=>!c.runtime.marketReady||c.runtime.loading||c.runtime.computing||c.runtime.indicatorErrors.length))return false;
    const chart=(await vp.capture(q)).find(c=>c.cellId==='cell-1');
    if(!chart||chart.symbol!==expected.symbol||chart.interval!==expected.interval||chart.bars.length<1500)return false;
    try{return await vp.verify(q,transform);}catch(error){failure=String(error);return false;}
  },45000).catch(e=>{throw new Error(e.message+' '+(failure??''));});
  assert.equal((await q.broker()).dataFlow.indicators.inputs.subscriptions,2);
  return result;
}
export async function initial(q,vp,checks) {
  const result=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');
  assert.equal(result.result.state,'ready');
  for(const [cell,id] of [['cell-1','qa-js-left'],['cell-2','qa-js-right']])assert.equal((await q.execute(cell,'addIndicator',definition(id))).state,'applied');
  await healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'},{});
  await q.record('dual-js-baseline',{values:await vp.verify(q),coverage:await checks.visibleCoverage(q),broker:await q.broker()});
  await q.execute('cell-2','indicatorParams',{indicatorId:'qa-js-right',params:{scale:2}});
  await healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'},{'qa-js-right':{scale:2}});
  await q.record('independent-params',{values:await vp.verify(q,{'qa-js-right':{scale:2}})});
  await q.execute('cell-2','indicatorScript',{indicatorId:'qa-js-right',script:'plot("close",bars.map(bar=>bar.close*Number(params.scale??1)+5),{pane:"main",color:"#38bdf8"});',language:'frontend-js',securityMode:'safe'});
  await healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'});
  await q.record('independent-script',{values:await vp.verify(q,transforms)});
}
export async function coldSwitch(q,vp,checks,symbol,interval) {
  // Pin the sibling to a distinct historical window before checking pan
  // isolation. Its live-tail time range can otherwise change on an incoming
  // candle independently of the operation being tested.
  const sibling=(await vp.capture(q)).find(c=>c.cellId==='cell-2');
  const siblingRange={from:sibling.bars[100].time,to:sibling.bars[300].time};
  assert.equal((await q.execute('cell-2','visibleTimeRange',siblingRange)).state,'applied');
  await q.until(async()=>{
    const r=(await q.query('cell-2')).snapshot.visibleRange?.time;
    return r&&Math.abs(r.from-siblingRange.from)<60&&Math.abs(r.to-siblingRange.to)<60;
  });
  const viewsBefore=await Promise.all(['cell-1','cell-2'].map(id=>q.query(id)));
  const left=(await vp.capture(q)).find(c=>c.cellId==='cell-1');
  const requested={from:left.bars[100].time,to:left.bars[200].time};
  assert.equal((await q.execute('cell-1','visibleTimeRange',requested)).state,'applied');
  await q.until(async()=>{const range=(await q.query('cell-1')).snapshot.visibleRange?.time;return range&&Math.abs(range.from-requested.from)<left.bars[1].time-left.bars[0].time?range:false;});
  const rightBefore=(await q.query('cell-2')).snapshot;
  assert.deepEqual(rightBefore.visibleRange.time,viewsBefore[1].snapshot.visibleRange.time,'left pan moved right viewport');
  assert.equal((await q.execute('cell-1','session',q.session(symbol,interval))).state,'applied');
  const values=await healthy(q,vp,{symbol,interval});
  const rightAfter=(await q.query('cell-2')).snapshot;
  assert.deepEqual(checks.comparable(rightAfter),checks.comparable(rightBefore),'switch changed sibling settings');
  await q.record('historical-cold-switch-'+symbol+'-'+interval,{requested,values,coverage:await checks.visibleCoverage(q),broker:await q.broker()});
}
export async function release(q,vp) {
  await q.execute('cell-1','removeIndicator',{indicatorId:'qa-js-left'});
  await q.until(async()=> (await q.broker()).dataFlow.indicators.inputs.subscriptions===1);
  const surviving=(await q.query('cell-2')).snapshot.indicators;
  assert.equal(surviving[0].id,'qa-js-right');assert.ok(surviving[0].outputPointCount>=499);
  await q.record('single-input-release',{surviving,broker:await q.broker()});
  await q.execute('cell-1','addIndicator',definition('qa-js-left'));
  await healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'});
  await q.record('input-reacquire',{values:await vp.verify(q,transforms)});
}
