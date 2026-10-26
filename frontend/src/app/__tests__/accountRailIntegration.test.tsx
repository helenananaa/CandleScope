import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import RightMarketRail, { type RightMarketRailProps } from "../RightMarketRail.js";

function renderRail(withTrading: boolean): string {
  // Collapsed views must expose their navigation without opening either account
  // service, requiring a live order book, or loading credentials.
  return renderToStaticMarkup(<RightMarketRail
    watchlist={{} as RightMarketRailProps["watchlist"]}
    orderBook={{} as RightMarketRailProps["orderBook"]}
    tradeFlow={{} as RightMarketRailProps["tradeFlow"]}
    openViewIds={[]}
    panelCollapsed
    onToggleView={() => undefined}
    viewHeights={{}}
    onViewHeightChange={() => undefined}
    {...(withTrading ? { trading: {
      context: {} as NonNullable<RightMarketRailProps["trading"]>["context"],
      onOpenQuickReplay: () => undefined,
    } } : {})}
  />);
}

test("live account navigation retains both practice and read-only entry points", () => {
  const html = renderRail(true);
  assert.match(html, /data-rail-view="accounts"/);
  assert.match(html, /data-rail-view="readonly-accounts"/);
  assert.ok(html.indexOf('data-rail-view="accounts"') < html.indexOf('data-rail-view="readonly-accounts"'));
});

test("read-only navigation remains available without a practice chart binding", () => {
  const html = renderRail(false);
  assert.doesNotMatch(html, /data-rail-view="accounts"/);
  assert.match(html, /data-rail-view="readonly-accounts"/);
});
