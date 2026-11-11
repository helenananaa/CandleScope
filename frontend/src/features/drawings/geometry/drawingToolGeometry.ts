import type { ScreenPoint } from "../drawingTypes.js";

/**
 * Screen-space geometry shared by the scene projector, the dynamic overlay and
 * tests. Inputs are already-projected CSS pixel coordinates; nothing here reads
 * prices or times, so the same result holds on linear and logarithmic scales.
 */

type Segment = readonly [ScreenPoint, ScreenPoint];

export interface ParallelChannelScreenGeometry {
  readonly baseline: Segment;
  readonly parallel: Segment;
  readonly midline: Segment;
  /** Where the width handle is drawn: the middle of the parallel line. */
  readonly offsetHandle: ScreenPoint;
}

function finitePoint(point: ScreenPoint | null | undefined): point is ScreenPoint {
  return !!point && Number.isFinite(point.x) && Number.isFinite(point.y);
}

/**
 * The parallel line passes through `through` and keeps the baseline's slope.
 * It is the baseline translated vertically, so its ends stay above/below the
 * baseline ends. A vertical baseline cannot be translated vertically onto an
 * arbitrary point, so that degenerate case translates horizontally instead.
 */
export function parallelChannelScreenGeometry(
  start: ScreenPoint | null | undefined,
  end: ScreenPoint | null | undefined,
  through: ScreenPoint | null | undefined,
): ParallelChannelScreenGeometry | null {
  if (!finitePoint(start) || !finitePoint(end) || !finitePoint(through)) return null;
  const dx = end.x - start.x;
  let parallelStart: ScreenPoint;
  let parallelEnd: ScreenPoint;
  if (Math.abs(dx) < 1e-9) {
    const offsetX = through.x - start.x;
    parallelStart = { x: start.x + offsetX, y: start.y };
    parallelEnd = { x: end.x + offsetX, y: end.y };
  } else {
    const baselineY = start.y + ((through.x - start.x) * (end.y - start.y)) / dx;
    const offsetY = through.y - baselineY;
    parallelStart = { x: start.x, y: start.y + offsetY };
    parallelEnd = { x: end.x, y: end.y + offsetY };
  }
  if (!finitePoint(parallelStart) || !finitePoint(parallelEnd)) return null;
  const midpoint = (a: ScreenPoint, b: ScreenPoint): ScreenPoint => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  return Object.freeze({
    baseline: Object.freeze([Object.freeze({ ...start }), Object.freeze({ ...end })] as const),
    parallel: Object.freeze([Object.freeze(parallelStart), Object.freeze(parallelEnd)] as const),
    midline: Object.freeze([
      Object.freeze(midpoint(start, parallelStart)),
      Object.freeze(midpoint(end, parallelEnd)),
    ] as const),
    offsetHandle: Object.freeze(midpoint(parallelStart, parallelEnd)),
  });
}

export interface ArrowHeadScreenGeometry {
  readonly tip: ScreenPoint;
  readonly left: ScreenPoint;
  readonly right: ScreenPoint;
  /** Where the shaft should stop so a thick line does not poke through the tip. */
  readonly shaftEnd: ScreenPoint;
}

/** Arrowhead length in CSS px for a stroke width; grows with width, stays readable when thin. */
export function arrowHeadLengthCssPx(lineWidthCssPx: number): number {
  const width = Number.isFinite(lineWidthCssPx) && lineWidthCssPx > 0 ? lineWidthCssPx : 1;
  return Math.max(10, width * 4);
}

/**
 * Filled triangular head at `to`, pointing away from `from`. Returns null for
 * a zero-length segment, which has no direction to point in.
 */
export function arrowHeadScreenGeometry(
  from: ScreenPoint | null | undefined,
  to: ScreenPoint | null | undefined,
  lineWidthCssPx: number,
): ArrowHeadScreenGeometry | null {
  if (!finitePoint(from) || !finitePoint(to)) return null;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy);
  if (!Number.isFinite(length) || length < 1e-6) return null;
  const ux = dx / length;
  const uy = dy / length;
  // Never let the head swallow more than the whole shaft.
  const headLength = Math.min(arrowHeadLengthCssPx(lineWidthCssPx), length);
  const halfWidth = headLength * 0.5;
  const baseX = to.x - ux * headLength;
  const baseY = to.y - uy * headLength;
  return Object.freeze({
    tip: Object.freeze({ x: to.x, y: to.y }),
    left: Object.freeze({ x: baseX - uy * halfWidth, y: baseY + ux * halfWidth }),
    right: Object.freeze({ x: baseX + uy * halfWidth, y: baseY - ux * halfWidth }),
    shaftEnd: Object.freeze({ x: to.x - ux * headLength * 0.6, y: to.y - uy * headLength * 0.6 }),
  });
}

/** Ray-casting point-in-polygon; vertices are taken in order and closed implicitly. */
export function pointInScreenPolygon(x: number, y: number, vertices: readonly ScreenPoint[]): boolean {
  if (!Number.isFinite(x) || !Number.isFinite(y) || vertices.length < 3) return false;
  let inside = false;
  for (let index = 0, previous = vertices.length - 1; index < vertices.length; previous = index, index += 1) {
    const current = vertices[index];
    const prior = vertices[previous];
    if (!finitePoint(current) || !finitePoint(prior)) return false;
    if ((current.y > y) !== (prior.y > y)
      && x < ((prior.x - current.x) * (y - current.y)) / (prior.y - current.y) + current.x) {
      inside = !inside;
    }
  }
  return inside;
}
