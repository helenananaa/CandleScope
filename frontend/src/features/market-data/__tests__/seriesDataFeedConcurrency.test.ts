import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { SharedKlineRequestCoordinator } from "../feed/sharedKlineRequestCoordinator.js";
import { ChartWorkScheduler } from "../chartWorkScheduler.js";
import { defaultKlineApi } from "../feed/klineApi.js";
import { MarketDataWorkspaceProvider } from "../MarketDataWorkspaceProvider.js";
import { MarketDataWorkspaceContext, type MarketDataWorkspaceResources } from "../marketDataWorkspaceContext.js";
import { finalizeMarketDataWorkspaceResources } from "../marketDataWorkspaceLifecycle.js";
import type { FeedCommitMode, KlineApi, KlineFetchResult } from "../klineContracts.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const result: KlineFetchResult = { data: [{ time: epochSeconds(60), close: 2 }] };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const turn = () => new Promise<void>((resolve) => setImmediate(resolve));
const aborted = (error: unknown) => (error as Error).name === "AbortError";
function harness(shared = false, scheduler?: ChartWorkScheduler) {
  const work = deferred<KlineFetchResult>();
  const signals: AbortSignal[] = [];
  const commits: string[] = [];
  const run = (...args: unknown[]) => {
    const signal = (args.at(-1) as { signal: AbortSignal }).signal;
    signals.push(signal);
    return work.promise;
  };
  const api: KlineApi = {
    fetchKlinesHistory: run, fetchKlinesBefore: run, fetchKlinesRange: run,
    fetchLatestKlines: run, getMultiStreamUrl: () => "ws://test",
  };
  const transport = shared ? new SharedKlineRequestCoordinator(api) : api;
  const feed = new SeriesDataFeed({
    api: transport, getActiveSeries: () => series,
    commitMergedChartData: (_s, _i, _rows, meta) => { commits.push(meta?.source || "merge"); },
    commitPatchedChartData: (_s, _i, _rows, meta) => { commits.push(meta?.source || "patch"); },
    ...(scheduler ? { chartWorkScheduler: scheduler, chartWorkSchedulerCellId: "cell-a" } : {}),
  });
  return { work, signals, commits, feed, api, transport };
}

type ReadOptions = { signal?: AbortSignal; commit?: FeedCommitMode; source?: string };
const readers = {
  history: (feed: SeriesDataFeed, options: ReadOptions) => feed.getHistory(series, options),
  before: (feed: SeriesDataFeed, options: ReadOptions) => feed.getBefore(series, { before: epochSeconds(120), ...options }),
  range: (feed: SeriesDataFeed, options: ReadOptions) => feed.getRange(series, { start: 60, end: 120, ...options }),
  latest: (feed: SeriesDataFeed, options: ReadOptions) => feed.getLatest(series, options),
};

for (const [kind, read] of Object.entries(readers)) {
  for (const shared of [false, true]) {
    test(`${kind}: ${shared ? "workspace" : "raw adapter"} callers share transport but retain commit choices`, async () => {
      const h = harness(shared);
      const snapshot = read(h.feed, { commit: "none" });
      const active = read(h.feed, { commit: "active" });
      await turn();
      assert.equal(h.signals.length, 1);
      h.work.resolve(result);
      assert.equal((await snapshot).committed, false);
      assert.equal((await active).committed, true);
      assert.equal(h.commits.length, 1);
    });
  }

  for (const cancelFirst of [false, true]) {
    test(`${kind}: cancelling ${cancelFirst ? "first" : "second"} caller leaves its peer alive`, async () => {
      const h = harness(true);
      const a = new AbortController();
      const b = new AbortController();
      const first = read(h.feed, { signal: a.signal, commit: "active" });
      const second = read(h.feed, { signal: b.signal, commit: "none" });
      const failure = assert.rejects(cancelFirst ? first : second, aborted);
      await turn();
      (cancelFirst ? a : b).abort();
      h.work.resolve(result);
      await failure;
      const surviving = await (cancelFirst ? second : first);
      assert.equal(surviving.committed, !cancelFirst);
      assert.equal(h.signals.length, 1);
      assert.equal(h.signals[0]?.aborted, false);
    });
  }
}

