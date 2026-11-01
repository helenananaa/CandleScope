import assert from 'node:assert/strict';
import cp from 'node:child_process';
import fs from 'node:fs/promises';
import * as q from '../backend-batch1-20261101/driver.mjs';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
q.s.receipt.schema='candlescope.seconds-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.transport='Packaged bundled backend, real public Binance/Gate/Upbit HTTP and WebSocket; no substituted responses.';
q.s.receipt.scope={platform:'macOS arm64',sources:['Binance spot1s','Binance custom7s','Gate spot1s','Upbit spot1s'],notCovered:['Windows','1s replay archives','ordinary USD-M1s','full157 release acceptance','all exchanges']};
const sessions=[q.session('BTCUSDT','1s'),q.session('BTCUSDT','7s'),{exchange:'gate',marketType:'spot',symbol:'BTC/USDT',interval:'1s'},{exchange:'upbit',marketType:'spot',symbol:'BTC/KRW',interval:'1s'}];
const api=async path=>q.s.page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},q.s.backend+path);
async function ready(indicators=false){return q.until(async()=>{const s=await q.inspect();await fs.writeFile(q.s.root+'/latest-workspace.next.json',JSON.stringify(s,null,2));await fs.rename(q.s.root+'/latest-workspace.next.json',q.s.root+'/latest-workspace.json');return s.cells.length===4&&s.persistence.state==='saved'&&s.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=10&&(!indicators||(c.runtime.indicatorsReady&&!c.runtime.computing&&!c.runtime.indicatorErrors?.length&&c.runtime.indicatorOutputPoints?.some(n=>n>0))))?s:(await q.delay(1000),false);},360000);}
async function range(session,first,last){const p=new URLSearchParams({exchange:session.exchange,market_type:session.marketType,symbol:session.symbol,interval:session.interval,start_ms:String(first*1000),end_ms:String(last*1000),repair:'none',wait_ms:'0',strict:'false'});const started=Date.now();let attempts=0;while(true){const r=await api('/api/v1/klines/range?'+p);attempts++;const clipped=r.body.complete&&Number.isFinite(r.body.effective_end_ms)&&r.body.effective_end_ms<last*1000;if(r.status!==200||(r.body.complete&&!clipped)||(!r.body.retryable&&!clipped)||Date.now()-started>=180000){q.s.receipt.rangeReads??=[];q.s.receipt.rangeReads.push({session,first,last,attempts,elapsedMs:Date.now()-started,status:r.status,historyState:r.body.history_state,effectiveEndMs:r.body.effective_end_ms,complete:r.body.complete,retryable:r.body.retryable,missingRanges:r.body.missing_ranges,cache:r.body.cache});return r;}await q.delay(200);}}
async function verify(){const charts=await capture(q);assert.equal(charts.length,4);const out=[];
 for(let i=0;i<4;i++){const chart=charts.find(c=>c.cellId==='cell-'+(i+1));assert.ok(chart);const bars=chart.bars.filter(b=>b.is_closed).slice(-100);assert.ok(bars.length>=9,chart.cellId);
 const response=await range(sessions[i],bars[0].time,bars.at(-1).time);assert.equal(response.status,200);assert.equal(response.body.complete,true,JSON.stringify(response.body).slice(0,600));assert.equal(response.body.all_rows_final,true);
 const rows=new Map(response.body.data.map(b=>[b.time,b]));for(const b of bars){const r=rows.get(b.time);assert.ok(r);for(const key of ['open','high','low','close','volume'])assert.equal(b[key],r[key],chart.cellId+' '+key);assert.equal(b.time%(i===1?7:1),0);}
 out.push({session:sessions[i],cellId:chart.cellId,bars:chart.bars.length,checked:bars.length,first:bars[0].time,last:bars.at(-1).time,quality:{complete:response.body.complete,all_rows_final:response.body.all_rows_final,history_state:response.body.history_state,excluded_ranges:response.body.excluded_ranges},rows:bars});}
 return out;}
