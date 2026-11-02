import assert from 'node:assert/strict';
import cp from 'node:child_process';
import * as q from '../backend-batch1-20261101/driver.mjs';
q.s.root=process.env.CANDLESCOPE_ACCOUNT_STREAM_QA_ROOT ?? process.cwd()+'/output/account-state-stream-native-20261101';
q.s.receipt.schema='candlescope.account-state-stream-native/1';
q.s.receipt.sourceCommit=cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
q.s.receipt.transport='Packaged bundled backend, actual guarded localhost stream/POST and UI; explicitly synthetic persisted disabled account without credentials or exchange account calls.';
q.s.receipt.scope='Committed private-account replacement snapshots, UI update without status poll, consumer release/reopen, decimal precision and persistent cursor after full owned exit/restart. Not two-venue sync, ordered financial deltas, practice or Windows acceptance.';
let running=false, authority, observer;
const requests=[];
async function launch(){await q.record('packaged-launch',await q.launch());running=true;
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});
 authority=await q.s.page.evaluate(()=>({session:window.candlescopeDesktop.getPluginManagementSession(),origin:location.origin}));
 q.s.page.on('request',r=>{if(r.url().includes('/readonly-accounts/'))requests.push({path:new URL(r.url()).pathname,method:r.method(),at:Date.now()});});}
function headers(write=false){return {'Origin':authority.origin,'X-CandleScope-Plugin-Session':authority.session.sessionToken,...(write?{'X-CandleScope-CSRF':authority.session.csrfToken,'X-CandleScope-User-Action':'account.disconnect','Content-Type':'application/json'}:{})};}
function url(path){return new URL(authority.session.apiBase).origin+'/api/v1/readonly-accounts'+path;}
async function read(path){const r=await fetch(url(path),{headers:headers()});assert.equal(r.status,200);return r.json();}
async function watch(){const controller=new AbortController();const r=await fetch(url('/events'),{headers:headers(),signal:controller.signal});assert.equal(r.status,200);assert.ok(r.headers.get('content-type').includes('application/x-ndjson'));assert.equal(r.headers.get('content-encoding'),'identity');let buffer='';const reader=r.body.getReader();const decoder=new TextDecoder();
 return {close:async()=>{controller.abort();await reader.cancel().catch(()=>{});},next:async()=>{const timeout=setTimeout(()=>controller.abort(),10000);try{while(true){const n=buffer.indexOf('\n');if(n>=0){const line=buffer.slice(0,n);buffer=buffer.slice(n+1);if(line.trim())return JSON.parse(line);continue;}const row=await reader.read();assert.equal(row.done,false);buffer+=decoder.decode(row.value,{stream:true});}}finally{clearTimeout(timeout);}}};}
async function show(name){const dock=q.s.page.locator('.readonly-account-dock');if(!await dock.isVisible())await q.s.page.getByRole('button',{name:'只读账户',exact:true}).click();await dock.getByText('UID NATIVE-SYNTHETIC-FIXTURE',{exact:true}).waitFor();await dock.getByText('1234.567890123456789',{exact:true}).waitFor();await dock.getByText('1234.567890123456789',{exact:true}).scrollIntoViewIfNeeded();await dock.screenshot({path:q.s.root+'/'+name+'.png'});return dock;}
async function quit(){await q.quit();await q.exited();running=false;await q.record('full-owned-exit',{elapsedMs:Date.now()-q.s.quitStartedAt,processes:q.s.quitPids});}
try{
 await launch();const initial=await read('/status');assert.equal(initial.account.venue_uid,'NATIVE-SYNTHETIC-FIXTURE');assert.equal(initial.account.enabled,0);assert.equal(initial.account.status,'error');assert.equal(initial.snapshots.balances.data[0].details[0].eq,'1234.567890123456789');
 await show('initial-account-stream');assert.equal(requests.filter(r=>r.path.endsWith('/events')).length,1);assert.equal(requests.filter(r=>r.path.endsWith('/status')).length,0);
 observer=await watch();const before=await observer.next();assert.equal(before.type,'snapshot');assert.deepEqual(before.cursor,initial.cursor);
 const offset=requests.length;
 // An independent authorized client performs the actual durable mutation.
 // It never calls the panel's action/refresh function or substitutes responses.
 const mutation=await fetch(url('/disconnect'),{method:'POST',headers:headers(true),body:JSON.stringify({forget:false})});assert.equal(mutation.status,200);
 const changed=await observer.next();assert.equal(changed.type,'snapshot');assert.equal(changed.state.account.status,'disconnected');assert.equal(changed.identity.venueUid,'NATIVE-SYNTHETIC-FIXTURE');assert.equal(changed.cursor.epoch,before.cursor.epoch);assert.ok(changed.cursor.sequence>before.cursor.sequence);assert.ok(!JSON.stringify(changed).includes('credential_id'));
 await q.s.page.locator('.readonly-account-dock').getByText('同步已暂停',{exact:true}).waitFor();await observer.close();observer=null;
 await q.delay(6200);assert.equal(requests.slice(offset).filter(r=>r.path.endsWith('/status')).length,0);await show('committed-account-stream');await q.record('committed-push-without-poll',{before:before.cursor,after:changed.cursor,account:changed.state.account,observedMs:6200,rendererRequests:requests.slice(offset)});
 const dock=q.s.page.locator('.readonly-account-dock');await dock.getByRole('button',{name:'关闭账户面板',exact:true}).click();await dock.waitFor({state:'hidden'});
 await show('reopened-account-stream');assert.equal(requests.filter(r=>r.path.endsWith('/events')).length,2);assert.equal(requests.filter(r=>r.path.endsWith('/status')).length,0);await q.record('release-and-reopen',{rendererRequests:requests});
 const current=await read('/status');assert.deepEqual(current.cursor,changed.cursor);assert.equal(current.counts.fills,1);const facts=await read('/facts/fills?limit=100');assert.equal(facts.items[0].contracts,'0.1234567890123456789');await quit();
 await launch();const restored=await read('/status');assert.deepEqual(restored,current);await show('restored-account-stream');await q.s.page.locator('.readonly-account-dock').getByText('同步已暂停',{exact:true}).waitFor();await q.record('restored-identity-and-cursor',{cursor:restored.cursor,uid:restored.account.venue_uid,exactDecimal:restored.snapshots.balances.data[0].details[0].eq});await quit();assert.deepEqual(q.s.receipt.errors,[]);q.s.receipt.passed=true;
}catch(e){q.s.receipt.failure=String(e.stack||e);process.exitCode=1;if(running&&q.s.page)await q.screenshot('failure').catch(()=>{});}
finally{await observer?.close().catch(()=>{});if(running)try{await quit();}catch(e){q.s.receipt.exitFailure=String(e);}await q.save();console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));}
