import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';
setup(q);q.s.receipt.schema='candlescope.native-export-download/1';
try {
 await q.record('launch',await q.launch());
 await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();
 await q.s.page.waitForLoadState('load');
 await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);
 await q.s.page.locator('.training-hub-card').first().getByRole('button',{name:'继续训练',exact:true}).click();
 await q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:60000});
 const id=new URL(q.s.page.url()).searchParams.get('run');
 const curve=await fetch(q.s.backend+'/api/v1/replay/runs/'+id+'/portfolio-equity').then(r=>r.json());
 await q.record('curve-availability',{available:curve.available,samples:curve.samples.length});
 const destination=q.s.root+'/native-export-probe.ndjson';
 await q.s.app.evaluate(({BrowserWindow},destination)=>{
  globalThis.qaDownloadEvents=[];globalThis.qaDownloadDone=null;
  const w=BrowserWindow.getAllWindows()[0];
  w.webContents.on('will-navigate',(e,url)=>globalThis.qaDownloadEvents.push({kind:'navigate',url,prevented:e.defaultPrevented}));
  w.webContents.session.once('will-download',(_e,item)=>{
   globalThis.qaDownloadEvents.push({kind:'download',url:item.getURL()});
   // Select a QA destination using Electron's native DownloadItem API. Network,
   // response, IPC validation and the real disk transfer remain unchanged.
   item.setSavePath(destination);
   item.once('done',(_event,state)=>{globalThis.qaDownloadDone={state,receivedBytes:item.getReceivedBytes(),totalBytes:item.getTotalBytes(),path:item.getSavePath(),mime:item.getMimeType()};});
  });
 },destination);
 await q.record('probe-scope',{method:'Real native bridge and DownloadItem stream; destination selected by the harness. Empty single-market export; nonempty curve UI and OS save dialog are not qualified.'});
 assert.deepEqual(await q.s.page.evaluate(id=>window.candlescopeDesktop.downloadReplayPortfolio(id),id),{started:true});
 const done=await q.until(()=>q.s.app.evaluate(()=>globalThis.qaDownloadDone),30000);
 assert.equal(done.state,'completed');
 const bytes=await fs.readFile(destination),lines=bytes.toString('utf8').trimEnd().split('\n'),records=lines.map(line=>JSON.parse(line));
 assert.ok(bytes.length>0);assert.equal(done.receivedBytes,bytes.length);
 const terminal=records.at(-1);assert.equal(terminal.kind,'complete');
 assert.equal(terminal.records,records.length-1);
 assert.equal(terminal.sha256,createHash('sha256').update(lines.slice(0,-1).join('\n')+'\n').digest('hex'));
 await q.record('download',{...done,bytes:bytes.length,records:records.length,terminal,sha256:createHash('sha256').update(bytes).digest('hex')});
 await q.record('native-events',await q.s.app.evaluate(()=>globalThis.qaDownloadEvents));
 q.s.receipt.passed=true;
}catch(e){q.s.receipt.failure=String(e.stack??e);q.s.receipt.passed=false;console.error(e);process.exitCode=1;}
try{await q.record('exit',{owned:await q.quit(),allExited:await q.exited()});}catch(e){q.s.receipt.exitError=String(e);q.s.receipt.passed=false;process.exitCode=1;}
await q.save();console.log('Native download:',q.s.receipt.passed);
