import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_BATCH1_QA_ROOT??path.join(root,'output/practice-main261-20261106/native-current-plugins');
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
 if(hash(asar.extractFile(path.join(resources,'app.asar'),file))!==expected||(!manifest.ciArtifact&&hash(fs.readFileSync(path.join(root,'frontend',file)))!==expected))mismatches.push(file);
if(manifest.ciArtifact&&hash(fs.readFileSync(path.join(resources,'app.asar')))!==manifest.asarSha256)mismatches.push('ci-original-app.asar');
for(const [file,expected] of Object.entries(manifest.plugins??{}))
 if(hash(fs.readFileSync(path.join(resources,file)))!==expected)mismatches.push(file);
if(manifest.sdkArtifacts){
 const current={};function sdkWalk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
  const file=path.join(dir,entry.name);if(entry.isDirectory())sdkWalk(file);
  else current[path.relative(resources,file)]=hash(fs.readFileSync(file));
 }}
 for(const [pkg,module] of [['candlescope-backtest-sdk','candlescope_backtest_sdk'],['candlescope-plugin-sdk','candlescope_plugin_sdk']]){
  sdkWalk(path.join(resources,'packages',pkg,'src',module));sdkWalk(path.join(resources,'python-runtime/site-packages',module));
 }
 for(const file of new Set([...Object.keys(current),...Object.keys(manifest.sdkArtifacts)]))if(current[file]!==manifest.sdkArtifacts[file])mismatches.push('ci-sdk:'+file);
}
const pluginSources=JSON.parse(cp.execFileSync(path.join(resources,'python-runtime/python/bin/python3.12'),['-B',path.join(root,'docs/qa/practice-main261-20261106/verify_current_plugins.py')],{encoding:'utf8',env:{...process.env,CANDLESCOPE_BATCH1_QA_ROOT:out}}));
let strictSignature=false,signatureError=null;
try {cp.execFileSync('codesign',['--verify','--deep','--strict',manifest.app],{stdio:'inherit'});strictSignature=true;}
catch(error){signatureError=String(error);}
const result={verifiedAt:new Date().toISOString(),sourceCommit:manifest.sourceCommit,sourceFiles:Object.keys(manifest.files).length,builtFiles:Object.keys(manifest.dist).length,pluginAssets:Object.keys(manifest.plugins??{}).length,ciArtifactId:manifest.ciArtifact?.id??null,sdkArtifactFiles:manifest.sdkArtifacts?Object.keys(manifest.sdkArtifacts).length:null,sdkPreexistingPyc:manifest.sdkArtifacts?Object.keys(manifest.sdkArtifacts).filter(file=>file.endsWith('.pyc')).length:null,pluginSources,mismatches,strictSignature,signatureError};
fs.writeFileSync(path.join(out,'verified-after.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));if(mismatches.length||!strictSignature)process.exit(1);
