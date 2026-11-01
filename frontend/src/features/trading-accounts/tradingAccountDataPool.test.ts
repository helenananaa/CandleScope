import assert from "node:assert/strict";
import test from "node:test";
import { structuralMock } from "../../test/testHelpers.js";
import type { AccountSummary } from "./tradingTypes.js";
import { TradingAccountDataPool } from "./tradingAccountDataPool.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(accept => { resolve = accept; });
  return { promise, resolve };
}

const summary = (id: string) => structuralMock<AccountSummary>({
  account: { id, kind: "practice" }, positions: [], workingOrders: [],
});

test("panel and two charts share a single account read; releasing one retains the others", async () => {
  const calls: string[] = [], signals: AbortSignal[] = [];
  const pool = new TradingAccountDataPool({
    summary: async (id, signal) => { calls.push(id); signals.push(signal!); return summary(id); },
    trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
  });
  const panel = pool.account("a"), chart = pool.account("a");
  assert.equal(panel, chart);
  const releasePanel = panel.retain(), releaseChart = chart.retain();
  try {
    await Promise.all([panel.refresh(), chart.refresh()]);
    assert.deepEqual(calls, ["a"]);
    releasePanel(); releasePanel();
    assert.equal(signals[0]!.aborted, false);
    assert.equal(chart.getSnapshot().summary?.account.id, "a");
  } finally { releasePanel(); releaseChart(); }
  assert.equal(chart.getSnapshot().summary, null);
  assert.deepEqual(chart.getSnapshot().trades, []);
});

test("different account views stay independent and abort only their own in-flight reads", async () => {
  const signals = new Map<string, AbortSignal>();
  const results = new Map<string, ReturnType<typeof deferred<AccountSummary>>>();
  const pool = new TradingAccountDataPool({
    summary: (id, signal) => { signals.set(id, signal!); const d = deferred<AccountSummary>(); results.set(id, d); return d.promise; },
    trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
  });
  const a = pool.account("a"), b = pool.account("b");
  const releaseA = a.retain(), releaseB = b.retain();
  const aRead = a.refresh(), bRead = b.refresh();
  await Promise.resolve();
  releaseA();
  assert.equal(signals.get("a")!.aborted, true);
  assert.equal(signals.get("b")!.aborted, false);
  results.get("a")!.resolve(summary("a")); results.get("b")!.resolve(summary("b"));
  try {
    await Promise.all([aRead, bRead]);
    assert.equal(a.getSnapshot().summary, null);
    assert.equal(b.getSnapshot().summary?.account.id, "b");
  } finally { releaseB(); }
});

test("a transport ignoring abort cannot replace a reopened account's newer data", async () => {
  const results: ReturnType<typeof deferred<AccountSummary>>[] = [];
  const pool = new TradingAccountDataPool({
    summary: () => { const d = deferred<AccountSummary>(); results.push(d); return d.promise; },
    trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
  });
  const a = pool.account("a"); const releaseOld = a.retain(); const old = a.refresh(); await Promise.resolve();
  releaseOld(); const releaseNew = a.retain(); const current = a.refresh(); await Promise.resolve();
  try {
    const newer = summary("a"); results[1]!.resolve(newer); await current;
    results[0]!.resolve(summary("a")); await old;
    assert.equal(a.getSnapshot().summary, newer);
    assert.equal(a.getSnapshot().loading, false);
  } finally { releaseNew(); }
});

test("mismatched account data never becomes visible and synchronous failures are contained", async () => {
  for (const throws of [false, true]) {
    const pool = new TradingAccountDataPool({
      summary: () => { if (throws) throw new Error("transport stopped"); return Promise.resolve(summary("other")); },
      trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
    });
    const a = pool.account("a"), release = a.retain();
    try {
      await a.refresh();
      assert.equal(a.getSnapshot().summary, null);
      assert.match(a.getSnapshot().error!, throws ? /transport stopped/ : /read owner/);
    } finally { release(); }
  }
});

test("refresh after a write waits for the older read then starts a fresh read", async () => {
  const old = deferred<AccountSummary>();
  let calls = 0;
  const fresh = summary("a");
  const pool = new TradingAccountDataPool({
    summary: () => ++calls === 1 ? old.promise : Promise.resolve(fresh),
    trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
  });
  const data = pool.account("a"), release = data.retain();
  try {
    await Promise.resolve();
    const refreshed = data.refreshAfterPending();
    assert.equal(calls, 1);
    old.resolve(summary("a"));
    await refreshed;
    assert.equal(calls, 2);
    assert.equal(data.getSnapshot().summary, fresh);
  } finally { release(); }
});

test("pending refresh after a write cannot revive a released account", async () => {
  const old = deferred<AccountSummary>();
  let calls = 0;
  const pool = new TradingAccountDataPool({
    summary: () => { calls++; return old.promise; },
    trades: async () => ({ trades: [] }), journal: async () => ({ entries: [] }),
  });
  const data = pool.account("a"), release = data.retain();
  await Promise.resolve();
  const refreshed = data.refreshAfterPending();
  release(); old.resolve(summary("a")); await refreshed;
  assert.equal(calls, 1);
  assert.equal(data.getSnapshot().summary, null);
});
