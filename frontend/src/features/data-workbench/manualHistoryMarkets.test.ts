import assert from "node:assert/strict";
import test from "node:test";
import { buildExchangeCatalog } from "../chart-session/exchangeCatalogRuntime.js";
import { manualHistoryExchanges, manualHistoryMarkets } from "./manualHistoryMarkets.js";

test("download choices follow historical kline capabilities including generic derivatives", () => {
  const catalog = buildExchangeCatalog([
    { exchange: "bitget", name: "Bitget", native_intervals: ["1m"], protocol_features: [], limits: {}, known_limitations: [],
      markets: ["spot", "swap.linear", "swap.inverse", "option"].map((market_type) => ({ market_type, product_type: market_type, label: market_type })),
      channels: [{ channel: "kline", market_types: ["spot", "swap.linear", "swap.inverse"], realtime: true, history: true, params: {} }] },
    { exchange: "ticker-only", name: "Ticker", native_intervals: [], protocol_features: [], limits: {}, known_limitations: [],
      markets: [{ market_type: "spot", product_type: "spot", label: "Spot" }],
      channels: [{ channel: "ticker", market_types: ["spot"], realtime: true, history: false, params: {} }] },
  ]);
  assert.deepEqual(manualHistoryExchanges(catalog).map((entry) => entry.id), ["bitget"]);
  assert.deepEqual(manualHistoryMarkets(catalog, "bitget").map((market) => market.market_type), ["spot", "swap.linear", "swap.inverse"]);
  assert.deepEqual(manualHistoryMarkets(catalog, "unknown"), []);
  assert.deepEqual(manualHistoryExchanges({}), []);
});
