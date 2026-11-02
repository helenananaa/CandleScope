import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import cp from 'node:child_process';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const root=process.cwd(), require=createRequire(path.join(root,'frontend/package.json'));
const {Arch}=require('builder-util');
const resources=path.join(root,'output/python-indicator-native-20261101/Installed App/CandleScope.app/Contents/Resources');
const project=fs.mkdtempSync(path.join(os.tmpdir(),'candlescope-real-bundle-guard-'));
fs.mkdirSync(path.join(project,'.desktop-runtime'));
fs.symlinkSync(path.join(resources,'python-runtime'),path.join(project,'.desktop-runtime/runtime'));
fs.symlinkSync(path.join(resources,'control'),path.join(project,'.desktop-runtime/control'));
const context={packager:{projectDir:project},electronPlatformName:'darwin',arch:Arch.arm64};
const beforePath=path.join(root,'frontend/scripts/.qa-before-runtime-guard.cjs');
try {
 fs.writeFileSync(beforePath,cp.execFileSync('git',['show','e3f7a8003c29e3dde5068983a9c906307d52f190:frontend/scripts/check-desktop-runtime.cjs'],{cwd:root}));
 await assert.rejects(require(beforePath)(context),/bundled Pine runtime/);
 await require(path.join(root,'frontend/scripts/check-desktop-runtime.cjs'))(context);
 const manifest=JSON.parse(fs.readFileSync(path.join(resources,'python-runtime/plugins/manifest.json')));
 console.log(JSON.stringify({before:'rejected actual prepared Pine+Python artifacts',after:'passed actual control/runtime architecture and both complete bundle size+sha256 checks',ids:manifest.plugins.map(p=>p.runtimeId),platform:'darwin',arch:'arm64'}));
} finally {fs.rmSync(beforePath,{force:true});fs.rmSync(project,{recursive:true,force:true});}
