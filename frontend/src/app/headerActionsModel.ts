/**
 * How many header actions fit inline, in order. When not all of them fit, room is kept for the
 * overflow button, and the rest go into its menu.
 */
export function fitHeaderActions(widths: readonly number[], available: number, gap: number, moreWidth: number): number {
  const total = widths.reduce((sum, width) => sum + width, 0) + gap * Math.max(0, widths.length - 1);
  if (total <= available) return widths.length;
  let used = moreWidth;
  let count = 0;
  for (const width of widths) {
    if (used + gap + width > available) break;
    used += gap + width;
    count += 1;
  }
  return count;
}

/** Header compaction steps that come before page actions give way to the 更多 menu. */
export const HEADER_COMPACT_BEFORE_ACTIONS = 2;
/** All header compaction steps; those after HEADER_COMPACT_BEFORE_ACTIONS apply only once the actions are in the menu. */
export const HEADER_COMPACT_LEVELS = 4;

export interface HeaderFit {
  /** The left side (context and tools) is wider than its space. */
  mainOverflows(): boolean;
  /** Every page action fits inline. */
  actionsFit(): boolean;
}

/**
 * The compaction level for the header, starting from `start`: the lowest level from there at which
 * it fits. Early steps hide low-value details (inline market metrics, the shortcut hint, the
 * wordmark) before any page action moves into the 更多 menu; later steps (badges, labels) only once
 * the left side still does not fit. `apply` sets a level on the header so the next measurement
 * reflects it. A resize starts from 0; a content change starts from the current level, so a ticking
 * price can only add steps and never makes the header flicker.
 */
export function chooseHeaderCompaction(apply: (level: number) => void, fit: HeaderFit, start = 0): number {
  let level = start;
  apply(level);
  while (level < HEADER_COMPACT_BEFORE_ACTIONS && (fit.mainOverflows() || !fit.actionsFit())) apply(++level);
  while (level < HEADER_COMPACT_LEVELS && fit.mainOverflows()) apply(++level);
  return level;
}
