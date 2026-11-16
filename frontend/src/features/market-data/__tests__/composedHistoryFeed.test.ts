import assert from "node:assert/strict";
import test from "node:test";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { KlineApi, KlineFetchResult } from "../klineContracts.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT", interval: "10007m" };
const empty: KlineFetchResult = { data: [], complete: false, retryable: true, history_state: "pending" };
function harness(contract: string | null | undefined) {
  const calls: { kind: string; contract?: string; materialized?: boolean }[] = [];
  const observe = (kind: string, options: { compositionContract?: string; materializedOnly?: boolean }) => {
    calls.push({ kind, ...(options.compositionContract ? { contract: options.compositionContract } : {}),
      ...(options.materializedOnly === undefined ? {} : { materialized: options.materializedOnly }) });
    return Promise.resolve(empty);
  };
  const api: KlineApi = {
    fetchKlinesHistory: (_s, _i, _d, _m, _e, options) => observe("history", options),
    fetchKlinesBefore: (_s, _i, _b, _n, _m, _e, options) => observe("before", options),
    fetchKlinesRange: (_s, _i, _a, _b, _m, _e, options) => observe("range", options),
    fetchLatestKlines: () => observe("latest", {}), getMultiStreamUrl: () => "ws://example/stream",
  };
  return { calls, feed: new SeriesDataFeed({ api, getActiveSeries: () => series,
    historyCompositionContractFor: () => contract }) };
}

test("the existing feed applies the contract to history, pagination and range recovery", async () => {
  const h = harness("qualified-v1");
  await h.feed.getHistory(series, { countBack: 128, commit: "none" });
  await h.feed.requestBeforePage(series, { before: epochSeconds(1_000_000), bars: 20, commit: "none" });
  await h.feed.getRange(series, { start: epochSeconds(1), end: epochSeconds(10), commit: "none" });
  assert.deepEqual(h.calls.map(call => [call.kind, call.contract]),
    [["history", "qualified-v1"], ["before", "qualified-v1"], ["range", "qualified-v1"]]);
});

test("missing permission allows a stored target probe and blocks source-expanding history outlets", async () => {
  const h = harness(null);
  await h.feed.getHistory(series, { countBack: 128, commit: "none" });
  await assert.rejects(h.feed.getBefore(series, { before: epochSeconds(1_000_000) }));
  await assert.rejects(h.feed.getRange(series, { start: epochSeconds(1), end: epochSeconds(10) }));
  assert.deepEqual(h.calls, [{ kind: "history", materialized: true }]);
});

test("an explicit older contract is not silently upgraded by refreshed capability", async () => {
  const h = harness("qualified-v2");
  await h.feed.getHistory(series, { countBack: 128, compositionContract: "qualified-v1", commit: "none" });
  assert.equal(h.calls[0]?.contract, "qualified-v1");
});
