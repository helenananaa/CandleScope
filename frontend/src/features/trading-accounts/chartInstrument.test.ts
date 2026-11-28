import assert from "node:assert/strict";
import test from "node:test";

import { klineSeriesIdentityField } from "../market-data/klineSeriesIdentity.js";
import { chartInstrumentFields } from "./chartInstrument.js";

const stock = {
  providerId: "twelvedata", venue: "xngs", assetClass: "stock", seriesVariant: "ohlcv",
  priceAdjustment: "raw", sessionVariant: "regular", volumeSemantics: "shares",
};

test("orders from a provider-series chart carry the chart's series", () => {
  const context = {
    exchange: "twelvedata", marketType: "stock", symbol: "AAPL:NASDAQ", interval: "1m", lastPrice: 350,
    ...klineSeriesIdentityField("twelvedata", stock),
  };
  assert.deepEqual(chartInstrumentFields(context), {
    exchange: "twelvedata", marketType: "stock", symbol: "AAPL:NASDAQ",
    identity: {
      provider_id: "twelvedata", venue: "xngs", asset_class: "stock", series_variant: "ohlcv",
      price_adjustment: "raw", session_variant: "regular", volume_semantics: "shares",
    },
  });
});

test("orders from an exchange chart keep their old body", () => {
  const context = {
    exchange: "binance", marketType: "futures", symbol: "BTCUSDT", interval: "1m", lastPrice: 1,
    ...klineSeriesIdentityField("binance", {}),
  };
  assert.deepEqual(chartInstrumentFields(context), { exchange: "binance", marketType: "futures", symbol: "BTCUSDT" });
});
