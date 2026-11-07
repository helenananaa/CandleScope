import fs from 'node:fs/promises';import path from 'node:path';import {spawn} from 'node:child_process';
const root=process.cwd(),qa=path.join(root,'docs/qa/practice-committed-updates-20261102'),out=process.env.CANDLESCOPE_QA_HTTP_ROOT??path.join(root,'output/practice-committed-updates-20261102/http-contract');
await fs.mkdir(out,{recursive:false});
const python='/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3.12';
const exits=[];
for(const mode of ['flow','restart']){
 const server=spawn(python,['-B',path.join(qa,'http_server.py')],{cwd:root,env:{...process.env,CANDLESCOPE_QA_STATE_ROOT:out},stdio:['ignore','pipe','pipe']});
 const stopped=new Promise(resolve=>server.once('exit',(code,signal)=>resolve({exitCode:code,signal})));
 let output='',errors='';server.stderr.on('data',b=>errors+=b);
 let ready;
 try{
  ready=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('HTTP server startup timeout: '+errors)),15000);server.stdout.on('data',b=>{output+=b;for(const line of output.split('\n'))try{const j=JSON.parse(line);if(j.ready){clearTimeout(timeout);resolve(j);}}catch{}});server.once('exit',code=>reject(Error('server early exit '+code+': '+errors)));});
  const client=spawn(process.execPath,['--import','tsx',path.join(qa,'http_client.mts'),mode],{cwd:path.join(root,'frontend'),env:{...process.env,CANDLESCOPE_QA_HTTP_BASE:'http://127.0.0.1:'+ready.port,CANDLESCOPE_QA_STATE_ROOT:out},stdio:['ignore','pipe','pipe']});
  let clientOutput='',clientError='';client.stdout.on('data',b=>clientOutput+=b);client.stderr.on('data',b=>clientError+=b);
  const code=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{client.kill('SIGTERM');reject(Error('HTTP model client timeout'));},60000);client.once('exit',code=>{clearTimeout(timeout);resolve(code);});});
  await fs.writeFile(path.join(out,mode+'-client.log'),clientOutput+clientError);
  if(code!==0)throw Error('client failed '+code+': '+clientError);
 }finally{
  server.kill('SIGTERM');const exit=await stopped;
  const shutdown=output.split('\n').map(line=>{try{return JSON.parse(line);}catch{return null;}}).find(value=>value?.shutdown_complete);
  exits.push({mode,serverPid:server.pid,...exit,shutdown});
  await fs.writeFile(path.join(out,mode+'-server.log'),output+errors);
  if(!shutdown||shutdown.manager.subscriptions!==0||shutdown.manager.read_jobs!==0)throw Error('Server lifecycle cleanup was not observed');
 }
}
await fs.writeFile(path.join(out,'owned-server-exits.json'),JSON.stringify(exits,null,2));
console.log(JSON.stringify({passed:true,output:out,exits}));
