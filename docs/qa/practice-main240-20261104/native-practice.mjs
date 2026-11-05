import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import cp from 'node:child_process';
import * as q from './native-driver.mjs';

// Startup itself discovers public catalogs. This must precede verification,
// Electron startup, or local API access. Preparation is not native evidence.
await q.assertPublicGate();
assert.equal(await fs.stat(q.s.root+'/profile').then(()=>true,error=>{if(error.code==='ENOENT')return false;throw error;}),false,'Preserve previous native profiles; use a new isolated candidate root');
const manifest=JSON.parse(await fs.readFile(q.s.root+'/source-package-manifest.json','utf8'));
q.s.receipt.driverCommit=q.s.receipt.sourceCommit;q.s.receipt.sourceCommit=manifest.sourceCommit;
q.s.receipt.scope='Native macOS practice UI entry, independent-client committed updates, shared/pinned account isolation, exact spot ledger oracle, save/full owned restart; not whole177 or Windows.';
const requests=[],streams=[],observers=[];
const instrument={exchange:'binance',marketType:'spot',symbol:'BTCUSDT'};
let running=false,a,b,launchId;
const panel=()=>q.s.page.locator('.trading-panel');
const wait=(check,timeout=30000)=>q.until(async()=>{await q.checkCircuit();return check();},timeout);
function verify(){cp.execFileSync('node',['docs/qa/practice-main240-20261104/verify.mjs'],{stdio:'inherit',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:q.s.root}});}
async function api(path,method='GET',body){
 await q.checkCircuit();const r=await fetch(q.s.backend+'/api/v1/trading/accounts'+path,{method,headers:body?{'content-type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})});
 const value=await r.json();assert.equal(r.status,200,JSON.stringify(value));await q.checkCircuit();return value;
}
async function launch(){
 running=true;await q.record('launch',await q.launch());
 launchId=crypto.randomUUID();
 q.s.page.on('request',r=>{if(r.url().includes('/api/v1/trading/accounts/')){
  const row={at:Date.now(),launchId,url:r.url(),method:r.method()};requests.push(row);
  if(r.url().endsWith('/events')){streams.push(row);r._qaPracticeStream=row;}
 }});
 q.s.page.on('requestfailed',r=>{if(r._qaPracticeStream)r._qaPracticeStream.endedAt=Date.now();});
 q.s.page.on('requestfinished',r=>{if(r._qaPracticeStream)r._qaPracticeStream.endedAt=Date.now();});
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000});await q.checkCircuit();await q.enableControl();
}
async function close(){
 for(const observer of observers.splice(0))await observer.stop();
 await q.quit();assert.equal(await q.exited(),true);running=false;
 await q.record('full-owned-exit',{allExited:true,elapsedMs:Date.now()-q.s.quitStartedAt});
}
async function showPanel(){if(!await panel().isVisible())await q.s.page.getByRole('button',{name:'交易账户',exact:true}).click();}
async function create(name){
 await panel().locator('button.trading-icon-button[aria-label="添加账户"]').click();
 const dialog=q.s.page.getByRole('dialog',{name:'添加账户',exact:true});
 await dialog.getByLabel('名称',{exact:true}).fill(name);
 await dialog.getByLabel('初始资金（USDT）',{exact:true}).fill('1000');
 await dialog.getByLabel('滑点（基点）',{exact:true}).fill('0');
 const response=q.s.page.waitForResponse(r=>r.url().endsWith('/trading/accounts')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'创建',exact:true}).click();const r=await response;
 assert.equal(r.status(),200);const account=await r.json();assert.equal(account.kind,'practice');return account;
}
// Read actual renderer state without publishing, refreshing, or modifying it.
async function view(){return q.s.page.evaluate(()=>{
 const element=document.querySelector('.trading-panel');if(!element)return null;
 let fiber=element[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))],state=null;
 if(!fiber)return null;while(fiber.return)fiber=fiber.return;
 function visit(node){if(!node||state)return;
  for(let hook=node.memoizedState;hook&&typeof hook==='object';hook=hook.next){
   const v=hook.memoizedState;
   if(v?.selected?.id&&v.selected.id===element.querySelector('select')?.value&&v.summary?.account?.id===v.selected.id&&Array.isArray(v.trades)&&Array.isArray(v.entries)){state=v;break;}
  }visit(node.child);visit(node.sibling);
 }visit(fiber.stateNode.current);
 return state?{selected:state.selected,summary:state.summary,trades:state.trades,entries:state.entries,error:state.error,text:element.innerText,selectedValue:element.querySelector('select')?.value}:null;
 });}
