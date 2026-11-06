import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_BATCH1_QA_ROOT;
assert.ok(out);const receipt=JSON.parse(fs.readFileSync(path.join(out,'ci-artifact-verification.json'),'utf8'));
assert.equal(receipt.appLaunched,false);
const app=path.join(out,'Installed App/CandleScope.app'),resources=path.join(app,'Contents/Resources');
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const files={},dist={},plugins={},sdkArtifacts={},mismatches=[];
for(const file of cp.execFileSync('git',['ls-files','-z'],{encoding:'utf8'}).split('\0').filter(Boolean)){
 if(file.startsWith('backend/app/')||file.startsWith('frontend/desktop/')||file.startsWith('packages/candlescope-plugin-sdk/src/')||file.startsWith('packages/candlescope-backtest-sdk/src/')){
  // Honor the repository's explicit checkout attributes (SDK eol=crlf).
  // Git blobs are LF; packaging uses the checked-out bytes on the CI runner.
  const expected=hash(cp.execFileSync('git',['cat-file','--filters','--path='+file,receipt.buildManifest.commit+':'+file],{maxBuffer:16*1024*1024}));
  assert.equal(hash(fs.readFileSync(path.join(root,file))),expected,'Current owning source differs from CI head: '+file);
  files[file]=expected;
  const bundled=file.startsWith('frontend/')?asar.extractFile(path.join(resources,'app.asar'),file.slice(9)):fs.readFileSync(path.join(resources,file));
  if(hash(bundled)!==expected)mismatches.push(file);
 }
}
for(const name of asar.listPackage(path.join(resources,'app.asar'))){
 const file=name.replace(/^\//,'');if(!file.startsWith('dist/'))continue;
 try{if(asar.statFile(path.join(resources,'app.asar'),file).files)continue;dist[file]=hash(asar.extractFile(path.join(resources,'app.asar'),file));}
 catch(error){throw new Error('Cannot read original CI frontend asset '+file,{cause:error});}
}
function walk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,entry.name);if(entry.isDirectory())walk(file);
 else plugins[path.relative(resources,file)]=hash(fs.readFileSync(file));
}}walk(path.join(resources,'python-runtime/plugins'));
function sdkWalk(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,entry.name);if(entry.isDirectory())sdkWalk(file);
 else sdkArtifacts[path.relative(resources,file)]=hash(fs.readFileSync(file));
}}
for(const [pkg,module] of [['candlescope-backtest-sdk','candlescope_backtest_sdk'],['candlescope-plugin-sdk','candlescope_plugin_sdk']]){
 sdkWalk(path.join(resources,'packages',pkg,'src',module));sdkWalk(path.join(resources,'python-runtime/site-packages',module));
}
assert.deepEqual(mismatches,[]);assert.ok(Object.keys(dist).length>100);
const manifest={sourceCommit:receipt.buildManifest.commit,ciArtifact:receipt.artifact,assembly:receipt.assembly,
 app,files,dist,plugins,sdkArtifacts,mismatches,asarSha256:hash(fs.readFileSync(path.join(resources,'app.asar')))};
const target=path.join(out,'source-package-manifest.json');assert.ok(!fs.existsSync(target));
fs.writeFileSync(target,JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify({sourceCommit:manifest.sourceCommit,sourceFiles:Object.keys(files).length,builtFiles:Object.keys(dist).length,pluginAssets:Object.keys(plugins).length,mismatches,ciOriginal:true}));
