import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { indicatorDescription, indicatorDisplayName, indicatorDisplayPanes } from "../indicatorDisplayName.js";

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

test("pane badges follow computed placement instead of custom save defaults", () => {
  assert.deepEqual(indicatorDisplayPanes({ paneTarget: "sub", lines: [{ data: [], pane: "main" }] }, false), ["main"]);
  assert.deepEqual(indicatorDisplayPanes({ paneTarget: "main", lines: [{ data: [], pane: "separate" }] }, false), ["sub"]);
  assert.deepEqual(indicatorDisplayPanes({ lines: [{ data: [] }, { data: [], pane: "separate" }] }, false), ["main", "sub"]);
  assert.deepEqual(indicatorDisplayPanes({ paneTarget: "sub" }, false), []);
  assert.deepEqual(indicatorDisplayPanes({ paneTarget: "main" }, true), ["main"]);
});

const CJK_TEXT = /[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/u;

test("built-in names and descriptions come from the catalog, even for presets saved with Chinese text", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    for (const engineName of ["MA", "EMA", "BOLL", "RSI", "MACD", "ATR", "VOL"]) {
      // Older builds stored the backend's Chinese VOL name and description with the workspace.
      const saved = { id: engineName.toLowerCase(), engineName, name: "成交量", description: "成交量柱状图，颜色跟随K线设置" };
      assert.doesNotMatch(indicatorDisplayName(saved), CJK_TEXT, engineName);
      if (engineName === "VOL") assert.doesNotMatch(indicatorDescription(saved), CJK_TEXT);
    }
    assert.equal(indicatorDisplayName({ id: "vol", name: "成交量", engineName: "VOL" }), "Volume (VOL)");
    assert.equal(indicatorDescription({ engineName: "VOL", description: "Volume" }), "Volume bars colored by candle direction");
    assert.equal(indicatorDescription({ engineName: "RSI", description: "Relative Strength Index" }), "Relative Strength Index");
    assert.equal(indicatorDescription({ description: "My own notes" }), "My own notes");
    setLocale("zh-CN");
    assert.equal(indicatorDescription({ engineName: "VOL", description: "Volume" }), "成交量柱状图，颜色跟随 K 线涨跌");
  } finally {
    setLocale(previous);
  }
});
