import assert from "node:assert/strict";
import test from "node:test";
import { parseDiscoveryResult } from "../symbolDiscoveryApi.js";

const fixture = () => ({
  symbols: [{ symbol: "AAPL:XNAS", exchange: "twelvedata", marketType: "stock", seriesKey: "full-series-key",
    providerId: "twelvedata", venue: "XNAS", assetClass: "stock", seriesVariant: "ohlcv", priceAdjustment: "raw", sessionVariant: "regular", volumeSemantics: "shares" }],
  total: 1, revision: "revision-1", nextOffset: null, partial: true,
  sources: [{ id: "twelvedata", status: "ready" }, { id: "okx", status: "not_loaded" }],
  facets: { assetClasses: [{ key: "stock", count: 1 }], markets: [], venues: [], quotes: [] },
});

test("discovery keeps complete provider identity and partial coverage", () => {
  const result = parseDiscoveryResult(fixture());
  assert.equal(result.symbols[0]?._key, "twelvedata:stock:AAPL:XNAS");
  assert.equal(result.symbols[0]?.sessionVariant, "regular");
  assert.equal(result.symbols[0]?.volumeSemantics, "shares");
  assert.equal(result.symbols[0]?.seriesKey, "full-series-key");
  assert.equal(result.partial, true);
  assert.equal(result.sources[1]?.status, "not_loaded");
});

test("malformed discovery cannot silently select a Binance default", () => {
  for (const field of ["exchange", "symbol", "marketType", "seriesKey"]) {
    const value = fixture();
    Reflect.deleteProperty(value.symbols[0]!, field);
    assert.throws(() => parseDiscoveryResult(value), /identity/);
  }
  assert.throws(() => parseDiscoveryResult({ ...fixture(), total: -1 }), /response/);
  assert.throws(() => parseDiscoveryResult({ ...fixture(), nextOffset: 0 }), /response/);
  assert.throws(() => parseDiscoveryResult({ ...fixture(), facets: { ...fixture().facets, quotes: [{ key: "USD", count: NaN }] } }), /facets/);
});
