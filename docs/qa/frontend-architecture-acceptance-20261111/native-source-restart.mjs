import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {captureRendered} from './rendered-probe.mjs';

assert.ok(process.env.CS_ACCEPTANCE_APP&&process.env.CS_ACCEPTANCE_PROFILE);
q.s.env.INGESTION_HTTP_TIMEOUT='120';q.s.env.PYTHONDONTWRITEBYTECODE='1';
q.s.receipt={schema:'candlescope.native-source-restart/1',sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
 scope:'Installed current-source Binance/OKX recovery and same-profile restart; actual source health and last 60 closed rendered values, separate from full endurance/viewport qualification',
 configuration:{ingestionHttpTimeoutSeconds:120},steps:[],errors:[]};
async function health(input){return q.s.page.evaluate(input=>{
 const el=document.querySelector('[data-chart-cell-id]');let root=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))];while(root.return)root=root.return;
 let manager;function visit(n){if(!n||manager)return;const v=n.memoizedProps?.value;if(v?.dataManager?.cache&&v.indicatorDataManager)manager=v.dataManager;visit(n.child);visit(n.sibling);}visit(root.stateNode.current);
 const plan=manager.cache.planHistory(input,500);return {action:plan.action,health:plan.health,count:plan.snapshot.rows.length,lastClosedTime:plan.snapshot.rows.at(-1)?.time};
 },input);}
async function oracle(){let last;return q.until(async()=>{try{
 const windows=await capture(q),display=await captureRendered(q),result=[];
 for(const chart of windows){
  const rendered=display.find(c=>c.cellId===chart.cellId);assert.ok(rendered);
  assert.deepEqual(rendered.lines.map(l=>l.id).sort(),['qa-ma','qa-js','qa-pine','qa-python'].sort());
  const candles=new Map(rendered.candles.map(b=>[Number(b.time),b])),closed=chart.bars.filter(b=>b.is_closed),rows=closed.slice(-60),checked=[];assert.equal(rows.length,60);
  for(const b of rows){assert.ok(candles.has(b.time));for(const key of ['open','high','low','close'])assert.equal(candles.get(b.time)[key],b[key]);}
  for(const line of rendered.lines){const points=new Map(line.data.map(p=>[Number(p.time),p.value]));
   for(const b of rows){const index=closed.findIndex(r=>r.time===b.time);assert.ok(index>=19);
    const expected=line.id==='qa-ma'?closed.slice(index-19,index+1).reduce((n,r)=>n+r.close,0)/20:b.close*(line.id==='qa-js'?2:line.id==='qa-pine'?3:4);
    assert.ok(Math.abs(points.get(b.time)-expected)<=Math.max(1e-7,Math.abs(expected)*1e-10),`${chart.cellId} ${line.id} missing/wrong ${b.time}`);
   }checked.push({id:line.id,closedPoints:rows.length});
  }result.push({cellId:chart.cellId,symbol:chart.symbol,checked});
 }return result;
 }catch(error){last=String(error);return false;}},180000).catch(error=>{throw new Error(String(error)+' '+last);});}
let active=false;let saved;
try{
 await fs.mkdir(q.s.root,{recursive:true});
 for(const phase of ['initial','restart']){
  await q.record(phase+'-launch',await q.launch({executablePath:process.env.CS_ACCEPTANCE_APP,profileRoot:process.env.CS_ACCEPTANCE_PROFILE}));active=true;await q.enableControl();
  const snap=await q.inspect();assert.equal(snap.cells.length,2);
  if(phase==='initial'){
   await q.execute(snap.cells[0].cellId,'session',{exchange:'okx',marketType:'spot',symbol:'BTC-USDT',interval:'1m'});
   await q.execute(snap.cells[1].cellId,'session',{exchange:'binance',marketType:'spot',symbol:'BTCUSDT',interval:'1m'});
  }
  await q.ready(2,300000);await q.indicatorsReady(2,180000);
  const current=await q.inspect(),sources=[];
  for(const cell of current.cells){const proof=await q.until(async()=>{const h=await health(cell.session);return h.action==='reuse'?h:false;},300000);sources.push({cellId:cell.cellId,session:cell.session,proof});}
  assert.deepEqual(new Set(current.cells.map(c=>c.session.exchange)),new Set(['binance','okx']));
  const configuration={layout:current.layout,cells:current.cells.map(c=>({cellId:c.cellId,session:c.session,indicatorSignature:c.runtime.indicatorSignature}))};
  if(saved)assert.deepEqual(configuration,saved);else saved=configuration;
  await q.record(phase+'-healthy-values',{sources,configuration,values:await oracle()});await q.screenshot(phase);
  assert.equal((await q.inspect()).persistence.state,'saved');const processes=await q.quit();await q.exited();active=false;await q.record(phase+'-full-exit',{processes});
 }
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(active){await q.screenshot('failure').catch(()=>{});await q.record('failure-workspace',await q.inspect()).catch(()=>{});}}
finally{if(active)try{await q.quit();await q.exited();}catch(error){q.s.receipt.exitFailure=String(error);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
