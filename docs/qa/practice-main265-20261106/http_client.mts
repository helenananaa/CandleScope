import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const base=process.env.CANDLESCOPE_QA_HTTP_BASE!;
const root=process.env.CANDLESCOPE_QA_STATE_ROOT!;
const browserEvents=new EventTarget();
Object.assign(browserEvents,{candlescopeDesktop:{apiBase:base+'/api/v1'}});
Object.defineProperty(globalThis,'window',{value:browserEvents,configurable:true});
const {tradingApi}=await import('../../../frontend/src/features/trading-accounts/tradingApi.js');
const {TradingAccountDataPool}=await import('../../../frontend/src/features/trading-accounts/tradingAccountDataPool.js');
const {streamTradingAccountState}=await import('../../../frontend/src/features/trading-accounts/tradingAccountStateStream.js');
const frames:Record<string,Array<{epoch:string;sequence:number}>>={};
const pool=new TradingAccountDataPool({...tradingApi,stateStream:async(id,signal,update)=>streamTradingAccountState(id,signal,state=>{
 (frames[id]??=[]).push({...state.cursor});update(state);
})});
const wait=async<T>(check:()=>T|false)=>{const until=Date.now()+15000;while(Date.now()<until){const value=check();if(value)return value;await new Promise(r=>setTimeout(r,10));}throw Error('state adoption timeout');};
const diag=async()=>{const r=await fetch(base+'/qa/diagnostics');assert.equal(r.status,200);return await r.json();};
const mode=process.argv[2];
if(mode==='flow'){
 const a=await tradingApi.createAccount({kind:'practice',name:'Actual HTTP A',settings:{initialBalance:'1000',slippageBps:'0'}});
 const b=await tradingApi.createAccount({kind:'practice',name:'Actual HTTP B',settings:{initialBalance:'1000',slippageBps:'0'}});
 const first=pool.account(a.id),same=pool.account(a.id),other=pool.account(b.id);
 const releases=[first.retain(),same.retain(),other.retain()];
 try{
  await wait(()=>first.getSnapshot().summary&&other.getSnapshot().summary);
  assert.equal((await diag()).manager.subscriptions,2);
  await tradingApi.placeOrder(a.id,{exchange:'binance',marketType:'futures',symbol:'BTCUSDT',side:'buy',type:'market',qty:'1',bracketStop:'98',bracketTarget:'103'});
  await wait(()=>first.getSnapshot().summary?.positions.length===1&&first.getSnapshot().summary?.workingOrders.length===2);
  assert.equal(other.getSnapshot().summary!.positions.length,0);
  const advanced=await fetch(base+'/qa/advance',{method:'POST'});assert.equal(advanced.status,200);
  await wait(()=>first.getSnapshot().trades[0]?.status==='closed');
  assert.equal(first.getSnapshot().summary!.balance,'1002.9294');
  assert.equal(first.getSnapshot().summary!.positions.length,0);assert.equal(first.getSnapshot().summary!.workingOrders.length,0);
  // Independent fee arithmetic in integer micro-USDT: 3 - .05 - .0206.
  assert.equal(3000000n-50000n-20600n,2929400n);
  assert.equal(first.getSnapshot().trades[0]!.netPnl,'2.9294');
  const placed=await tradingApi.placeOrder(a.id,{exchange:'binance',marketType:'futures',symbol:'BTCUSDT',side:'buy',type:'limit',qty:'1',limitPrice:'80'});
  await wait(()=>first.getSnapshot().summary!.workingOrders.length===1);
  await tradingApi.cancelOrder(a.id,placed.order.id);await wait(()=>first.getSnapshot().summary!.workingOrders.length===0);
  releases[0]!();assert.equal((await diag()).manager.subscriptions,2);
  releases[1]!();releases[2]!();
  await wait(asyncNever);
 }finally{for(const release of releases)release();}
 function asyncNever(){return first.getSnapshot().summary===null&&other.getSnapshot().summary===null;}
 let current=await diag();for(let i=0;i<100&&current.manager.subscriptions;i++){await new Promise(r=>setTimeout(r,10));current=await diag();}
 assert.equal(current.manager.subscriptions,0);assert.equal(current.network.blocked_attempts,0);
 assert.equal(current.requests.filter((r:{path:string})=>/\/(summary|trades|journal)$/.test(r.path)).length,0);
 assert.equal(current.requests.filter((r:{path:string})=>r.path.endsWith('/events')).length,2);
 await fs.writeFile(root+'/expected.json',JSON.stringify({a:a.id,b:b.id,cursor:frames[a.id]!.at(-1),balance:'1002.9294',netPnl:'2.9294'}));
 await fs.writeFile(root+'/http-flow.json',JSON.stringify({passed:true,scope:'Real trading routes/SQLite and unmodified frontend transport/pool over loopback; controlled candles, GZip middleware; not browser/native/LIVE startup.',frames,diagnostics:current},null,2));
}else{
 const expected=JSON.parse(await fs.readFile(root+'/expected.json','utf8'));
 const data=pool.account(expected.a),release=data.retain();
 try{
  await wait(()=>data.getSnapshot().summary);
  assert.equal(data.getSnapshot().summary!.balance,expected.balance);assert.equal(data.getSnapshot().trades[0]!.netPnl,expected.netPnl);
  assert.deepEqual(frames[expected.a]!.at(-1),expected.cursor);
 }finally{release();}
 let current=await diag();for(let i=0;i<100&&current.manager.subscriptions;i++){await new Promise(r=>setTimeout(r,10));current=await diag();}
 assert.equal(current.manager.subscriptions,0);assert.equal(current.network.blocked_attempts,0);
 await fs.writeFile(root+'/http-restart.json',JSON.stringify({passed:true,scope:'Fresh backend and frontend model process, original SQLite facts/cursor retained. Not native application restart.',expected,frames,diagnostics:current},null,2));
}
console.log(JSON.stringify({mode,passed:true}));
