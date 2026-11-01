import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as q from './acceptance-driver.mjs';
import {setup} from './setup-native.mjs';

setup(q);
const step=async(name,fn)=>{console.log(new Date().toISOString(),name);const result=await fn();await q.record(name,result);return result;};
const ready=async()=>{
  await q.s.page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({timeout:90_000});
  await q.s.page.waitForFunction(()=>Number(document.querySelector('[data-replay-cell-bars]')?.getAttribute('data-replay-cell-bars'))>=20);
  assert.deepEqual(q.s.receipt.errors,[]);
};
async function request(route){const response=await fetch(q.s.backend+'/api/v1/replay'+route);assert.equal(response.status,200);return response.json();}
const state=async()=>{
  const id=new URL(q.s.page.url()).searchParams.get('run');assert.ok(id,'No run');
  return {run:await request('/runs/'+id),tracks:await request('/runs/'+id+'/tracks'),
    manager:await q.s.page.evaluate(()=>window.__CANDLESCOPE_REPLAY_DATA__?.snapshot()),
    ui:await q.s.page.locator('[data-replay-cursor-ms]').first().evaluate(el=>Object.fromEntries([...el.attributes].map(a=>[a.name,a.value])))};
};
async function advance(){
  const before=await q.s.page.locator('[data-replay-cursor-ms]').first().getAttribute('data-replay-cursor-ms');
  await q.s.page.locator('[data-replay-action="advance-base"]').click();
  await q.s.page.waitForFunction(old=>Number(document.querySelector('[data-replay-cursor-ms]')?.getAttribute('data-replay-cursor-ms'))>Number(old),before);
  await ready();
}
try {
  await step('packaged-launch',q.launch);
  q.s.page.setDefaultTimeout(30_000);
  // firstWindow + bootstrap precedes completion of the desktop boot loadURL.
  // Let that navigation finish before navigating to the replay entry.
  await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();
  await q.s.page.waitForLoadState('load');
  await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);
  await q.s.page.getByRole('button',{name:'新建训练',exact:true}).click();
  await q.s.page.getByRole('textbox',{name:'商品',exact:true}).fill('BTCUSDT');
  await q.s.page.getByRole('textbox',{name:'开始时间（UTC）',exact:true}).fill('2023-11-15T12:00');
  await q.s.page.locator('#training-hub-create-advanced > summary').click();
  await q.s.page.getByRole('spinbutton',{name:'指标预热 BAR 只保证指标计算所需数据，不决定图表可向前滚动多远。',exact:true}).fill('100');
  await q.s.page.locator('[data-training-field="forward-cache-ms"]').fill('3600000');
  await q.s.page.getByRole('combobox',{name:'可见历史',exact:true}).selectOption('DURATION');
  await q.s.page.getByRole('spinbutton',{name:'可见历史时长（ms）',exact:false}).fill('21600000');
  await q.s.page.getByRole('textbox',{name:'Maker 基点',exact:true}).fill('2');
  await q.s.page.getByRole('textbox',{name:'Taker 基点',exact:true}).fill('5');
  await q.s.page.getByRole('textbox',{name:'市价滑点 bps',exact:true}).fill('1');
  await q.s.page.getByRole('button',{name:'确认时间并创建训练',exact:true}).click();
  await ready();
  await step('created-paused',state);
  await q.s.page.screenshot({path:q.s.root+'/created.png'});
  await q.s.page.locator('[data-replay-panel="order-ticket"]').getByRole('button',{name:'市价',exact:true}).click();
  await q.s.page.locator('[data-replay-field="order-quantity"]').fill('0.01');
  await q.s.page.locator('[data-replay-action="place-order"][data-side="BUY"]').click();
  await q.delay(800);
  await advance();
  await step('buy-filled',state);
  for(let i=0;i<4;i++)await advance();
  await q.s.page.locator('[data-replay-panel="order-ticket"] [data-mode="close"]').click();
  await q.s.page.locator('[data-replay-field="order-quantity"]').fill('0.01');
  await q.s.page.locator('[data-replay-action="place-order"][data-side="SELL"]').click();
  await q.delay(800);
  await advance();
  await step('closed-cycle',state);
  await q.s.page.screenshot({path:q.s.root+'/closed-cycle.png'});
  const saved=await state();
  const runId=saved.tracks.run_id;
  await q.s.page.getByRole('button',{name:'存档大厅',exact:true}).click();
  await q.s.page.getByRole('button',{name:'新建训练',exact:true}).waitFor();
  await step('saved-hub',async()=>({runId,manager:await q.s.page.evaluate(()=>window.__CANDLESCOPE_REPLAY_DATA__?.snapshot())}));
  await step('full-exit',async()=>({owned:await q.quit(),allExited:await q.exited()}));
  await step('restart',q.launch);
  await q.s.page.getByRole('button',{name:'设置',exact:true}).waitFor();
  await q.s.page.waitForLoadState('load');
  await q.s.page.goto(new URL('/replay.html',q.s.page.url()).href);
  await q.s.page.locator('.training-hub-card').first().getByRole('button',{name:'继续训练',exact:true}).click();
  await ready();
  const restored=await step('restored-paused',state);
  assert.equal(restored.tracks.run_id,runId);
  assert.deepEqual(restored.tracks.portfolio,saved.tracks.portfolio);
  assert.deepEqual(restored.tracks.global_clock,saved.tracks.global_clock);
  await q.s.page.screenshot({path:q.s.root+'/restored.png'});
  await advance();
  await step('continued-after-restart',state);
  assert.deepEqual(q.s.receipt.errors,[]);
  await step('final-exit',async()=>({owned:await q.quit(),allExited:await q.exited()}));
  q.s.receipt.passed=true;await q.save();console.log('NATIVE REPLAY BASIC PASS');
}catch(error){
  q.s.receipt.passed=false;q.s.receipt.failure=String(error.stack??error);await q.save();console.error(error);
  try{await fs.writeFile(q.s.root+'/failure-page.txt',await q.s.page.locator('body').ariaSnapshot());await q.s.page.screenshot({path:q.s.root+'/failure.png'});}catch{}
  try{await q.quit();await q.exited();}catch{}
  process.exitCode=1;
}
