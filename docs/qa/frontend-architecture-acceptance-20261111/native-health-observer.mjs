import fs from 'node:fs/promises';
import path from 'node:path';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
const root=path.resolve(process.argv[2]),profile=path.resolve(process.argv[3]);
const receipt=JSON.parse(await fs.readFile(root+'/acceptance.json','utf8'));
const launch=receipt.steps.find(step=>step.name==='launch').evidence;
const result={schema:'candlescope.frontend-live-health-observer/1',sourceCommit:receipt.sourceCommit,appPid:launch.identity.pid,
 scope:'Read-only control/CDP observations of demanded series health and closed-tail advancement; no source substitution',samples:[],errors:[]};
const alive=()=>{try{process.kill(result.appPid,0);return true;}catch{return false;}};
const save=()=>fs.writeFile(root+'/live-health-observations.json',JSON.stringify(result,null,2));
async function sample(){
 const client=new ControlClient(profile+'/control/connection.json');await client.connect();
 const {snapshot}=await client.call('workspace.inspect',{windowId:'main-window'});
 const sessions=snapshot.cells.map(cell=>({cellId:cell.cellId,session:cell.session,marketReady:cell.runtime.marketReady,indicatorsReady:cell.runtime.indicatorsReady}));
 const port=(await fs.readFile(profile+'/DevToolsActivePort','utf8')).split('\n')[0];
 const tabs=await fetch('http://127.0.0.1:'+port+'/json/list').then(response=>response.json());
 const tab=tabs.find(tab=>tab.type==='page'&&tab.url.startsWith('http'));
 const ws=new WebSocket(tab.webSocketDebuggerUrl);
 try{
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  const expression=`(()=>{const element=document.querySelector('[data-chart-cell-id]');let root=element[Object.keys(element).find(key=>key.startsWith('__reactFiber$'))];while(root.return)root=root.return;let provider;function visit(node){if(!node||provider)return;const value=node.memoizedProps?.value;if(value?.dataManager?.cache&&value.indicatorDataManager)provider=value;visit(node.child);visit(node.sibling);}visit(root.stateNode.current);return ${JSON.stringify(sessions)}.map(cell=>{const plan=provider.dataManager.cache.planHistory(cell.session,500);return {...cell,action:plan.action,health:plan.health,count:plan.snapshot.rows.length,lastClosedTime:plan.snapshot.rows.at(-1)?.time,version:plan.snapshot.version};});})()`;
  const reply=new Promise((resolve,reject)=>{ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id===1){if(message.result?.exceptionDetails)reject(new Error(message.result.exceptionDetails.text));else resolve(message.result.result.value);}};ws.onerror=reject;});
  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression,returnByValue:true}}));
  return await Promise.race([reply,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Observation timed out')),10000))]);
 }finally{ws.close();}
}
try{
 while(alive()){
  const at=Date.now();
  try{result.samples.push({at,cells:await sample()});}
  catch(error){result.errors.push({at,error:String(error)});}
  await save();await new Promise(resolve=>setTimeout(resolve,30000));
 }
 result.exitObserved=true;
}finally{result.finishedAt=Date.now();await save();}
