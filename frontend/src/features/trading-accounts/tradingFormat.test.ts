import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../i18n/index.js";
import { seriesPricePrecision } from "../../chart-adapter/mainSeriesPriceFormat.js";
import { formatAmount, formatPercent, formatPrice, formatProfitFactor, formatQty, formatR, formatRBucket } from "./tradingFormat.js";

test("stats figures: R multiples, percentages and profit factor without losses", () => {
  setLocale("en");
  assert.equal(formatR("1.25"), "+1.25R");
  assert.equal(formatR("-0.5"), "−0.50R");
  assert.equal(formatR(null), "—");
  assert.equal(formatPercent("0.6667"), "67%");
  assert.equal(formatPercent(null), "—");
  assert.equal(formatProfitFactor({ profitFactor: "3.75", grossProfit: "30" }), "3.75");
  assert.equal(formatProfitFactor({ profitFactor: null, grossProfit: "5" }), "∞");
  assert.equal(formatProfitFactor({ profitFactor: null, grossProfit: "0" }), "—");
});

test("R bucket labels show open ends and negative bounds", () => {
  assert.equal(formatRBucket({ fromR: null, toR: "-2" }), "≤ −2R");
  assert.equal(formatRBucket({ fromR: "-1", toR: "0" }), "−1 … 0R");
  assert.equal(formatRBucket({ fromR: "3", toR: null }), "≥ 3R");
});

test("computed prices round to the chart's price precision instead of keeping their noise", () => {
  setLocale("en");
  assert.equal(formatPrice("1698.270156", 2), "1,698.27");
  assert.equal(formatPrice("1685.998583", 2), "1,686.00");
  assert.equal(formatPrice(0.9530000000000001, 3), "0.953");
  assert.equal(formatPrice("0.9530000000000001", 3), "0.953");
  assert.equal(formatPrice("107.0107"), "107.0107", "without a precision a price keeps its own digits");
  assert.equal(formatPrice("107.0107", 1.5), "107.0107", "a non-integer precision is ignored");
  assert.equal(formatPrice(null, 2), "—");
  assert.equal(formatQty("1.178"), "1.178", "quantities keep their own step");
  assert.equal(formatQty(0.30000000000000004), "0.3");
});

test("MFE and MAE amounts use the amount format, not the price format", () => {
  setLocale("en");
  assert.equal(formatAmount("15.890156"), "15.89");
  assert.equal(formatAmount("4.729844"), "4.73");
  assert.equal(formatAmount(15.890156000000081), "15.89");
});

test("the chart's price precision comes from the bars' own digits, at least two and at most eight", () => {
  assert.equal(seriesPricePrecision([{ open: 1698.27, high: 1701.5, low: 1695.1, close: 1698.3 }]), 2);
  assert.equal(seriesPricePrecision([{ open: 0.953, high: 0.96, low: 0.95, close: 0.951 }]), 3);
  assert.equal(seriesPricePrecision([{ open: 0.000012345678912, high: 1, low: 1, close: 1 }]), 8);
  assert.equal(seriesPricePrecision([]), 2);
});
