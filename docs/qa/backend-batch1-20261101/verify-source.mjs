import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(),out=process.env.CANDLESCOPE_BATCH1_QA_ROOT ?? path.join(root,'output/batch1-native-20261101');
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const resources=path.join(out,'Installed App/CandleScope.app/Contents/Resources');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const result={sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
 assembly:'Vite desktop build + electron-builder; effective-ceiling follow-up copied and byte-compiled before final root ad-hoc signing and strict verification',
 runtime:'Reused standalone runtime from PR189 candidate; requirements, CCXT lock, SDK and runtime/control preparation inputs verified unchanged',
 files:{},dist:{},mismatches:[]};
for(const file of cp.execFileSync('git',['ls-files','-z','backend/app','frontend/desktop'],{encoding:'utf8'}).split('\0').filter(Boolean)){
 const expected=hash(fs.readFileSync(file));result.files[file]=expected;
 const actual=file.startsWith('backend/')?fs.readFileSync(path.join(resources,file)):asar.extractFile(path.join(resources,'app.asar'),file.slice(9));
 if(hash(actual)!==expected)result.mismatches.push(file);
}
function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else{const rel=path.relative(path.join(root,'frontend'),p);const expected=hash(fs.readFileSync(p));result.dist[rel]=expected;if(hash(asar.extractFile(path.join(resources,'app.asar'),rel))!==expected)result.mismatches.push(rel);}}}
walk(path.join(root,'frontend/dist'));
fs.writeFileSync(path.join(out,'source-package-manifest.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({sourceCommit:result.sourceCommit,sourceFiles:Object.keys(result.files).length,distFiles:Object.keys(result.dist).length,mismatches:result.mismatches}));
if(result.mismatches.length)process.exit(1);
