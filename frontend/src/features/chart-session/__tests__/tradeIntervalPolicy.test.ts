import assert from "node:assert/strict";
import test from "node:test";
import { buildExchangeCatalog, getNativeIntervals } from "../exchangeCatalogRuntime.js";
import { canResolveIntervalForSeriesIdentity, hasTradeCandleSource, resolveSupportedInterval } from "../intervalPolicy.js";
import { buildRealtimeTrackedIntervals } from "../trackedIntervalsPolicy.js";
import { getFullSubscriptionIntervals } from "../../watchlist/watchlistSubscriptionPolicy.js";
import { resolveWatchlistFullSubscriptionInputs } from "../../watchlist/watchlistSubscriptionRuntime.js";

const catalog = buildExchangeCatalog([{
  exchange: "kraken", name: "Kraken", markets: [{ market_type: "spot", product_type: "spot", label: "Spot" }],
  native_intervals: ["1m", "5m", "1h"], protocol_features: [], known_limitations: [],
  limits: { "trade_candles.markets": ["spot"] },
}]);

test("trade capability enables fixed periods without advertising native seconds", () => {
  const native = getNativeIntervals("kraken", catalog, "spot", "history");
  assert.deepEqual(native.map((item) => item.value), ["1m", "5m", "1h"]);
  assert.equal(hasTradeCandleSource(catalog, "kraken", "spot"), true);
  assert.equal(hasTradeCandleSource(catalog, "kraken", "futures"), false);
  assert.equal(hasTradeCandleSource(null, "kraken", "spot"), false);
  for (const period of ["1s", "3s", "7s", "61s", "13m", "90m"]) {
    assert.equal(canResolveIntervalForSeriesIdentity("kraken", period, [], undefined, true), true);
  }
  assert.equal(canResolveIntervalForSeriesIdentity("kraken", "1M", [], undefined, true), false);
  assert.equal(canResolveIntervalForSeriesIdentity("kraken", "7s", ["1m"], { venue: "another-venue" }, true), false);
  assert.equal(resolveSupportedInterval({
    exchange: "kraken", marketType: "spot", interval: "7s", exchangeCatalog: catalog,
    savedCustomIntervals: ["7s"], nativeIntervals: native, isNativeIntervalSupported: () => false,
  }), "7s");
  assert.deepEqual(buildRealtimeTrackedIntervals("7s", ["1m"], "1m", true), ["7s", "1m"]);
  assert.deepEqual(buildRealtimeTrackedIntervals("7s", ["1m"]), ["1m"]);
});

test("watchlist includes saved trade periods only for an admitted market", () => {
  const custom = [{ value: "7s", createdAt: 1, lastUsedAt: 1, usageCount: 1, pinned: false, order: 0 }];
  const ready = resolveWatchlistFullSubscriptionInputs("kraken:spot:BTC/USD", catalog, custom, "ready");
  assert.equal(ready.tradeCandlesAvailable, true);
  assert.ok(getFullSubscriptionIntervals(ready).includes("7s"));
  const loading = resolveWatchlistFullSubscriptionInputs("kraken:spot:BTC/USD", catalog, custom, "loading");
  assert.ok(!getFullSubscriptionIntervals(loading).includes("7s"));
});
