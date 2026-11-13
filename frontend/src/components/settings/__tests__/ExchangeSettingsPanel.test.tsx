import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import ExchangeSettingsPanel from "../ExchangeSettingsPanel.js";
import type { ExchangeCapabilityPayload } from "../../../features/settings/exchangeSettingsRuntime.js";

function exchange(id: string, { routable = true }: { routable?: boolean } = {}): ExchangeCapabilityPayload {
  return {
    exchange: id,
    name: id.toUpperCase(),
    markets: [{ market_type: "spot", product_type: "spot", label: "Spot" }],
    native_intervals: [],
    capability_schema_version: 3,
    channels: [{ channel: "kline", market_types: ["spot"], realtime: true, history: true,
      realtime_transports: ["plugin_stream"], history_transports: ["rest_history"], params: { interval: ["1m", "1h"] } }],
    protocol_features: ["provider.ccxt_primary"],
    limits: {},
    known_limitations: [],
    support: { provider: "ccxt_primary", routable, verification_level: routable ? "shadow" : "catalog_only",
      qualification: null, qualifications: [], products: { markets: {} } },
  };
}

function panel(exchanges: ExchangeCapabilityPayload[], current = "binance") {
  return renderToStaticMarkup(<ExchangeSettingsPanel
    currentExchange={current} supportedExchanges={exchanges} exchangeCatalogSummary={null}
    exchangeConnectionChecks={{}} exchangeListLoading={false} exchangeListError={null}
    onRefreshExchanges={() => undefined} onTestExchangeMarket={() => undefined} />);
}

test("an exchange row is its name, one line of plain text and at most a status badge", () => {
  const html = panel([exchange("binance"), exchange("aster", { routable: false })]);
  const rows = html.split('<li class="st-ex-item"').slice(1);
  assert.equal(rows.length, 2);
  const [binance, aster] = rows;
  assert.match(binance!, /class="ui-badge" data-tone="accent">当前</);
  assert.match(binance!, /<span class="st-ex-meta">CCXT 专用增强 · Spot<\/span>/);
  assert.doesNotMatch(binance!.split("st-ex-detail")[0]!, /验证|影子/, "verification is not in the row");
  assert.match(aster!, /data-tone="danger">不可路由</);
});

test("verification and channel tables are behind disclosures in the expanded exchange", () => {
  const html = panel([exchange("binance")]);
  const detail = html.split("st-ex-detail")[1] ?? "";
  assert.match(detail, /<details class="ui-disclosure"[^>]*><summary[^>]*>.*?数据通道：1/s);
  assert.match(detail, /<dt>验证<\/dt><dd>已与并行数据比对验证<\/dd>/);
  assert.doesNotMatch(html, /并行影子验收/);
});