async function chart(){return q.s.page.evaluate(()=>{
 const element=document.querySelector('[data-chart-cell-id="cell-1"]');if(!element)return null;
 let fiber=element[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))];if(!fiber)return null;while(fiber.return)fiber=fiber.return;
 let result=null;function visit(node){if(!node||result)return;const p=node.memoizedProps;
  if(p?.seriesStore&&p.datasetKey&&p.externalPriceLineSource){result={dataset:p.datasetKey,lastBar:p.seriesStore.last(),lines:p.externalPriceLineSource.getSnapshot().lines,markers:p.externalMarkerSource?.getSnapshot().markers??[]};return;}
  visit(node.child);visit(node.sibling);
 }visit(fiber.stateNode.current);return result;
 });}
async function selected(id,predicate=()=>true){return wait(async()=>{
 const state=await view();return state?.selected.id===id&&state.selectedValue===id&&!state.error&&predicate(state)?state:false;
 });}
async function pin(id){
 await q.s.page.getByRole('button',{name:'图 1 的交易与笔记',exact:true}).click();
 const dialog=q.s.page.getByRole('dialog',{name:'图 1 的交易与笔记',exact:true});
 await dialog.getByRole('combobox').selectOption(id);
 await dialog.getByLabel('显示成交标记',{exact:true}).check();
 await dialog.getByLabel('显示持仓和保护线',{exact:true}).check();
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();
}
async function observe(id){
 const controller=new AbortController(),frames=[];let failure=null,reader;
 const r=await fetch(q.s.backend+'/api/v1/trading/accounts/'+id+'/events',{signal:controller.signal});assert.equal(r.status,200);
 const task=(async()=>{const decoder=new TextDecoder();let pending='';reader=r.body.getReader();
  try{while(true){const part=await reader.read();if(part.done)break;pending+=decoder.decode(part.value,{stream:true});let at;
   while((at=pending.indexOf('\n'))>=0){const line=pending.slice(0,at);pending=pending.slice(at+1);if(!line.trim())continue;
    const frame=JSON.parse(line);assert.equal(frame.schema,'candlescope.trading-account-state/1');
    if(frame.type==='snapshot'){
     assert.equal(frame.identity.accountId,id);assert.equal(frame.replacement,true);assert.equal(frame.identity.ledgerEpoch,frame.state.cursor.epoch);
     const prior=frames.at(-1);if(prior){assert.equal(frame.connectionEpoch,prior.connectionEpoch);assert.ok(frame.sequence>prior.sequence);assert.equal(frame.state.cursor.epoch,prior.state.cursor.epoch);assert.ok(frame.state.cursor.sequence>=prior.state.cursor.sequence);}
     frames.push(frame);assert.ok(frames.length<1000,'Unbounded observer trace');
    }else assert.equal(frame.type,'heartbeat');
   }
  }}catch(error){if(!controller.signal.aborted)failure=String(error.stack??error);}finally{reader.releaseLock();}
 })();
 const observer={frames,check(){assert.equal(failure,null);},async stop(){controller.abort();await task;this.check();}};observers.push(observer);
 await wait(()=>{observer.check();return frames.length>0;});return observer;
}
function active(id){return streams.filter(row=>row.launchId===launchId&&row.url.endsWith('/'+id+'/events')&&!row.endedAt);}
async function settleShared(){await q.delay(1800);await wait(()=>active(a.id).length===1&&active(b.id).length===1);}
function noPoll(since){const old=requests.filter(row=>row.at>=since&&row.method==='GET'&&/\/(summary|trades|journal)(\?|$)/.test(row.url));assert.deepEqual(old,[],'Renderer performed legacy account reads');}
function stable(state){return {balance:state.summary.balance,positions:state.summary.positions,workingOrders:state.summary.workingOrders,trades:state.trades.map(t=>({id:t.id,status:t.status,openQty:t.openQty,netPnl:t.netPnl}))};}
function oracle(fills){return JSON.parse(cp.execFileSync('/Users/ryanliang/CandleScope/backend/.venv/bin/python',['-B','-c',
 'import json,sys; from decimal import Decimal as D; f=json.load(sys.stdin); assert len(f)==2; assert all(x["feeCurrency"]=="USDT" for x in f); bought=sum((D(x["qty"]) for x in f if x["side"]=="buy"),D(0)); sold=sum((D(x["qty"]) for x in f if x["side"]=="sell"),D(0)); assert bought==sold==D("0.001"); cash=sum(((D(1) if x["side"]=="sell" else D(-1))*D(x["price"])*D(x["qty"])-D(x["fee"]) for x in f),D(0)); print(json.dumps({"balance":str(D(1000)+cash),"netPnl":str(cash)}))'
 ],{encoding:'utf8',input:JSON.stringify(fills)}));}
