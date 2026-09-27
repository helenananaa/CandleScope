import assert from "node:assert/strict";
import test from "node:test";
import { ReplayChartProjection } from "../replayChartProjection.js";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import type { ReplayRuntimeLifecycle } from "../useReplayRuntime.js";
import type { ReplayDisplayProjectionResponse } from "../replayDisplayProjection.js";

const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

test("same-market cells keep independent history windows while following one source", async () => {
  const listeners = new Set<() => void>();
  const bar = (time: number) => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 1 });
  const source = new SeriesWindowStore({ intervalSeconds: 60, seriesKey: "replay-test" });
  source.replace([bar(600), bar(660)]);
  let store = { sessionConfig: { source_kind: "bar", base_interval: "1m", symbol: "BTCUSDT", exchange: "binance", market_type: "spot" },
    virtualTimeMs: 720_000, dataEpoch: "epoch", sessionId: "session", generation: 1 };
  const lifecycle = { store: { seriesStore: source }, getSnapshot: () => ({ store }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
  } as unknown as ReplayRuntimeLifecycle;
  const past = new ReplayChartProjection(lifecycle, "track-1", "1m");
  const latest = new ReplayChartProjection(lifecycle, "track-1", "1m");
  const releasePast = past.retain();
  const releaseLatest = latest.retain();
  past.seriesStore.maxBars = 2;
  past.seriesStore.applyRange([bar(300), bar(360)]);
  assert.equal(past.seriesStore.rightTruncated, true);
  const historical = past.seriesStore.snapshot();
  source.applyRange([bar(720)]);
  store = { ...store, virtualTimeMs: 780_000 };
  listeners.forEach((notify) => notify()); await settle();
  assert.deepEqual(past.seriesStore.snapshot(), historical);
  assert.equal(latest.seriesStore.snapshot().at(-1)?.time, 720);
  releasePast(); releaseLatest();
});

test("shared coarse charts serialize requests, invalidate old epochs and release independently", async () => {
  let notify = () => {};
  let store = { sessionConfig: { source_kind: "bar", base_interval: "1m", symbol: "BTCUSDT", exchange: "binance", market_type: "spot" },
    virtualTimeMs: 100_000, dataEpoch: "epoch-1", sessionId: "session", generation: 1 };
  const source = new SeriesWindowStore();
  const lifecycle = { store: { seriesStore: source }, getSnapshot: () => ({ store }),
    subscribe: (listener: () => void) => { notify = listener; return () => { notify = () => {}; }; },
  } as unknown as ReplayRuntimeLifecycle;
  const requests: { signal?: AbortSignal; resolve: (value: ReplayDisplayProjectionResponse) => void; reject: (error: Error) => void }[] = [];
  const projection = new ReplayChartProjection(lifecycle, "track-1", "15m", {
    displayProjectionBySession: (_session, _binding, signal) => new Promise((resolve, reject) => {
      requests.push({ ...(signal ? { signal } : {}), resolve, reject });
    }),
  });
  const releaseA = projection.retain();
  const releaseB = projection.retain();
  assert.equal(requests.length, 1);
  store = { ...store, virtualTimeMs: 101_000 };
  notify(); await settle();
  assert.equal(requests.length, 1, "fast clock does not abort/starve the in-flight request");
  releaseA(); releaseA();
  assert.equal(requests[0]!.signal?.aborted, false);
  store = { ...store, generation: 2, dataEpoch: "epoch-2" };
  notify(); await settle();
  assert.equal(requests[0]!.signal?.aborted, true);
  assert.equal(requests.length, 2);
  requests[0]!.resolve({} as ReplayDisplayProjectionResponse);
  await settle();
  assert.equal(projection.getSnapshot().error, null, "obsolete data is ignored before decoding");
  assert.equal(projection.seriesStore.barCount, 0);
  requests[1]!.reject(new Error("history offline")); await settle();
  assert.equal(projection.getSnapshot().error, "history offline");
  projection.retry();
  assert.equal(requests.length, 3, "paused charts can explicitly recover without a new clock tick");
  releaseB();
  assert.equal(requests[2]!.signal?.aborted, true);
});
