import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import ChartAppearancePanel from "../settings/ChartAppearancePanel.js";
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

test("from a chart, Settings shows the app theme and this chart's own appearance separately", () => {
  const following = renderToStaticMarkup(
    <ChartAppearancePanel appearanceScope="chart" appearanceTargets={targets({})} settings={DEFAULT_SETTINGS} onUpdate={() => undefined} />,
  );
  assert.match(following, /data-settings-chart-appearance="true"/);
  assert.match(following, /当前图表外观/);
  assert.match(following, /aria-pressed="true"[^>]*>跟随应用主题/);
  assert.match(following, /aria-pressed="true"[^>]*><span class="st-theme-icon">.*?亮色/, "the app theme card reflects the app, not the chart");
  assert.doesNotMatch(following, /type="color" aria-label="自定义背景色"/);

  const own = renderToStaticMarkup(
    <ChartAppearancePanel appearanceScope="chart" appearanceTargets={targets({ theme: "custom", customBg: "#f4efe2" })}
      settings={DEFAULT_SETTINGS} onUpdate={() => undefined} />,
  );
  assert.match(own, /aria-pressed="true"[^>]*>单独设置/);
  assert.match(own, /type="color" aria-label="自定义背景色" value="#f4efe2"/);
});
