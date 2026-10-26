import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StatusBar, { type StatusBarModel } from "../StatusBar.js";
import { t } from "../../i18n/index.js";

function render(wsStatus: string) {
  const status: StatusBarModel = { connectionStatus: "connected", dataSource: "cache", exchangeLabel: "Binance",
    marketLabel: "spot", wsStatus, wsStatusLabel: "", barCount: 1500, loadingMoreLeft: false,
    hasMoreLeft: true, exchangeCatalogStatus: "ready" };
  return renderToStaticMarkup(<StatusBar status={status} />);
}
test("cached history does not claim the exchange is live while waiting for data", () => {
  for (const status of ["loading", "connecting", "reconnecting", "fallback"]) {
    const html = render(status);
    assert.match(html, /data-connection-status="loading"/);
    assert.ok(!html.includes(t("status.connectedTo", { exchange: "Binance" })));
    assert.ok(!html.includes(t("status.ws.live")));
    assert.match(html, /data-live-bar-count="1500"/);
  }
});
test("observed live data and disconnected transports retain distinct indicators", () => {
  assert.match(render("live"), /data-connection-status="connected"/);
  assert.ok(render("live").includes(t("status.connectedTo", { exchange: "Binance" })));
  assert.match(render("disconnected"), /data-connection-status="disconnected"/);
});
