import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { indicatorDisplayName } from "../indicatorDisplayName.js";

test("display names follow engine identity and leave user names intact", () => {
  const previous = getLocale();
  try {
    setLocale("zh-CN");
    assert.equal(indicatorDisplayName({ id: "instance-1", name: "Simple Moving Average", engineName: "MA" }), "简单移动平均线 (SMA)");
    assert.equal(indicatorDisplayName({ id: "custom", name: "Simple Moving Average" }), "Simple Moving Average");
    assert.equal(indicatorDisplayName({ id: "custom", name: "My RSI", engineName: "unknown" }), "My RSI");
    setLocale("en");
    assert.equal(indicatorDisplayName({ id: "r", engineName: "RSI" }), "Relative Strength Index (RSI)");
  } finally {
    setLocale(previous);
  }
});
