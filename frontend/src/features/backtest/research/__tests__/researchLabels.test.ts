import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../../i18n/registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../../i18n/index.js";
import {
  chartContextStatusLabel,
  researchFidelityLabel,
  researchStateLabel,
  researchTimeRangeLabel,
  shortFingerprint,
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

test("epoch-millisecond ranges read as UTC dates and fingerprints drop their algorithm", () => {
  setLocale("en");
  const range = researchTimeRangeLabel(Date.UTC(2026, 8, 6, 8, 48), Date.UTC(2026, 8, 7, 13, 18, 59, 999));
  assert.match(range, /2026/);
  assert.match(range, /UTC$/);
  assert.doesNotMatch(range, /1788/);
  assert.equal(researchTimeRangeLabel(null, undefined), "— → — UTC");
  assert.equal(shortFingerprint("sha256:a4eedb2cf5c14b4570271b356a570c62"), "a4eedb2cf5c1…");
  assert.equal(shortFingerprint("abc"), "abc");
  assert.equal(shortFingerprint(undefined), "—");
});
