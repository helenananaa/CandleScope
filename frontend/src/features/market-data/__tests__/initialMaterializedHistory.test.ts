import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { useChartInitialLoad, type UseChartInitialLoadOptions } from "../useChartInitialLoad.js";
import type { KlineApi, KlineFetchResult, KlineHistoryRequestOptions } from "../klineContracts.js";
import type { KlineBar } from "../marketDataTypes.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT", interval: "10007m" };
const ready: KlineFetchResult = {
  data: [{ time: epochSeconds(600420), open: 1, high: 2, low: 1, close: 2, volume: 3, is_closed: true }],
  source: "storage", complete: true, retryable: false, history_state: "ready",
  all_rows_final: true, verified_contiguous: true, has_tail_gap: false, missing_ranges: [],
};

function harness(response: () => Promise<KlineFetchResult>, interval = "10007m") {
  const activeSeries = { ...series, interval };
  const calls: KlineHistoryRequestOptions[] = [];
  const commits: KlineBar[][] = [];
  const errors: unknown[] = [];
  const pending: unknown[] = [];
  let markStarted!: () => void;
  const started = new Promise<void>(resolve => { markStarted = resolve; });
  let load!: ReturnType<typeof useChartInitialLoad>;
  const forbidden = async (): Promise<KlineFetchResult> => {
    throw new Error("an unbudgeted probe must not fall through to another request");
  };
  const api: KlineApi = {
    fetchKlinesHistory: async (_symbol, _interval, _days, _market, _exchange, options) => {
      calls.push(options);
      markStarted();
      return response();
    },
    fetchKlinesBefore: forbidden, fetchKlinesRange: forbidden, fetchLatestKlines: forbidden,
    getMultiStreamUrl: () => { throw new Error("no stream in history probe"); },
  };
  const feed = new SeriesDataFeed({ api, getActiveSeries: () => activeSeries,
    commitMergedChartData: (_symbol, _interval, rows) => { commits.push(rows); },
  });
  if (interval === "10007m") {
    feed.repairVisibleGaps = async () => { throw new Error("probe must not admit gap repair"); };
  }
  const noop = () => {};
  const options: UseChartInitialLoadOptions = {
    enabled: true, exchange: "binance", marketType: "futures",
    nativeIntervalValues: ["1m", "3m", "5m", "15m", "30m", "1h", "1d"],
    getFromCache: () => [], seriesDataFeed: feed,
    activateCachedChartData: () => null, detachActiveChartData: noop,
    replaceChartData: noop, markChartDataTransition: noop,
    commitMergedChartData: (_symbol, _interval, rows) => { commits.push(rows); },
    commitPatchedChartData: noop, pendingInitialHistoryRef: { current: null },
    setInitialHistoryPending: value => { pending.push(value); },
    updateLastPrice: noop, setConnectionStatus: noop, setLoading: noop,
    setError: value => { errors.push(value); }, setLoadingMoreLeft: noop,
    setHasMoreLeft: noop, setCrosshairData: noop, setDataSource: noop,
  };
  function Host() {
    // This single SSR render exposes the callback to the test; it does not
    // drive component state or any rendered output.
    // eslint-disable-next-line react-hooks/globals
    load = useChartInitialLoad(options);
    return null;
  }
  // Exercise the real hook callback and feed without mounting a desktop app.
  renderToString(createElement(Host));
  return { calls, commits, errors, pending, feed, load, started };
}

for (const interval of ["45m", "90m", "2d", "4d", "5d"]) {
  test(`${interval} initial hook requests the small first stage through the real feed`, async () => {
    const h = harness(async () => ready, interval);
    await h.load("BTCUSDT", interval);
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0]?.countBack, 128);
    assert.notEqual(h.calls[0]?.materializedOnly, true);
    assert.deepEqual(h.commits.filter(rows => rows.length > 0), [ready.data]);
    assert.equal(h.pending.at(-1), false);
  });
}

test("over-budget initial history paints a trusted stored target using one read-only probe", async () => {
  const h = harness(async () => ready);
  await h.load("BTCUSDT", "10007m");
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0]?.materializedOnly, true);
  assert.equal(h.calls[0]?.countBack, 500);
  assert.equal(h.calls[0]?.maxWaitMs, 0);
  assert.deepEqual(h.commits, [ready.data]);
  assert.equal(h.pending.at(-1), false);
  assert.equal(h.errors.some(error => error instanceof Error), false);
});

for (const [name, result] of Object.entries({
  empty: { ...ready, data: [], complete: false, history_state: "pending" as const, retryable: true },
  gap: { ...ready, complete: false, missing_ranges: [{ start_ms: 0, end_ms: 1 }] },
  untrusted: { ...ready, all_rows_final: false },
})) {
  test(`over-budget ${name} probe does not commit or retry base history`, async () => {
    const h = harness(async () => result);
    await h.load("BTCUSDT", "10007m");
    assert.equal(h.calls.length, 1);
    assert.deepEqual(h.commits, []);
    assert.equal(h.pending.at(-1), false);
    assert.ok(h.errors.at(-1) instanceof Error);
  });
}

test("a superseded materialized result never publishes into the next generation", async () => {
  let resolve!: (result: KlineFetchResult) => void;
  const h = harness(() => new Promise(done => { resolve = done; }));
  const work = h.load("BTCUSDT", "10007m");
  // Wait for the observable transport boundary, not a timing delay.
  await h.started;
  h.feed.beginEpoch(series);
  resolve(ready);
  await work;
  assert.deepEqual(h.commits, []);
  assert.equal(h.errors.some(error => error instanceof Error), false);
});
