import {
  axisTimeKey,
  findNumericDisplayIndexForTimeAnchor,
  mapSourceViewportAnchorToDisplayLogicalRange,
  sourceTimeFromAxisTime,
  sourceTimeFromDisplayRow,
  sourceTimeRangeFromDisplayRow,
} from "./axisTime.js";
import type {
  AxisTime,
  DisplayRow,
  LogicalRange,
  SurfaceViewportSnapshot,
} from "./chartRepresentationTypes.js";
import { addUtcCalendarMonths, createIntervalTimeline } from "../../utils/intervalTimeline.js";

import { createViewportTimeScale, type ViewportTimeRow } from "./viewportTimeScale.js";

export const SURFACE_VIEWPORT_CACHE_LIMIT = 32;

const VIEWPORT_GEOMETRY_EPSILON = 1e-6;

export function surfaceViewportOwnsRestore(snapshot: SurfaceViewportSnapshot | null | undefined): boolean {
  return Boolean(snapshot && (snapshot.transferredFromDatasetKey !== undefined
    || snapshot.preserveSourceRange || snapshot.preserveGeometry));
}

/** Capture elapsed axis time, including fractional edges and future carriers. */
export function sourceRangeFromLogicalRows(
  rows: readonly DisplayRow[], logicalRange: unknown, sourceInterval?: unknown,
  axisCarrierRows?: readonly ViewportTimeRow[],
): LogicalRange | null {
  const logical = finiteRange(logicalRange);
  return logical ? createViewportTimeScale(rows, sourceInterval, axisCarrierRows)?.sourceRange(logical) ?? null : null;
}

function finiteRange(range: unknown): LogicalRange | null {
  const record = range && typeof range === "object"
    ? range as Record<string, unknown>
    : null;
  const from = Number(record?.from);
  const to = Number(record?.to);
  return Number.isFinite(from) && Number.isFinite(to) && from <= to
    ? { from, to }
    : null;
}

function stableAxisTime(time: AxisTime): AxisTime {
  return time && typeof time === "object" ? { ...time } : time;
}

export function buildSurfaceViewportCacheKey(
  datasetKey: unknown,
  surfaceConfigKey: unknown,
): string | null {
  if (!datasetKey || !surfaceConfigKey) return null;
  return JSON.stringify([datasetKey, surfaceConfigKey]);
}

export function bindSurfaceViewportSourceAnchor(
  captured: SurfaceViewportSnapshot | null | undefined,
  source: SurfaceViewportSnapshot | null | undefined,
): SurfaceViewportSnapshot | null {
  if (!captured || !source || captured.datasetKey !== source.datasetKey) return captured ?? null;
  // A same-period return can restore geometry around a real source anchor.
  // Newly loaded history then replaces the formerly estimated left-edge date.
  if (source.preserveGeometry) {
    return {
      ...captured,
      anchorTime: source.anchorTime,
      anchorSourceTime: source.anchorSourceTime,
      logicalSpan: source.logicalSpan,
      screenOffset: source.screenOffset,
      estimatedLeftEdge: true,
      preserveGeometry: true,
    };
  }
  return {
    ...captured,
    anchorSourceTime: source.anchorSourceTime,
    sourceRange: source.sourceRange ?? captured.sourceRange,
    ...(source.transferredFromDatasetKey === undefined ? {} : { transferredFromDatasetKey: source.transferredFromDatasetKey }),
    ...(source.preserveSourceRange ? { preserveSourceRange: true } : {}),
  };
}

export function preserveBoundSurfaceViewportSourceAnchor(
  captured: SurfaceViewportSnapshot | null | undefined,
  bound: SurfaceViewportSnapshot | null | undefined,
): SurfaceViewportSnapshot | null {
  if (!captured || !bound
    || captured.datasetKey !== bound.datasetKey
    || captured.surfaceConfigKey !== bound.surfaceConfigKey
    || captured.axisMode !== bound.axisMode) return captured ?? null;
  // Once the owned geometry has been rendered, a new period command captures
  // its actual dates, including newly loaded history, rather than old estimates.
  if (bound.preserveGeometry) return captured;
  // The surface clears an explicit bound on user navigation, linked navigation
  // or follow-latest. Until then, late auxiliary series may rebase LWC's shared
  // logical axis; that internal geometry change must not become a new intent.
  const ownsSourceRange = bound.transferredFromDatasetKey !== undefined || bound.preserveSourceRange;
  if (!ownsSourceRange && (axisTimeKey(captured.anchorTime) !== axisTimeKey(bound.anchorTime)
    || Math.abs(captured.logicalSpan - bound.logicalSpan) > VIEWPORT_GEOMETRY_EPSILON
    || Math.abs(captured.screenOffset - bound.screenOffset) > VIEWPORT_GEOMETRY_EPSILON)) {
    return captured ?? null;
  }
  return {
    ...captured,
    anchorSourceTime: bound.anchorSourceTime,
    sourceRange: bound.sourceRange ?? captured.sourceRange,
    ...(bound.transferredFromDatasetKey === undefined ? {} : { transferredFromDatasetKey: bound.transferredFromDatasetKey }),
    ...(bound.preserveSourceRange ? { preserveSourceRange: true } : {}),
  };
}

