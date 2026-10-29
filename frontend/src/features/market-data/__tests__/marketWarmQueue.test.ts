import assert from "node:assert/strict";
import test from "node:test";
import { MarketWarmQueue, type MarketWarmQueueOptions, type MarketWarmRequest } from "../manager/marketWarmQueue.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import type { KlineFetchResult } from "../klineContracts.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const request = (patch: Partial<MarketWarmRequest> = {}): MarketWarmRequest => ({
  series, limit: 5, estimatedSourceRows: 5, owner: "hover-a", reason: "hover", ...patch,
});
const turn = () => new Promise<void>(resolve => setImmediate(resolve));
function harness(patch: Partial<MarketWarmQueueOptions> = {}) {
  let now = 0, sequence = 0;
  const timers = new Map<number, { work: () => void; at: number }>();
  const schedule = (work: () => void, delay: number) => {
    const id = ++sequence; timers.set(id, { work, at: now + delay }); return id;
  };
  const cancel = (handle: unknown) => { timers.delete(Number(handle)); };
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0, now: () => now, schedule, cancel });
  const reads: Array<{ request: MarketWarmRequest; signal: AbortSignal; resolve(value: KlineFetchResult): void; reject(error: unknown): void }> = [];
  const queue = new MarketWarmQueue({ gate, now: () => now, schedule, cancel,
    read: (request, signal) => new Promise((resolve, reject) => {
      reads.push({ request, signal, resolve, reject });
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }), ...patch });
  return { queue, gate, reads, timers,
    advance: (ms: number) => {
      now += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.work(); }
    },
    dispose: () => { queue.dispose(); gate.dispose(); },
  };
}

test("two warming owners share one request and cancellation releases only one demand", async t => {
  const h = harness(); t.after(h.dispose);
  const first = h.queue.request(request());
  const second = h.queue.request(request({ owner: "watchlist", reason: "watchlist" }));
  await turn(); assert.equal(h.reads.length, 1);
  first.release(); assert.equal(await first.done, "cancelled");
  assert.equal(h.reads[0]!.signal.aborted, false);
  h.reads[0]!.resolve({ data: [] });
  assert.equal(await second.done, "warmed");
  assert.equal(h.queue.diagnostics().active, 0);
});

test("explicit hover intent can skip background grace but still yields to foreground and active hydration", async t => {
  const gate = new ForegroundPreloadGate({ quietDwellMs: 30_000 });
  let calls = 0;
  const queue = new MarketWarmQueue({ gate, read: async () => { calls += 1; return { data: [] }; } });
  t.after(() => { queue.dispose(); gate.dispose(); });
  const foreground = gate.enterForeground("chart-load");
  const hover = queue.request(request());
  await turn(); assert.equal(calls, 0);
  foreground.release();
  assert.equal(await hover.done, "warmed"); assert.equal(calls, 1);
  const hydrate = gate.tryAcquireHydration("active-chart-history")!;
  const nextHover = queue.request(request({ series: { ...series, interval: "5m" } }));
  await turn(); assert.equal(calls, 1);
  gate.release(hydrate); await nextHover.done; assert.equal(calls, 2);
  const background = queue.request(request({ reason: "watchlist", series: { ...series, interval: "15m" } }));
  await turn(); assert.equal(calls, 2);
  background.release();
});

test("foreground handoff preserves the in-flight admission when hover leaves and another foreground reader aborts", async t => {
  const h = harness(); t.after(h.dispose);
  const warm = h.queue.request(request()); await turn();
  const hold = h.queue.prepareForeground(series);
  const foreground = h.gate.enterForeground("selected-chart");
  warm.release();
  const cancelled = new AbortController();
  const first = h.queue.joinForeground(series, 5, cancelled.signal)!;
  const rejected = assert.rejects(first, { name: "AbortError" });
  const second = h.queue.joinForeground(series, 5)!;
  cancelled.abort(); await rejected;
  assert.equal(h.reads.length, 1);
  assert.equal(h.reads[0]!.signal.aborted, false);
  const response = { data: [], complete: false };
  h.reads[0]!.resolve(response);
  assert.deepEqual(await second, response);
  hold.release(); foreground.release();
  assert.equal(h.queue.diagnostics().promoted, 1);
});

