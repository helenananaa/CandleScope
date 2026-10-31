import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import { registerSharedMarketCache, snapshotSharedMarketCacheDiagnostics } from "../sharedMarketCacheOwner.js";
import { collectFrontendCacheDiagnostics } from "../cacheDiagnostics.js";
import { planFrontendGc } from "../cachePolicy.js";
import { executeFrontendGcPlan } from "../cacheTrim.js";
import { dependencyAvailable, klineDependencyKey } from "../cacheRegistry.js";
import type { EpochSeconds, KlineBar } from "../../market-data/marketDataTypes.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time = 60, close = 10): KlineBar => ({ time: time as EpochSeconds,
  open: 10, high: 30, low: 0, close, volume: 1, is_closed: true });
function plan() {
  const market = snapshotSharedMarketCacheDiagnostics();
  return planFrontendGc({ klineBars: market.totalBars, estimatedBytes: market.estimatedBytes, owners: { market } },
    { maxKlineBars: 0, maxEstimatedBytes: 1 });
}

test("workspace cache registration accounts for shared facts once and releases dependency availability", t => {
  const cache = new SharedMarketCache();
  const release = registerSharedMarketCache(cache); t.after(release);
  cache.admitRealtime(series, row());
  assert.equal(collectFrontendCacheDiagnostics().owners!.market!.totalBars, 1);
  assert.equal(dependencyAvailable(klineDependencyKey(series)), true);
  const result = executeFrontendGcPlan(plan());
  assert.equal(result.removedBars, 1);
  assert.equal(result.removedEstimatedBytes, 200);
  assert.equal(result.accountingMatchesPlan, true);
  assert.equal(cache.read(series).rows.length, 0);
  assert.equal(dependencyAvailable(klineDependencyKey(series)), false);
  release();
  assert.equal(snapshotSharedMarketCacheDiagnostics().totalBars, 0);
});

test("GC cannot apply a stale plan after access, mutation, recreation, request or range acquisition", t => {
  const cache = new SharedMarketCache(); t.after(registerSharedMarketCache(cache));
  for (const change of [
    () => { cache.read(series); },
    () => { cache.admitRealtime(series, row(60, 20), "bar.amended"); },
    () => { cache.invalidate(series); cache.admitRealtime(series, row()); },
    () => { const read = cache.beginRead(series); t.after(() => read.release()); },
  ]) {
    cache.clear(); cache.admitRealtime(series, row());
    const stale = plan();
    assert.equal(stale.victims.length, 1);
    change();
    assert.equal(executeFrontendGcPlan(stale).removedCount, 0);
    assert.equal(cache.read(series).rows.length, 1);
  }
  cache.clear(); cache.admitRealtime(series, row());
  const stale = plan();
  const range = cache.retain(series, { from: 60, to: 60 });
  assert.equal(executeFrontendGcPlan(stale).removedCount, 0);
  range.release();
});

test("same series in separate workspaces has independent ownership and forged relief is rejected", t => {
  const first = new SharedMarketCache(), second = new SharedMarketCache();
  t.after(registerSharedMarketCache(first)); t.after(registerSharedMarketCache(second));
  first.admitRealtime(series, row()); second.admitRealtime(series, row());
  const proposal = plan();
  assert.equal(proposal.victims.length, 2);
  assert.notEqual(proposal.victims[0]!.key, proposal.victims[1]!.key);
  const one = proposal.victims[0]!;
  const forged = { ...proposal, victims: [{ ...one, estimatedBytes: 1 }] };
  assert.equal(executeFrontendGcPlan(forged).removedCount, 0);
  const result = executeFrontendGcPlan({ ...proposal, victims: [one] });
  assert.equal(result.removedCount, 1);
  assert.equal(snapshotSharedMarketCacheDiagnostics().totalBars, 1);
});
