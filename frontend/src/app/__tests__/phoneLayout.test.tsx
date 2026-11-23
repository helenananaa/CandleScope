import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import MarketRightRailFrame from "../MarketRightRailFrame.js";
import type { MarketRailViewDescriptor } from "../marketRailTypes.js";
import { PHONE_LAYOUT_QUERY, isPhoneLayout } from "../phoneLayout.js";
import { readAppStyles } from "../../test/appStyles.js";

const views: MarketRailViewDescriptor[] = [
  { id: "watchlist", title: "自选", icon: <span />, order: 10, sizing: "flex" },
  { id: "order-book", title: "盘口", icon: <span />, order: 20, sizing: "fixed", defaultHeight: 320 },
  { id: "tape", title: "成交", icon: <span />, order: 30, sizing: "fixed" },
];

/** Runs `render` in a window as narrow as a phone held upright. */
function onPhone<T>(render: () => T): T {
  const scope = globalThis as { window?: unknown };
  const previous = scope.window;
  scope.window = {
    innerWidth: 390,
    matchMedia: (query: string) => ({
      matches: query === PHONE_LAYOUT_QUERY,
      addEventListener() {},
      removeEventListener() {},
    }),
    addEventListener() {},
    removeEventListener() {},
  };
  try {
    return render();
  } finally {
    scope.window = previous;
  }
}

function renderRail(openViewIds: readonly string[], panelCollapsed = false): string {
  return renderToStaticMarkup(
    <MarketRightRailFrame
      views={views}
      openViewIds={openViewIds}
      panelCollapsed={panelCollapsed}
      onToggleView={() => undefined}
      onTogglePanelCollapsed={() => undefined}
      renderView={(viewId) => <div data-kept={viewId} />}
      layout={{ width: 320 }}
    />,
  );
}

test("the phone layout follows the stylesheets' width", () => {
  assert.equal(PHONE_LAYOUT_QUERY, "(max-width: 640px)");
  assert.equal(isPhoneLayout(), false, "no window, no phone");
  assert.equal(onPhone(isPhoneLayout), true);
  const styles = readAppStyles();
  for (const rule of [".app-header-end", ".market-activity-bar", ".market-rail-panel", ".pane-control-bar"]) {
    const block = styles.split("@media (max-width: 640px)").slice(1).find((part) => part.includes(rule));
    assert.ok(block, `${rule} has phone rules`);
  }
});

test("on a phone the accordion rail shows one view in a sheet, the one opened last", () => {
  const html = onPhone(() => renderRail(["watchlist", "order-book"]));
  assert.match(html, /class="market-rail-panel market-rail-sheet"/);
  assert.match(html, /data-kept="order-book"/);
  assert.doesNotMatch(html, /data-kept="watchlist"/);
  assert.doesNotMatch(html, /market-rail-accordion-trigger/);
  // A sheet as wide as the window: no width of its own, no resize handle, and its tabs close it.
  assert.doesNotMatch(html, /wl-resize-handle/);
  assert.doesNotMatch(html, /style="width:/);
  assert.doesNotMatch(html, /data-rail-action="toggle-panel"/);
  assert.match(html, /class="market-activity-item active"[^>]*data-rail-view="order-book"/);
  assert.doesNotMatch(html, /class="market-activity-item active"[^>]*data-rail-view="watchlist"/);
});

test("on a phone a hidden panel leaves only the bar, with no tab current", () => {
  const html = onPhone(() => renderRail(["watchlist", "order-book"], true));
  assert.match(html, /data-panel-open="false"/);
  assert.doesNotMatch(html, /market-activity-item active/);
});

test("wider windows keep the accordion column", () => {
  const html = renderRail(["watchlist", "order-book"]);
  assert.doesNotMatch(html, /market-rail-sheet/);
  assert.match(html, /data-kept="watchlist"/);
  assert.match(html, /data-kept="order-book"/);
  assert.match(html, /data-rail-action="toggle-panel"/);
});
