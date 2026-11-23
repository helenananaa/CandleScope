import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { t } from "../../../i18n/index.js";
import WatchlistSidebar from "../WatchlistSidebar.js";
import { createWatchlistPriceStore, type WatchlistPriceTick } from "../watchlistPriceStore.js";

function renderWith(tick: WatchlistPriceTick): string {
  const controller = createWatchlistPriceStore({ request: (callback) => { callback(); return 0; }, cancel: () => undefined });
  controller.enqueue([tick]);
  return renderToStaticMarkup(
    <WatchlistSidebar
      currentSymbol="BTCUSDT"
      currentMarketType="futures"
      currentExchange="binance"
      onSelectSymbol={() => undefined}
      watchlists={[{ id: "main", name: "Main", color: "#3b82f6", symbols: ["futures:BTCUSDT"] }]}
      priceStore={controller.store}
      subscriptionTiers={{ "futures:BTCUSDT": "price" }}
    />,
  );
}

test("a watchlist price whose feed is offline stays visible but is marked stale", () => {
  const stale = renderWith({ symbol: "futures:BTCUSDT", price: 61668.79, daily_change_pct: 0.65, stale: true });
  assert.match(stale, /data-price-stale="true"/);
  assert.match(stale, /wl-col-price[^"]*wl-stale/);
  assert.match(stale, /wl-tier-offline/);
  assert.ok(stale.includes(t("watchlist.priceStale")));
  assert.ok(stale.includes("61668.79") || stale.includes("61,668.79"));

  const live = renderWith({ symbol: "futures:BTCUSDT", price: 61668.79, daily_change_pct: 0.65 });
  assert.doesNotMatch(live, /data-price-stale/);
  assert.doesNotMatch(live, /wl-stale|wl-tier-offline/);
  assert.ok(!live.includes(t("watchlist.priceStale")));
});
