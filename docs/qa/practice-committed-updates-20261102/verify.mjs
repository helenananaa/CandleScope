import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_BATCH1_QA_ROOT??path.join(root,'output/practice-committed-updates-20261102/offline-strategy-native');
const manifest=JSON.parse(fs.readFileSync(path.join(out,'source-package-manifest.json'),'utf8'));
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const resources=path.join(manifest.app,'Contents/Resources');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const mismatches=[];
for(const [file,expected] of Object.entries(manifest.files)){
 const actual=!file.startsWith('frontend/')?fs.readFileSync(path.join(resources,file)):asar.extractFile(path.join(resources,'app.asar'),file.slice(9));
 if(hash(actual)!==expected||hash(fs.readFileSync(file))!==expected)mismatches.push(file);
 if(file.startsWith('packages/')){
  const relative=file.split('/src/')[1];
  if(hash(fs.readFileSync(path.join(resources,'python-runtime/site-packages',relative)))!==expected)mismatches.push('sdk-mirror:'+file);
 }
}
for(const [file,expected] of Object.entries(manifest.dist))
 if(hash(asar.extractFile(path.join(resources,'app.asar'),file))!==expected||hash(fs.readFileSync(path.join(root,'frontend',file)))!==expected)mismatches.push(file);
for(const [file,expected] of Object.entries(manifest.plugins??{}))
 if(hash(fs.readFileSync(path.join(resources,file)))!==expected)mismatches.push(file);
const pluginSources=JSON.parse(cp.execFileSync(path.join(resources,'python-runtime/python/bin/python3.12'),['-B',path.join(root,'docs/qa/practice-committed-updates-20261102/verify_current_plugins.py')],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:out}}));
let strictSignature=false,signatureError=null;
try {cp.execFileSync('codesign',['--verify','--deep','--strict',manifest.app],{stdio:'inherit'});strictSignature=true;}
catch(error){signatureError=String(error);}
const result={verifiedAt:new Date().toISOString(),sourceCommit:manifest.sourceCommit,sourceFiles:Object.keys(manifest.files).length,builtFiles:Object.keys(manifest.dist).length,pluginAssets:Object.keys(manifest.plugins??{}).length,pluginSources,mismatches,strictSignature,signatureError};
fs.writeFileSync(path.join(out,'verified-after.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));if(mismatches.length||!strictSignature)process.exit(1);
