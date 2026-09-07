import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChartLoadError } from "../ChartLoadError.js";
import { buildChartLoadDiagnostic, copyChartLoadDiagnostic } from "../chartLoadDiagnostic.js";

test("load failures expose the original diagnostic as safe selectable text without a development command", () => {
  const html = renderToStaticMarkup(<ChartLoadError error={'DataManager not initialized <script>alert(1)</script>'} onRetry={() => {}} />);
  assert.match(html, /<details/);
  assert.match(html, /DataManager not initialized &lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|--reload/);
  assert.match(html, /id="retry-btn"/);
  assert.match(html, /复制诊断摘要/);
});

test("diagnostic copying preserves the chart identity and original multiline failure", async () => {
  const text = buildChartLoadDiagnostic("HTTP 503\nDataManager not initialized", { symbol: "BTC-USDT-SWAP", interval: "15m" });
  let copied = "";
  assert.equal(await copyChartLoadDiagnostic(text, async (value) => { copied = value; }), true);
  assert.equal(copied, "CandleScope — chart data load failure\nSymbol: BTC-USDT-SWAP\nInterval: 15m\nError:\nHTTP 503\nDataManager not initialized");
});

test("clipboard denial or absence reports failure without claiming the summary was copied", async () => {
  assert.equal(await copyChartLoadDiagnostic("error", async () => { throw new Error("NotAllowedError"); }), false);
  assert.equal(await copyChartLoadDiagnostic("error", () => { throw new TypeError("clipboard unavailable"); }), false);
});
