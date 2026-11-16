import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {capture} from '../backend-batch1-20261101/value-probe.mjs';
import {captureRendered} from './rendered-probe.mjs';
const root=path.resolve(process.argv[2]),profile=path.resolve(process.argv[3]);
const initial=JSON.parse(await fs.readFile(root+'/acceptance.json','utf8'));
const pid=initial.steps.find(step=>step.name==='launch').evidence.identity.pid;
const result={schema:'candlescope.frontend-near-end-values/1',sourceCommit:initial.sourceCommit,appPid:pid,attempts:[],
 scope:'Read-only actual candle/indicator series verification near the end of the original live 30-minute app process'};
const alive=()=>{try{process.kill(pid,0);return true;}catch{return false;}};
async function read(){
 const port=(await fs.readFile(profile+'/DevToolsActivePort','utf8')).split('\n')[0];
 const tabs=await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json());const tab=tabs.find(t=>t.type==='page'&&t.url.startsWith('http'));
 const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});let id=0;
 const q={s:{page:{evaluate:async fn=>{
  const request=++id;const reply=new Promise((resolve,reject)=>{ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id===request){if(message.result.exceptionDetails)reject(new Error(message.result.exceptionDetails.text));else resolve(message.result.result.value);}};ws.onerror=reject;});
  ws.send(JSON.stringify({id:request,method:'Runtime.evaluate',params:{expression:'('+fn.toString()+')()',returnByValue:true}}));return reply;
 }}}};
 try{
  const windows=await capture(q),display=await captureRendered(q),checked=[];assert.equal(windows.length,2);
  for(const window of windows){
   const bars=(Array.isArray(window.bars)?window.bars:Object.values(window.bars)).filter(bar=>bar.is_closed);
   const actual=display.find(chart=>chart.cellId===window.cellId);assert.ok(actual);assert.equal(actual.lines.length,4);
   const candles=new Map(actual.candles.map(bar=>[Number(bar.time),bar])),points=[];
   for(const id of ['qa-ma','qa-js','qa-pine','qa-python']){
    const line=actual.lines.find(line=>line.id===id);assert.ok(line);const values=new Map(line.data.map(point=>[Number(point.time),point.value]));let count=0;
    for(let index=Math.max(19,bars.length-60);index<bars.length;index++){
     const bar=bars[index],candle=candles.get(bar.time);assert.ok(candle);
     for(const key of ['open','high','low','close'])assert.equal(candle[key],bar[key]);
     const expected=id==='qa-ma'?bars.slice(index-19,index+1).reduce((sum,bar)=>sum+bar.close,0)/20:bar.close*(id==='qa-js'?2:id==='qa-pine'?3:4);
     assert.ok(Math.abs(values.get(bar.time)-expected)<=Math.max(1e-7,Math.abs(expected)*1e-10),window.cellId+' '+id+' '+bar.time);count++;
    }
    assert.ok(count>=20);points.push({id,checked:count});
   }
   checked.push({cellId:window.cellId,symbol:window.symbol,interval:window.interval,lastClosedTime:bars.at(-1).time,points});
  }
  return checked;
 }finally{ws.close();}
}
try{
 let started;
 while(alive()){
  const main=JSON.parse(await fs.readFile(root+'/acceptance.json','utf8'));
  const step=main.steps.find(step=>step.name==='soak-0');
  if(step&&main.soak.length)started=Date.parse(step.at)-main.soak[0].elapsedMs;
  if(started&&Date.now()-started>=1770000)break;
  await new Promise(resolve=>setTimeout(resolve,10000));
 }
 assert.ok(alive()&&started,'Original live process exited before the near-end checkpoint');
 while(alive()&&Date.now()-started<1800000){
  const at=Date.now();
  try{const checked=await read();result.attempts.push({at,elapsedMs:at-started,checked});result.passed=true;break;}
  catch(error){result.attempts.push({at,elapsedMs:at-started,error:String(error)});await new Promise(resolve=>setTimeout(resolve,1000));}
 }
 assert.equal(result.passed,true,'No valid near-end numerical checkpoint');
}catch(error){result.failure=String(error);process.exitCode=1;}
finally{await fs.writeFile(root+'/near-end-values.json',JSON.stringify(result,null,2));console.log(JSON.stringify({passed:result.passed??false,failure:result.failure}));}
