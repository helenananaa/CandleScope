import assert from "node:assert/strict";
import test from "node:test";
import {
  PluginChartOwner, type PluginChartObservation, type PluginChartBar, type PluginChartScope,
} from "../unifiedChartContext.js";

const target = { sessionId: "session", frontendInstanceId: "entry", entryId: "backend" };
const bar: PluginChartBar = { openTimeMs: 1000, observedThroughMs: 1500, open: 1, high: 3, low: 1, close: 2, volume: 1, closed: false };
const base: PluginChartObservation = {
  mode: "replay", runId: "run-a", trackId: "btc", seriesId: "series-a", dataRevision: "1",
  symbol: "BTC/USDT", interval: "1m", visibleThroughMs: 1500,
};
function idProvider(prefix: string) {
  let id = 0;
  return () => `${prefix}-${++id}`;
}

test("an identical chart id in two windows cannot share handles, and charts send only their own rows", async () => {
  const calls: Array<{ scope: PluginChartScope; bars: PluginChartBar[] }> = [];
  const transport = async (body: unknown) => {
    const call = body as typeof calls[number];
    calls.push(call);
    return { scope: call.scope, result: { points: [] } };
  };
  const left = new PluginChartOwner(transport, idProvider("left"));
  const right = new PluginChartOwner(transport, idProvider("right"));
  left.attach("cell-a", { observe: () => base, bars: () => [bar] });
  left.attach("cell-b", { observe: () => ({ ...base, trackId: "eth" }), bars: () => [{ ...bar, close: 3 }] });
  right.attach("cell-a", { observe: () => base, bars: () => [{ ...bar, close: 1 }] });

  const [a, b] = left.list();
  await assert.rejects(right.invoke(a!, target, null), /observation changed/i);
  await Promise.all([left.invoke(a!, target, null), left.invoke(b!, target, null), right.invoke(right.list()[0]!, target, null)]);
  assert.deepEqual(calls.map(call => [call.scope.documentId, call.scope.chartId, call.bars[0]?.close]), [
    [left.id, "cell-a", 2], [left.id, "cell-b", 3], [right.id, "cell-a", 1],
  ]);
});

test("a rewind aborts an outstanding call even if the same cursor is later restored", async () => {
  let deferred: { resolve(value: unknown): void; signal: AbortSignal } | undefined;
  let observation = base;
  let changed: (() => void) | undefined;
  const owner = new PluginChartOwner((_, signal) => new Promise(resolve => { deferred = { resolve, signal }; }), idProvider("chart"));
  const attach = owner.attach("cell", {
    observe: () => observation, bars: () => [bar],
    subscribe(listener) { changed = listener; return () => { changed = undefined; }; },
  });
  const scope = owner.list()[0]!;
  const pending = owner.invoke(scope, target, null);
  observation = { ...base, dataRevision: "2", visibleThroughMs: 1200 };
  changed?.();
  observation = base;
  changed?.();
  assert.equal(deferred?.signal.aborted, true);
  deferred?.resolve({ scope });
  await assert.rejects(pending, /observation changed/i);

  const remount = owner.attach("cell", { observe: () => base, bars: () => [bar] });
  attach.dispose();
  assert.equal(owner.list().length, 1);
  assert.equal(owner.isCurrent(scope), false);
  remount.dispose();
  assert.deepEqual(owner.list(), []);
});

test("a late response for another chart or plugin entry is rejected at adoption", async () => {
  const identity = { pluginId: "example.multi", generation: 1, version: "1.0.0", packageSha256: "sha256:digest" };
  const owner = new PluginChartOwner(async (body) => {
    const { scope } = body as { scope: PluginChartScope };
    return { scope, identity, instanceId: "other-entry" };
  }, idProvider("chart"));
  owner.attach("cell", { observe: () => base, bars: () => [bar] });
  await assert.rejects(owner.invoke(owner.list()[0]!, {
    sessionId: "session", pluginId: identity.pluginId, identity, entryId: "backend", instanceId: "approved-entry",
  }, null), /instance changed/i);
});
