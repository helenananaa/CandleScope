import type { NativeResult } from "./nativeBacktestApi.js";

export type DrawingRow = Record<string, unknown>;
export type DrawingKind = "lines" | "labels" | "boxes" | "polylines" | "linefills" | "tables";
export interface NativeDrawing { kind: DrawingKind; row: DrawingRow }
export const drawingRows = (value: unknown): DrawingRow[] => Array.isArray(value)
  ? value.filter((row): row is DrawingRow => row !== null && typeof row === "object" && !Array.isArray(row)) : [];
export const drawingNumber = (value: unknown): number | undefined => typeof value === "number" && Number.isFinite(value) ? value : undefined;
export const drawingText = (value: unknown, fallback = ""): string => typeof value === "string" || typeof value === "number" ? String(value) : fallback;
export function drawingColor(value: unknown, fallback = "#38bdf8"): string {
  // Pine uses RGB integers, RGBA integers, and a 2^32 flag for low RGB RGBA.
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 0x100ffffff) {
    if (value <= 0xffffff) return `#${value.toString(16).padStart(6,"0")}`;
    if (value <= 0xffffffff || value >= 0x100000000) return `#${(value % 0x100000000).toString(16).padStart(8,"0")}`;
  }
  // Render colors only, never arbitrary SVG paint servers/URLs from script output.
  return typeof value === "string" && /^(#[\da-f]{3,8}|rgba?\([\d.,%\s]+\)|transparent|red|green|blue|black|white|yellow|orange|purple|gray)$/i.test(value) ? value : fallback;
}
function normalize(row: DrawingRow): DrawingRow {
  return Object.fromEntries(Object.entries(row).map(([key,value]) => [key.replaceAll("_", "").toLowerCase(), value]));
}

export function nativeDrawings(result: NativeResult): { objects: NativeDrawing[]; pine: boolean } {
  const raw = (result.raw_output.strategy_output ?? result.raw_output) as DrawingRow;
  const pine = !raw.objects && (Array.isArray(raw.plots) || result.account_authority === "pine-compat-runtime");
  const source = normalize((raw.objects ?? raw) as DrawingRow);
  const objects: NativeDrawing[] = [];
  for (const kind of ["lines","labels","boxes","polylines","linefills","tables"] as const) {
    for (const item of drawingRows(source[kind])) {
      let row = normalize(item);
      if (pine) {
        const snapshots = drawingRows(row.snapshots).map(normalize).filter((snapshot) =>
          (drawingNumber(snapshot.barindex) ?? Infinity) < result.bars.length);
        const last = snapshots.at(-1);
        if (!last || last.exists === false) continue;
        row = { ...row, ...last };
      } else if (kind === "lines" && Array.isArray(row.data)) continue;
      row.cells = drawingRows(row.cells).map(normalize);
      row.merges = drawingRows(row.merges ?? row.mergedcells).map(normalize);
      row.points = drawingRows(row.points).map(normalize);
      objects.push({ kind, row });
    }
  }
  return { objects, pine };
}

/** Interpolate timestamps against the actual, possibly gapped, chart timeline. */
export function drawingIndex(value: unknown, xloc: unknown, bars: NativeResult["bars"], pine: boolean): number | undefined {
  const x = drawingNumber(value);
  if (x === undefined || !bars.length) return undefined;
  if (!drawingText(xloc).endsWith("bar_time")) return x;
  const time = pine ? x / 1000 : x;
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid]!.time < time) low = mid + 1; else high = mid; }
  if (bars[low]?.time === time) return low;
  const left = Math.max(0, Math.min(bars.length - 2, low - 1));
  const duration = (bars[left + 1]?.time ?? bars[left]!.time + 60) - bars[left]!.time;
  return left + (time - bars[left]!.time) / duration;
}

export function drawingPoint(row: DrawingRow, bars: NativeResult["bars"], pine: boolean): { x: number; y: number } | null {
  const x = drawingIndex(row.x, row.xloc, bars, pine);
  let y = drawingNumber(row.y);
  const anchor = bars[Math.max(0, Math.min(bars.length - 1, Math.round(x ?? 0)))];
  if (anchor && drawingText(row.yloc).endsWith("abovebar")) y = anchor.high + Math.max(anchor.high-anchor.low, Math.abs(anchor.high)*.005)*.2;
  if (anchor && drawingText(row.yloc).endsWith("belowbar")) y = anchor.low - Math.max(anchor.high-anchor.low, Math.abs(anchor.low)*.005)*.2;
  return x === undefined || y === undefined ? null : { x, y };
}

export function drawingCellSpan(row: number, column: number, merges: DrawingRow[]): { hidden: boolean; rowSpan: number; colSpan: number } {
  for (const merge of merges) {
    const top = drawingNumber(merge.startrow), left = drawingNumber(merge.startcolumn);
    const bottom = drawingNumber(merge.endrow), right = drawingNumber(merge.endcolumn);
    if (top === undefined || left === undefined || bottom === undefined || right === undefined) continue;
    if (row >= top && row <= bottom && column >= left && column <= right)
      return { hidden: row !== top || column !== left, rowSpan: bottom-top+1, colSpan: right-left+1 };
  }
  return { hidden: false, rowSpan: 1, colSpan: 1 };
}
