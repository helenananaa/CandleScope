// Executed by the Python service integration tests against an isolated HTTP server.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SeriesWindowStore } from "../src/features/market-data/window/seriesWindowStore.js";
import { ReplayCanonicalIndicators, type ReplayCanonicalBinding } from "../src/features/replay/replayCanonicalIndicators.js";
import { ReplayHistoryProvider } from "../src/features/replay/replayHistoryProvider.js";
import { ReplayReviewHistory } from "../src/features/replay/replayReviewHistory.js";
import { replayDisplayBarToKline } from "../src/features/replay/replaySeriesProjection.js";
import { ReplayV2ApiClient } from "../src/features/replay/replayV2Api.js";
import type { ReplayDisplayBar } from "../src/features/replay/replayTypes.js";
import { reviewIndicatorBars } from "../src/features/replay/useReplayReviewIndicators.js";

const input = JSON.parse(readFileSync(process.argv[2]!, "utf8")) as {
  origin: string; cases: { binding: ReplayCanonicalBinding; rows?: ReplayDisplayBar[] }[];
};
const requests: { path: string; status: number }[] = [];
const fetcher: typeof fetch = async (url, options) => {
  const absolute = new URL(String(url), input.origin);
  const response = await fetch(absolute, options);
  requests.push({ path: absolute.pathname + absolute.search, status: response.status });
  return response;
};
const api = new ReplayV2ApiClient({ basePath: `${input.origin}/api/v1/replay`, fetcher });
const output = [];
for (const { binding, rows } of input.cases) {
  const store = new SeriesWindowStore({ maxBars: 20_000 });
  let history: ReplayReviewHistory | undefined;
  if (rows) store.replace(rows.map(replayDisplayBarToKline));
  else {
    const provider = new ReplayHistoryProvider({ sessionId: binding.sessionId, trackId: binding.trackId,
      identity: binding.identity, fetcher });
    history = new ReplayReviewHistory(store, provider, binding.dataEpoch, binding.revealedBoundaryMs, () => {},
      api.displayProjectionBySession.bind(api));
    await history.initialize("review-service-probe");
    assert.ok(store.barCount > 0);
  }
  const initial = store.snapshot();
  const canonical = new ReplayCanonicalIndicators(store, () => binding, () => {}, fetcher, api.displayProjectionBySession.bind(api));
  const disconnect = canonical.connect();
  let result;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      result = await canonical.compute({ jobs: [{ clientId: "rsi", jobKey: String(store.version), request: {
        mode: "builtin", name: "RSI", params: { period: 2 }, exchange: binding.identity.exchange,
        marketType: binding.identity.market_type, symbol: binding.identity.symbol, interval: binding.identity.display_interval,
        ohlcv: reviewIndicatorBars(store.snapshot(), "probe", "probe", binding.revealedBoundaryMs).map(row => ({ time: Number(row.time), open: Number(row.open), high: Number(row.high),
          low: Number(row.low), close: Number(row.close), volume: Number(row.volume), is_closed: row.replayClosed !== false })),
      } }] });
      break;
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) throw error;
    }
  }
  assert.equal(result?.ok, true, JSON.stringify({ result, binding, first: store.first(), last: store.last(),
    breaks: store.snapshot().filter((row, i, all) => (i > 0 && Number(row.time) * 1000 <= Number(all[i - 1]!.replayCloseTimeMs))
      || (row.replayClosed === false && i < all.length - 1)) }));
  if (rows) assert.deepEqual({ ...store.last(), replayContextHistory: store.last()?.replayContextHistory === true },
    { ...initial.at(-1), replayContextHistory: initial.at(-1)?.replayContextHistory === true });
  output.push({ identity: binding.identity, initial, final: store.snapshot(), payload: result.results[0]!.payload });
  disconnect(); history?.cancel();
}
console.log(JSON.stringify({ output, requests }));