function equalDecimal(left,right){assert.equal(cp.execFileSync('/Users/ryanliang/CandleScope/backend/.venv/bin/python',['-B','-c','import sys; from decimal import Decimal; assert Decimal(sys.argv[1])==Decimal(sys.argv[2]); print("equal")',left,right],{encoding:'utf8'}).trim(),'equal');}
try{
 verify();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-before.json');await launch();
 const configured=await q.configure([{session:q.session('BTCUSDT','1m'),indicators:[]}],'single');assert.ok(['ready','applied'].includes(configured.result.state));
 await wait(async()=>{const s=await q.inspect();return s.cells.length===1&&s.cells[0].runtime.marketReady&&!s.cells[0].runtime.loading&&s.persistence.state==='saved'?s:false;},180000);
 await showPanel();a=await create('Native committed A');await selected(a.id);
 await panel().getByLabel('数量（BTC）',{exact:true}).fill('0.001');
 const response=q.s.page.waitForResponse(r=>r.url().endsWith('/orders')&&r.request().method()==='POST');
 await panel().getByRole('button',{name:'提交买入',exact:true}).click();const r=await response;assert.equal(r.status(),200);const entry=await r.json();assert.equal(entry.order.status,'filled');
 const entered=await selected(a.id,v=>v.summary.positions.length===1);const tradeId=entered.summary.positions[0].id;assert.equal(entered.summary.positions[0].openQty,'0.001');
 await pin(a.id);await wait(async()=>{const c=await chart();return c?.lines.some(line=>line.id==='trading:entry:'+tradeId)?c:false;});
 await q.record('native-ui-entry',{entry,view:entered,chart:await chart()});await q.screenshot('native-practice-entry');
 b=await create('Native committed B');await selected(b.id,v=>v.trades.length===0);await settleShared();
 const observer=await observe(a.id),commitsStarted=Date.now();
 const pending=await api('/'+a.id+'/orders','POST',{...instrument,side:'buy',type:'limit',qty:'0.001',limitPrice:'1'});assert.equal(pending.order.status,'working');
 await wait(()=>{observer.check();return observer.frames.find(frame=>frame.state.summary.workingOrders.some(order=>order.id===pending.order.id));});
 await panel().getByRole('combobox',{name:'当前账户',exact:true}).selectOption(a.id);
 await selected(a.id,v=>v.summary.workingOrders.some(order=>order.id===pending.order.id));
 await panel().getByRole('tab',{name:/^持仓/}).click();assert.ok((await panel().innerText()).includes('BTCUSDT'));
 await api('/'+a.id+'/orders/'+pending.order.id+'/cancel','POST');
 const cancelled=await selected(a.id,v=>v.summary.workingOrders.length===0);assert.equal(cancelled.summary.positions.length,1);
 await panel().getByRole('combobox',{name:'当前账户',exact:true}).selectOption(b.id);await selected(b.id,v=>v.trades.length===0);
 // Selecting A legitimately releases B's final consumer; selecting B again
 // opens its stream. Only the following uninterrupted phase forbids reconnects.
 await settleShared();const phase=Date.now(),streamCount=streams.length;
 const closedOrder=await api('/'+a.id+'/orders','POST',{...instrument,side:'sell',type:'market',qty:'0.001',reduceOnly:true});assert.equal(closedOrder.order.status,'filled');
 const closedFrame=await wait(()=>{observer.check();return observer.frames.find(frame=>frame.state.summary.positions.length===0&&frame.state.trades.some(t=>t.id===tradeId&&t.status==='closed'));});
 await wait(async()=>{const c=await chart();return c&&!c.lines.some(line=>line.id==='trading:entry:'+tradeId)&&c.markers.filter(m=>m.id.startsWith('trading-live:fill:')).length>=2?c:false;});
 await selected(b.id,v=>v.trades.length===0&&v.summary.positions.length===0&&v.summary.balance==='1000');
 while(Date.now()-phase<22000){await q.checkCircuit();observer.check();await q.delay(350);}
 noPoll(commitsStarted);assert.equal(streams.length,streamCount,'Uninterrupted push phase reconnected renderer streams');assert.equal(active(a.id).length,1);assert.equal(active(b.id).length,1);
 await q.record('independent-commits-push-isolation',{pending,cancelled,closedOrder,closedFrame,chart:await chart(),panel:await view(),elapsedMs:Date.now()-phase,rendererRequests:requests.filter(row=>row.at>=commitsStarted),observerFrames:observer.frames});
 await panel().getByRole('combobox',{name:'当前账户',exact:true}).selectOption(a.id);const flat=await selected(a.id,v=>v.summary.positions.length===0&&v.trades.some(t=>t.status==='closed'));
 const fills=(await api('/'+a.id+'/fills')).fills,expected=oracle(fills);equalDecimal(flat.summary.balance,expected.balance);equalDecimal(flat.trades.find(t=>t.id===tradeId).netPnl,expected.netPnl);
 const saved=stable(flat),savedCursor=closedFrame.state.cursor;await q.screenshot('native-practice-flat');
 await wait(async()=>{const s=await q.inspect();return s.persistence.state==='saved'?s:false;});await q.record('saved-flat-ledger',{fills,expected,view:flat,cursor:savedCursor});
 await close();verify();await fs.copyFile(q.s.root+'/verified-after.json',q.s.root+'/verified-between.json');await launch();
 await wait(async()=>{const s=await q.inspect();return s.cells[0]?.runtime.marketReady&&!s.cells[0].runtime.loading&&s.persistence.state==='saved'?s:false;},180000);
 await showPanel();const restored=await selected(a.id,v=>v.trades.some(t=>t.id===tradeId&&t.status==='closed'));assert.deepEqual(stable(restored),saved);assert.deepEqual((await api('/'+a.id+'/fills')).fills,fills);
 const restartObserver=await observe(a.id),restoredCursor=restartObserver.frames[0].state.cursor;assert.equal(restoredCursor.epoch,savedCursor.epoch);assert.ok(restoredCursor.sequence>=savedCursor.sequence);
 await q.s.page.getByRole('button',{name:'图 1 的交易与笔记',exact:true}).click();const menu=q.s.page.getByRole('dialog',{name:'图 1 的交易与笔记',exact:true});assert.equal(await menu.getByRole('combobox').inputValue(),a.id);await menu.getByRole('button',{name:'关闭',exact:true}).click();
 await q.screenshot('native-practice-restored');await q.record('full-restart-restored',{view:restored,cursor:restoredCursor,chart:await chart()});
 for(const observer of observers.splice(0))await observer.stop();
 await q.s.page.getByRole('button',{name:'图 1 的交易与笔记',exact:true}).click();
 await menu.getByLabel('显示成交标记',{exact:true}).uncheck();await menu.getByLabel('显示持仓和保护线',{exact:true}).uncheck();await menu.getByLabel('显示笔记标记',{exact:true}).uncheck();
 await menu.getByRole('button',{name:'关闭',exact:true}).click();
 await panel().getByRole('button',{name:'关闭',exact:true}).click();await wait(()=>active(a.id).length===0);
 const beforeReopen=streams.length;await showPanel();await selected(a.id,v=>v.trades.some(t=>t.id===tradeId&&t.status==='closed'));await wait(()=>active(a.id).length===1);
 assert.equal(streams.length,beforeReopen+1);assert.deepEqual(stable(await view()),saved);
 await q.record('last-renderer-consumer-release-and-reopen',{activeBeforeReopen:0,activeAfterReopen:active(a.id),view:await view(),scope:'Renderer stream cancellation and normal app cleanup; backend internal subscription count is not exposed by native debug API.'});
 assert.deepEqual(q.s.receipt.errors,[]);await close();verify();q.s.receipt.passed=true;
}catch(error){q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);process.exitCode=1;if(q.s.page)await q.screenshot('native-practice-failure').catch(()=>{});}
finally{
 if(running&&q.s.app){q.s.identity??={pid:q.s.app.process()?.pid};try{await close();}catch(error){q.s.receipt.exitFailure=String(error);}}
 if(q.s.app&&!running)try{verify();}catch(error){q.s.receipt.passed=false;q.s.receipt.packageFailure=String(error);process.exitCode=1;}
 await fs.mkdir(q.s.root,{recursive:true});await fs.writeFile(q.s.root+'/practice-renderer-requests.json',JSON.stringify({requests,streams},null,2));await q.save();
 console.log(JSON.stringify({passed:q.s.receipt.passed??false,failure:q.s.receipt.failure}));
}
