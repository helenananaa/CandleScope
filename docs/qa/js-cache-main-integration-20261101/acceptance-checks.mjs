import assert from 'node:assert/strict';
export async function monitor(q) { return q.s.page.evaluate(()=>window.__CANDLESCOPE_INDICATOR_MONITOR__?.snapshot()); }
export async function visibleCoverage(q) {
  const m=await monitor(q), views=await Promise.all(['cell-1','cell-2'].map(id=>q.query(id)));
  return m.runtimes.map((r,i)=>{
    const view=views[i].snapshot.visibleRange?.time;
    assert.ok(view,'visible range missing');
    const end=Math.min(view.to,r.chart.lastClosedTime), start=Math.max(view.from,r.chart.firstTime);
    const indicators=r.indicators.map(ind=>{
      assert.equal(ind.error,null);
      const lines=ind.lines.map(l=>{
        assert.equal(l.invalidPoints,0);assert.equal(l.duplicateTimes,0);assert.equal(l.outOfOrderPoints,0);
        const visibleGaps=l.interiorMissingRanges.filter(g=>g.start<=end&&g.end>=start);
        assert.equal(visibleGaps.length,0,`${ind.id} has a gap inside painted viewport`);
        assert.ok(l.pointCount>0,`${ind.id} no points`);
        // Recursive builtin warmup can omit a leading prefix. JS/Pine close scripts cannot.
        if(ind.id.includes('-js-') || ind.id.includes('-pine-')) { assert.ok(l.firstTime<=start,`${ind.id} starts after viewport`);assert.ok(l.lastTime>=end,`${ind.id} ends before viewport`); }
        return {id:l.lineId,points:l.pointCount,first:l.firstTime,last:l.lastTime,visibleGaps};
      }); return {id:ind.id,lines};
    });return {context:r.context,view,checked:{start,end},indicators};
  });
}
export async function watch(q) {
  q.s.indicatorSamples=[]; q.s.cdp=await q.s.page.context().newCDPSession(q.s.page);await q.s.cdp.send('Network.enable');
  q.s.cdp.on('Network.webSocketFrameReceived',e=>{try{const j=JSON.parse(e.response.payloadData);if(j.clientId&&String(j.type).startsWith('indicator.')) {
    q.s.indicatorSamples.push({at:Date.now(),type:j.type,clientId:j.clientId,range:j.range,revision:j.dataRevision,lines:j.lines?.map(l=>({id:l.id,count:l.data?.length,closedLast:l.data?.findLast(p=>Number(p.time)<=Number(j.dataRevision?.closedThrough)),last:l.data?.at(-1)}))});if(q.s.indicatorSamples.length>2000)q.s.indicatorSamples.shift();}}catch{}});
}
export function comparable(snapshot) {return {session:snapshot.session,indicators:snapshot.indicators?.map(i=>Object.fromEntries(['id','name','engineName','kind','executionTarget','language','script','securityMode','params','visible','pane','paneId','paneTarget'].filter(k=>i[k]!==undefined).map(k=>[k,i[k]])))};}
