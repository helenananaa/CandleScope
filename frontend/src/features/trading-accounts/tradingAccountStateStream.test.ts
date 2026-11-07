import assert from "node:assert/strict";
import test from "node:test";
import { streamTradingAccountState, type TradingAccountSnapshot } from "./tradingAccountStateStream.js";
import { TradingAccountDataPool } from "./tradingAccountDataPool.js";

const ledger="a".repeat(32),connection="b".repeat(32);
const state = (): TradingAccountSnapshot => ({ cursor:{epoch:ledger,sequence:1},
  summary:{account:{id:"account",kind:"practice",name:"测试账户",quoteCurrency:"USDT",settings:{},createdAtMs:1,archived:false,
    capabilities:{placeOrders:true,manualFills:false,sync:false}},balance:"1234.567890123456789",equity:"1234.567890123456789",
    unrealizedPnl:"0",usedMargin:"0",available:"1234.567890123456789",positions:[],workingOrders:[],feeds:[],closedTrades:0},trades:[],entries:[] });
const frame = (seq=1) => ({schema:"candlescope.trading-account-state/1",type:"snapshot",replacement:true,
  identity:{accountId:"account",ledgerEpoch:ledger},connectionEpoch:connection,sequence:seq,state:state()});
const turns=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};

test("framing preserves split UTF8 and Decimal text; identical duplicates do not reapply",async()=>{
  const previous=globalThis.fetch;let cancelled=false;
  try {
    const first=JSON.stringify(frame()), second=JSON.stringify(frame(2));
    globalThis.fetch=async(_url,init)=>{
      assert.equal(init?.redirect,"error");assert.equal(init?.credentials,"omit");
      const bytes=new TextEncoder().encode(first+'\n'+first+'\n'+second+'\n');
      return new Response(new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=13)c.enqueue(bytes.slice(i,i+13));},cancel(){cancelled=true;}}),
        {headers:{"content-type":"application/x-ndjson"}});
    };
    const controller=new AbortController();const updates:TradingAccountSnapshot[]=[];
    await assert.rejects(streamTradingAccountState("account",controller.signal,s=>{updates.push(s);if(updates.length===2)controller.abort();}));
    assert.equal(updates.length,2);assert.equal(updates[0]!.summary.account.name,"测试账户");
    assert.equal(updates[0]!.summary.balance,"1234.567890123456789");assert.equal(cancelled,true);
  } finally {globalThis.fetch=previous;}
});

test("account, database, connection, revision and same-sequence conflicts cannot overwrite state",async()=>{
  const previous=globalThis.fetch;
  try {
    const cases=[
      {...frame(2),identity:{accountId:"other",ledgerEpoch:ledger}},
      {...frame(2),connectionEpoch:"c".repeat(32)},
      {...frame(2),state:{...state(),cursor:{epoch:"c".repeat(32),sequence:2}}},
      {...frame(2),state:{...state(),cursor:{epoch:ledger,sequence:0}}},
      {...frame(),state:{...state(),summary:{...state().summary,balance:"1"}}},
      {...frame(2),state:{...state(),summary:{...state().summary,balance:1}}},
      {...frame(2),state:{...state(),trades:[{accountId:"other",id:"t"}]}},
    ];
    for(const bad of cases){
      let updates=0;
      globalThis.fetch=async()=>new Response(JSON.stringify(frame())+'\n'+JSON.stringify(bad)+'\n',{headers:{"content-type":"application/x-ndjson"}});
      await assert.rejects(streamTradingAccountState("account",new AbortController().signal,()=>{updates++;}),/Invalid/);
      assert.equal(updates,1);
    }
  } finally {globalThis.fetch=previous;}
});

