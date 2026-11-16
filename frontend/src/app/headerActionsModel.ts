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
