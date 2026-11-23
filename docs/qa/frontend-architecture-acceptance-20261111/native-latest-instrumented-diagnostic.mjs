import fs from 'node:fs/promises';
import * as q from '/Users/ryanliang/.codex/worktrees/indicator-results-161-164-20261111/CandleScope/docs/qa/backend-batch1-20261101/driver.mjs';
import {capture} from '/Users/ryanliang/.codex/worktrees/indicator-results-161-164-20261111/CandleScope/docs/qa/backend-batch1-20261101/value-probe.mjs';
q.s.env.INGESTION_HTTP_TIMEOUT='120';q.s.receipt={scope:'Instrumented diagnostic only; wraps Feed getBars to record unchanged result, not acceptance',steps:[],errors:[]};let active=false;
try{
 await fs.mkdir(q.s.root,{recursive:true});await q.record('launch',await q.launch({executablePath:process.env.CS_ACCEPTANCE_APP,profileRoot:process.env.CS_ACCEPTANCE_PROFILE}));active=true;await q.enableControl();
 const series={symbol:'BTCUSDT',interval:'1m',exchange:'binance',marketType:'spot'};
 await q.configure([{session:series,indicators:[]},{session:series,indicators:[]}],'split-vertical');const w=await q.ready(2,300000);const primary=w.cells[0].cellId,secondary=w.cells[1].cellId;
 const command=async(groupId,command,args)=>{const requestId='diag-'+Date.now();await q.s.control.call('app.execute',{windowId:'main-window',groupId,command,args,requestId});return q.until(async()=>{const r=await q.s.control.call('request.get',{requestId});return r.final?r:false;},30000);};
 await command('workspace','setLinkGroup',{cellIds:[primary,secondary],groupId:null});
 for(let i=0;i<22;i++){const before=(await capture(q)).find(c=>c.cellId===primary),old=before.bars[0].time;await q.execute(primary,'loadMoreLeft',{});await q.until(async()=>{const c=(await capture(q)).find(c=>c.cellId===primary);return c.bars[0].time<old;},120000);if(before.bars.length>=10000)break;}
 const deep=(await capture(q)).find(c=>c.cellId===primary);await q.execute(primary,'visibleTimeRange',{from:deep.bars[1000].time,to:deep.bars[1080].time});
 await q.s.page.evaluate(()=>{window.__latestDiag=[];const el=document.querySelector('[data-chart-cell-id]');let root=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(root.return)root=root.return;const seen=new Set();function visit(n){if(!n)return;let h=n.memoizedState;for(let i=0;h&&i<1000;i++,h=h.next)for(const v of [h.memoizedState?.current,h.memoizedState?.[0],h.memoizedState]){if(!v||seen.has(v))continue;if(typeof v.currentEpoch==='function'&&v.requestDemandBySeries instanceof Map){seen.add(v);const old=v.getBars;v.getBars=async function(...args){const input={series:args[0],options:args[1],epoch:this.currentEpoch(args[0])};const r=await old.apply(this,args);const{data,rows,...meta}=r;window.__latestDiag.push({input,result:{...meta,count:data?.length,first:data?.[0],last:data?.at(-1)},epochAfter:this.currentEpoch(args[0]),demand:[...this.requestDemandBySeries]});return r;};}}visit(n.child);visit(n.sibling);}visit(root.stateNode.current);});
 await q.s.page.locator(`[data-chart-cell-id="${primary}"] .chart-return-to-realtime`).click();
 await q.delay(12000);await q.record('after-click',{charts:(await capture(q)).map(c=>({cellId:c.cellId,count:c.bars.length,first:c.bars[0],last:c.bars.at(-1)})),diag:await q.s.page.evaluate(()=>window.__latestDiag)});await q.screenshot('after-click');
}catch(error){q.s.receipt.failure=String(error.stack??error);process.exitCode=1;}
finally{if(active){await q.quit();await q.exited();}await q.save();}
