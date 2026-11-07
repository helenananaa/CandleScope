import assert from "node:assert/strict";
import test from "node:test";
import { ChartCalculationSessions } from "../chartCalculationSessions.js";
import { parseIndicatorPayloadEnvelope } from "../indicatorContracts.js";
import type { IndicatorCalculationPosition, IndicatorRangeRequest } from "../indicatorTypes.js";

const A = "a".repeat(32), B = "b".repeat(32);
function position(domainId=A, generation=1, sequence=1, origin=100): IndicatorCalculationPosition {
  return { schemaVersion:1,domainId,generation,sequence,origin,observedThrough:500,closedThrough:500,
    view:"current-projection",inputRevision:"source:1" };
}
function payload(calculation=position(), type="indicator.snapshot") {
  return parseIndicatorPayloadEnvelope({ ok:true,type,calculation });
}
function input(start=100): IndicatorRangeRequest {
  return { clientId:"one",kind:"script",language:"pine",script:"plot(close)",params:{},
    exchange:"binance",marketType:"spot",symbol:"BTCUSDT",interval:"1m",start,end:500 };
}
function deferred<T>() {
  let resolve!: (value:T)=>void;
  const promise = new Promise<T>(yes=>{ resolve=yes; });
  return { promise,resolve };
}

test("concurrent ranges share one owned open and reject foreign/regressing partial output",async()=>{
  const opened = deferred<ReturnType<typeof payload>>();let opens=0;
  const sessions = new ChartCalculationSessions({ open:async()=>{ opens++;return opened.promise; },
    read:async()=>payload(),close:async()=>{} },()=>{});
  sessions.setContext("chart");
  const first=sessions.range("chart","definition",input(),100),second=sessions.range("chart","definition",input(),100);
  await Promise.resolve();opened.resolve(payload());
  const [one,two]=await Promise.all([first,second]);assert.equal(opens,1);
  assert.equal(sessions.admit("one","definition",one),"reset");
  assert.equal(sessions.admit("one","definition",two),"same");
  assert.equal(sessions.admit("one","definition",payload(position(B))),"reject");
  assert.equal(sessions.admit("one","definition",payload(position(A,2,2),"indicator.replace_range")),"reject");
  assert.equal(sessions.admit("one","definition",payload(position(A,2,2))),"reset");
  assert.equal(sessions.admit("one","definition",one),"reject");
  assert.equal(sessions.admit("one","different",payload(position(A,2,2))),"reject");
  await sessions.dispose();
});

test("an abandoned open is observed and releases exactly its own domain",async()=>{
  const opened=deferred<ReturnType<typeof payload>>(),closed:string[]=[];
  const sessions=new ChartCalculationSessions({ open:async()=>opened.promise,read:async()=>payload(),
    close:async id=>{closed.push(id);} },()=>{});
  sessions.setContext("old");
  const pending=sessions.range("old","definition",input(),100);
  await Promise.resolve();sessions.setContext("new");opened.resolve(payload());
  await assert.rejects(pending,{name:"AbortError"});await sessions.dispose();
  assert.deepEqual(closed,[A]);
});

test("CAS recovery advances request position without admitting an error as a projection",async()=>{
  let reads=0;
  const sessions=new ChartCalculationSessions({ open:async()=>payload(),read:async request=>{
    reads++;
    if(reads===1)return parseIndicatorPayloadEnvelope({ok:false,code:"INDICATOR_CALCULATION_CHANGED",calculation:position(A,2,2)});
    assert.equal(request.calculation.generation,2);return payload(position(A,2,2));
  },close:async()=>{} },()=>{});
  sessions.setContext("chart");const result=await sessions.range("chart","definition",input(),100);
  assert.equal(reads,2);assert.equal(sessions.admit("one","definition",result),"reset");await sessions.dispose();
});

test("failed cleanup retains the resource slot and is retried before opening replacement",async()=>{
  let fail=true,opens=0;
  const sessions=new ChartCalculationSessions({ open:async()=>payload(position(opens++?B:A)),read:async request=>payload(position(request.calculation.domainId)),
    close:async()=>{if(fail)throw Error("physical release failed");} },()=>{},1);
  sessions.setContext("chart");await sessions.range("chart","first",input(),100);
  sessions.reconcile(new Map());
  await assert.rejects(sessions.range("chart","next",input(),100),/physical release failed/);
  assert.equal(opens,1);fail=false;
  const next=await sessions.range("chart","next",input(),100);assert.equal(next.calculation?.domainId,B);
  await sessions.dispose();
});

test("left expansion replaces the domain and old observations cannot enter it",async()=>{
  let opens=0;const closed:string[]=[];
  const sessions=new ChartCalculationSessions({open:async request=>payload(position(opens++?B:A,1,1,request.start)),
    read:async request=>payload(position(request.calculation.domainId,1,1,request.calculation.domainId===A?100:50)),
    close:async id=>{closed.push(id);} },()=>{});
  sessions.setContext("chart");const old=await sessions.range("chart","same-definition",input(),100);
  const next=await sessions.range("chart","same-definition",input(50),50);
  assert.equal(next.calculation?.domainId,B);assert.equal(sessions.admit("one","same-definition",old),"reject");
  assert.deepEqual(closed,[A]);await sessions.dispose();
});

test("lost output uses an explicit complete-origin rebuild, never a standalone tail",async()=>{
  let reads=0;
  const sessions=new ChartCalculationSessions({open:async()=>payload(),read:async request=>{
    reads++;if(reads===1)return parseIndicatorPayloadEnvelope({ok:false,code:"INDICATOR_CALCULATION_OUTPUT_LOST"});
    assert.equal(request.rebuild,true);return payload(position(A,2,2));
  },close:async()=>{}},()=>{});
  sessions.setContext("chart");assert.equal((await sessions.range("chart","definition",input(400),100)).calculation?.generation,2);
  await sessions.dispose();
});

test("calculation wire values are strict and never coerced into another projection",()=>{
  for(const changed of [{schemaVersion:true},{generation:true},{sequence:1.5},{domainId:"bad"},
    {view:"historical"},{closedThrough:501},{observedThrough:99}]) {
    assert.throws(()=>parseIndicatorPayloadEnvelope({ok:true,calculation:{...position(),...changed}}));
  }
});