/**
 * Capture a projection-safe horizontal viewport.
 *
 * The anchor is always a real display row, even when the right edge is in the
 * future whitespace carrier. `screenOffset` then preserves that whitespace.
 */
export function buildSurfaceViewportSnapshot({
  axisMode,
  barSpacing,
  datasetKey,
  displayRows = [],
  logicalRange,
  sourceRange = null,
  surfaceConfigKey,
}: {
  axisMode?: unknown;
  barSpacing?: unknown;
  datasetKey?: unknown;
  displayRows?: readonly DisplayRow[];
  logicalRange?: unknown;
  sourceRange?: unknown;
  surfaceConfigKey?: unknown;
} = {}): SurfaceViewportSnapshot | null {
  const logical = finiteRange(logicalRange);
  if (!logical || displayRows.length === 0) return null;

  const lastIndex = displayRows.length - 1;
  const anchorIndex = Math.max(0, Math.min(lastIndex, Math.round(logical.to)));
  const anchorRow = displayRows[anchorIndex];
  if (!anchorRow) return null;
  const anchorTime = anchorRow.time;
  // A display bucket can represent several revealed source bars. Prefer its
  // lineage tail over the bucket-open axis coordinate so a 1m -> 15m -> 1m
  // round trip does not degrade 12:07 into 12:00.
  const anchorSourceTime = sourceTimeFromDisplayRow(anchorRow)
    ?? sourceTimeFromAxisTime(anchorTime);
  if (anchorTime == null || anchorSourceTime === null || !Number.isFinite(anchorSourceTime)) {
    return null;
  }

  const normalizedSourceRange = finiteRange(sourceRange);
  const normalizedBarSpacing = Number(barSpacing);
  return {
    anchorSourceTime,
    anchorTime: stableAxisTime(anchorTime),
    axisMode,
    barSpacing: Number.isFinite(normalizedBarSpacing) && normalizedBarSpacing > 0
      ? normalizedBarSpacing
      : null,
    datasetKey,
    logicalSpan: logical.to - logical.from,
    estimatedLeftEdge: axisMode === "derived-ordinal" && logical.from < 0,
    screenOffset: anchorIndex - logical.to,
    sourceRange: normalizedSourceRange,
    surfaceConfigKey,
  };
}

/** An unchanged period round trip must not turn unloaded left padding into a
 * zoom command when history arrives. Preserve the remembered real anchor and
 * pixel density. A navigation in the other period changes the source range
 * and continues to use the incoming transfer instead.
 */
export function selectPeriodViewportRestore(
  transferred: SurfaceViewportSnapshot | null,
  remembered: SurfaceViewportSnapshot | null,
): SurfaceViewportSnapshot | null {
  if (!transferred || !remembered) return transferred ?? remembered;
  if (remembered.axisMode !== "derived-ordinal" || !remembered.estimatedLeftEdge
    || remembered.datasetKey !== transferred.datasetKey
    || remembered.surfaceConfigKey !== transferred.surfaceConfigKey
    || !remembered.sourceRange || !transferred.sourceRange) return transferred;
  if (Math.abs(remembered.sourceRange.from - transferred.sourceRange.from) > VIEWPORT_GEOMETRY_EPSILON
    || Math.abs(remembered.sourceRange.to - transferred.sourceRange.to) > VIEWPORT_GEOMETRY_EPSILON) return transferred;
  return { ...remembered, transferredFromDatasetKey: undefined, preserveSourceRange: false, preserveGeometry: true };
}

/**
 * Rebuild a snapshot on the current display projection. Returning to the same
 * surface uses the full ordinal identity. Period transfers retain elapsed
 * axis time, including after sparse target data is filled by history.
 */
