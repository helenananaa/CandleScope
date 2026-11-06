import assert from "node:assert/strict";
import test from "node:test";
import { sharesReplayMarketScope } from "../replayMarketScope.js";

test("imported BAR watchlists preserve independent source IDs without admitting online venues", () => {
  const config = { exchange: "local-" + "a".repeat(32), market_type: "local_bar", source_kind: "bar" };
  const second = { exchange: "local-" + "b".repeat(32), market_type: "local_bar" };
  assert.equal(sharesReplayMarketScope(config, second), true);
  for (const rejected of [{ exchange: "binance", market_type: "local_bar" }, { ...second, market_type: "spot" }, { ...second, exchange: "local-not-a-dataset" }])
    assert.equal(sharesReplayMarketScope(config, rejected), false);
  assert.equal(sharesReplayMarketScope({ ...config, source_kind: "agg_trade" }, second), false);
  assert.equal(sharesReplayMarketScope({ exchange: "binance", market_type: "spot", source_kind: "bar" }, { exchange: "okx", market_type: "spot" }), false);
});
