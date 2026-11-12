import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';

const root=path.resolve(process.argv[2]),profile=path.resolve(process.argv[3]);
const receipt=JSON.parse(await fs.readFile(root+'/acceptance.json','utf8'));
const pid=receipt.steps.find(step=>step.name==='launch').evidence.identity.pid;
const alive=()=>{try{process.kill(pid,0);return true;}catch{return false;}};
while(alive()){
 let latest;
 try{latest=JSON.parse(await fs.readFile(root+'/acceptance.json','utf8'));}catch{}
 const sample=latest?.soak?.at(-1);
 if(sample?.cycle===10&&sample.elapsedMs>=1_650_000){
  await promisify(execFile)(process.execPath,[new URL('./native-config-snapshot.mjs',import.meta.url).pathname,
   profile,root+'/pre-restart-configuration.json']);
  await fs.writeFile(root+'/configuration-observer.json',JSON.stringify({sourceCommit:receipt.sourceCommit,
   appPid:pid,at:Date.now(),cycle:sample.cycle,elapsedMs:sample.elapsedMs,
   scope:'Read-only exact indicator definitions and layout after all ten cycles, before first full exit',passed:true},null,2));
  process.exit(0);
 }
 await new Promise(resolve=>setTimeout(resolve,5000));
}
throw new Error('The original application exited before the final configuration observation');
