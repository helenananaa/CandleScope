import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const root=process.cwd(), out=path.join(root,'output/seconds-native-20261101');
const app=path.join(out,'Installed App/CandleScope.app');
const resources=path.join(app,'Contents/Resources');
const asar=createRequire(path.join(root,'frontend/package.json'))('@electron/asar');
const stage=path.join(out,'frontend-repack');
if(fs.existsSync(stage))throw new Error('Staging path already exists');
asar.extractAll(path.join(resources,'app.asar'),stage);
for(const name of ['dist','desktop']){
  fs.rmSync(path.join(stage,name),{recursive:true});
  fs.cpSync(path.join(root,'frontend',name),path.join(stage,name),{recursive:true});
}
fs.copyFileSync(path.join(root,'frontend/package.json'),path.join(stage,'package.json'));
const next=path.join(resources,'app.next.asar');
await asar.createPackage(stage,next);
const header=asar.getRawHeader(next);
const hash=crypto.createHash('sha256').update(header.headerString).digest('hex');
fs.renameSync(next,path.join(resources,'app.asar'));
cp.execFileSync('/usr/libexec/PlistBuddy',['-c',`Set :ElectronAsarIntegrity:Resources/app.asar:hash ${hash}`,path.join(app,'Contents/Info.plist')]);
// Preserve the accepted nested framework signatures when only resources change.
cp.execFileSync('/usr/bin/codesign',['--force','--sign','-',app],{stdio:'inherit'});
cp.execFileSync('/usr/bin/codesign',['--verify','--deep','--strict',app],{stdio:'inherit'});
const assembly={at:new Date().toISOString(),sourceCommit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
 assembly:'Accepted candidate runtime reused; current tracked backend/app copied and byte-compiled with bundled Python. Current frontend built with VITE_DESKTOP_BUILD=1; app.asar repacked with existing production dependencies and current desktop files, integrity header updated, root ad-hoc signed with accepted nested signatures preserved, deep strictly verified. Not a fresh full runtime build.',
 app,asarHeaderSha256:hash};
fs.writeFileSync(path.join(out,'assembly.json'),JSON.stringify(assembly,null,2)+'\n');
fs.rmSync(stage,{recursive:true});
console.log(JSON.stringify(assembly));
