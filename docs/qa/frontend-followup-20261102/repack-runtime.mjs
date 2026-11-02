import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {createRequire} from 'node:module';
const root=process.cwd(), app=path.resolve(process.argv[2]), out=path.resolve(process.argv[3]);
const resources=path.join(app,'Contents/Resources');
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const stage=path.join(out,'frontend-repack');
if(fs.existsSync(stage)) throw new Error('Preserve existing repack staging');
asar.extractAll(path.join(resources,'app.asar'),stage);
for(const name of ['dist','desktop']) {
  fs.rmSync(path.join(stage,name),{recursive:true});
  fs.cpSync(path.join(root,'frontend',name),path.join(stage,name),{recursive:true});
}
fs.copyFileSync(path.join(root,'frontend/package.json'),path.join(stage,'package.json'));
const next=path.join(resources,'app.next.asar');
await asar.createPackage(stage,next);
const hash=crypto.createHash('sha256').update(asar.getRawHeader(next).headerString).digest('hex');
fs.renameSync(next,path.join(resources,'app.asar'));
cp.execFileSync('/usr/libexec/PlistBuddy',['-c',`Set :ElectronAsarIntegrity:Resources/app.asar:hash ${hash}`,path.join(app,'Contents/Info.plist')]);
cp.execFileSync('codesign',['--force','--sign','-',app],{stdio:'inherit'});
cp.execFileSync('codesign',['--verify','--deep','--strict',app],{stdio:'inherit'});
fs.writeFileSync(path.join(out,'assembly.json'),JSON.stringify({
  sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  assembly:'Qualified stability candidate runtime cloned with APFS; current backend compiled with bundled Python, current desktop frontend rebuilt/repacked, unchanged verified Pine+Python package assets reused after input-tree/hash checks, root ad-hoc signed. Not a fresh full runtime/engine build.',
  app,asarHeaderSha256:hash,
},null,2)+'\n');
fs.rmSync(stage,{recursive:true});
console.log(JSON.stringify({app,asarHeaderSha256:hash}));
