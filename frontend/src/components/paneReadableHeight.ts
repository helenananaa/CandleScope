import { COLLAPSED_PANE_HEIGHT } from "./paneControlModel.js";

export function readablePaneMinimums(
  paneIds: readonly string[],
  collapsedPaneIds: readonly string[],
  maximizedPaneId: string | null,
): number[] {
  const collapsed = new Set(collapsedPaneIds);
  const maximized = maximizedPaneId !== null && paneIds.includes(maximizedPaneId);
  return paneIds.map((id) => (maximized ? id !== maximizedPaneId : collapsed.has(id))
    ? COLLAPSED_PANE_HEIGHT
    : id === "main" ? 180 : 80);
}

/** Preserve the actual pixel budget while taking space only from panes above
 * their minimum. Null means no adjustment (or layout has not caught up yet). */
export function constrainReadablePaneHeights(
  heights: readonly number[],
  minimums: readonly number[],
): number[] | null {
  if (heights.length === 0 || heights.length !== minimums.length
    || heights.some((height) => !Number.isFinite(height) || height <= 0)) return null;
  if (heights.every((height, index) => height >= minimums[index]! - 1)) return null;
  const budget = heights.reduce((sum, height) => sum + height, 0);
  const minimumBudget = minimums.reduce((sum, height) => sum + height, 0);
  if (budget < minimumBudget) return null;
  const excess = heights.map((height, index) => Math.max(0, height - minimums[index]!));
  const totalExcess = excess.reduce((sum, height) => sum + height, 0);
  return minimums.map((minimum, index) => minimum + (budget - minimumBudget)
    * (totalExcess > 0 ? excess[index]! / totalExcess : 1 / heights.length));
}
