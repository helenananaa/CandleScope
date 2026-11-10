import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const {chromium}=createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const root=path.resolve(process.env.CANDLESCOPE_READER_QA_ROOT);await fs.mkdir(root);
const backend='http://127.0.0.1:23181',receipt={scope:'Synthetic canonical BARs, actual production readonly component/Manager/HTTP/WS/SDK/account; no API response interception or public feed/native qualification.',steps:[],mutations:[],errors:[]};
const save=()=>fs.writeFile(root+'/receipt.json',JSON.stringify(receipt,null,2)+'\n');
async function api(route,body){const r=await fetch(backend+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert.ok(r.ok,await r.clone().text());return r.json();}
async function record(name,value){receipt.steps.push({name,value,at:new Date().toISOString()});await save();}
let browser,page;
try{
 const first=(await api('/_qa/bootstrap')).run_id;
 await api('/_qa/amend',{index:12});
 const firstResult=await api(`/api/v1/backtests/continuous/runs/${first}/results/query`,{});
 const second=(await api('/_qa/new',{})).run_id;await api('/_qa/append',{});
 const secondResult=await api(`/api/v1/backtests/continuous/runs/${second}/results/query`,{});
 await api('/_qa/offline',{});
 browser=await chromium.launch({channel:'chrome',headless:true});
 page=await browser.newPage({viewport:{width:1140,height:1050}});let initialRequests=0;
 page.on('pageerror',error=>receipt.errors.push(String(error.stack||error)));
 page.on('request',request=>{
  const url=new URL(request.url());
  if(['http:','https:'].includes(url.protocol)&&!['127.0.0.1','localhost'].includes(url.hostname))receipt.errors.push('Unexpected external request: '+url.origin);
  if(url.pathname.endsWith('/initial'))initialRequests++;
  if(request.method()==='POST'&&url.pathname.includes('/continuous/')&&!url.pathname.endsWith('/results/query'))receipt.mutations.push(url.pathname);
 });
 await page.goto('http://127.0.0.1:23180/tests/fixtures/continuous-repair/entry.html?reader=1');
 const select=page.getByLabel('保存账户',{exact:true});await select.waitFor();
 async function choose(id,expected){
  await select.selectOption(id);const account=page.locator(`[data-continuous-account="${id}"]`);await account.waitFor();
  const values=await account.locator('.continuous-account dd').allTextContents();
  assert.deepEqual(values,[expected.summary.valuation.equity,expected.summary.account.position_qty,String(expected.identity.sequence)]);
  return {id,values,identity:expected.identity,visible:await account.innerText()};
 }
 const a=await choose(first,firstResult);await page.getByText('已处理的来源历史发生修订，执行已停止，当前结果已过期。',{exact:true}).waitFor();
 await record('stale-saved-account-displays-exact-committed-values',a);
 const b=await choose(second,secondResult);assert.equal(await page.getByText('已处理的来源历史发生修订，执行已停止，当前结果已过期。',{exact:true}).count(),0);
 await page.screenshot({path:root+'/second-account.png',fullPage:true});
 await record('switching-accounts-never-shows-prior-financial-identity',b);
 const beforeRefresh=initialRequests;
 const response=page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname.endsWith('/continuous/runs'));
 await page.getByRole('button',{name:'刷新账户列表',exact:true}).click();await response;
 await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='刷新账户列表'&&!b.disabled));
 assert.equal(initialRequests,beforeRefresh);
 await page.getByRole('button',{name:'关闭修复视图',exact:true}).click();
 await page.waitForFunction(()=>window.continuousRepairQA.diagnostics().observers===0);
 assert.deepEqual(await page.evaluate(()=>window.continuousRepairQA.diagnostics().views),[]);
 await page.getByRole('button',{name:'重新打开修复视图',exact:true}).click();
 await page.locator(`[data-continuous-account="${second}"]`).waitFor();
 assert.equal(await select.inputValue(),second);
 await page.reload();await page.locator(`[data-continuous-account="${second}"]`).waitFor();
 assert.equal(await select.inputValue(),second);
 await record('refresh-keeps-observation-close-releases-and-reload-remembers',{initialRequestsBeforeRefresh:beforeRefresh,selected:second});
 await page.setViewportSize({width:420,height:1050});await page.screenshot({path:root+'/narrow-account.png',fullPage:true});
 assert.deepEqual(receipt.mutations,[]);assert.deepEqual(receipt.errors,[]);
 assert.deepEqual((await api(`/api/v1/backtests/continuous/runs/${first}/results/query`,{})).identity,firstResult.identity);
 assert.deepEqual((await api(`/api/v1/backtests/continuous/runs/${second}/results/query`,{})).identity,secondResult.identity);
 receipt.passed=true;
}catch(error){receipt.failure=String(error.stack||error);process.exitCode=1;
 if(page&&!page.isClosed()){
  await fs.writeFile(root+'/failure-page.txt',await page.locator('body').ariaSnapshot().catch(()=>''));
  await page.screenshot({path:root+'/failure.png',fullPage:true}).catch(()=>{});
 }
}
finally{if(browser)await browser.close();await save();console.log(JSON.stringify({passed:receipt.passed??false,failure:receipt.failure,steps:receipt.steps.length}));}
