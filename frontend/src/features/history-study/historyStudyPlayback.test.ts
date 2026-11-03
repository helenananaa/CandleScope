import assert from "node:assert/strict";
import test from "node:test";
import { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { HistoryStudy } from "./historyStudyTypes.js";
import { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import { historyStudyOwner } from "./historyStudyOwner.js";

function input(): HistoryStudy {
  return { id: "study-a", capturedAtMs: 1_000_000, inputKind: "captured-market-history",
    series: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "5m" },
    rows: Array.from({ length: 4 }, (_, i) => ({ time: 300 * (i + 1), closeTimeMs: 300_000 * (i + 2),
      open: 10, high: 20 + i, low: 2, close: 15, volume: i, is_closed: true })) };
}

test("owner tuples preserve valid Unicode workspace IDs without route slashes or collisions", () => {
  assert.notEqual(historyStudyOwner("a:b", "c"), historyStudyOwner("a", "b:c"));
  const owner = historyStudyOwner("历史/工作区：甲", "cell-1");
  assert.match(owner, /^[A-Za-z0-9_-]+$/);
  assert.equal(historyStudyOwner("历史/工作区：甲", "cell-1"), owner);
  assert.notEqual(historyStudyOwner("历史/工作区：甲", "cell-2"), owner);
});

test("hidden prefetched candles never enter the reader; rewinds commit before observers run", () => {
  const source = input();
  const a = new HistoryStudyPlayback(source, 750_000), b = new HistoryStudyPlayback(source, 1_200_000);
  assert.deepEqual(a.store.snapshot().map(r => r.time), [300]);
  assert.equal(a.store.snapshot()[0]?.high, 20, "forming 600s candle's final high must be absent");
  assert.equal(a.store.getByTime(600), null);
  const unchanged = a.store.snapshot();
  a.seek(800_000);
  assert.equal(a.store.snapshot(), unchanged, "intrabar time changes do not copy/recommit the prefix");
  a.step(1);
  assert.deepEqual(a.store.snapshot().map(r => r.time), [300, 600]);
  const seen: number[][] = [];
  a.store.subscribe(() => seen.push(a.store.snapshot().map(r => Number(r.time))));
  a.seek(599_999);
  assert.deepEqual(seen, [[]]);
  assert.deepEqual(b.store.snapshot().map(r => r.time), [300, 600, 900]);
  source.rows[0]!.high = 999;
  a.seek(600_000);
  assert.equal(a.store.snapshot()[0]?.high, 20, "saved input is detached from mutable callers");
  assert.throws(() => { a.input.rows[0]!.high = 999; });
});

test("step boundaries and save/reload use close times rather than opening timestamps", () => {
  const a = new HistoryStudyPlayback(input(), 300_000);
  assert.equal(a.store.barCount, 0);
  assert.equal(a.step(1), 600_000);
  assert.equal(a.step(1), 900_000);
  assert.equal(a.step(-1), 600_000);
  a.seek(1_000_000);
  assert.equal(a.step(-1), 900_000);
  const restored = new HistoryStudyPlayback(JSON.parse(JSON.stringify(a.input)) as HistoryStudy, a.cursorMs);
  assert.deepEqual(restored.store.snapshot(), a.store.snapshot());
  assert.throws(() => a.seek(NaN));
  assert.equal(a.seek(Number.MAX_SAFE_INTEGER), a.maximumMs);
});

test("one observer abort does not cancel another; disposed manager rejects late publications", async () => {
  const pending: { signal: AbortSignal; resolve: (value: unknown) => void }[] = [];
  const owner = new HistoryStudyDataManager((_path, options) => new Promise(resolve => pending.push({ signal: options.signal, resolve })));
  const controller = new AbortController();
  const first = owner.read("a", controller.signal), second = owner.read("b");
  controller.abort();
  pending[0]!.resolve({ active: true });
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(pending[1]!.signal.aborted, false);
  owner.dispose();
  pending[1]!.resolve({ active: true });
  await assert.rejects(second, { name: "AbortError" });
  await assert.rejects(owner.read("c"), /closed/);
  assert.deepEqual(owner.diagnostics(), { requests: 0, closed: true });
});