test("shared live connection never polls while idle and final release fences late callbacks",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  const streams:{signal:AbortSignal;update:(value:TradingAccountSnapshot)=>void}[]=[];
  let reads=0;
  const pool=new TradingAccountDataPool({summary:async()=>{reads++;return state().summary;},trades:async()=>{reads++;return{trades:[]};},journal:async()=>{reads++;return{entries:[]};},
    stateStream:async(_id,signal,update)=>{streams.push({signal,update});await new Promise<void>(resolve=>signal.addEventListener("abort",()=>resolve(),{once:true}));}});
  const panel=pool.account("account"),chart=pool.account("account");
  const releasePanel=panel.retain(),releaseChart=chart.retain();await turns();
  assert.equal(streams.length,1);streams[0]!.update(state());
  t.mock.timers.tick(60000);await turns();assert.equal(streams.length,1);assert.equal(reads,0);
  releasePanel();assert.equal(streams[0]!.signal.aborted,false);
  releaseChart();assert.equal(streams[0]!.signal.aborted,true);
  const releaseNew=panel.retain();await turns();assert.equal(streams.length,2);
  streams[1]!.update({...state(),summary:{...state().summary,balance:"2000"}});
  streams[0]!.update(state());assert.equal(panel.getSnapshot().summary?.balance,"2000");
  releaseNew();await panel.refreshAfterPending();await turns();assert.equal(streams.length,2);
});

test("a write refresh opens a later snapshot; reconnect never calls polling endpoints",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  const streams:{signal:AbortSignal;update:(s:TradingAccountSnapshot)=>void;fail:(e:Error)=>void}[]=[];
  const pool=new TradingAccountDataPool({summary:async()=>{throw Error("poll");},trades:async()=>{throw Error("poll");},journal:async()=>{throw Error("poll");},
    stateStream:async(_id,signal,update)=>new Promise<void>((resolve,reject)=>{streams.push({signal,update,fail:reject});signal.addEventListener("abort",()=>resolve(),{once:true});})});
  const data=pool.account("account"),release=data.retain();await turns();streams[0]!.update(state());
  const refreshed=data.refreshAfterPending();await turns();assert.equal(streams.length,2);assert.equal(streams[0]!.signal.aborted,true);
  const next={...state(),cursor:{epoch:ledger,sequence:3}};streams[1]!.update(next);await refreshed;
  streams[1]!.fail(Error("offline"));await turns();assert.equal(data.getSnapshot().error,"offline");
  t.mock.timers.tick(2001);await turns();assert.equal(streams.length,3);streams[2]!.update(next);
  assert.equal(data.getSnapshot().error,null);release();await turns();
});

test("silent connections expire, while transport heartbeats extend the read deadline",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  const previous=globalThis.fetch;
  let wire!:ReadableStreamDefaultController<Uint8Array>,cancelled=false;
  try {
    globalThis.fetch=async()=>new Response(new ReadableStream<Uint8Array>({start(c){wire=c;},cancel(){cancelled=true;}}),
      {headers:{"content-type":"application/x-ndjson"}});
    let updates=0;
    const running=streamTradingAccountState("account",new AbortController().signal,()=>{updates++;});
    const rejected=assert.rejects(running,/timed out/);
    await turns();wire.enqueue(new TextEncoder().encode(JSON.stringify(frame())+'\n'));await turns();
    t.mock.timers.tick(20000);wire.enqueue(new TextEncoder().encode(JSON.stringify({schema:"candlescope.trading-account-state/1",type:"heartbeat"})+'\n'));await turns();
    t.mock.timers.tick(20000);await turns();assert.equal(cancelled,false);
    t.mock.timers.tick(10001);await rejected;assert.equal(cancelled,true);assert.equal(updates,1);
  } finally {globalThis.fetch=previous;}
});

test("manual accounts keep quote revalidation until a live valuation owner exists",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  const signals:AbortSignal[]=[];
  const pool=new TradingAccountDataPool({summary:async()=>state().summary,trades:async()=>({trades:[]}),journal:async()=>({entries:[]}),
    stateStream:async(_id,signal,update)=>{signals.push(signal);const manual=state();manual.summary.account.kind="manual";update(manual);
      await new Promise<void>(resolve=>signal.addEventListener("abort",()=>resolve(),{once:true}));}});
  const data=pool.account("account"),release=data.retain();await turns();assert.equal(signals.length,1);
  t.mock.timers.tick(15001);await turns();assert.equal(signals.length,2);assert.equal(signals[0]!.aborted,true);
  release();t.mock.timers.tick(60000);await turns();assert.equal(signals.length,2);
});
