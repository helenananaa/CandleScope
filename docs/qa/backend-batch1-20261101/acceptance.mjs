import assert from 'node:assert/strict';
import cp from 'node:child_process';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
import * as q from './driver.mjs';
import * as vp from './value-probe.mjs';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.scope={pullRequests:[178,188,189,190,191],platform:'macOS arm64',realProvider:'Binance public',practice:'isolated profile, virtual funds only',notCovered:['Windows/x64 installed acceptance','full 157-item acceptance','all resource owners from #156','HEDGE/exchange account execution from #177']};
let running=false,accountId;
const api=async(path,method='GET',body)=>q.s.page.evaluate(async({url,method,body})=>{const r=await fetch(url,{method,headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw new Error(r.status+' '+JSON.stringify(data));return data;},{url:q.s.backend+path,method,body});
const summary=()=>api('/api/v1/trading/accounts/'+accountId+'/summary');
const snapshot=()=>api('/debug/snapshot');
const leaseCount=(s,key)=>s.stream_leases.series.find(x=>x.key===key)?.consumer_count??0;
const definition=id=>({id,name:'Batch1 JS close',kind:'script',executionTarget:'local',language:'frontend-js',securityMode:'safe',script:'plot("close",bars.map(bar=>bar.close),{pane:"main",color:"#f59e0b"});',params:{},visible:true});
async function verifiedCharts(){let lastFailure;return q.until(async()=>{assert.deepEqual(q.s.receipt.errors,[]);const snap=await q.inspect();if(snap.cells.some(c=>c.runtime.barCount<500||c.runtime.loading||c.runtime.computing))return false;try{return await vp.verify(q);}catch(error){lastFailure=String(error);return false;}},180000).catch(error=>{throw new Error(error.message+'; last value check: '+lastFailure);});}
async function launch(){const e=await q.launch();running=true;await q.record('packaged-launch',e);}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-process-exit',{processes:q.s.quitPids,allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt});}
async function accountPanel(){if(!await q.s.page.locator('.trading-panel').isVisible())await q.s.page.getByRole('button',{name:'交易账户',exact:true}).click();}
async function observePosition(name,after=0){const s=await q.until(async()=>{const v=await summary();return v.positions.length===1&&v.workingOrders.length===0&&v.feeds.length===1&&v.feeds[0].status==='live'&&(v.feeds[0].timing?.measuredAtMs??0)>after?v:false;},90000);const diag=await snapshot();assert.ok(leaseCount(diag,'BTCUSDT@1m')>=1);await q.record(name,{summary:s,streamLeases:diag.stream_leases,barDelivery:diag.bar_delivery});return s;}
try{
 await launch();await q.enableControl();
 const configured=await q.configure([{session:q.session('BTCUSDT'),indicators:[]},{session:q.session('BTCUSDT'),indicators:[]}],'split-vertical');assert.equal(configured.result.state,'ready');
 await q.ready(2,120000);
 for(const [cell,id] of [['cell-1','batch-js-one'],['cell-2','batch-js-two']])assert.equal((await q.execute(cell,'addIndicator',definition(id))).state,'applied');
 await q.indicatorsReady(2,60000);await q.record('native-js-values',await verifiedCharts());
 await accountPanel();await q.s.page.getByRole('button',{name:'添加账户',exact:true}).first().click();
 const dialog=q.s.page.getByRole('dialog',{name:'添加账户',exact:true});await dialog.getByLabel('名称',{exact:true}).fill('Batch 1 native practice');
 const created=q.s.page.waitForResponse(r=>r.url().endsWith('/trading/accounts')&&r.request().method()==='POST');await dialog.getByRole('button',{name:'创建',exact:true}).click();
 const createdResponse=await created;assert.equal(createdResponse.status(),200);const account=await createdResponse.json();accountId=account.id;assert.ok(accountId);assert.equal(account.kind,'practice');
 await q.s.page.getByLabel('数量（BTC）',{exact:true}).fill('0.001');
 const ordered=q.s.page.waitForResponse(r=>r.url().endsWith('/orders')&&r.request().method()==='POST');await q.s.page.getByRole('button',{name:'提交买入',exact:true}).click();
 const orderedResponse=await ordered;assert.equal(orderedResponse.status(),200);const order=await orderedResponse.json();assert.equal(order.order.status,'filled');await q.record('ui-practice-entry',{account,order});
 await q.s.page.getByRole('tab',{name:/^持仓/}).click();
 const first=await observePosition('position-only-feed');
 assert.equal((await q.execute('cell-1','session',q.session('ETHUSDT','7m'))).state,'applied');
 assert.equal((await q.execute('cell-2','session',q.session('SOLUSDT','15m'))).state,'applied');
 await q.ready(2,180000);await q.indicatorsReady(2,90000);
 await q.record('cold-custom-and-native-chart-values',await verifiedCharts());
 const live=await observePosition('position-feed-after-charts-switch',first.feeds[0].timing.measuredAtMs);
 await q.screenshot('position-with-other-charts');
 const before=await snapshot();const stateBefore=before.bar_aggregator.pipelines['7m'].bar_state.component_execution;assert.equal(stateBefore.enabled,true);assert.ok(stateBefore.indexed_states>0);
 const changed=await q.until(async()=>{const d=await snapshot();const c=d.bar_aggregator.pipelines['7m'].bar_state.component_execution;return c.tail_replacements>stateBefore.tail_replacements||c.appends>stateBefore.appends?d:false;},90000);
 await q.record('real-custom-component-updates',{before:stateBefore,after:changed.bar_aggregator.pipelines['7m'].bar_state.component_execution});
 const gc=await api('/api/v1/settings/cache-gc/backend-memory/run','POST',{cold_idle_seconds:0});
 const afterGc=await snapshot();assert.ok(afterGc.cache.series['BTCUSDT@1m']);assert.ok(leaseCount(afterGc,'BTCUSDT@1m')>=1);assert.ok(!gc.results.some(r=>r.key==='BTCUSDT@1m'&&r.removed_bars>0));
 await q.record('native-memory-gc-preserves-position',{gc,streamLeases:afterGc.stream_leases,cache:afterGc.cache});
 await q.ready(2,60000);await q.record('saved-workspace',await q.inspect());await quit();
 await launch();await q.enableControl();await q.ready(2,180000);await q.indicatorsReady(2,90000);await q.record('restart-chart-values',await verifiedCharts());
 const restored=await q.inspect();assert.equal(restored.cells[0].session.symbol,'ETHUSDT');assert.equal(restored.cells[0].session.interval,'7m');
 await accountPanel();await q.s.page.getByRole('tab',{name:/^持仓/}).click();
 await observePosition('restart-position-only-feed',live.feeds[0].timing.measuredAtMs);await q.screenshot('restart-position');
 const beforeClose=await snapshot();const closeResponse=q.s.page.waitForResponse(r=>r.url().endsWith('/orders')&&r.request().method()==='POST');await q.s.page.getByRole('button',{name:'市价平仓',exact:true}).click();const closeResult=await closeResponse;assert.equal(closeResult.status(),200);
 const closed=await q.until(async()=>{const v=await summary();return v.positions.length===0&&v.workingOrders.length===0&&v.feeds.length===0?v:false;},30000);
 const released=await q.until(async()=>{const d=await snapshot();return leaseCount(d,'BTCUSDT@1m')<leaseCount(beforeClose,'BTCUSDT@1m')?d:false;},30000);
 await q.record('final-close-releases-practice-demand',{order:await closeResult.json(),summary:closed,before:beforeClose.stream_leases,after:released.stream_leases});
 await q.s.page.getByRole('button',{name:'设置',exact:true}).first().click();await q.s.page.getByRole('button',{name:'数据管理',exact:true}).click();await q.s.page.getByRole('button',{name:'高级维护',exact:true}).click();
 const scanResponse=q.s.page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/settings/storage/gap-scan')&&r.request().method()==='POST',{timeout:90000});await q.s.page.locator('.st-tool-card').filter({hasText:'数据缺口扫描与修复'}).getByRole('button').first().click();const scan=await scanResponse;assert.equal(scan.status(),200);const audit=await scan.json();assert.equal(audit.scope,'inspected_ranges');await q.record('integrated-manual-audit',audit);await q.screenshot('integrated-audit');await q.s.page.getByRole('button',{name:'保存并关闭',exact:true}).click();
 await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(error){q.s.receipt.failure=String(error.stack||error);process.exitCode=1;if(running)await q.screenshot('failure').catch(()=>{});}
finally{if(running)try{await quit();}catch(error){q.s.receipt.exitFailure=String(error);q.s.app.process().kill('SIGTERM');}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
