import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChartIntervalUnavailable } from "../ChartIntervalUnavailable.js";
import { t } from "../../i18n/index.js";

test("unavailable restore names the requested series and offers only declared alternatives", () => {
  const html = renderToStaticMarkup(<ChartIntervalUnavailable
    session={{ symbol: "BTCUSDT", exchange: "binance", marketType: "futures", interval: "7s" }}
    nativeIntervals={[{ value: "1m", seconds: 60 }]}
    onSelectInterval={() => {}}
  />);
  assert.match(html, /BTCUSDT.*7s/);
  assert.match(html, /data-interval-admission="unavailable"/);
  assert.match(html, /value="1m"/);
  assert.doesNotMatch(html, /value="1h"/);
  assert.ok(html.includes(t("interval.unavailableHelp")));
  assert.ok(!html.includes(t("chart.backendHint")));
  assert.doesNotMatch(html, /id="retry-btn"/);
});
