import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_BATCH1_QA_ROOT??path.join(root,'output/replay-imported-multimarket-20261106/native-current');
const app=path.join(out,'Installed App/CandleScope.app'),resources=path.join(app,'Contents/Resources');
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const stage=path.join(out,'frontend-repack');
if(fs.existsSync(stage))throw new Error('Preserve existing staging');
asar.extractAll(path.join(resources,'app.asar'),stage);
for(const name of ['dist','desktop']){
 fs.rmSync(path.join(stage,name),{recursive:true});
 fs.cpSync(path.join(root,'frontend',name),path.join(stage,name),{recursive:true});
}
fs.copyFileSync(path.join(root,'frontend/package.json'),path.join(stage,'package.json'));
const next=path.join(resources,'app.next.asar');
await asar.createPackage(stage,next);
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
const hash=digest(asar.getRawHeader(next).headerString);
fs.renameSync(next,path.join(resources,'app.asar'));
asar.uncache(path.join(resources,'app.asar'));
cp.execFileSync('/usr/libexec/PlistBuddy',['-c',`Set :ElectronAsarIntegrity:Resources/app.asar:hash ${hash}`,path.join(app,'Contents/Info.plist')]);
cp.execFileSync('codesign',['--force','--deep','--sign','-',app],{stdio:'inherit'});
cp.execFileSync('codesign',['--verify','--deep','--strict',app],{stdio:'inherit'});
fs.rmSync(stage,{recursive:true});
const files={},dist={},plugins={},mismatches=[];
function pluginFiles(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,e.name);if(e.isDirectory())pluginFiles(file);
 else plugins[path.relative(resources,file)]=digest(fs.readFileSync(file));
}}
pluginFiles(path.join(resources,'python-runtime/plugins'));
for(const file of cp.execFileSync('git',['ls-files','-z'],{encoding:'utf8'}).split('\0').filter(Boolean)){
 if(file.startsWith('backend/app/')||file.startsWith('frontend/desktop/')||file.startsWith('packages/candlescope-plugin-sdk/src/')||file.startsWith('packages/candlescope-backtest-sdk/src/')){
  files[file]=digest(fs.readFileSync(file));
  const bundled=!file.startsWith('frontend/')?fs.readFileSync(path.join(resources,file)):asar.extractFile(path.join(resources,'app.asar'),file.slice(9));
  if(files[file]!==digest(bundled))mismatches.push(file);
 }
}
function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){
 const p=path.join(dir,e.name);if(e.isDirectory()){walk(p);continue;}
 const rel='dist/'+path.relative(path.join(root,'frontend/dist'),p);
 dist[rel]=digest(fs.readFileSync(p));
 if(dist[rel]!==digest(asar.extractFile(path.join(resources,'app.asar'),rel)))mismatches.push(rel);
}}
walk(path.join(root,'frontend/dist'));
const receipt={sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
 assembly:'Local macOS arm64 candidate: verified runtime clone, current tracked backend and SDK, newly built frontend/desktop and source-verified plugin bridges, updated ASAR integrity and deep ad-hoc signing. Full standalone runtime build not performed.',
 runtimeSource:process.env.CANDLESCOPE_QA_RUNTIME_SOURCE??'qualified retained H127 app',
 app,files,dist,plugins,mismatches,asarHeaderSha256:hash,asarSha256:digest(fs.readFileSync(path.join(resources,'app.asar')))};
fs.writeFileSync(path.join(out,'source-package-manifest.json'),JSON.stringify(receipt,null,2)+'\n');
if(mismatches.length)throw new Error(JSON.stringify(mismatches));
console.log(JSON.stringify({sourceCommit:receipt.sourceCommit,sourceFiles:Object.keys(files).length,builtFiles:Object.keys(dist).length,mismatches}));
