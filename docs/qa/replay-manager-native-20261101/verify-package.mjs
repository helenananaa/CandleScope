import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(), out=path.dirname(new URL(import.meta.url).pathname);
const require=createRequire(path.join(root,'frontend/package.json')),asar=require('@electron/asar');
const resources=path.join(out,'Installed App/CandleScope.app/Contents/Resources');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const result={sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),zipSha256:hash(fs.readFileSync(path.join(out,'CandleScope-0.3.0-macos-arm64.zip'))),asarSha256:hash(fs.readFileSync(path.join(resources,'app.asar'))),files:{},dist:{},mismatches:[]};
for(const file of cp.execFileSync('git',['ls-files','-z'],{encoding:'utf8'}).split('\0').filter(Boolean)) {
 if(!/^(frontend\/(src|desktop|scripts)\/|frontend\/(package.*json|vite.*)|backend\/app\/|backend\/(requirements.txt|ccxt-fork.lock.json)|packages\/)/.test(file))continue;
 result.files[file]=hash(fs.readFileSync(file));
 let bundled;
 if(file.startsWith('backend/'))bundled=fs.readFileSync(path.join(resources,file));
 else if(file.startsWith('frontend/desktop/'))bundled=asar.extractFile(path.join(resources,'app.asar'),file.slice(9));
 if(bundled&&hash(bundled)!==result.files[file])result.mismatches.push(file);
}
function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else{const rel=path.relative(path.join(root,'frontend'),p);const expected=hash(fs.readFileSync(p));result.dist[rel]=expected;if(hash(asar.extractFile(path.join(resources,'app.asar'),rel))!==expected)result.mismatches.push(rel);}}}
walk(path.join(root,'frontend/dist'));
fs.writeFileSync(path.join(out,'source-package-manifest.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({sourceCommit:result.sourceCommit,sourceFiles:Object.keys(result.files).length,distFiles:Object.keys(result.dist).length,mismatches:result.mismatches,zipSha256:result.zipSha256,asarSha256:result.asarSha256}));
if(result.mismatches.length)process.exit(1);
