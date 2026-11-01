export interface ChartAccountOverlaySettings {
  /** null explicitly follows the trading panel, preserving existing workspaces. */
  accountId: string | null;
  trades: boolean;
  positions: boolean;
  notes: boolean;
}

export function normalizeChartAccountOverlay(value?: unknown): ChartAccountOverlaySettings {
  const source = value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    accountId: typeof source.accountId === "string" && source.accountId.trim().length > 0
      && source.accountId.length <= 256 ? source.accountId : null,
    trades: typeof source.trades === "boolean" ? source.trades : true,
    positions: typeof source.positions === "boolean" ? source.positions : true,
    notes: source.notes === true,
  };
}

export function sameChartAccountOverlay(left: ChartAccountOverlaySettings, right: ChartAccountOverlaySettings): boolean {
  return left.accountId === right.accountId && left.trades === right.trades
    && left.positions === right.positions && left.notes === right.notes;
}
