import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
q.s.receipt.schema='candlescope.backend-first-stage-live-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.transport='Local packaged candidate and bundled backend; fresh isolated profile, real public market requests and virtual practice funds only.';
q.s.receipt.scope='Cold 1m/5m readiness, saved independent chart configuration, practice entry and coherent ledger projections, owned full exit/restart. Unscoped scheduling and SQLite write interleavings qualified separately by deterministic regressions.';
let running=false,accountId;
const api=(path,method='GET',body)=>q.s.page.evaluate(async({url,method,body})=>{
 const r=await fetch(url,{method,headers:body?{'content-type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})});
 const value=await r.json();if(!r.ok)throw new Error(r.status+' '+JSON.stringify(value));return value;
},{url:q.s.backend+path,method,body});
async function launch(){try{await q.record('launch',await q.launch());running=true;}catch(e){running=Boolean(q.s.app);if(running)q.s.identity={pid:q.s.app.process().pid};throw e;}await q.enableControl();}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
async function ledger(){return {
 summary:await api('/api/v1/trading/accounts/'+accountId+'/summary'),
 fills:await api('/api/v1/trading/accounts/'+accountId+'/fills'),
 trades:await api('/api/v1/trading/accounts/'+accountId+'/trades'),
 stats:await api('/api/v1/trading/accounts/'+accountId+'/stats'),
};}
function stable(value){return {balance:value.summary.balance,positions:value.summary.positions.map(p=>({symbol:p.symbol,openQty:p.openQty,side:p.side})),fills:value.fills,trades:value.trades.trades.map(t=>({id:t.id,openQty:t.openQty,status:t.status}))};}
try{
 await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT','1m'),indicators:[]},{session:q.session('BTCUSDT','5m'),indicators:[]}],'split-vertical');
 assert.ok(['applied','ready'].includes(configured.result.state),JSON.stringify(configured.result));
 const coldStarted=Date.now(),ready=await q.ready(2,60000);
 await q.record('cold-native-1m-and-5m',{elapsedMs:Date.now()-coldStarted,snapshot:ready});
 await q.screenshot('cold-native-charts');
 if(!await q.s.page.locator('.trading-panel').isVisible())await q.s.page.getByRole('button',{name:'交易账户',exact:true}).click();
 await q.s.page.getByRole('button',{name:'添加账户',exact:true}).first().click();
 const dialog=q.s.page.getByRole('dialog',{name:'添加账户',exact:true});
 await dialog.getByLabel('名称',{exact:true}).fill('Stage1 isolated practice');
 const creating=q.s.page.waitForResponse(r=>r.url().endsWith('/trading/accounts')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'创建',exact:true}).click();
 const created=await creating;assert.equal(created.status(),200);const account=await created.json();
 assert.equal(account.kind,'practice');accountId=account.id;
 await q.s.page.getByLabel('数量（BTC）',{exact:true}).fill('0.001');
 const ordering=q.s.page.waitForResponse(r=>r.url().endsWith('/orders')&&r.request().method()==='POST');
 await q.s.page.getByRole('button',{name:'提交买入',exact:true}).click();
 const ordered=await ordering;assert.equal(ordered.status(),200);const order=await ordered.json();assert.equal(order.order.status,'filled');
 const first=await q.until(async()=>{const v=await ledger();return v.summary.positions.length===1&&v.summary.workingOrders.length===0?v:false;},30000);
 assert.equal(first.summary.positions[0].openQty,'0.001');
 await q.record('practice-committed-projections',{order,ledger:first});
 await q.screenshot('practice-before-restart');
 const saved=await q.ready(2,30000);await q.record('saved-workspace',saved);await quit();
 await launch();await q.ready(2,60000);
 const restored=await ledger();assert.deepEqual(stable(restored),stable(first));
 const workspace=await q.inspect();assert.deepEqual(workspace.cells.map(c=>c.session.interval),['1m','5m']);
 await q.record('restored-ledger-and-workspace',{ledger:restored,workspace});
 await q.screenshot('practice-after-restart');await quit();
 assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;
 if(running){await q.screenshot('live-failure').catch(()=>{});try{await q.record('failure-diagnostics',await api('/debug/snapshot'));}catch{}}
}finally{
 if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error);}
 await q.save();await fs.writeFile(q.s.root+'/live-acceptance.json',JSON.stringify(q.s.receipt,null,2)+'\n');
 console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
