import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { indicatorParamLabel, indicatorSourceLabel } from "../indicatorParamLabels.js";

test("builtin labels localize while custom and unknown parameter labels remain authored", () => {
  const previous = getLocale();
  try {
    setLocale("zh-CN");
    assert.equal(indicatorParamLabel("hist_up_color", "Histogram Up Color", true), "正值柱颜色");
    assert.equal(indicatorParamLabel("source", "source", true), "价格来源");
    assert.equal(indicatorParamLabel("source", "My custom feed", false), "My custom feed");
    assert.equal(indicatorParamLabel("custom_window", "专用窗口", true), "专用窗口");
    assert.equal(indicatorSourceLabel("close"), "收盘价");
    assert.equal(indicatorSourceLabel("hlcc4"), "(最高价 + 最低价 + 2 × 收盘价) / 4");
    assert.equal(indicatorSourceLabel("custom_feed"), "custom_feed");
    setLocale("en");
    assert.equal(indicatorParamLabel("source", "source", true), "Price source");
  } finally {
    setLocale(previous);
  }
});
