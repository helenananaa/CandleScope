import assert from "node:assert/strict";
import test from "node:test";
import { buildExportContextLines, buildExportIndicatorContext, wrapExportContext } from "../exportContext.js";
import { buildExportOptionsKey, normalizeExportOptions } from "../exportService.js";

test("a shared chart retains identity and visible indicator parameters without a watermark", () => {
  const indicators = buildExportIndicatorContext([
    { id: "ma", name: "MA", params: { period: 20, source: "close" }, lines: [{ data: [], pane: "main" }] },
    { id: "rsi", name: "RSI", params: { period: 14 }, lines: [{ data: [], pane: "rsi" }] },
    { id: "hidden", visible: false, params: { period: 10 } },
  ]);
  const options = normalizeExportOptions({ metadata: { exchange: "okx", marketType: "futures", symbol: "BTC-USDT-SWAP", interval: "15m", indicators } });
  assert.equal(options.watermarkEnabled, false);
  assert.deepEqual(buildExportContextLines(options), ["okx · futures · BTC-USDT-SWAP · 15m", "MA (period=20, source=close)", "RSI (period=14)"]);
  assert.deepEqual(buildExportContextLines({ ...options, scope: "main-pane" }), ["okx · futures · BTC-USDT-SWAP · 15m", "MA (period=20, source=close)"]);
  assert.deepEqual(buildExportContextLines({ ...options, scope: "page" }), []);
  assert.deepEqual(buildExportContextLines({ ...options, includeContext: false }), []);
});

test("context preferences migrate safely and changes invalidate previews", () => {
  assert.equal(normalizeExportOptions({ watermarkEnabled: false }).includeContext, true);
  assert.equal(normalizeExportOptions({ includeContext: false }).includeContext, false);
  const before = { metadata: { indicators: [{ label: "MA (period=20)", mainPane: true }] } };
  assert.notEqual(buildExportOptionsKey(before), buildExportOptionsKey({ ...before, includeContext: false }));
  assert.notEqual(buildExportOptionsKey(before), buildExportOptionsKey({ metadata: { indicators: [{ label: "MA (period=30)", mainPane: true }] } }));
  assert.deepEqual(normalizeExportOptions({ metadata: { indicators: [null, "invalid", { label: 5 }, { label: "RSI" }] } }).metadata?.indicators, [{ label: "RSI", mainPane: false }]);
});

test("narrow images wrap long unbroken symbols without losing content", () => {
  assert.deepEqual(wrapExportContext(["MA period=20 color=#fff"], 14, (value) => value.length), ["MA period=20", "color=#fff"]);
  const text = "BTC-USDT-SWAP period=1234567890 中文参数";
  const lines = wrapExportContext([text], 8, (value) => [...value].length);
  assert.ok(lines.every((line) => [...line].length <= 8));
  assert.equal(lines.join("").replaceAll(" ", ""), text.replaceAll(" ", ""));
});