test("scheduler admission cannot split simultaneous identical reads into serial HTTP requests", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  const h = harness(true, scheduler);
  const first = h.feed.getHistory(series, { commit: "none" });
  const second = h.feed.getHistory(series, { commit: "active" });
  await turn();
  h.work.resolve(result);
  const outcomes = await Promise.all([first, second]);
  assert.deepEqual(outcomes.map((r) => r.committed), [false, true]);
  assert.equal(h.signals.length, 1);
  scheduler.dispose();
});

test("all owners abort promptly and a new caller starts a fresh physical request", async () => {
  const h = harness(true);
  const a = new AbortController();
  const b = new AbortController();
  const first = h.feed.getHistory(series, { signal: a.signal });
  const second = h.feed.getHistory(series, { signal: b.signal });
  const failures = Promise.all([assert.rejects(first, aborted), assert.rejects(second, aborted)]);
  await turn();
  a.abort(); b.abort();
  await failures;
  assert.equal(h.signals[0]?.aborted, true);
  const third = h.feed.getHistory(series);
  await turn();
  assert.equal(h.signals.length, 2);
  h.work.resolve(result);
  await third;
  assert.equal(h.commits.length, 1);
});

for (const departure of ["abort", "unregister"] as const) {
  test(`queued sponsor ${departure} transfers scheduling to another Cell`, async () => {
    const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
    const blocker = deferred<void>();
    const blocking = scheduler.run("blocker", "initial-history", () => blocker.promise);
    const h = harness(true, scheduler);
    const peerCommits: number[] = [];
    const peer = new SeriesDataFeed({ api: h.transport, getActiveSeries: () => series,
      chartWorkScheduler: scheduler, chartWorkSchedulerCellId: "cell-b",
      commitMergedChartData: () => { peerCommits.push(1); } });
    const controller = new AbortController();
    const first = h.feed.getHistory(series, { signal: controller.signal });
    const second = peer.getHistory(series);
    const failure = assert.rejects(first, departure === "abort" ? aborted : /unregistered/);
    try {
      await turn();
      assert.equal(h.signals.length, 0);
      if (departure === "abort") controller.abort();
      else scheduler.unregisterCell("cell-a");
      await failure;
      await turn();
      assert.equal(scheduler.diagnostics().pendingAsync, 1);
      assert.equal(scheduler.diagnostics().cells.find((c) => c.cellId === "cell-b")?.pending["load-more"], 1);
      blocker.resolve();
      await blocking;
      await turn();
      assert.equal(h.signals.length, 1);
      h.work.resolve(result);
      assert.equal((await second).committed, true);
      assert.deepEqual(peerCommits, [1]);
      assert.deepEqual(h.commits, []);
    } finally {
      blocker.resolve(); h.work.resolve(result); scheduler.dispose();
    }
  });
}

test("a foreground join promotes queued preload without rejecting its original owner", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  const blocker = deferred<void>();
  const blocking = scheduler.run("blocker", "initial-history", () => blocker.promise);
  const h = harness(true, scheduler);
  const preload = h.feed.getHistory(series, { priority: "preload", commit: "none" });
  await turn();
  assert.equal(scheduler.diagnostics().cells.find((c) => c.cellId === "cell-a")?.pending.prefetch, 1);
  const foreground = h.feed.getHistory(series, { source: "initial-history", commit: "active" });
  await turn();
  assert.equal(scheduler.diagnostics().pendingAsync, 1);
  assert.equal(scheduler.diagnostics().cells.find((c) => c.cellId === "cell-a")?.pending["initial-history"], 1);
  blocker.resolve(); await blocking; await turn();
  h.work.resolve(result);
  assert.deepEqual((await Promise.all([preload, foreground])).map((r) => r.committed), [false, true]);
  assert.equal(h.signals.length, 1);
  scheduler.dispose();
});

