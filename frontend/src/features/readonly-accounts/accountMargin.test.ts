import assert from "node:assert/strict";
import test from "node:test";
import { balanceDetails, balanceMargin, positionMargin } from "./accountMargin.js";

test("a cross position reports leverage, liquidation price and margin with their currencies", () => {
  assert.deepEqual(positionMargin({
    marginMode: "cross", leverage: "10", liquidationPrice: "83512.7", priceCurrency: "USDT",
    margin: "110.412", marginCurrency: "USDT", settleCurrency: "USDT", eventTimeMs: 1_709_251_200_000,
  }), {
    marginMode: "cross", leverage: "10", liquidationPrice: "83512.7", priceCurrency: "USDT",
    margin: "110.412", marginCurrency: "USDT", settleCurrency: "USDT", updatedMs: 1_709_251_200_000,
  });
});

test("snapshots saved before the margin fields existed read as unknown, never as zero", () => {
  const value = positionMargin({ marginMode: "cross", settleCurrency: "BTC", eventTimeMs: 1 });
  assert.equal(value.leverage, null);
  assert.equal(value.liquidationPrice, null);
  assert.equal(value.margin, null);
  assert.equal(value.marginCurrency, null);
  assert.equal(value.settleCurrency, "BTC");
});

test("malformed or impossible values are unknown", () => {
  const value = positionMargin({ marginMode: "portfolio", leverage: "0", liquidationPrice: "-5", margin: "1e3",
    priceCurrency: "usd t", eventTimeMs: -1 });
  assert.deepEqual(value, { marginMode: null, leverage: null, liquidationPrice: null, priceCurrency: null,
    margin: null, marginCurrency: null, settleCurrency: null, updatedMs: null });
});

test("available margin comes from each currency's available equity and its update time", () => {
  const details = balanceDetails([{ totalEq: "1", details: [
    { ccy: "USDT", eq: "10234.51", availEq: "10124.098", uTime: "1709251200000" },
    { ccy: "ETH", eq: "0.0351", availEq: "", uTime: "1709251200001" },
  ] }, "invalid"]);
  assert.deepEqual(details.map(balanceMargin), [
    { currency: "USDT", availableMargin: "10124.098", updatedMs: 1_709_251_200_000 },
    { currency: "ETH", availableMargin: null, updatedMs: 1_709_251_200_001 },
  ]);
  assert.deepEqual(balanceDetails(null), []);
});
