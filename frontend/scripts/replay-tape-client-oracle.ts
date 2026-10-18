import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { IndicatorComputeBatchJob } from "../src/features/indicators/indicatorTypes.js";
import { SeriesWindowStore } from "../src/features/market-data/window/seriesWindowStore.js";
import { ReplayCanonicalIndicators, type ReplayCanonicalBinding } from "../src/features/replay/replayCanonicalIndicators.js";
import type { ReplayHistoryIdentity } from "../src/features/replay/replayHistoryProvider.js";
import { ReplayReviewHistory } from "../src/features/replay/replayReviewHistory.js";
import { replayDisplayBarToKline } from "../src/features/replay/replaySeriesProjection.js";
import { ReplayTapeHistoryProvider } from "../src/features/replay/replayTapeHistoryProvider.js";
import type { ReplayTapeViewerObservation } from "../src/features/replay/replayTapeViewer.js";
import { ReplayChartProjection } from "../src/features/replay/replayChartProjection.js";
import type { ReplayRuntimeLifecycle } from "../src/features/replay/useReplayRuntime.js";
import { structuralMock } from "../src/test/testHelpers.js";
import type { ReplayDigest, ReplayDisplayBar } from "../src/features/replay/replayTypes.js";

type Case = { sessionId: string; identity: ReplayHistoryIdentity;
  request: { source_sequence: number; revealed_boundary_ms: number; data_epoch: ReplayDigest; track_id: string;
    history_epoch: ReplayDigest; name: string; params: Record<string, number>; bars: ReplayDisplayBar[] };
  expected: [string, unknown[]][] };
const input = JSON.parse(readFileSync(process.argv[2]!, "utf8")) as { origin: string; cases: Case[] };
let tapeGets = 0, posts = 0, reviewRows = 0, displayCommits = 0;
for (const item of input.cases) {
  const request = item.request;
  const transport: typeof fetch = async (url, init) => {
    const target = new URL(String(url), input.origin);
    if (target.pathname.endsWith("/tape-projection")) tapeGets++;
    else {
      assert.ok(target.pathname.endsWith("/indicator-compute"), `legacy endpoint used: ${target}`);
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      assert.equal(body.source_sequence, request.source_sequence);
      assert.equal(body.history_epoch, request.history_epoch);
      posts++;
    }
    return fetch(target, init);
  };
  const binding: ReplayCanonicalBinding = { sessionId: item.sessionId, trackId: request.track_id,
    identity: item.identity, dataEpoch: request.data_epoch, sourceSequence: request.source_sequence,
    revealedBoundaryMs: request.revealed_boundary_ms };
  const provider = new ReplayTapeHistoryProvider({ ...binding, fetcher: transport, apiBase: input.origin });
  let store = new SeriesWindowStore({ maxBars: 20000 });
  let hasMore = true, error: string | null = null;
  const review = new ReplayReviewHistory(store, provider, request.data_epoch, request.revealed_boundary_ms,
    state => { hasMore = state.hasMore; error = state.error; });
  await review.initialize("http-tape-client");
  assert.ok(store.barCount > 0 && store.barCount <= 500);
  const selectedTail = store.last();
  for (let page = 0; hasMore && page < 20; page++) {
    await review.loadMoreLeft();
    assert.equal(error, null);
  }
  assert.equal(hasMore, false); assert.deepEqual(store.last(), selectedTail);
  reviewRows += store.barCount;
  assert.equal(provider.historyEpoch, request.history_epoch);
  const source = new ReplayCanonicalIndicators(store, () => ({ ...binding, historyEpoch: provider.historyEpoch! }),
    () => {}, transport);
  const job = (): IndicatorComputeBatchJob => ({ clientId: "rsi", jobKey: `rsi-${store.version}`,
    request: { mode: "builtin", name: request.name, params: request.params, exchange: item.identity.exchange,
      marketType: item.identity.market_type, symbol: item.identity.symbol, interval: item.identity.display_interval,
      ohlcv: request.bars.map(row => ({ time: row.open_time_ms / 1000, open: Number(row.open), high: Number(row.high),
        low: Number(row.low), close: Number(row.close), volume: Number(row.volume), is_closed: row.is_closed })) } });
  const check = async (client: ReplayCanonicalIndicators) => {
    const result = await client.compute({ jobs: [job()] });
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.deepEqual(result.results[0]!.payload.lines?.map(line => [line.name, line.data]), item.expected);
  };
  await check(source);
  // The training view starts with a live projection and must first migrate its
  // prices and metadata to the same tape generation used by the review.
  store.replace(request.bars.map(replayDisplayBarToKline));
  const training = new ReplayCanonicalIndicators(store, () => binding, () => {}, transport);
  await assert.rejects(training.compute({ jobs: [job()] }), { name: "AbortError" });
  await check(training);
  const closed = await provider.loadBefore({ beforeMs: request.bars[0]!.open_time_ms,
    dataEpoch: request.data_epoch, revealedBoundaryMs: request.revealed_boundary_ms, limit: 500 });
  assert.ok(closed.bars.every(row => row.is_closed));
  assert.equal(closed.history_epoch, request.history_epoch);
  review.cancel();

  // Production display observer reads an earlier tape prefix, then the selected
  // prefix from the real HTTP service. Its committed source owns the indicator.
  const authority = { generation: 1, sourceSequence: Math.max(0, request.source_sequence - 1),
    virtualTimeMs: request.revealed_boundary_ms };
  let observed: ReplayTapeViewerObservation | null = null;
  const listeners = new Set<() => void>();
  const lifecycle = structuralMock<ReplayRuntimeLifecycle>({
    store: { seriesStore: new SeriesWindowStore({ seriesKey: "http-tape-source" }),
      getAuthoritySnapshot: () => ({ ...authority, sessionId: item.sessionId, hasAuthoritativeSnapshot: true }) },
    getSnapshot: () => ({ store: { ...authority, sessionId: item.sessionId, dataEpoch: request.data_epoch,
      sessionConfig: { ...item.identity, source_kind: "agg_trade" } } }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  });
  const display = new ReplayChartProjection(lifecycle, request.track_id, item.identity.display_interval, undefined, transport);
  store = display.seriesStore;
  const unsubscribe = display.subscribe(() => {
    const value = display.getSnapshot().tapeObservation;
    if (value && value !== observed) {
      observed = value; displayCommits++; authority.sourceSequence = request.source_sequence;
      listeners.forEach(notify => notify());
    }
  });
  const release = display.retain();
  try {
    const deadline = performance.now() + 30000;
    while ((observed as ReplayTapeViewerObservation | null)?.sourceSequence !== request.source_sequence) {
      if (display.getSnapshot().error) throw new Error(String(display.getSnapshot().error));
      assert.ok(performance.now() < deadline, "real HTTP display observer did not reach the selected source");
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    const current = observed as unknown as ReplayTapeViewerObservation;
    assert.equal(current.historyEpoch, request.history_epoch);
    const live = new ReplayCanonicalIndicators(store, () => ({ ...binding, sourceSequence: current.sourceSequence,
      revealedBoundaryMs: current.virtualTimeMs, historyEpoch: current.historyEpoch }), () => {}, transport);
    await check(live);
  } finally { release(); unsubscribe(); }
}
console.log(JSON.stringify({ status: "PASS", comparisons: input.cases.length * 3, tapeGets, posts, reviewRows, displayCommits }));
