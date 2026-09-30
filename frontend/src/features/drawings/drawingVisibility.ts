/** A null/missing interval filter preserves legacy visibility on every interval. */
export function validDrawingIntervals(value: unknown): value is readonly string[] | null | undefined {
  return value == null || (Array.isArray(value) && value.length > 0 && value.length <= 64
    && new Set(value).size === value.length
    && value.every(item => typeof item === "string" && /^[1-9]\d{0,5}[smhdwM]$/.test(item)));
}

export function drawingVisibleAtInterval(
  drawing: { readonly hidden?: boolean; readonly visibleIntervals?: readonly string[] | null }, interval: string,
): boolean {
  return !drawing.hidden && (drawing.visibleIntervals == null || drawing.visibleIntervals.includes(interval));
}
