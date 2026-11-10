/** Assemble a local arm64 candidate; preserve the retained runtime and profiles. */
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_NATIVE_QA_ROOT,source=process.env.CANDLESCOPE_QA_RUNTIME_SOURCE;
assert.ok(out&&source,'Set explicit fresh output and verified runtime source');
const app=path.join(out,'Installed App/CandleScope.app'),resources=path.join(app,'Contents/Resources');
assert.ok(!fs.existsSync(app),'Preserve existing candidates');
assert.ok(fs.existsSync(path.join(root,'frontend/dist/index.html')));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const git=(...args)=>cp.execFileSync('git',args,{encoding:'utf8'}).trim();
const run=(file,args,options={})=>cp.execFileSync(file,args,{stdio:'inherit',...options});
run('codesign',['--verify','--deep','--strict',source]);
for(const name of ['requirements.txt','ccxt-fork.lock.json'])assert.deepEqual(
 fs.readFileSync(path.join(source,'Contents/Resources/backend',name)),fs.readFileSync(path.join(root,'backend',name)),name);
const before=fs.statfsSync(path.dirname(out));
fs.mkdirSync(path.dirname(app),{recursive:true});
run('/bin/cp',['-cR',source,app]);
function removeOwned(relative){
 const target=path.join(resources,relative),actual=fs.realpathSync(target);
 assert.ok(actual.startsWith(fs.realpathSync(resources)+path.sep),`Refuse external resource ${relative}`);
 fs.rmSync(target,{recursive:true});
}
removeOwned('backend/app');
for(const file of git('ls-files','-z','backend/app').split('\0').filter(Boolean)){
 const target=path.join(resources,file);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,file),target);
}
for(const [pkg,module] of [['candlescope-plugin-sdk','candlescope_plugin_sdk'],['candlescope-backtest-sdk','candlescope_backtest_sdk']]){
 for(const relative of [`packages/${pkg}/src/${module}`,`python-runtime/site-packages/${module}`]){
  removeOwned(relative);fs.cpSync(path.join(root,'packages',pkg,'src',module),path.join(resources,relative),{
   recursive:true,filter:filename=>!filename.split(path.sep).includes('__pycache__')});
 }
}
const python=path.join(resources,'python-runtime/python/bin/python3.12');
run(python,['-B','-m','compileall','-q',path.join(resources,'backend/app')]);
const plugins=JSON.parse(cp.execFileSync(python,['-B',path.join(root,'docs/qa/continuous-native-20261105/verify_plugins.py')],{
 encoding:'utf8',env:{...process.env,CANDLESCOPE_NATIVE_QA_ROOT:out}}));
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar'),stage=path.join(out,'frontend-repack');
assert.ok(!fs.existsSync(stage));asar.extractAll(path.join(resources,'app.asar'),stage);
for(const name of ['dist','desktop']){
 fs.rmSync(path.join(stage,name),{recursive:true});fs.cpSync(path.join(root,'frontend',name),path.join(stage,name),{recursive:true});
}
fs.copyFileSync(path.join(root,'frontend/package.json'),path.join(stage,'package.json'));
const next=path.join(resources,'app.next.asar');await asar.createPackage(stage,next);
const headerSha=sha(asar.getRawHeader(next).headerString);
fs.renameSync(next,path.join(resources,'app.asar'));asar.uncache(path.join(resources,'app.asar'));
run('/usr/libexec/PlistBuddy',['-c',`Set :ElectronAsarIntegrity:Resources/app.asar:hash ${headerSha}`,path.join(app,'Contents/Info.plist')]);
run('codesign',['--force','--deep','--sign','-',app]);run('codesign',['--verify','--deep','--strict',app]);
const files={},built={},assets={},mismatches=[];
for(const file of git('ls-files','-z').split('\0').filter(Boolean)){
 if(!['backend/app/','frontend/desktop/','packages/candlescope-plugin-sdk/src/','packages/candlescope-backtest-sdk/src/'].some(prefix=>file.startsWith(prefix)))continue;
 files[file]=sha(fs.readFileSync(path.join(root,file)));
 const data=file.startsWith('frontend/')?asar.extractFile(path.join(resources,'app.asar'),file.slice(9)):fs.readFileSync(path.join(resources,file));
 if(sha(data)!==files[file])mismatches.push(file);
 if(file.startsWith('packages/'))assert.equal(sha(fs.readFileSync(path.join(resources,'python-runtime/site-packages',file.split('/src/')[1]))),files[file]);
}
function walk(directory,each){for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
 const file=path.join(directory,entry.name);if(entry.isDirectory())walk(file,each);else each(file);
}}
walk(path.join(root,'frontend/dist'),file=>{
 const relative='dist/'+path.relative(path.join(root,'frontend/dist'),file);built[relative]=sha(fs.readFileSync(file));
 if(sha(asar.extractFile(path.join(resources,'app.asar'),relative))!==built[relative])mismatches.push(relative);
});
walk(path.join(resources,'python-runtime/plugins'),file=>assets[path.relative(resources,file)]=sha(fs.readFileSync(file)));
assert.deepEqual(mismatches,[]);
fs.rmSync(stage,{recursive:true});const after=fs.statfsSync(path.dirname(out));
const manifest={sourceCommit:git('rev-parse','HEAD'),sourceRuntime:source,app,
 assembly:'Local arm64 candidate using APFS-cloned verified runtime, current tracked backend/SDK/desktop and previously verified unchanged frontend build; current source/pin verified plugins, updated ASAR integrity and deep ad-hoc signature. Not a standalone runtime rebuild or functional acceptance.',
 files,built,assets,plugins,asarHeaderSha256:headerSha,asarSha256:sha(fs.readFileSync(path.join(resources,'app.asar'))),mismatches,
 observedFreeDelta:(after.bavail*after.bsize)-(before.bavail*before.bsize)};
fs.writeFileSync(path.join(out,'source-package-manifest.json'),JSON.stringify(manifest,null,2)+'\n');
run('codesign',['--verify','--deep','--strict',source]);
console.log(JSON.stringify({source:manifest.sourceCommit,app,sourceFiles:Object.keys(files).length,builtFiles:Object.keys(built).length,pluginAssets:Object.keys(assets).length,plugins,mismatches,observedFreeDelta:manifest.observedFreeDelta}));
