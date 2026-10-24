import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../i18n/index.js";
import { formatPercent, formatProfitFactor, formatR, formatRBucket } from "./tradingFormat.js";

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