test("aborting all queued callers removes admission before any physical fetch", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  const blocker = deferred<void>();
  const blocking = scheduler.run("blocker", "initial-history", () => blocker.promise);
  const h = harness(true, scheduler);
  const a = new AbortController();
  const b = new AbortController();
  const failures = Promise.all([
    assert.rejects(h.feed.getHistory(series, { signal: a.signal }), aborted),
    assert.rejects(h.feed.getHistory(series, { signal: b.signal }), aborted),
  ]);
  await turn();
  a.abort(); b.abort();
  await failures; await turn();
  assert.equal(scheduler.diagnostics().pendingAsync, 0);
  blocker.resolve(); await blocking; await turn();
  assert.equal(h.signals.length, 0);
  scheduler.dispose();
});

test("shared raw adapter retains per-Cell epoch and realtime reconciliation", async () => {
  const h = harness();
  const commits: number[] = [];
  const peer = new SeriesDataFeed({ api: h.api, getActiveSeries: () => series,
    commitMergedChartData: (_s, _i, rows) => { commits.push(rows[0]!.close!); } });
  const stale = h.feed.getHistory(series);
  const current = peer.getHistory(series);
  await turn();
  assert.equal(h.signals.length, 1);
  h.feed.beginEpoch(series);
  peer.recordRealtimeRows(series, [{ time: epochSeconds(60), close: 7, is_closed: true }]);
  h.work.resolve(result);
  assert.equal((await stale).stale, true);
  assert.equal((await current).stale, false);
  assert.deepEqual(commits, [7]);
  assert.deepEqual(h.commits, []);
});

test("shared range pages retain caller-specific page limits and indicator owners", async () => {
  const h = harness();
  let calls = 0;
  const owners: string[] = [];
  h.api.fetchKlinesRange = async () => {
    calls += 1;
    return calls === 1 ? h.work.promise : { data: [{ time: epochSeconds(60), close: 1 }], complete: true };
  };
  h.feed.configure({ commitMergedChartData: (_s, _i, _rows, meta) => { owners.push(meta?.indicatorWindowOwner || ""); } });
  const capped = h.feed.getRange(series, { start: 60, end: 180, maxPages: 1, indicatorWindowOwner: "one" });
  const complete = h.feed.getRange(series, { start: 60, end: 180, maxPages: 2, indicatorWindowOwner: "two" });
  await turn();
  h.work.resolve({ data: [{ time: epochSeconds(180), close: 3 }], truncated: true, next_end_ms: 120_000 });
  assert.equal((await capped).pageCount, 1);
  assert.equal((await complete).pageCount, 2);
  assert.equal(calls, 2);
  assert.deepEqual(owners, ["one", "two", "two"]);
});

test("one commit failure does not reject another caller's result", async () => {
  const h = harness();
  h.feed.configure({ commitMergedChartData: () => { throw new Error("bad owner"); } });
  const failure = assert.rejects(h.feed.getHistory(series, { commit: "active" }), /bad owner/);
  const snapshot = h.feed.getHistory(series, { commit: "none" });
  await turn(); h.work.resolve(result);
  await failure;
  assert.equal((await snapshot).committed, false);
  assert.equal(h.signals.length, 1);
});

test("a pre-aborted logical read never starts HTTP work", async () => {
  const h = harness();
  const controller = new AbortController(); controller.abort();
  await assert.rejects(h.feed.getHistory(series, { signal: controller.signal }), aborted);
  await turn();
  assert.equal(h.signals.length, 0);
});

