import assert from 'node:assert/strict';
import * as q from './acceptance-driver.mjs';
import * as vp from './value-probe.mjs';
import * as checks from './acceptance-checks.mjs';
import * as scenario from './native-scenarios.mjs';

const step = async (name, action) => {
  console.log(new Date().toISOString(), name);
  return action();
};
try {
  await q.record('integrated-package-launch', await q.launch());
  await q.enableControl();
  await step('independent charts, parameters and script', () => scenario.initial(q, vp, checks));
  for (const [symbol, interval] of [['ETHUSDT','5m'],['BTCUSDT','1m'],['SOLUSDT','15m'],['BTCUSDT','1m'],['XRPUSDT','3m'],['BTCUSDT','1m']]) {
    await step(`cold switch ${symbol}/${interval}`, () => scenario.coldSwitch(q,vp,checks,symbol,interval));
  }
  await scenario.release(q,vp);
  const left=(await vp.capture(q)).find(chart=>chart.cellId==='cell-1');
  const historicalRange={from:left.bars[100].time,to:left.bars[200].time};
  await q.execute('cell-1','visibleTimeRange',historicalRange);
  await q.until(async()=>Math.abs((await q.query('cell-1')).snapshot.visibleRange.time.from-historicalRange.from)<60);
  const before = await vp.verify(q,scenario.transforms);
  const beforeRange = (await q.query('cell-1')).snapshot.visibleRange;
  const cdp = await q.s.page.context().newCDPSession(q.s.page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  const proto = await cdp.send('Runtime.evaluate',{expression:'WebSocket.prototype'});
  const sockets = await cdp.send('Runtime.queryObjects',{prototypeObjectId:proto.result.objectId});
  const closed = await cdp.send('Runtime.callFunctionOn',{objectId:sockets.objects.objectId,returnByValue:true,functionDeclaration:'function(){ return this.map(socket => { const url = socket.url; socket.close(4001); return url; }); }'});
  assert.ok(closed.result.value.some(url=>url.includes('/stream/')),'no actual app stream disconnected');
  await q.s.app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(window=>window.minimize()));
  const offlineSince=Date.now();
  await q.record('offline-minimized-start',{before,urls:closed.result.value});
  for (let i=0;i<5;i++) { await q.delay(25_000); console.log('offline seconds',Math.round((Date.now()-offlineSince)/1000)); }
  const offlineFetch = await q.s.page.evaluate(async url=>{try { await fetch(url);return 'unexpected success'; } catch { return 'network failure'; }},q.s.backend+'/health');
  assert.equal(offlineFetch,'network failure');
  await q.record('offline-minimized-observed',{durationMs:Date.now()-offlineSince,offlineFetch,broker:await q.broker()});
  await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await q.s.app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(window=>{window.restore();window.show();}));
  const recoveryStarted=Date.now();
  q.s.receipt.recovery={startedAt:recoveryStarted,samples:[]};
  const recovered=await q.until(async()=>{
    const values=await scenario.healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'});
    q.s.receipt.recovery.samples.push({elapsedMs:Date.now()-recoveryStarted,lastClosed:values.map(c=>c.lastClosed)});
    return values.every((chart,i)=>chart.lastClosed>=before[i].lastClosed+120)?values:false;
  },45_000);
  const afterRange=(await q.query('cell-1')).snapshot.visibleRange;
  assert.deepEqual(afterRange.time,beforeRange.time,'historical time window changed after reconnect');
  assert.ok(Math.abs((afterRange.logical.to-afterRange.logical.from)-(beforeRange.logical.to-beforeRange.logical.from))<0.1,'historical zoom changed after reconnect');
  await q.record('offline-recovered',{elapsedMs:Date.now()-recoveryStarted,values:recovered,coverage:await checks.visibleCoverage(q),broker:await q.broker()});
  const saved=await Promise.all(['cell-1','cell-2'].map(id=>q.query(id)));
  await q.record('saved-before-exit',{charts:saved,workspace:await q.inspect()});
  const firstBackend=q.s.backend;
  await q.record('full-exit',{owned:await q.quit(),allExited:await q.exited()});
  const portClosed=await fetch(firstBackend+'/health').then(()=>false,()=>true);
  assert.equal(portClosed,true);
  await q.record('backend-port-closed',{origin:firstBackend,portClosed});
  await q.record('restart-launch',await q.launch());
  await q.enableControl();
  await scenario.healthy(q,vp,{symbol:'BTCUSDT',interval:'1m'});
  const restored=await Promise.all(['cell-1','cell-2'].map(id=>q.query(id)));
  for(let i=0;i<2;i++) {
    assert.deepEqual(checks.comparable(restored[i].snapshot),checks.comparable(saved[i].snapshot));
    const a=saved[i].snapshot.visibleRange.logical,b=restored[i].snapshot.visibleRange.logical;
    assert.ok(Math.abs((a.to-a.from)-(b.to-b.from))<0.1,'saved zoom changed');
  }
  await q.record('restart-restored',{charts:restored,values:await vp.verify(q,scenario.transforms),coverage:await checks.visibleCoverage(q),viewportPolicy:'latest bar on reopening, saved zoom retained'});
  await q.s.page.screenshot({path:q.s.root+'/restart.png'});
  await q.execute('cell-1','removeIndicator',{indicatorId:'qa-js-left'});
  await q.until(async()=> (await q.broker()).dataFlow.indicators.inputs.subscriptions===1);
  await q.execute('cell-2','removeIndicator',{indicatorId:'qa-js-right'});
  await q.until(async()=> (await q.broker()).dataFlow.indicators.inputs.subscriptions===0);
  await q.until(async()=>q.s.page.workers().every(worker=>!worker.url().startsWith('blob:')));
  await q.record('final-input-release',{broker:await q.broker(),workers:q.s.page.workers().map(worker=>worker.url())});
  assert.deepEqual(q.s.receipt.errors,[]);
  await q.record('final-exit',{owned:await q.quit(),allExited:await q.exited()});
  q.s.receipt.passed=true;
  await q.save();
  console.log('NATIVE ACCEPTANCE PASS');
} catch(error) {
  console.error(error);
  q.s.receipt.passed=false;
  q.s.receipt.failure=String(error.stack??error);
  try { await q.screenshot('failure');q.s.receipt.failureState={workspace:await q.inspect(),broker:await q.broker()}; } catch {}
  await q.save();
  if(q.s.app) { try { await q.quit();await q.exited(); } catch {} }
  process.exitCode=1;
}
