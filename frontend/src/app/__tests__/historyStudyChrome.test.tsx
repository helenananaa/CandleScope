import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TopBar, { type TopBarProps } from "../TopBar.js";

test("study chrome identifies its saved market and omits live selectors, strategy actions and quotes", () => {
  const html = renderToStaticMarkup(<TopBar
    symbolSearch={{ currentSymbol: "ETHUSDT" } as TopBarProps["symbolSearch"]}
    controls={{ onOpenSettings: () => {}, onToggleIndicatorPanel: () => {}, onToggleAlertPanel: () => {},
      indicatorPanelOpen: false, alertPanelOpen: true, activeIndicatorCount: 0 }}
    advancedMarketData={{ summaryEnabled: true, identityKey: "live-future-metrics" } as TopBarProps["advancedMarketData"]}
    replayEntry={{ state: "enabled" } as TopBarProps["replayEntry"]}
    onOpenReplayLauncher={() => {}}
    researchEnabled={false}
    intervalControl={<span>LIVE_INTERVAL_PICKER</span>}
    identityAccessory={<button>LIVE_STRATEGY_ACTION</button>}
    studyContext={{ symbol: "BTCUSDT", interval: "1m" }}
  />);
  assert.match(html, /data-study-context="true"/);
  assert.match(html, /BTCUSDT/);
  assert.match(html, /history-study-interval[^>]*>1m/);
  assert.doesNotMatch(html, /ETHUSDT|LIVE_INTERVAL_PICKER|LIVE_STRATEGY_ACTION|alert-toggle-btn|data-market-metric/);
});