async function values(){const charts=await capture(q),out=[];for(const chart of charts){const bars=chart.bars.filter(b=>b.is_closed);assert.equal(chart.lines.length,1);const line=chart.lines[0],points=new Map(line.data.map(p=>[Number(p.time),p.value]));const view=(await q.query(chart.cellId)).snapshot.visibleRange?.time;assert.ok(view);let checked=0,maxError=0;for(let i=4;i<bars.length;i++){if(bars[i].time<view.from||bars[i].time>view.to)continue;const actual=points.get(bars[i].time),expected=bars.slice(i-4,i+1).reduce((n,b)=>n+b.close,0)/5;assert.ok(actual!==undefined,chart.cellId+' missing visible MA5 '+bars[i].time);const error=Math.abs(actual-expected);assert.ok(error<Math.max(1e-7,Math.abs(expected)*1e-10));maxError=Math.max(maxError,error);checked++;}assert.ok(checked>=3);out.push({cellId:chart.cellId,checked,maxError});}return out;}
let running=false;
async function launch(){try{await q.record('packaged-launch',await q.launch());running=true;await q.enableControl();}catch(e){running=Boolean(q.s.app);q.s.identity??={pid:q.s.app?.process()?.pid};throw e;}}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-process-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
try{
 await launch();
 for(const exchange of ['binance','gate','upbit']){
  const caps=await api('/api/v1/exchanges/'+exchange+'/capabilities');assert.equal(caps.status,200);
  const symbols=await q.until(async()=>{
   const result=await api('/api/v1/symbols/exchange-info?exchange='+exchange+'&market_type=spot&search=BTC');
   if(result.status===200)return result;
   await q.record('catalog-pending-'+exchange,result);
   assert.equal(result.status,503);assert.equal(result.body.detail?.retryable,true);
   await q.delay(3000);return false;
  },180000);
  for(const session of sessions.filter(s=>s.exchange===exchange))assert.ok(symbols.body.symbols.some(s=>s.symbol===session.symbol),'Catalog lacks '+session.symbol);
  await q.record('source-catalog-'+exchange,{caps,symbols});
 }
 // The bulk configuration control deliberately supports only Binance/OKX.
 // Use the registered chart-session command for other advertised providers.
 const configured=await q.configure(sessions.map((session,i)=>({session:i<2?session:q.session('BTCUSDT','1s'),indicators:[]})),'quad');
 await q.record('workspace-layout-configured',configured);assert.ok(['applied','ready'].includes(configured.result.state));
 for(const i of [2,3]){const changed=await q.execute('cell-'+(i+1),'session',sessions[i]);await q.record('source-session-selected-'+sessions[i].exchange,changed);assert.equal(changed.state,'applied');}
 await ready();
 await q.record('canonical-seconds-quality',await verify());
 for(let i=1;i<=4;i++)assert.equal((await q.execute('cell-'+i,'addIndicator',{id:'seconds-ma-'+i,name:'MA',engineName:'MA',kind:'builtin',executionTarget:'hosted',params:{period:5},visible:true})).state,'applied');
 await ready(true);await q.record('visible-indicator-values',await values());const before=await verify();
 await q.until(async()=>{const charts=await capture(q);return charts.length===4&&charts.every(c=>c.bars.filter(b=>b.is_closed).at(-1)?.time>before.find(x=>x.cellId===c.cellId).last)?true:false;},90000);
 const saved=await verify();await q.record('new-closes-and-saved-workspace',{quality:saved,values:await values(),workspace:await ready(true)});await q.screenshot('saved-seconds');await quit();
 await launch();await ready(true);const restored=await verify();for(const item of saved){const r=await range(item.session,item.first,item.last);assert.equal(r.status,200);assert.equal(r.body.complete,true);const rows=new Map(r.body.data.map(b=>[b.time,b]));for(const b of item.rows)for(const key of ['open','high','low','close','volume'])assert.equal(rows.get(b.time)?.[key],b[key]);}await q.record('restart-restores-persisted-seconds',{quality:restored,values:await values(),workspace:await q.inspect()});await q.screenshot('restored-seconds');await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running){await q.screenshot('failure').catch(()=>{});for(const [name,path]of [['storage-health','/api/v1/settings/storage/health'],['support','/api/v1/support/diagnostics'],['runtime-snapshot','/debug/snapshot']])await q.record('failure-'+name,await api(path).catch(e=>({error:String(e)}))).catch(()=>{});}}
finally{if(running)try{await quit();}catch(e){q.s.receipt.exitFailure=String(e);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