export function planSurfaceViewportRestore(
  displayRows: readonly DisplayRow[],
  snapshot: SurfaceViewportSnapshot | null | undefined,
  {
  axisMode,
  datasetKey,
  sourceInterval,
  surfaceConfigKey,
  axisCarrierRows,
  }: {
    axisMode?: unknown;
    datasetKey?: unknown;
    sourceInterval?: unknown;
    surfaceConfigKey?: unknown;
    axisCarrierRows?: readonly ViewportTimeRow[] | undefined;
  } = {},
): { barSpacing: number | null; logicalRange: LogicalRange; sameSurface: boolean } | null {
  // Sparse P&F/Kagi seeds can have source bars but no display rows. Passing a
  // null range to the controller fits content and reports success, which would
  // consume the transfer before history has produced a restorable surface.
  if (!snapshot || snapshot.datasetKey !== datasetKey || displayRows.length === 0) return null;
  const sameSurface = snapshot.surfaceConfigKey === surfaceConfigKey
    && snapshot.axisMode === axisMode;
  if (axisMode === "derived-ordinal"
    && (snapshot.transferredFromDatasetKey !== undefined || snapshot.preserveSourceRange)
    && snapshot.sourceRange && snapshot.sourceRange.to > snapshot.sourceRange.from) {
    const range = createViewportTimeScale(displayRows, sourceInterval, axisCarrierRows)?.logicalRange(snapshot.sourceRange);
    if (range) return { barSpacing: null, logicalRange: range, sameSurface: false };
  }
  // Across periods, retain elapsed market time rather than the old count of
  // candles. Interpolate on the target grid, including calendar intervals.
  if (axisMode === "time" && snapshot.transferredFromDatasetKey !== undefined
    && snapshot.sourceRange && snapshot.sourceRange.to > snapshot.sourceRange.from
    && displayRows.length >= 2) {
    const timeline = createIntervalTimeline(sourceInterval);
    const locate = (time: number): number | null => {
      const first = displayRows[0]?.time;
      const last = displayRows.at(-1)?.time;
      if (timeline && typeof first === "number" && typeof last === "number"
        && (time < first || time >= last)) {
        const anchor = time < first ? first : last;
        const anchorIndex = time < first ? 0 : displayRows.length - 1;
        if (timeline.spec.monthCount) {
          const target = new Date(time * 1000);
          const origin = new Date(anchor * 1000);
          const months = (target.getUTCFullYear() - origin.getUTCFullYear()) * 12
            + target.getUTCMonth() - origin.getUTCMonth();
          const offset = Math.floor(months / timeline.spec.monthCount);
          const left = addUtcCalendarMonths(anchor, offset * timeline.spec.monthCount);
          const right = addUtcCalendarMonths(anchor, (offset + 1) * timeline.spec.monthCount);
          if (left != null && right != null && right > left) {
            return anchorIndex + offset + (time - left) / (right - left);
          }
        } else {
          const width = timeline.spec.widthSeconds
            ?? (timeline.spec.weekCount ? timeline.spec.weekCount * 604800 : null);
          if (width && width > 0) return anchorIndex + (time - anchor) / width;
        }
      }
      const index = Math.min(displayRows.length - 2, findNumericDisplayIndexForTimeAnchor(displayRows, time));
      if (index < 0) return null;
      const left = displayRows[index]?.time;
      const right = displayRows[index + 1]?.time;
      if (typeof left !== "number" || typeof right !== "number" || right <= left) return null;
      return index + (time - left) / (right - left);
    };
    const from = locate(snapshot.sourceRange.from);
    const to = locate(snapshot.sourceRange.to);
    if (from !== null && to !== null && to > from) {
      return { barSpacing: null, logicalRange: { from, to }, sameSurface: false };
    }
  }
  // Source-bar density can dwarf a sparse synthetic projection. Only adapt
  // during a representation/dataset transfer; an exact-surface user zoom is
  // intentional and must survive restoration unchanged.
  const adaptSparseProjection = axisMode === "derived-ordinal"
    && (!sameSurface || snapshot.transferredFromDatasetKey !== undefined)
    && displayRows.length > 0
    && snapshot.logicalSpan > displayRows.length;
  const logicalSpan = adaptSparseProjection ? Math.max(1, displayRows.length) : snapshot.logicalSpan;
  const logicalRange = mapSourceViewportAnchorToDisplayLogicalRange(displayRows, {
    anchorTime: sameSurface ? snapshot.anchorTime : snapshot.anchorSourceTime,
    sourceTime: snapshot.anchorSourceTime,
    logicalSpan,
    screenOffset: adaptSparseProjection
      ? snapshot.screenOffset * logicalSpan / snapshot.logicalSpan
      : snapshot.screenOffset,
  });
  if (!logicalRange) return null;
  return {
    barSpacing: sameSurface && !adaptSparseProjection ? snapshot.barSpacing : null,
    logicalRange,
    sameSurface,
  };
}