test("production HTTP adapter dedupes fetch and keeps abort, source and commit local", async (t) => {
  const work = deferred<Response>();
  const calls: Array<{ url: string; signal: AbortSignal | null | undefined }> = [];
  t.mock.method(globalThis, "fetch", (url: string, options?: RequestInit) => {
    calls.push({ url: String(url), signal: options?.signal });
    return work.promise;
  });
  const commits: string[] = [];
  const feed = new SeriesDataFeed({ api: defaultKlineApi, getActiveSeries: () => series,
    commitMergedChartData: (_s, _i, _rows, meta) => { commits.push(meta?.source || ""); } });
  const abort = new AbortController();
  const first = feed.getHistory(series, { countBack: 1, commit: "none", signal: abort.signal });
  const second = feed.getHistory(series, { countBack: 1, commit: "active", source: "visible-owner" });
  const failure = assert.rejects(first, aborted);
  await turn(); abort.abort(); await failure;
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.signal?.aborted, false);
  assert.match(calls[0]!.url, /count_back=1/);
  assert.doesNotMatch(calls[0]!.url, /clientContext|visible-owner|epoch|schedule/);
  work.resolve(new Response(JSON.stringify({ data: [{ time: 60, open: 1, high: 3, low: 1, close: 2, volume: 5, is_closed: true }] })));
  assert.equal((await second).committed, true);
  assert.deepEqual(commits, ["visible-owner"]);
});

for (const brokerEnabled of [true, false]) {
  test(`production workspace injection retains shared HTTP ownership with broker=${brokerEnabled}`, async (t) => {
    const location = Object.getOwnPropertyDescriptor(globalThis, "location");
    Object.defineProperty(globalThis, "location", { value: { host: "example.test", protocol: "http:" }, configurable: true });
    t.after(() => {
      if (location) Object.defineProperty(globalThis, "location", location);
      else Reflect.deleteProperty(globalThis, "location");
    });
    const capture = t.mock.fn((value: MarketDataWorkspaceResources | null) => Boolean(value));
    renderToStaticMarkup(createElement(MarketDataWorkspaceProvider, { brokerEnabled, batchStreamEnabled: false },
      createElement(MarketDataWorkspaceContext.Consumer, { children: capture })));
    const resources = capture.mock.calls[0]?.arguments[0];
    assert.ok(resources);
    t.after(() => finalizeMarketDataWorkspaceResources(resources));
    const work = deferred<Response>();
    let calls = 0;
    t.mock.method(globalThis, "fetch", () => { calls += 1; return work.promise; });
    const first = new SeriesDataFeed({ api: resources.klineApi, chartWorkScheduler: resources.workScheduler,
      chartWorkSchedulerCellId: "a", getActiveSeries: () => series });
    const second = new SeriesDataFeed({ api: resources.klineApi, chartWorkScheduler: resources.workScheduler,
      chartWorkSchedulerCellId: "b", getActiveSeries: () => series });
    const reads = [first.getHistory(series), second.getHistory(series)];
    await turn();
    assert.equal(calls, 1);
    assert.equal(resources.requestCoordinator?.diagnostics().logicalInflight, 2);
    work.resolve(new Response(JSON.stringify({ data: [] })));
    await Promise.all(reads);
    assert.equal(resources.requestCoordinator?.diagnostics().totalPhysical, 1);
  });
}

test("workspace shutdown rejects queued consumers and retracts physical admission", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  const blocker = deferred<void>();
  const blocking = scheduler.run("blocker", "initial-history", () => blocker.promise);
  const h = harness(true, scheduler);
  const failures = Promise.all([
    assert.rejects(h.feed.getHistory(series), aborted),
    assert.rejects(h.feed.getHistory(series), aborted),
  ]);
  await turn();
  (h.transport as SharedKlineRequestCoordinator).closeAll();
  await failures; await turn();
  assert.equal(scheduler.diagnostics().pendingAsync, 0);
  assert.equal(h.signals.length, 0);
  blocker.resolve(); await blocking; scheduler.dispose();
});
