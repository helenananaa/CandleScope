// Read actual Lightweight Charts series in the committed native React tree.
// Component input props alone do not establish that a display commit landed.
export async function captureRendered(q) {
 return q.s.page.evaluate(()=>{
  const el=document.querySelector('[data-chart-cell-id]');if(!el)return [];
  let root=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(root.return)root=root.return;
  const charts=[],seen=new Set();
  function visit(node){
   if(!node)return;const p=node.memoizedProps;
   if(p?.seriesStore&&p.datasetKey&&!seen.has(p.seriesStore)){
    let hook=node.memoizedState,entries,candles;
    for(let count=0;hook&&count<1000;count++,hook=hook.next){
     const value=hook.memoizedState?.current;
     if(Array.isArray(value)&&value.length&&value.every(e=>e?.lineConfig&&typeof e.series?.data==='function'))entries=value;
     if(value&&typeof value.data==='function'&&typeof value.seriesType==='function'&&value.seriesType()==='Candlestick')candles=value.data();
    }
    if(entries&&candles){
     seen.add(p.seriesStore);let parent=node,cellId;
     while(parent){cellId??=parent.memoizedProps?.['data-chart-cell-id'];parent=parent.return;}
     charts.push({cellId,symbol:p.symbol,interval:p.interval,candles,
      lines:entries.map(e=>({id:e.lineConfig.indicatorId,data:e.series.data()}))});
    }
   }
   visit(node.child);visit(node.sibling);
  }
  visit(root.stateNode.current);return charts;
 });
}
