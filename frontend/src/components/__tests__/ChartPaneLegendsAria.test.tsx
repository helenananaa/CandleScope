import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IndicatorPaneLabels, MainChartLegend } from "../ChartPaneLegends.js";
import { createPaneCrosshairStore } from "../paneCrosshairStore.js";
import { getLocale, setLocale } from "../../i18n/index.js";

test("main legend exposes the same signed movement visually and to assistive technology", () => {
  const previous = getLocale();
  try {
    setLocale("zh-CN");
    for (const [close, expected] of [[99.23, "-0.77"], [100.77, "+0.77"], [100, "+0"]] as const) {
      const crosshairStore = createPaneCrosshairStore(null);
      crosshairStore.publish(10);
      const html = renderToStaticMarkup(<MainChartLegend seriesStore={null} lines={[]} allowSourceCrosshairFallback={false}
        crosshairStore={crosshairStore} crosshair={{ time: 10, open: 100, high: 101, low: 99, close, volume: 5 }} />);
      const aria = html.match(/aria-label="([^"]*)"/)?.[1];
      assert.ok(aria?.includes(`涨跌 ${expected}，`), aria || "Missing chart aria-label");
      assert.ok(html.includes(`class="chart-main-change-absolute">${expected} / `));
      crosshairStore.dispose();
    }
  } finally { setLocale(previous); }
});

test("an empty indicator pane exposes its preparation or error status", () => {
  const crosshairStore = createPaneCrosshairStore(null);
  try {
    const html = renderToStaticMarkup(<IndicatorPaneLabels collapsedPaneIds={[]} crosshairStore={crosshairStore}
      linesByPaneId={new Map()} panes={[{ id: "separate-rsi", label: "RSI", lines: [], statusText: "计算中 25%" }]} />);
    assert.ok(html.includes('aria-label="RSI · 计算中 25%"'), html);
    assert.ok(html.includes('role="status">计算中 25%</span>'), html);
    assert.ok(html.includes('data-pane-id="separate-rsi"'), html);
    const ready = renderToStaticMarkup(<IndicatorPaneLabels collapsedPaneIds={[]} crosshairStore={crosshairStore}
      linesByPaneId={new Map()} panes={[{ id: "separate-rsi", label: "RSI", lines: [], statusText: null }]} />);
    assert.ok(!ready.includes('role="status"') && ready.includes('aria-label="RSI"'), ready);
  } finally { crosshairStore.dispose(); }
});
