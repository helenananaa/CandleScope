import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import ChartAppearancePanel from "../settings/ChartAppearancePanel.js";
import ChartAppearanceSection from "../settings/ChartAppearanceSection.js";
import { DEFAULT_SETTINGS, type AppearanceTargets } from "../../features/settings/chartAppearanceSettings.js";

function targets(override: AppearanceTargets["chart"]["override"]): AppearanceTargets {
  return {
    application: { theme: "light", customBg: "#102030", upColor: "#22c55e", downColor: "#ef4444", update: () => undefined },
    chart: { override, set: () => undefined },
  };
}

test("application settings offer dark, light and system but no custom app background", () => {
  const html = renderToStaticMarkup(<ChartAppearancePanel settings={DEFAULT_SETTINGS} onUpdate={() => undefined} />);
  assert.match(html, /应用主题/);
  assert.match(html, /跟随系统/);
  assert.doesNotMatch(html, /st-theme-label">自定义</);
  assert.doesNotMatch(html, /data-settings-chart-appearance/);
});

test("where charts set their own appearance in their menu, Settings only counts them and resets all", () => {
  const withWorkspace = (overrides: number): AppearanceTargets => ({ ...targets({ theme: "dark" }), workspace: { overrides, resetAll: () => undefined } });
  const counted = renderToStaticMarkup(
    <ChartAppearancePanel appearanceScope="chart" appearanceTargets={withWorkspace(2)} settings={DEFAULT_SETTINGS} onUpdate={() => undefined} />,
  );
  assert.doesNotMatch(counted, /data-settings-chart-appearance/);
  assert.match(counted, /data-settings-chart-overrides="2"/);
  assert.match(counted, /使用自己外观的图表：2/);
  assert.match(counted, /全部恢复跟随应用/);
  const none = renderToStaticMarkup(
    <ChartAppearancePanel appearanceScope="chart" appearanceTargets={withWorkspace(0)} settings={DEFAULT_SETTINGS} onUpdate={() => undefined} />,
  );
  assert.doesNotMatch(none, /data-settings-chart-overrides/);
});

test("the chart menu's appearance section follows the app or sets the chart's own look", () => {
  const following = renderToStaticMarkup(<ChartAppearanceSection targets={targets({})} />);
  assert.match(following, /aria-label="图表外观"/);
  assert.match(following, /role="radio" aria-checked="true"[^>]*>跟随应用主题/);
  assert.doesNotMatch(following, /type="color"/);

  const custom = renderToStaticMarkup(
    <ChartAppearanceSection targets={{ ...targets({ theme: "custom", customBg: "#f4efe2", upColor: "#00ff00", downColor: "#ff0000" }), chart: { override: { theme: "custom", customBg: "#f4efe2", upColor: "#00ff00", downColor: "#ff0000" }, set: () => undefined, linkedCharts: 2 } }} />,
  );
  assert.match(custom, /role="radio" aria-checked="true"[^>]*>单独设置/);
  assert.match(custom, /role="radio" aria-checked="true"[^>]*>自定义/);
  assert.match(custom, /type="color" value="#f4efe2"/);
  assert.match(custom, /type="checkbox"[^>]*checked=""/);
  assert.match(custom, /type="color" value="#00ff00"/);
  assert.match(custom, /同步到联动的图表：2/);
});
