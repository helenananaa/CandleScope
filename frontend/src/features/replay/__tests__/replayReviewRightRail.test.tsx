import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReplayReviewRightRail from "../components/ReplayReviewRightRail.js";
import type { ReplayReviewResponse } from "../replayIntegrityModel.js";
import { getLocale, setLocale } from "../../../i18n/index.js";

function render(portfolio: Record<string, unknown>) {
  // The selected adapter differs from the shared three-track wallet in the
  // native legacy archive. Only the frozen response participates in rendering.
  const review = {
    selected_event_id: "event-94", events: [{ event_id: "event-94", public_time: { label: "2026-10-10 00:17:59" } }],
    projection: { viewer_state: { selected_track_id: "track-1" }, tracks: [{ track_id: "track-1", symbol: "LTCUSDT" }],
      domain: { equity: "9999.84775598", portfolio }, orders: [], fills: [], ledger: [], drawing_revision: 10 },
  } as unknown as ReplayReviewResponse;
  const previous = getLocale();
  try { setLocale("en"); return renderToStaticMarkup(<ReplayReviewRightRail review={review} />); }
  finally { setLocale(previous); }
}

test("frozen multi-track sidebar displays shared portfolio equity", () => {
  const html = render({ status: "EXACT_SNAPSHOT", equity: "9999.56560194", available_equity: "9999.56560194", unrealized_pnl: "0", positions: [] });
  assert.match(html, /9999\.56560194/);
  assert.doesNotMatch(html, /9999\.84775598/);
});

test("unavailable historical valuation never falls back to adapter equity", () => {
  const html = render({ status: "UNAVAILABLE", equity: null, available_equity: null, unrealized_pnl: null, positions: null });
  assert.doesNotMatch(html, /9999\.84775598/);
  assert.match(html, /<dd>--<\/dd>/);
});

test("frozen HEDGE legs are limited to the selected track", () => {
  const html = render({ status: "EXACT_SNAPSHOT", equity: "86.70588889446106", positions: [
    { track_id: "track-1", position_side: "LONG", quantity: "0.75" },
    { track_id: "track-1", position_side: "SHORT", quantity: "91.18263882" },
    { track_id: "track-2", position_side: "LONG", quantity: "999.12345" },
  ] });
  assert.match(html, /Long 0\.75 · Short 91\.18263882/i);
  assert.doesNotMatch(html, /999\.12345/);
});
