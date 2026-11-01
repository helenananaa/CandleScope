import assert from 'node:assert/strict';
export async function capture(q) {
  return q.s.page.evaluate(() => {
    const el = document.querySelector('[data-chart-cell-id]');
    let fiber = el[Object.keys(el).find(k => k.startsWith('__reactFiber$'))];
    while (fiber.return) fiber = fiber.return;
    const seen = new Set(), charts = [];
    function visit(node) {
      if (!node) return;
      const p = node.memoizedProps;
      if (p?.seriesStore && p.datasetKey && !seen.has(p.seriesStore)) {
        seen.add(p.seriesStore);
        let parent = node, cellId;
        while (parent) { cellId ??= parent.memoizedProps?.['data-chart-cell-id']; parent = parent.return; }
        charts.push({ cellId, dataset: p.datasetKey, symbol: p.symbol, interval: p.interval,
          bars: p.seriesStore.snapshot(), lines: (p.mainOverlayLines ?? []).map(line => ({
            id: line.indicatorId, name: line.name, data: line.data,
          })) });
      }
      visit(node.child); visit(node.sibling);
    }
    visit(fiber.stateNode.current);
    return charts;
  });
}
export async function verify(q, transforms = {}) {
  const charts = await capture(q), evidence = [];
  assert.equal(charts.length,2,'both chart surfaces must be mounted');
  for (const chart of charts) {
    const closed = chart.bars.filter(b => b.is_closed);
    assert.ok(closed.length >= 499);
    const url = new URL(q.s.backend + '/api/v1/klines/range');
    const params = {symbol:chart.symbol,interval:chart.interval,exchange:'binance',market_type:'spot',
      start_ms:closed[0].time*1000,end_ms:closed.at(-1).time*1000,repair:'none',wait_ms:0,strict:false};
    Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,String(v)));
    const response = await q.s.page.evaluate(async u => {const r=await fetch(u);return {status:r.status,body:await r.json()};}, url.href);
    assert.equal(response.status,200); assert.equal(response.body.complete,true);
    const source = new Map(response.body.data.map(bar => [bar.time,bar]));
    for (const bar of closed) {
      const remote = source.get(bar.time); assert.ok(remote, 'missing backend row '+bar.time);
      for (const k of ['open','high','low','close','volume']) assert.equal(bar[k],remote[k],`${chart.cellId} ${bar.time} ${k}`);
    }
    const lines=[];
    for (const line of chart.lines) {
      const values = new Map(line.data.map(p=>[Number(p.time),p.value]));
      assert.equal(values.size,line.data.length,'duplicate indicator timestamps');
      const transform=transforms[line.id]??{scale:1,offset:0};
      for (const bar of closed) {
        const actual=values.get(bar.time), expected=bar.close*transform.scale+(transform.offset??0);
        assert.ok(actual!==undefined,`${line.id} missing closed point ${bar.time}`);
        assert.ok(Math.abs(actual-expected)<1e-7,`${line.id} ${bar.time}: ${actual} != ${expected}`);
      }
      lines.push({id:line.id,checked:closed.length,points:line.data.length,transform});
    }
    assert.ok(lines.length,'missing JS curve');
    evidence.push({cellId:chart.cellId,symbol:chart.symbol,interval:chart.interval,bars:chart.bars.length,
      firstClosed:closed[0].time,lastClosed:closed.at(-1).time,backendRows:source.size,lines});
  }
  return evidence;
}
