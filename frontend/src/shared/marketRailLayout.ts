/** Source-neutral geometry shared by live and replay right-rail adapters. */
export const MARKET_RAIL_DEFAULT_WIDTH = 320;
export const MARKET_RAIL_MIN_WIDTH = 260;
export const MARKET_RAIL_MAX_WIDTH = Number.MAX_SAFE_INTEGER;

/** Left drawing toolbar beside the chart. */
const CHART_TOOLBAR_WIDTH = 40;

/**
 * The chart keeps at least 65% of the window (up to 760px), so a saved rail width that suits a
 * wide window cannot squeeze the chart on a small one. At 1024px the rail and its tab strip take
 * about 31% of the window; from about 1180px the default width fits.
 */
export function marketRailWidthBounds(viewportWidth: number): { min: number; max: number } {
  const chartMin = Math.min(760, Math.round(viewportWidth * 0.65));
  const max = Math.max(0, viewportWidth - MARKET_ACTIVITY_BAR_WIDTH - CHART_TOOLBAR_WIDTH - chartMin);
  return { min: Math.min(MARKET_RAIL_MIN_WIDTH, max), max };
}

/** Fixed outer activity-bar strip (VS Code style). Wide enough for labels such as "Watchlist" or "交易账户" on one line, and two-word labels on two. */
export const MARKET_ACTIVITY_BAR_WIDTH = 60;

export const MARKET_DOCK_DEFAULT_HEIGHT = 360;
export const MARKET_DOCK_MIN_HEIGHT = 220;
export const MARKET_DOCK_MAX_HEIGHT = 640;
export const MARKET_DOCK_COLLAPSED_HEIGHT = 36;
export const MARKET_RAIL_MIN_SIDEBAR_HEIGHT = 180;
export const MARKET_RAIL_SPLITTER_HEIGHT = 5;

/** Built-in live rail view ids. Plugins may register additional ids. */
export const LIVE_RAIL_VIEW_IDS = {
  watchlist: "watchlist",
  orderBook: "order-book",
  tape: "tape",
  profile: "profile",
  readonlyAccounts: "readonly-accounts",
  accounts: "accounts",
} as const;

export type LiveRailViewId = (typeof LIVE_RAIL_VIEW_IDS)[keyof typeof LIVE_RAIL_VIEW_IDS];

export const DEFAULT_LIVE_OPEN_VIEW_IDS: readonly string[] = [
  LIVE_RAIL_VIEW_IDS.watchlist,
  LIVE_RAIL_VIEW_IDS.orderBook,
];
