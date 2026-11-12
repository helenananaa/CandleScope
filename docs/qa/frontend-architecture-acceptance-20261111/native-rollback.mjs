import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {captureRendered} from './rendered-probe.mjs';
assert.ok(process.env.CS_ROLLBACK_BASELINE_APP&&process.env.CS_ROLLBACK_CANDIDATE_APP&&process.env.CS_ROLLBACK_PROFILE);
q.s.env.PYTHONDONTWRITEBYTECODE='1';
q.s.receipt={schema:'candlescope.frontend-renderer-rollback/1',steps:[],errors:[],
 sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
 precondition:process.env.CS_ROLLBACK_WARMUP==='1'?'Current renderer first restores the same saved source profile; warm-data schema/transport rollback only':'Saved profile without a current-renderer warmup',
 scope:'Sequential baseline/candidate production frontend bundles on the same verified current backend/runtime and isolated saved profile; not an old backend release downgrade',
 baseline:'12514a92fb4cc8745e3564538dd68247316e019d'};
if(process.env.CS_ROLLBACK_INGESTION_HTTP_TIMEOUT){
 const timeout=Number(process.env.CS_ROLLBACK_INGESTION_HTTP_TIMEOUT);assert.ok(Number.isInteger(timeout)&&timeout>0&&timeout<=300);
 q.s.env.INGESTION_HTTP_TIMEOUT=String(timeout);q.s.receipt.configuration={ingestionHttpTimeoutSeconds:timeout};
}
async function oracle(){
 let last;
 return q.until(async()=>{try{
  const windows=await capture(q),rendered=await captureRendered(q),result=[];assert.equal(windows.length,2);assert.equal(rendered.length,2);
  for(const window of windows){
   const display=rendered.find(c=>c.cellId===window.cellId);assert.ok(display);const closed=window.bars.filter(b=>b.is_closed);
   const range=(await q.query(window.cellId)).snapshot.visibleRange.time;
   const visible=closed.filter(b=>b.time>=range.from&&b.time<=range.to);assert.ok(visible.length>=20);
   const candles=new Map(display.candles.map(b=>[Number(b.time),b]));
   for(const bar of visible){assert.ok(candles.has(bar.time));for(const key of ['open','high','low','close'])assert.equal(candles.get(bar.time)[key],bar[key]);}
   const points=[];
   for(const id of ['qa-ma','qa-js','qa-pine','qa-python']){
    const line=display.lines.find(l=>l.id===id);assert.ok(line,'missing rendered '+id);const values=new Map(line.data.map(p=>[Number(p.time),p.value]));let checked=0;
    for(const bar of visible){const index=closed.findIndex(b=>b.time===bar.time);if(index<19)continue;
     const expected=id==='qa-ma'?closed.slice(index-19,index+1).reduce((sum,b)=>sum+b.close,0)/20:bar.close*(id==='qa-pine'?3:id==='qa-python'?4:2);
     assert.ok(Math.abs(values.get(bar.time)-expected)<=Math.max(1e-7,Math.abs(expected)*1e-10));checked++;
    }
    assert.ok(checked>=20);points.push({id,checked});
   }
   result.push({cellId:window.cellId,symbol:window.symbol,interval:window.interval,visibleCandles:visible.length,points});
  }
  return result;
 }catch(error){last=String(error);return false;}},180000).catch(error=>{throw new Error(String(error)+' '+last);});
}
async function savedConfiguration(snapshot){
 const definitions=await q.s.page.evaluate(()=>{
  const el=document.querySelector('[data-chart-cell-id]');let root=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(root.return)root=root.return;
  const cells={};function visit(node){if(!node)return;const cell=node.memoizedProps?.cell;
   if(cell?.id&&Array.isArray(cell.indicators))cells[cell.id]=cell.indicators;visit(node.child);visit(node.sibling);}
  visit(root.stateNode.current);return cells;
 });
 return {layout:snapshot.layout,cells:snapshot.cells.map(cell=>{assert.ok(definitions[cell.cellId]);return {cellId:cell.cellId,session:cell.session,indicators:definitions[cell.cellId]};})};
}
let baseline,active=false;
try{
 await fs.mkdir(q.s.root,{recursive:true});
 const phases=[...(process.env.CS_ROLLBACK_WARMUP==='1'?[['warmup',process.env.CS_ROLLBACK_CANDIDATE_APP]]:[]),['baseline',process.env.CS_ROLLBACK_BASELINE_APP],['candidate',process.env.CS_ROLLBACK_CANDIDATE_APP]];
 for(const [phase,executablePath] of phases){
  await q.record(phase+'-launch',await q.launch({executablePath,profileRoot:process.env.CS_ROLLBACK_PROFILE}));active=true;
  await q.enableControl();await q.ready(2,180000);await q.indicatorsReady(2,180000);
  const snapshot=await q.inspect(),configuration=await savedConfiguration(snapshot),broker=await q.broker();
  if(process.env.CS_ROLLBACK_ORIGINAL_CONFIGURATION){
   const original=JSON.parse(await fs.readFile(process.env.CS_ROLLBACK_ORIGINAL_CONFIGURATION,'utf8'));
   const definitions=cells=>cells.map(cell=>({cellId:cell.cellId,indicators:cell.indicators})).sort((a,b)=>a.cellId.localeCompare(b.cellId));
   assert.equal(configuration.layout,original.layout);
   assert.deepEqual(definitions(configuration.cells),definitions(original.cells),'current restart changed exact saved scripts/parameters');
   await q.record(phase+'-original-definitions-preserved',{original:process.env.CS_ROLLBACK_ORIGINAL_CONFIGURATION,layout:configuration.layout,definitions:definitions(configuration.cells)});
  }
  if(!baseline)baseline=configuration;else assert.deepEqual(configuration,baseline,'frontend rollback changed saved chart configuration');
  const distinctSeries=new Set(snapshot.cells.map(cell=>JSON.stringify(cell.session))).size;
  assert.equal(snapshot.persistence.state,'saved');
  const expectedPhysical=broker.marketDataManager.mode==='batch'?1:distinctSeries;
  assert.equal(broker.marketDataManager.physicalStreams,expectedPhysical,'unexpected physical market transport duplication');
  assert.equal(broker.marketDataManager.activeLogicalSubscriptions,distinctSeries,'saved source subscriptions were not all active');
  await q.record(phase+'-transport-topology',{mode:broker.marketDataManager.mode,expectedPhysical,distinctSeries,broker:broker.marketDataManager});
  assert.ok(broker.indicator.logicalClients<=2,'duplicate indicator owners after version switch');
  await q.record(phase+'-oracle',{configuration,broker,oracle:await oracle()});await q.screenshot(phase);
  const processes=await q.quit();await q.exited();active=false;await q.record(phase+'-full-exit',{processes});
 }
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(active)try{await q.record('failure-workspace',await q.inspect());await q.screenshot('failure');}catch{}}
finally{if(active)try{await q.quit();await q.exited();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure,root:path.resolve(q.s.root)}));}
