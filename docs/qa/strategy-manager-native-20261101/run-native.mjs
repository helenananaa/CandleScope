import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as q from './acceptance-driver.mjs';
const root=q.s.root;
q.s.env={...q.s.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',KLINES_DB_PATH:root+'/profile/data/market.db',REPLAY_DB_PATH:root+'/profile/data/replay.db',BACKTEST_DB_PATH:root+'/profile/data/backtest.db',BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1',BACKTEST_COLOCATED_BAR_ENABLED:'1',BACKTEST_CHECKPOINT_EVENT_INTERVAL:'32'};
await fs.mkdir(root+'/profile/data',{recursive:true});
const start=1700000040000,count=600;
const csv='time,open,high,low,close,volume\n'+Array.from({length:count},(_,i)=>`${start+i*60000},${100+i%20},${101+i%20},${99+i%20},${100+i%20},100`).join('\n');
await fs.writeFile(root+'/manager-native.csv',csv);
const sourceFile=await fs.readFile('frontend/src/features/backtest/chart-tester/chartStrategyTesterUiModel.ts','utf8');
const source=JSON.parse(sourceFile.split('export const PYTHON_SMA_SOURCE = ')[1].split(';\n')[0]);
const requests=[],streams=[],responseTasks=[];
async function launch(){
 const identity=await q.launch();
 q.s.page.on('request',r=>{if(r.url().includes('/api/'))requests.push({at:Date.now(),method:r.method(),url:r.url(),path:new URL(r.url()).pathname,body:r.postData()});});
 q.s.page.on('response',r=>{if(r.request().method()==='GET'&&/\/backtests\/runs\/[^/]+\/events$/.test(new URL(r.url()).pathname))responseTasks.push((async()=>{streams.push({status:r.status(),headers:await r.allHeaders(),url:r.url()});})().catch(error=>{q.s.receipt.observerErrors??=[];q.s.receipt.observerErrors.push(String(error));}));});
 const health=await (await fetch(q.s.backend+'/health')).json();assert.equal(health.runtime_mode,'LOCAL_OFFLINE');assert.equal(health.data_manager.status,'not_initialized');assert.equal(health.local_offline.network.blocked_attempts,0);
 await q.record('launch',{...identity,health});
 await q.s.page.goto(new URL('/index.html',q.s.page.url()).href,{waitUntil:'domcontentloaded'});await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();await q.enableControl();
 await q.s.page.goto(new URL('/strategy.html',q.s.page.url()).href,{waitUntil:'domcontentloaded'});
 await q.s.page.getByTestId('research-data-source-bar').waitFor({timeout:30000});
}
async function host(){await q.s.page.getByRole('button',{name:'CandleScope 撮合 / 教学模板',exact:true}).click();}
const json=async(path)=>{const r=await fetch(q.s.backend+path);assert.ok(r.ok,await r.clone().text());return r.json();};
async function run(){const next=q.s.page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/backtests/runs'&&r.request().method()==='POST',{timeout:30000});await q.s.page.getByTestId('strategy-research-run').click();const response=await next;assert.equal(response.status(),200);return response.json();}
try{
 await launch();
 await q.s.page.getByTestId('research-data-source-bar').getByRole('button',{name:'打开本地资料库',exact:true}).click();
 const form=q.s.page.getByTestId('research-data-import-form');await form.waitFor();
 await form.locator('input[type=file]').setInputFiles(root+'/manager-native.csv');
 await form.getByLabel('数据集名称',{exact:true}).fill('Native Manager Fixture');await form.getByLabel('商品',{exact:true}).fill('MANAGERFIXTURE');await form.getByRole('combobox',{name:'时间格式',exact:true}).selectOption('ms');
 await form.getByRole('button',{name:'导入到本地资料库',exact:true}).click();await form.waitFor({state:'hidden',timeout:30000});
 await host();await q.s.page.getByTestId('strategy-research-template-PYTHON_SMA').click();await q.s.page.getByTestId('strategy-python-confirm').check();
 const offset=requests.length,created=await run();const runId=created.run_id;assert.ok(runId);
 const result=q.s.page.locator('[data-testid="strategy-research-result-panel"][data-fidelity="BAR_APPROX"]');await result.waitFor({timeout:90000});
 const report=await json(`/api/v1/backtests/runs/${runId}/report`),record=await json(`/api/v1/backtests/runs/${runId}`),chart=await json(`/api/v1/backtests/runs/${runId}/chart`);
 assert.equal(record.state,'COMPLETED');assert.equal(chart.bars.length,600);assert.ok(report.metrics.fill_count>0);
 const runRequests=requests.slice(offset);assert.equal(runRequests.filter(r=>r.path===`/api/v1/backtests/runs/${runId}/events`).length,1);assert.equal(runRequests.filter(r=>r.path===`/api/v1/backtests/runs/${runId}`).length,1,'one committed result lookup; no polling');
 await q.screenshot('completed-research');await q.record('completed-research',{runId,record,reportHashes:report.hashes,metrics:report.metrics,chartHash:chart.chart_hash,rendererRunRequests:runRequests});
 await q.delay(1000);await q.record('full-exit',{owned:await q.quit(),allExited:await q.exited()});
 await launch();await host();await q.s.page.locator('[data-testid="strategy-research-result-panel"][data-fidelity="BAR_APPROX"]').waitFor({timeout:30000});
 const restored=await json(`/api/v1/backtests/runs/${runId}/report`);assert.deepEqual(restored.hashes,report.hashes);assert.deepEqual(restored.metrics,report.metrics);
 await q.screenshot('restored-research');await q.record('restart-results',{runId,reportHashes:restored.hashes,metrics:restored.metrics});
 // Set the deterministic failing fixture through the published editor command;
 // submission and error presentation still use the real UI and runtime.
 const badSource=source.replace('        self.warmup(observation)\n','        if observation.sequence > 100:\n            raise RuntimeError("native-manager-intentional-failure")\n        self.warmup(observation)\n');assert.notEqual(source,badSource);
 async function sourceCommand(command,args){
   const {groups}=await q.s.control.call('app.commands',{windowId:'main-window'});const group=groups.find(g=>g.id==='host-strategy:strategy-research');assert.ok(group);
   const requestId='native165-'+crypto.randomUUID();await q.s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command,args,requestId,expectedContext:group.contextToken});
   const result=await q.until(async()=>{const row=await q.s.control.call('request.get',{requestId});return row.final?row:false;});assert.equal(result.state,'applied',JSON.stringify(result));
 }
 await sourceCommand('source',{source:badSource});await sourceCommand('flush',{});
 const script=(await q.s.control.call('app.query',{windowId:'main-window',groupId:'host-strategy:strategy-research',command:'inspect',args:{}})).snapshot;assert.equal(script.source,badSource);
 await q.record('failure-fixture-source',{method:'published host-strategy source and flush commands; no response substitution',sourceVerified:true});
 await q.s.page.getByTestId('strategy-python-confirm').check();
 const failed=await run();const submitted=JSON.parse(requests.filter(r=>r.method==='POST'&&r.path.endsWith('/strategy-revisions')).at(-1).body);assert.equal(submitted.source_text,badSource);await q.s.page.getByRole('alert').filter({hasText:'native-manager-intentional-failure'}).waitFor({timeout:90000});
 assert.equal((await json(`/api/v1/backtests/runs/${failed.run_id}`)).state,'FAILED');await q.screenshot('strategy-failure-reason');await q.record('failure-visible',{runId:failed.run_id,message:await q.s.page.getByRole('alert').filter({hasText:'native-manager-intentional-failure'}).innerText()});
 const health=await json('/health');assert.equal(health.local_offline.network.blocked_attempts,0);assert.equal(health.data_manager.status,'not_initialized');await q.record('offline-isolation',health);
 assert.deepEqual(q.s.receipt.errors,[]);await q.record('final-exit',{owned:await q.quit(),allExited:await q.exited()});await Promise.all(responseTasks);
 assert.equal(streams.length,2);assert.ok(streams.every(stream=>stream.status===200&&stream.headers['content-type'].includes('application/x-ndjson')));assert.deepEqual(q.s.receipt.observerErrors??[],[]);
 await fs.writeFile(root+'/strategy-transport.json',JSON.stringify({requests,streams},null,2));q.s.receipt.passed=true;await q.save();console.log('NATIVE STRATEGY MANAGER PASS');
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);try{await fs.writeFile(root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.screenshot('failure');}catch{}try{await q.quit();await q.exited();}catch{}await fs.writeFile(root+'/strategy-transport.json',JSON.stringify({requests,streams},null,2));process.exitCode=1;}
