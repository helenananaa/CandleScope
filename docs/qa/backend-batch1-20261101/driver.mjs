import path from 'node:path';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { ControlClient } from '../../../packages/candlescope-control/client.mjs';
const require = createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE ?? '/tmp/candlescope178-tooling/package.json');
const { _electron } = require('playwright-core');
export const s = {
  env: { HOME: "/Users/ryanliang", PATH: "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin", TMPDIR: "/tmp", LANG: "en_US.UTF-8" },
  root: process.env.CANDLESCOPE_BATCH1_QA_ROOT ?? path.resolve(fileURLToPath(new URL('../../../output/batch1-native-20261101/', import.meta.url))),
  receipt: { schema: 'candlescope.backend-batch1-native/1', sourceCommit: 'd5ba2b8ff0cb303ef2dff8f6fe0f168247409c96',
    transport: 'packaged bundled backend, real public Binance HTTP and WebSocket, no response substitution', steps: [], errors: [] },
  traffic: { requests: [], responses: [], sockets: [], failures: [] },
};
export const delay = ms => new Promise(r => setTimeout(r, ms));
export async function save() {
  await fs.writeFile(s.root+'/acceptance.json', JSON.stringify(s.receipt,null,2)+'\n');
  await fs.writeFile(s.root+'/traffic.json', JSON.stringify(s.traffic,null,2)+'\n');
}
export async function record(name, evidence) {
  s.receipt.steps.push({ name, at:new Date().toISOString(), evidence });
  await save(); return { passed:name };
}
export async function until(check, timeout=25000) {
  const end=Date.now()+timeout; let last;
  while(Date.now()<end) { last=await check(); if(last) return last; await delay(200); }
  throw new Error('Timed out waiting for acceptance state');
}
export async function launch() {
  s.startedAt=Date.now();
  s.app=await _electron.launch({executablePath:s.root+'/Installed App/CandleScope.app/Contents/MacOS/CandleScope',
    args:['--no-sandbox'], env:{...s.env,
      CANDLESCOPE_DESKTOP_USER_DATA:s.root+'/profile',CANDLE_DATA_DIR:s.root+'/profile/data',
      CANDLESCOPE_DESKTOP_UI_PORT:'0',CANDLESCOPE_DESKTOP_BACKEND_PORT:'0',
      CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT:s.root+'/profile/plugins',CANDLESCOPE_LOCAL_DATA_DIR:s.root+'/profile/local-data'},timeout:90000});
  s.page=await s.app.firstWindow({timeout:90000}); attach();
  await s.page.waitForFunction(()=>Boolean(window.candlescopeDesktop),null,{timeout:60000});
  s.identity=await s.app.evaluate(({app})=>({packaged:app.isPackaged,pid:process.pid,userData:app.getPath('userData'),resources:process.resourcesPath}));
  s.bootstrap=await s.page.evaluate(()=>window.candlescopeDesktop.getBootstrap());
  s.backend=new URL(s.bootstrap.sidecar.healthUrl).origin;
  assert.equal(s.identity.packaged,true);
  assert.ok(s.bootstrap.sidecar.command.startsWith(s.identity.resources));
  return {identity:s.identity,sidecar:s.bootstrap.sidecar};
}
function attach() {
  s.page.on('pageerror',e=>s.receipt.errors.push({at:Date.now(),message:e.message,stack:e.stack}));
  s.page.on('request',r=>{if((/\/(klines|indicators)\//.test(r.url())))s.traffic.requests.push({at:Date.now(),url:r.url(),method:r.method(),body:r.postData()});});
  s.page.on('requestfailed',r=>{if(r.url().includes('/api/'))s.traffic.failures.push({at:Date.now(),url:r.url(),error:r.failure()?.errorText});});
  s.page.on('response',async r=>{if(!(/\/(klines|indicators)\//.test(r.url())))return;try{const j=await r.json();const rows=j.data??j.bars??[];
    s.traffic.responses.push({at:Date.now(),url:r.url(),status:r.status(),count:j.count??rows.length,first:rows[0]?.open_time,last:rows.at(-1)?.open_time,streamVersion:j.stream_version,historyState:j.history_state,complete:j.complete});}catch{}});
  s.page.on('websocket',ws=>{const row={at:Date.now(),url:ws.url(),sent:[],received:0,versions:[]};s.traffic.sockets.push(row);
    ws.on('framesent',e=>{if(row.sent.length<2000)row.sent.push(String(e.payload));});
    ws.on('framereceived',e=>{row.received++;try{const j=JSON.parse(String(e.payload));if (row.url.includes('/stream/indicators')) { row.events ??= []; if (row.events.length < 3000) row.events.push({ at:Date.now(),type:j.type,clientId:j.clientId,subscriptionId:j.subscriptionId,range:j.range,barTime:j.barTime,values:j.values,revision:j.dataRevision,points:j.lines?.reduce((n,l)=>n+(l.data?.length??0),0),lines:j.lines?.map(l=>({id:l.id,count:l.data?.length,first:l.data?.[0],last:l.data?.at(-1)})),ok:j.ok,error:j.error }); } if(j.stream_version){row.lastVersion=j.stream_version;if(row.versions.length<5)row.versions.push(j.stream_version);}}catch{}});
    ws.on('close',()=>row.closedAt=Date.now());});
}
export async function enableControl() {
  await s.page.getByRole('button',{name:'设置',exact:true}).click();
  await s.page.getByRole('button',{name:'AI MCP',exact:true}).click();
  await s.page.getByRole('checkbox',{name:'为本次授权启用可选的桌面工作流工具',exact:true}).check();
  await s.page.getByRole('checkbox',{name:'允许本机客户端在本次应用会话中修改图表并推进模拟回放。',exact:true}).check();
  await s.page.getByRole('button',{name:'启用控制',exact:true}).click();
  await s.page.getByRole('button',{name:'保存并关闭',exact:true}).click();
  s.control=new ControlClient(s.root+'/profile/control/connection.json');await s.control.connect();
}
export const inspect=async()=> (await s.control.call('workspace.inspect',{windowId:'main-window'})).snapshot;
export const broker=()=>s.page.evaluate(()=>window.__CANDLESCOPE_WINDOW_BROKER__?.snapshot({compact:true}));
export const query=(cellId,command='inspect',args={})=>s.control.call('app.query',{windowId:'main-window',groupId:'chart:'+cellId,command,args});
export async function configure(charts,layout) {
  const snap=await inspect();const requestId='native178-'+Date.now();
  const ack=await s.control.call('workspace.configure',{requestId,workspaceId:snap.workspaceId,windowId:'main-window',expectedRevision:snap.revision,...(layout?{layout}:{}),charts});
  const result=await until(async()=>{const r=await s.control.call('request.get',{requestId});return r.final?r:false;},30000);
  return {ack,result,snapshot:await inspect()};
}
export async function execute(cellId,command,args) {
  const groups=await s.control.call('app.commands',{windowId:'main-window'});
  const group=(groups.groups??groups).find(x=>x.id==='chart:'+cellId);
  assert.ok(group,'Chart command group missing');
  const requestId='native178-cmd-'+crypto.randomUUID();
  await s.control.call('app.execute',{windowId:'main-window',groupId:group.id,command,args,requestId,expectedContext:group.contextToken});
  return until(async()=>{const r=await s.control.call('request.get',{requestId});return r.final?r:false;});
}
export async function ready(count=1,timeout=25000) {
  return until(async()=>{const snap=await inspect();return snap.cells.length===count&&snap.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=500)&&snap.persistence.state==='saved'?snap:false;},timeout);
}
export function session(symbol,interval='1m') {return {exchange:'binance',marketType:'spot',symbol,interval};}
export async function screenshot(name) {await s.page.screenshot({path:s.root+'/'+name+'.png'});}
export async function quit() {
  const lines=cp.execFileSync('ps',['-axo','pid=,ppid=,args='],{encoding:'utf8'}).trim().split('\n').map(l=>{const m=l.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);return m&&{pid:+m[1],ppid:+m[2],args:m[3]};}).filter(Boolean);
  const owned=new Set([s.identity.pid]);for(let i=0;i<10;i++)for(const p of lines)if(owned.has(p.ppid))owned.add(p.pid);
  s.quitPids=lines.filter(p=>owned.has(p.pid));
  s.quitStartedAt=Date.now();
  await s.app.close();
  return s.quitPids.map(p=>({pid:p.pid,args:p.args}));
}
export async function exited() {
  return until(async()=>{const rows=cp.execFileSync('ps',['-axo','pid=,args='],{encoding:'utf8'}).trim().split('\n');
    return s.quitPids.every(p=>!rows.some(l=>l.trim().startsWith(p.pid+' ')&&l.includes(p.args)))?true:false;},30000);
}

export async function indicatorsReady(count=2,timeout=25000) {
  return until(async()=>{const snap=await inspect();return snap.cells.length===count&&snap.cells.every(c=>c.runtime.marketReady&&!c.runtime.loading&&c.runtime.barCount>=500&&c.runtime.indicatorsReady&&!c.runtime.computing&&!c.runtime.indicatorErrors?.length&&c.runtime.indicatorOutputPoints.length>0&&c.runtime.indicatorOutputPoints.every(n=>n>0))&&snap.persistence.state==='saved'?snap:false;},timeout);
}
