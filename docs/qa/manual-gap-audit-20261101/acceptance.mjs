import fs from 'node:fs/promises';
import cp from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { _electron } = createRequire('/tmp/candlescope178-tooling/package.json')('playwright-core');
const root = path.dirname(new URL(import.meta.url).pathname);
const profile = path.join(root, 'profile');
const executable = path.join(root, 'Installed App/CandleScope.app/Contents/MacOS/CandleScope');
const receipt = {schema:'candlescope.manual-gap-audit-native/1', sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  fixture:'50,020 contiguous synthetic BTCUSDT 1m rows in an isolated profile; real bundled backend and actual settings actions; no response substitution', steps:[], errors:[], passed:false};
let app, page;
const save = () => fs.writeFile(path.join(root,'acceptance.json'), JSON.stringify(receipt,null,2)+'\n');
const record = async (name, evidence) => {receipt.steps.push({name,at:new Date().toISOString(),evidence}); await save(); console.log(name);};
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function until(check, timeout=30000) {const end=Date.now()+timeout;while(Date.now()<end){const v=await check();if(v)return v;await delay(200);}throw new Error('Acceptance condition timed out');}
const env={HOME:'/Users/ryanliang',PATH:'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',TMPDIR:'/tmp',LANG:'en_US.UTF-8',
  CANDLESCOPE_DESKTOP_USER_DATA:profile,CANDLE_DATA_DIR:path.join(profile,'data'),KLINES_DB_PATH:path.join(profile,'data/candlescope.db'),
  CANDLESCOPE_DESKTOP_UI_PORT:'0',CANDLESCOPE_DESKTOP_BACKEND_PORT:'0',
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT:path.join(profile,'plugins'),CANDLESCOPE_LOCAL_DATA_DIR:path.join(profile,'local-data')};
async function launch() {
  app = await _electron.launch({executablePath:executable,env,timeout:90000});
  page = await app.firstWindow({timeout:60000});
  page.on('pageerror',e=>receipt.errors.push({message:e.message,stack:e.stack}));
  await page.waitForURL(url=>url.protocol==='http:'&&url.hostname==='127.0.0.1',{waitUntil:'load',timeout:90000});
  await page.waitForFunction(()=>Boolean(window.candlescopeDesktop),null,{timeout:30000});
  const identity=await app.evaluate(({app})=>({packaged:app.isPackaged,pid:process.pid,userData:app.getPath('userData'),resources:process.resourcesPath}));
  const bootstrap=await page.evaluate(()=>window.candlescopeDesktop.getBootstrap());
  assert.equal(identity.packaged,true); assert.equal(identity.userData,profile);
  assert.ok(bootstrap.sidecar.command.startsWith(path.join(identity.resources,'python-runtime')));
  await record('packaged-launch',{identity,sidecar:bootstrap.sidecar});
}
function processTree() {
  const rows=cp.execFileSync('ps',['-axo','pid=,ppid=,args='],{encoding:'utf8'}).trim().split('\n').map(line=>{const m=line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);return m&&{pid:+m[1],ppid:+m[2],args:m[3]};}).filter(Boolean);
  const owned=new Set([app.process().pid]); for(let i=0;i<10;i++)for(const row of rows)if(owned.has(row.ppid))owned.add(row.pid);
  return rows.filter(row=>owned.has(row.pid));
}
async function quit() {
  const owned=processTree(); await app.evaluate(({app})=>app.quit());
  await until(()=>{const now=cp.execFileSync('ps',['-axo','pid=,args='],{encoding:'utf8'});return owned.every(row=>!now.split('\n').some(line=>line.trim().startsWith(row.pid+' ')&&line.includes(row.args)));},30000);
  app=null; await record('full-exit',{owned,allExited:true});
}
async function scan(title='数据缺口扫描与修复') {
  const card=page.locator('.st-tool-card').filter({hasText:title});
  const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/settings/storage/gap-scan')&&r.request().method()==='POST',{timeout:60000});
  await card.getByRole('button').first().click();
  const r=await response; assert.equal(r.status(),200); const body=await r.json();
  await page.getByText(body.message,{exact:true}).waitFor();
  assert.equal(body.scope,'inspected_ranges');
  for(const row of body.results.filter(x=>x.scanned_from_ms!=null)) {
    assert.ok(row.symbol&&row.interval); assert.ok(row.scanned_to_ms>=row.scanned_from_ms);
  }
  return body;
}
try {
  await launch();
  await page.getByRole('button',{name:'设置',exact:true}).first().click();
  await page.getByRole('button',{name:'数据管理',exact:true}).click();
  assert.equal(await page.getByText('数据缺口扫描与修复',{exact:true}).isVisible(),false);
  await page.getByRole('button',{name:'高级维护',exact:true}).click();
  const results=[];
  for(let i=0;i<3;i++) {
    const result=await scan();results.push(result);await record('manual-scan-'+i,result);
    await page.screenshot({path:path.join(root,'inspection-'+i+'.png')});
    if(results.some(x=>x.has_more)&&results.some(x=>!x.has_more))break;
  }
  assert.ok(results.some(x=>x.has_more),'missing unfinished page evidence');
  assert.ok(results.some(x=>!x.has_more),'missing continuation completion evidence');
  const interior=results.flatMap(x=>x.results).filter(x=>x.symbol==='BTCUSDT'&&x.interval==='1m'&&x.lane==='interior');
  assert.ok(interior.some(x=>x.truncated&&x.next_cursor_ms));
  assert.ok(new Set(interior.map(x=>x.scanned_from_ms)).size>1,'cursor did not advance');
  assert.ok(interior.some(x=>!x.truncated&&x.status==='ok'&&x.remaining_gaps===0),'continued range was not verified');
  assert.ok(results.every(x=>!x.has_more||x.status!=='ok'));
  await page.getByRole('button',{name:'保存并关闭',exact:true}).click();
  await page.getByRole('button',{name:'设置',exact:true}).first().click();
  await page.getByRole('button',{name:'外观显示',exact:true}).click();
  await page.locator('[data-settings-locale="true"]').selectOption('en');
  await page.getByRole('button',{name:'Save and close',exact:true}).click();
  const saved=await until(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('candlescope-settings')||'{}').locale==='en'));
  await record('saved-settings',{locale:'en',saved});
  await quit();
  await launch();
  await page.getByRole('button',{name:'Settings',exact:true}).first().click();
  assert.equal(await page.locator('[data-settings-locale="true"]').inputValue(),'en');
  await page.getByRole('button',{name:'Data',exact:true}).click();
  await page.getByRole('button',{name:'Advanced maintenance',exact:true}).click();
  assert.ok(await page.getByText('Gap scan and repair',{exact:true}).isVisible());
  await page.screenshot({path:path.join(root,'restart-maintenance.png')});
  await record('restart-settings-and-maintenance',{locale:'en',advancedMaintenanceVisible:true});
  const restarted = await scan('Gap scan and repair');
  assert.ok(restarted.results.some(x=>x.symbol==='BTCUSDT'&&x.interval==='1m'&&x.scanned_bars>0&&x.status!=='error'));
  await record('restart-manual-scan', restarted);
  await page.getByRole('button',{name:'Save and close',exact:true}).click();
  await quit();
  assert.deepEqual(receipt.errors,[]);
  receipt.passed=true;
} catch(error) {receipt.failure=String(error.stack||error);process.exitCode=1;if(page)await page.screenshot({path:path.join(root,'failure.png')}).catch(()=>{});}
finally {await save();if(app){try{await quit();}catch{app.process().kill('SIGTERM');}} await save();console.log(JSON.stringify({passed:receipt.passed,failure:receipt.failure}));}
