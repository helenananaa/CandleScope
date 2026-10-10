import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { structuralMock } from "../../../../test/testHelpers.js";
import { getLocale, setLocale } from "../../../../i18n/locale.js";
import ResearchResultsPanel from "../ResearchResultsPanel.js";
import type { BacktestResearchRuntime } from "../backtestResearchTypes.js";

function renderMetrics(trades: number, winRate: string | null) {
  return renderToStaticMarkup(<ResearchResultsPanel runtime={structuralMock<BacktestResearchRuntime>({
    view: { advancedEnabled: true, report: {
      metrics: { realized_net_pnl: "59.147449520918", trade_count: trades, win_rate: winRate },
      trades: [], equity_curve: [], fidelity_mode: "BAR_APPROX", hashes: {},
    } },
  })} />);
}

test("advanced results format ratios and amounts and collapse raw diagnostics", () => {
  const previous = getLocale();
  setLocale("en");
  try {
    const html = renderMetrics(6, "1");
    assert.match(html, />100%</);
    assert.match(html, />59.15</);
    assert.doesNotMatch(html, /59.147449520918/);
    assert.match(html, /<details><summary>/);
    assert.doesNotMatch(html, /<details open/);
    assert.doesNotMatch(renderMetrics(0, "0"), />0%</);
    assert.doesNotMatch(renderMetrics(6, null), />0%</);
  } finally { setLocale(previous); }
});
