import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const root=process.cwd(),out=path.resolve(process.env.CANDLESCOPE_READER_NATIVE_OUT),profile=path.resolve(process.env.CANDLESCOPE_READER_NATIVE_PROFILE);
assert.ok(!fs.existsSync(out),'Preserve previous receipts');fs.mkdirSync(out,{recursive:true});
const candidate=path.resolve(process.env.CANDLESCOPE_NATIVE_QA_ROOT),manifest=JSON.parse(fs.readFileSync(candidate+'/source-package-manifest.json','utf8'));
const seed=JSON.parse(fs.readFileSync(profile+'/seed-receipt.json','utf8'));
const appPath=manifest.app,resources=appPath+'/Contents/Resources';
const { _electron }=createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const asar=createRequire(root+'/frontend/package.json')('@electron/asar');
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const env={...process.env,CANDLESCOPE_RUNTIME_MODE:'LOCAL_OFFLINE',PYTHONDONTWRITEBYTECODE:'1',
 CANDLESCOPE_DESKTOP_USER_DATA:profile,CANDLE_DATA_DIR:profile+'/data',KLINES_DB_PATH:profile+'/data/candlescope.db',
 BACKTEST_ENABLED:'1',BACKTEST_BAR_ENABLED:'1',BACKTEST_DB_PATH:profile+'/data/backtest.db',REPLAY_DB_PATH:profile+'/data/replay.db',
 CANDLESCOPE_LOCAL_DATA_DIR:profile+'/local-data',CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT:profile+'/plugins',
 CANDLESCOPE_DESKTOP_UI_PORT:'0',CANDLESCOPE_DESKTOP_BACKEND_PORT:'0',BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED:'1'};
