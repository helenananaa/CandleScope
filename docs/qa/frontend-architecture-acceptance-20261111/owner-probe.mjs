// Read bounded ownership metadata in the committed React tree without changing it.
export async function captureOwners(q){return q.s.page.evaluate(()=>{
 const el=document.querySelector('[data-chart-cell-id]');if(!el)return [];
 let root=el[Object.keys(el).find(key=>key.startsWith('__reactFiber$'))];while(root.return)root=root.return;
 const result=[],seen=new Set();function visit(node){if(!node)return;let hook=node.memoizedState;
  for(let i=0;hook&&i<1000;i++,hook=hook.next)for(const value of [hook.memoizedState?.current,hook.memoizedState?.[0],hook.memoizedState]){
   if(!value||seen.has(value))continue;
   if(typeof value.hasPending==='function'&&value.pending instanceof Map){seen.add(value);result.push({kind:'indicator-window',pending:[...value.pending].map(([key,state])=>({key,owners:[...state.owners],epoch:state.epoch,ranges:state.ranges}))});}
   if(typeof value.currentEpoch==='function'&&value.requestDemandBySeries instanceof Map){seen.add(value);result.push({kind:'feed',demands:[...value.requestDemandBySeries],epochs:[...value.epochBySeries],repairGenerations:[...value.gapRepairGenerationBySeries],pendingRepairs:[...value.pendingGapRepairs].map(([key,p])=>({key,range:p.range,attempts:p.attempts,terminalReason:p.terminalReason,nextPollAt:p.nextPollAt}))});}
  }visit(node.child);visit(node.sibling);
 }visit(root.stateNode.current);return result;
});}
