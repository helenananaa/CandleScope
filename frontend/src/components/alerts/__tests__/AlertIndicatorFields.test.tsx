import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { LOCALES, loadLocaleCatalog } from "../../../i18n/registry.js";
import { alertIndicatorOptions, type AlertIndicatorSpec } from "../../../features/alerts/alertIndicatorCatalog.js";
import { canonicalAlertField, labelForSource } from "../../../features/alerts/alertRuleModel.js";
import AlertsPanel from "../AlertsPanel.js";
import { AlertIndicatorParamFields } from "../AlertIndicatorFields.js";
import { AlertIndicatorCatalogContext, useAlertIndicatorOptions } from "../alertIndicatorCatalogContext.js";

test.before(async () => { await Promise.all(LOCALES.map(loadLocaleCatalog)); });

const specs: AlertIndicatorSpec[] = [{
  name: "RSI", outputs: ["rsi"], params: [
    { key: "period", label: "Period", type: "int", defaultValue: 14, min: 2, max: 100 },
    { key: "source", label: "Source", type: "string", defaultValue: "close", options: ["close", "hl2"] },
  ],
}];

function Options({ current }: { current: string }) {
  const options = useAlertIndicatorOptions(current);
  return <select value={canonicalAlertField(current)} onChange={() => undefined}>
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>;
}

test("an existing non-default indicator remains selectable when the registry uses defaults", () => {
  const key = "ind:RSI:rsi:period=7,source=hl2";
  const html = renderToStaticMarkup(<AlertIndicatorCatalogContext.Provider value={{ specs, options: alertIndicatorOptions(specs) }}>
    <Options current={key} />
  </AlertIndicatorCatalogContext.Provider>);
  assert.match(html, /<option[^>]*selected=""[^>]*>RSI\(7, hl2\)<\/option>/);
  assert.equal(html.split(`value="${key}"`).length - 1, 1);
  assert.match(html, /RSI\(14\)/);
});

test("indicator parameters retain the selected calculation values in kit controls", () => {
  const html = renderToStaticMarkup(<AlertIndicatorCatalogContext.Provider value={{ specs, options: alertIndicatorOptions(specs) }}>
    <AlertIndicatorParamFields value="ind:RSI:rsi:period=7,source=hl2" onChange={() => undefined} />
  </AlertIndicatorCatalogContext.Provider>);
  assert.match(html, /class="alert-field-grid"/);
  assert.match(html, /class="ui-input[^"]*"/);
  assert.match(html, /value="7"/);
  assert.match(html, /<option value="hl2" selected=""/);
  assert.doesNotMatch(html, /alert-condition-grid|alert-field compact/);
});

test("price source options follow a locale change after the drawer module was imported", () => {
  const previous = getLocale();
  try {
    for (const locale of ["zh-CN", "en"] as const) {
      setLocale(locale);
      const html = renderToStaticMarkup(<AlertsPanel isOpen onClose={() => undefined}
        currentSymbol="BTCUSDT" currentMarketType="spot" currentExchange="binance" currentInterval="1h" />);
      const label = labelForSource("close");
      assert.ok(html.includes(`>${label}</option>`), `close source label follows ${locale}`);
    }
  } finally {
    setLocale(previous);
  }
});
