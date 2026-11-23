import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IndicatorPaneLabels, MainChartLegend } from "../ChartPaneLegends.js";
import { createPaneCrosshairStore } from "../paneCrosshairStore.js";
import { getLocale, setLocale, t } from "../../i18n/index.js";
import type { IndicatorLine } from "../../chart-adapter/chartAdapterTypes.js";

const MARKER = "chart-legend-seed-marker";
// EMA200 on a short series: every stored bar precedes convergence.
const shortSeed = [{ start: 60, end: 180, warmupBars: 2964, seedBars: 0 }];

function emaLine(partialSeed?: IndicatorLine["partialSeed"]): IndicatorLine {
  return {
    id: "ema", indicatorId: "ema-200", title: "EMA", pane: "main",
    data: [{ time: 60, value: 100 }, { time: 120, value: 101 }, { time: 180, value: 102 }],
    ...(partialSeed ? { partialSeed } : {}),
  };
}

function renderMain(lines: IndicatorLine[]): string {
  const crosshairStore = createPaneCrosshairStore(null);
  try {
    return renderToStaticMarkup(<MainChartLegend seriesStore={null} lines={lines} allowSourceCrosshairFallback={false}
      crosshairStore={crosshairStore} crosshair={null} />);
  } finally { crosshairStore.dispose(); }
}

test("chart legends mark partial-seed values with an explained marker", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const notice = t("legend.partialSeed", { seed: 0, warmup: 2964 });
    assert.match(notice, /0 of 2964 warmup bars/);

    const partial = renderMain([emaLine(shortSeed)]);
    assert.ok(partial.includes(MARKER), partial);
    assert.ok(partial.includes(`title="${notice}"`), partial);
    assert.ok(partial.match(/^<div[^>]*aria-label="([^"]*)"/)?.[1]?.endsWith(notice), partial);

    const convergedHtml = renderMain([emaLine()]);
    assert.equal(convergedHtml.includes(MARKER), false);

    const crosshairStore = createPaneCrosshairStore(null);
    const pane = { id: "sub-rsi", label: "RSI", lines: [] };
    const rsi = { ...emaLine(shortSeed), id: "rsi", indicatorId: "rsi", pane: "sub-rsi" };
    const paneHtml = renderToStaticMarkup(<IndicatorPaneLabels collapsedPaneIds={[]} crosshairStore={crosshairStore}
      linesByPaneId={new Map([[pane.id, [rsi]]])} panes={[pane]} />);
    crosshairStore.dispose();
    assert.ok(paneHtml.includes(MARKER), paneHtml);
    assert.ok(paneHtml.includes(notice), paneHtml);
  } finally { setLocale(previous); }
});
