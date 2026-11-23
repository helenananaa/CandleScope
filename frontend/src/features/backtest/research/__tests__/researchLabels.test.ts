import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../../i18n/registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../../i18n/index.js";
import {
  chartContextStatusLabel,
  researchFidelityLabel,
  researchStateLabel,
} from "../researchLabels.js";

test("research states and accuracy tiers are named, and unknown codes stay visible", () => {
  setLocale("zh-CN");
  assert.equal(researchStateLabel("DRAFT"), "草稿");
  assert.equal(researchStateLabel("COMPLETED"), "已完成");
  assert.equal(researchStateLabel("CANCELED"), researchStateLabel("CANCELLED"));
  assert.equal(researchStateLabel("BLINDED"), "结果隐藏中");
  assert.equal(researchStateLabel("SOMETHING_NEW"), "SOMETHING_NEW");
  assert.equal(researchStateLabel(null), "—");
  assert.equal(researchFidelityLabel("BAR_APPROX"), "按 K 线估算");
  assert.equal(researchFidelityLabel("AGG_TRADE_EXECUTION"), researchFidelityLabel("AGG_TRADE_TAPE"));
  setLocale("en");
  assert.equal(researchStateLabel("AWAITING_HOLDOUT"), "Awaiting held-out test");
  assert.equal(researchFidelityLabel("BOOK_SAMPLED"), "Sampled order book");
  assert.equal(chartContextStatusLabel("AMBIGUOUS_MARKET"), "Couldn't tell which market this chart shows.");
  assert.equal(chartContextStatusLabel("NEW_STATUS"), "NEW_STATUS");
});