test("queued work cannot bypass the foreground scheduler by being promoted", async t => {
  const h = harness(); t.after(h.dispose);
  const foreground = h.gate.enterForeground("busy-chart");
  const warm = h.queue.request(request());
  const hold = h.queue.prepareForeground(series);
  assert.equal(h.queue.joinForeground(series, 5), null);
  await turn(); assert.equal(h.reads.length, 0);
  hold.release(); warm.release(); foreground.release();
  assert.equal(await warm.done, "cancelled");
  await turn(); assert.equal(h.reads.length, 0);
});

test("foreground preemption resumes a retained warm intent after the gate reopens", async t => {
  const h = harness(); t.after(h.dispose);
  const warm = h.queue.request(request()); await turn();
  const foreground = h.gate.enterForeground("unrelated-chart");
  assert.equal(h.reads[0]!.signal.aborted, true);
  await turn(); assert.equal(h.reads.length, 1);
  foreground.release(); await turn(); assert.equal(h.reads.length, 2);
  h.reads[1]!.resolve({ data: [] });
  assert.equal(await warm.done, "warmed");
});

test("hover priority reconciles the gate FIFO without starving a previously queued watchlist demand", async t => {
  const h = harness(); t.after(h.dispose);
  const foreground = h.gate.enterForeground("busy-chart");
  const watchlist = h.queue.request(request({ reason: "watchlist", owner: "list", series: { ...series, symbol: "ETHUSDT" } }));
  const hover = h.queue.request(request());
  foreground.release(); await turn();
  assert.equal(h.reads[0]!.request.series.symbol, "BTCUSDT");
  h.reads[0]!.resolve({ data: [] }); await hover.done; await turn();
  assert.equal(h.reads[1]!.request.series.symbol, "ETHUSDT");
  h.reads[1]!.resolve({ data: [] }); await watchlist.done;
});

test("queue, input expansion, estimated bytes and rolling source-row limits bound speculative work", async t => {
  const h = harness({ maxPending: 2, sourceRowsPerMinute: 10, maxInflightBytes: 1_000 }); t.after(h.dispose);
  assert.equal(await h.queue.request(request({ limit: 6, estimatedSourceRows: 6 })).done, "budget");
  assert.equal(await h.queue.request(request({ estimatedSourceRows: 11 })).done, "budget");
  const first = h.queue.request(request({ estimatedSourceRows: 10 }));
  const second = h.queue.request(request({ series: { ...series, interval: "5m" } }));
  assert.equal(await h.queue.request(request({ series: { ...series, interval: "15m" } })).done, "budget");
  await turn(); h.reads[0]!.resolve({ data: [] }); await first.done; await turn();
  assert.equal(h.reads.length, 1);
  h.advance(59_999); await turn(); assert.equal(h.reads.length, 1);
  h.advance(1); await turn(); assert.equal(h.reads.length, 2);
  h.reads[1]!.resolve({ data: [] }); await second.done;
});

test("partial results and failures cool down without retaining candle arrays or spinning", async t => {
  const h = harness({ cooldownMs: 1_000 }); t.after(h.dispose);
  const first = h.queue.request(request()); await turn();
  h.reads[0]!.resolve({ data: [], complete: false }); await first.done;
  assert.equal(await h.queue.request(request()).done, "cooldown");
  h.advance(1_000);
  const retry = h.queue.request(request()); await turn();
  h.reads[1]!.reject(new Error("fixture offline"));
  assert.equal(await retry.done, "failed");
  assert.equal(await h.queue.request(request()).done, "cooldown");
  assert.equal(h.reads.length, 2);
});

test("full series identity prevents warm-result handoff across adjustment semantics; disposal cancels all leases", async () => {
  const h = harness();
  const warm = h.queue.request(request()); await turn();
  const hold = h.queue.prepareForeground({ ...series, priceAdjustment: "adjusted" });
  assert.equal(h.queue.joinForeground({ ...series, priceAdjustment: "adjusted" }, 5), null);
  assert.equal(h.queue.diagnostics().promoted, 0);
  hold.release(); h.dispose();
  assert.equal(await warm.done, "cancelled");
  assert.equal(h.reads[0]!.signal.aborted, true);
  assert.equal(h.timers.size, 0);
});
