import fs from 'node:fs/promises';
import {ControlClient} from '../../../packages/candlescope-control/client.mjs';
const profile=process.argv[2],output=process.argv[3];
const client=new ControlClient(profile+'/control/connection.json');await client.connect();
const {snapshot}=await client.call('workspace.inspect',{windowId:'main-window'});
const port=(await fs.readFile(profile+'/DevToolsActivePort','utf8')).split('\n')[0];
const tabs=await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json());const tab=tabs.find(t=>t.type==='page'&&t.url.startsWith('http'));
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
try{
 const response=new Promise((resolve,reject)=>{ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id===1){if(message.result.exceptionDetails)reject(new Error(message.result.exceptionDetails.text));else resolve(message.result.result.value);}};ws.onerror=reject;});
 ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:`(()=>{const el=document.querySelector('[data-chart-cell-id]');let root=el[Object.keys(el).find(key=>key.startsWith('__reactFiber$'))];while(root.return)root=root.return;const cells={};function visit(node){if(!node)return;const cell=node.memoizedProps?.cell;if(cell?.id&&Array.isArray(cell.indicators))cells[cell.id]=cell.indicators;visit(node.child);visit(node.sibling);}visit(root.stateNode.current);return cells;})()`,returnByValue:true}}));
 const definitions=await response;
 await fs.writeFile(output,JSON.stringify({at:Date.now(),layout:snapshot.layout,cells:snapshot.cells.map(cell=>({cellId:cell.cellId,session:cell.session,indicators:definitions[cell.cellId]}))},null,2));
 console.log('Captured exact saved indicator definitions and layout');
}finally{ws.close();}
