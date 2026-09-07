import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../../i18n/index.js";
import { formatChartStrategyNumber } from "../chartStrategyResultModel.js";

test("result formatting uses ratio units and preserves missing metrics", () => {
  setLocale("zh-CN");
  assert.equal(formatChartStrategyNumber("0.02857142857142857142857142857", "percent"), "2.86%");
  assert.equal(formatChartStrategyNumber("1", "percent"), "100.00%");
  assert.equal(formatChartStrategyNumber("0", "percent"), "0.00%");
  assert.equal(formatChartStrategyNumber("-959.863449776"), "-959.86");
  assert.equal(formatChartStrategyNumber("0.0000000123456789", "price"), "0.000000012345679");
  assert.equal(formatChartStrategyNumber(null), "—");
  assert.equal(formatChartStrategyNumber({ value: null, reason: "NO_TRADES" }, "percent"), "—");
  assert.equal(formatChartStrategyNumber({ value: "0.5" }, "percent"), "50.00%");
});