for(const name of ['ELECTRON_RUN_AS_NODE','PYTHONPATH','CANDLESCOPE_DESKTOP_URL','CANDLESCOPE_DESKTOP_SKIP_SIDECAR','CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON','CANDLESCOPE_PYTHON'])delete env[name];
const urls=[];
const receipt={scope:'Source-verified local arm64 packaged LOCAL_OFFLINE app, previously seeded synthetic account. Actual UI/API/WS; no response substitution, source unmasking or public LIVE qualification.',source:manifest.sourceCommit,profile,steps:[],errors:[],mutations:[]};
const save=()=>fs.writeFileSync(out+'/receipt.json',JSON.stringify(receipt,null,2)+'\n');
function record(name,value){receipt.steps.push({name,at:new Date().toISOString(),value});save();}
function verify(){
 return JSON.parse(cp.execFileSync('node',[root+'/docs/qa/continuous-stack-native-main261-20261106/verify.mjs'],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:candidate}}));
}
function rows(){return cp.execFileSync('/bin/ps',['-axo','pid=,ppid=,command='],{encoding:'utf8'}).trim().split('\n').map(line=>{
 const m=line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);return {pid:Number(m[1]),ppid:Number(m[2]),command:m[3]};
});}
let app,page;
async function launch(){
 app=await _electron.launch({executablePath:appPath+'/Contents/MacOS/CandleScope',env,timeout:45000});
 page=await app.firstWindow({timeout:45000});page.setDefaultTimeout(20000);
 page.on('request',r=>{const u=new URL(r.url());if(['http:','https:','ws:','wss:'].includes(u.protocol))urls.push(u.href);});page.on('websocket',ws=>urls.push(ws.url()));
 // firstWindow precedes the desktop's awaited loadURL; do not abort that startup navigation.
 await page.waitForURL(url=>url.protocol==='http:'&&url.hostname==='127.0.0.1',{timeout:45000,waitUntil:'load'});
 await page.waitForLoadState('load',{timeout:45000});
 page.on('pageerror',error=>receipt.errors.push(String(error.stack||error)));
 page.on('request',request=>{const url=new URL(request.url());
  if(request.method()==='POST'&&url.pathname.includes('/continuous/')&&!url.pathname.endsWith('/results/query'))receipt.mutations.push(url.pathname);
 });
 const identity=await app.evaluate(({app})=>({packaged:app.isPackaged,userData:app.getPath('userData'),mode:process.env.CANDLESCOPE_RUNTIME_MODE,pid:process.pid}));
 assert.equal(identity.packaged,true);assert.equal(identity.userData,profile);assert.equal(identity.mode,'LOCAL_OFFLINE');
 const bootstrap=await page.evaluate(()=>window.candlescopeDesktop.getBootstrap());const h=await fetch(bootstrap.sidecar.healthUrl);assert.equal(h.status,200);const health=await h.json();assert.equal(health.runtime_mode,'LOCAL_OFFLINE');assert.equal(health.local_offline.network.installed,true);assert.equal(health.local_offline.network.blocked_attempts,0);record('offline-health',{health,bootstrap});return identity;
}
async function show(name){
 await page.goto(new URL('/strategy.html',page.url()).href);
 await page.getByRole('button',{name:'保存的常驻账户',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'保存的常驻账户',exact:true});await dialog.waitFor();
 const select=dialog.getByRole('combobox',{name:'保存账户',exact:true});await select.selectOption(seed.runId);
 const account=dialog.locator(`[data-continuous-account="${seed.runId}"]`);await account.waitFor();
 await dialog.getByText('上次修复已完成，但来源历史再次发生修订，请重新预览当前范围。',{exact:true}).waitFor();
 assert.equal(await dialog.locator('[data-continuous-repair-phase="COMMITTED"]').count(),1);
 const values=await account.locator('.continuous-account dd').allTextContents();
 assert.deepEqual(values,[seed.view.summary.valuation.equity,seed.view.summary.account.position_qty,String(seed.saved.run.sequence)]);
 const text=await dialog.innerText();assert.match(text,/REPAIR_REQUIRED/);
 assert.equal(await dialog.getByRole('button',{name:/初始化新运行|确认并修复|暂停|停止运行|取消修复/}).count(),0);
 const caps=await page.evaluate(async()=>{const r=await fetch(window.candlescopeDesktop.apiBase+'/backtests/continuous/capabilities');return {status:r.status,body:await r.json()};});
 assert.equal(caps.status,200);assert.equal(caps.body.execution_enabled,false);assert.equal(caps.body.runtime_mode,'LOCAL_OFFLINE');
 const bootstrap=await page.evaluate(()=>window.candlescopeDesktop.getBootstrap());
 const healthResponse=await fetch(bootstrap.sidecar.healthUrl);assert.equal(healthResponse.status,200);const health=await healthResponse.json();
 assert.equal(health.runtime_mode,'LOCAL_OFFLINE');assert.equal(health.local_offline.network.installed,true);assert.equal(health.local_offline.network.blocked_attempts,0);
 record(name+'-network-boundary',{health,urls:[...urls]});
 await page.screenshot({path:out+'/'+name+'.png',fullPage:true});
 record(name,{runId:seed.runId,values,phase:seed.saved.run.phase,repairPhase:'COMMITTED',caps:caps.body,text});
}
async function quit(name){
 const pid=await app.evaluate(()=>process.pid),before=rows(),owned=new Set([pid]);let added=true;
 while(added){added=false;for(const row of before)if(owned.has(row.ppid)&&!owned.has(row.pid)){owned.add(row.pid);added=true;}}
 const all=before.filter(row=>owned.has(row.pid)),started=Date.now();await app.close();app=null;
 const deadline=Date.now()+10000;
 while(rows().some(row=>owned.has(row.pid))&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,100));
 const after=rows();assert.deepEqual(after.filter(row=>owned.has(row.pid)),[]);
 assert.deepEqual(after.filter(row=>row.command.includes(appPath)),[]);
 const cold=JSON.parse(cp.execFileSync(resources+'/python-runtime/python/bin/python3.12',['-B',root+'/docs/qa/continuous-stack-native-main261-20261106/cold_account.py','--profile',profile],{encoding:'utf8',env}));
 assert.equal(cold.savedSha256,seed.savedSha256);record(name,{quitMs:Date.now()-started,ownedProcesses:all,allOwnedExited:true,cold,verified:verify()});
}
try{
 record('verified-before',verify());record('first-launch',await launch());await show('native-readonly-before');
 await quit('full-exit-before-restart');record('second-launch',await launch());await show('native-readonly-after-restart');
 assert.deepEqual(receipt.mutations,[]);assert.deepEqual(receipt.errors,[]);assert.ok(urls.length>0);assert.deepEqual(urls.filter(value=>!['127.0.0.1','localhost','[::1]'].includes(new URL(value).hostname)),[]);receipt.urls=urls;await quit('full-exit-after-restart');receipt.passed=true;
}catch(error){receipt.failure=String(error.stack||error);process.exitCode=1;
 if(page&&!page.isClosed()){fs.writeFileSync(out+'/failure-page.txt',await page.locator('body').ariaSnapshot().catch(()=>''));await page.screenshot({path:out+'/failure.png',fullPage:true,timeout:5000}).catch(()=>{});}
}finally{
 if(app){try{await quit('failure-normal-exit');}catch(error){receipt.cleanupFailure=String(error.stack||error);}}
 save();console.log(JSON.stringify({passed:receipt.passed??false,failure:receipt.failure,cleanupFailure:receipt.cleanupFailure,steps:receipt.steps.length}));
}