export function rememberSurfaceViewport(
  cache: Map<string, SurfaceViewportSnapshot>,
  snapshot: SurfaceViewportSnapshot | null | undefined,
  {
  limit = SURFACE_VIEWPORT_CACHE_LIMIT,
  }: { limit?: unknown } = {},
): boolean {
  const key = buildSurfaceViewportCacheKey(
    snapshot?.datasetKey,
    snapshot?.surfaceConfigKey,
  );
  if (!(cache instanceof Map) || !key || !snapshot) return false;

  cache.delete(key);
  cache.set(key, snapshot);
  const safeLimit = Math.max(1, Math.floor(Number(limit)) || SURFACE_VIEWPORT_CACHE_LIMIT);
  while (cache.size > safeLimit) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
  return true;
}

export function selectSurfaceViewportSnapshot(
  cache: Map<string, SurfaceViewportSnapshot>,
  {
  datasetKey,
  outgoingSnapshot = null,
  surfaceConfigKey,
  }: {
    datasetKey?: unknown;
    outgoingSnapshot?: SurfaceViewportSnapshot | null;
    surfaceConfigKey?: unknown;
  } = {},
): {
  snapshot: SurfaceViewportSnapshot | null;
  source: "remembered" | "transfer" | "none";
} {
  const key = buildSurfaceViewportCacheKey(datasetKey, surfaceConfigKey);
  const remembered = cache instanceof Map && key ? cache.get(key) : null;
  if (remembered) return { snapshot: remembered, source: "remembered" };
  if (outgoingSnapshot?.datasetKey === datasetKey) {
    return { snapshot: outgoingSnapshot, source: "transfer" };
  }
  return { snapshot: null, source: "none" };
}

/**
 * Explicitly carry a captured viewport across a dataset identity change.
 *
 * Dataset isolation remains the default: a transfer is accepted only when it
 * was captured from the currently-owned outgoing dataset. Callers must opt in
 * at the transition boundary and provide the exact incoming dataset key.
 */
export function transferSurfaceViewportSnapshot(
  snapshot: SurfaceViewportSnapshot | null | undefined,
  {
    fromDatasetKey,
    toDatasetKey,
  }: {
    fromDatasetKey?: unknown;
    toDatasetKey?: unknown;
  } = {},
): SurfaceViewportSnapshot | null {
  if (!snapshot
    || !fromDatasetKey
    || !toDatasetKey
    || fromDatasetKey === toDatasetKey
    || snapshot.datasetKey !== fromDatasetKey) return null;
  return {
    ...snapshot,
    // Axis coordinates are dataset-local (a coarse bucket open or an ordinal
    // order). Cross-dataset restoration must resolve from stable source time.
    anchorTime: snapshot.anchorSourceTime,
    transferredFromDatasetKey: fromDatasetKey,
    datasetKey: toDatasetKey,
  };
}

/**
 * A cross-dataset transfer must not snap to the nearest edge while the target
 * interval is still publishing or paging the rows around the captured anchor.
 */
export function surfaceViewportHasAnchorCoverage(
  displayRows: readonly DisplayRow[] | null | undefined,
  snapshot: SurfaceViewportSnapshot | null | undefined,
  { sourceInterval }: { sourceInterval?: unknown } = {},
): boolean {
  const anchor = Number(snapshot?.anchorSourceTime);
  if (!displayRows?.length || !Number.isFinite(anchor)) return false;

  const timeline = createIntervalTimeline(sourceInterval);
  for (const row of displayRows) {
    const range = sourceTimeRangeFromDisplayRow(row);
    if (!range) continue;
    if (range.from <= anchor && anchor <= range.to) return true;
    // Source candles normally carry only their bucket-open timestamp. A
    // captured 12:07 anchor is covered by a loaded 12:05 five-minute candle,
    // even though no target candle opens at 12:07. Use the declared grid, not
    // the next available row: missing sessions/intervals must remain gaps.
    const end = range.from === range.to ? timeline?.next(range.from) : null;
    if (end != null && range.from <= anchor && anchor < end) return true;
  }
  return false;
}
