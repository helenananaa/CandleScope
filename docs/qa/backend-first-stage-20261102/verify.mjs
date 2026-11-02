import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(),out=path.join(root,'output/backend-first-stage-20261102/native');
const manifest=JSON.parse(fs.readFileSync(path.join(out,'source-package-manifest.json'),'utf8'));
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const resources=path.join(manifest.app,'Contents/Resources');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const mismatches=[];
for(const [file,expected] of Object.entries(manifest.files)){
 const actual=file.startsWith('backend/')?fs.readFileSync(path.join(resources,file)):asar.extractFile(path.join(resources,'app.asar'),file.slice(9));
 if(hash(actual)!==expected||hash(fs.readFileSync(file))!==expected)mismatches.push(file);
}
for(const [file,expected] of Object.entries(manifest.dist))
 if(hash(asar.extractFile(path.join(resources,'app.asar'),file))!==expected||hash(fs.readFileSync(path.join(root,'frontend',file)))!==expected)mismatches.push(file);
cp.execFileSync('codesign',['--verify','--deep','--strict',manifest.app],{stdio:'inherit'});
const result={sourceCommit:manifest.sourceCommit,sourceFiles:Object.keys(manifest.files).length,builtFiles:Object.keys(manifest.dist).length,mismatches,strictSignature:true};
fs.writeFileSync(path.join(out,'verified-after.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));if(mismatches.length)process.exit(1);
