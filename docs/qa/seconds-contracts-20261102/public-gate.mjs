import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

/** Startup discovers public catalogs, so reject before Electron is launched. */
export async function assertPublicGate(root) {
 let deadline=Date.parse('2026-11-02T16:14:01.202Z');
 for(const file of ['/Users/ryanliang/CandleScope/output/backend-goal-20261102/STATE.json',root+'/new-cooldown.json']) {
  let value;
  try{value=JSON.parse(await fs.readFile(file,'utf8'));}
  catch(error){if(error.code==='ENOENT')continue;throw error;}
  const observed=Date.parse(value.public_cooldown?.retry_not_before_utc??value.retry_not_before_utc??'');
  if(Number.isFinite(observed))deadline=Math.max(deadline,observed);
 }
 assert.ok(Date.now()>=deadline,'PUBLIC_COOLDOWN: no native launch before '+new Date(deadline).toISOString());
}
