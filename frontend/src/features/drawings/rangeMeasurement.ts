import type { DrawingDataPoint, RangeMeasureType } from "./drawingTypes.js";

export interface RangeMeasurement {
  readonly priceDelta: number;
  readonly percentDelta: number | null;
  readonly elapsedSeconds: number;
}

/** Source time is elapsed wall time, including market closures; never a bar count. */
export function measureDrawingRange(points: readonly DrawingDataPoint[]): RangeMeasurement | null {
  const [a, b] = points;
  if (points.length !== 2 || !a || !b
    || typeof a.time !== "number" || typeof b.time !== "number"
    || ![a.time, b.time, a.price, b.price].every(Number.isFinite)) return null;
  const priceDelta = b.price - a.price;
  const elapsedSeconds = b.time - a.time;
  const percentDelta = a.price === 0 ? null : priceDelta / Math.abs(a.price) * 100;
  if (!Number.isFinite(priceDelta) || !Number.isFinite(elapsedSeconds)
    || (percentDelta !== null && !Number.isFinite(percentDelta))) return null;
  return Object.freeze({ priceDelta, percentDelta, elapsedSeconds });
}

function signed(value: number): string {
  const rounded = Number(value.toPrecision(8));
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function duration(seconds: number): string {
  let rest = Math.abs(seconds);
  const parts: string[] = [];
  for (const [size, unit] of [[86400, "d"], [3600, "h"], [60, "m"]] as const) {
    const count = Math.floor(rest / size);
    if (count) { parts.push(`${count}${unit}`); rest -= count * size; }
  }
  if (rest || !parts.length) parts.push(`${Number(rest.toPrecision(8))}s`);
  return `${seconds < 0 ? "−" : seconds > 0 ? "+" : ""}${parts.join(" ")}`;
}

export function rangeMeasurementLabel(value: RangeMeasurement, type: RangeMeasureType): string {
  const price = `Δ ${signed(value.priceDelta)} (${value.percentDelta === null ? "—" : `${signed(value.percentDelta)}%`})`;
  if (type === "price") return price;
  const time = `Δt ${duration(value.elapsedSeconds)}`;
  return type === "time" ? time : `${price} · ${time}`;
}
