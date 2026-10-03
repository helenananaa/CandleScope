import {
  alignIndicatorBgcolorsToTimes,
  alignIndicatorLinesToTimes,
  alignIndicatorMarkersToTimes,
  buildAllowedTimeKeys,
} from "../chart-adapter/chartSeriesData.js";
import type { IndicatorSubPane } from "../features/indicators/indicatorPaneProjection.js";
import type {
  IndicatorBgColor, IndicatorFill, IndicatorHLine, IndicatorLine, IndicatorMarker,
} from "../features/indicators/indicatorTypes.js";

// Build one ordered, time-aligned render description per pane. Filtering caches
// live here so unrelated panes and indicator ids cannot leak annotations or fills.
export interface PaneDescriptor {
  id: string;
  paneIndex: number;
  label: string;
  lines: ReturnType<typeof alignIndicatorLinesToTimes>;
  markers: ReturnType<typeof alignIndicatorMarkersToTimes>;
  fills: IndicatorFill[];
  hlines: IndicatorHLine[];
  bgcolors: ReturnType<typeof alignIndicatorBgcolorsToTimes>;
}

function paneKeyForItem(item: { pane?: string; indicatorId?: string } | null | undefined): string {
  const pane = item?.pane || "main";
  if (pane === "main") return "main";
  if (!item?.indicatorId) return pane;
  return `${pane}-${item.indicatorId}`;
}

const paneItemFilterCache = new WeakMap<object, Map<string, readonly unknown[]>>();

function filterItemsForPane<T extends { pane?: string; indicatorId?: string }>(
  items: readonly T[] | null | undefined,
  paneId: string,
): T[] {
  if (!items) return [];
  const cacheKey = items as object;
  let byPane = paneItemFilterCache.get(cacheKey);
  if (!byPane) {
    byPane = new Map();
    paneItemFilterCache.set(cacheKey, byPane);
  }
  const cached = byPane.get(paneId);
  if (cached) return cached as T[];
  const filtered = items.filter((item) => paneKeyForItem(item) === paneId);
  byPane.set(paneId, filtered);
  return filtered;
}

function filterFillsForLines(
  fills: readonly IndicatorFill[] | null | undefined,
  lines: readonly { id?: string; indicatorId?: string }[] | null | undefined,
): IndicatorFill[] {
  const lineKeys = new Set();
  for (const line of lines || []) {
    if (!line?.id) continue;
    lineKeys.add(`${line.indicatorId || ""}:${line.id}`);
  }
  return (fills || []).filter((fill) => (
    lineKeys.has(`${fill.indicatorId || ""}:${fill.plot1_id}`)
    && lineKeys.has(`${fill.indicatorId || ""}:${fill.plot2_id}`)
  ));
}

export function buildPaneDescriptors({
  dataTimeSet,
  intervalSeconds,
  mainOverlayLines,
  paneOrder,
  subPanes,
  indicatorMarkers,
  indicatorFills,
  indicatorHlines,
  indicatorBgcolors,
}: {
  dataTimeSet: ReadonlySet<number>;
  intervalSeconds: number | null;
  mainOverlayLines: IndicatorLine[];
  paneOrder: readonly string[];
  subPanes: IndicatorSubPane[];
  indicatorMarkers: IndicatorMarker[];
  indicatorFills: IndicatorFill[];
  indicatorHlines: IndicatorHLine[];
  indicatorBgcolors: IndicatorBgColor[];
}): PaneDescriptor[] {
  const allowedTimeKeys = buildAllowedTimeKeys(dataTimeSet);
  const mainLines = alignIndicatorLinesToTimes(
    mainOverlayLines,
    dataTimeSet,
    allowedTimeKeys,
    intervalSeconds,
  );
  const descriptors: PaneDescriptor[] = [{
    id: "main",
    paneIndex: 0,
    label: "",
    lines: mainLines,
    markers: alignIndicatorMarkersToTimes(filterItemsForPane(indicatorMarkers, "main"), dataTimeSet, allowedTimeKeys),
    fills: filterFillsForLines(indicatorFills, mainLines),
    hlines: filterItemsForPane(indicatorHlines, "main"),
    bgcolors: alignIndicatorBgcolorsToTimes(filterItemsForPane(indicatorBgcolors, "main"), dataTimeSet, allowedTimeKeys),
  }];

  for (const [index, subPane] of subPanes.entries()) {
    const lines = alignIndicatorLinesToTimes(
      subPane.lines,
      dataTimeSet,
      allowedTimeKeys,
      intervalSeconds,
    );
    descriptors.push({
      id: subPane.id,
      paneIndex: index + 1,
      label: subPane.label,
      lines,
      markers: alignIndicatorMarkersToTimes(filterItemsForPane(indicatorMarkers, subPane.id), dataTimeSet, allowedTimeKeys),
      fills: filterFillsForLines(indicatorFills, lines),
      hlines: filterItemsForPane(indicatorHlines, subPane.id),
      bgcolors: alignIndicatorBgcolorsToTimes(filterItemsForPane(indicatorBgcolors, subPane.id), dataTimeSet, allowedTimeKeys),
    });
  }

  const descriptorById = new Map(descriptors.map((descriptor) => [descriptor.id, descriptor]));
  return paneOrder.flatMap((paneId, paneIndex) => {
    const descriptor = descriptorById.get(paneId);
    return descriptor ? [{ ...descriptor, paneIndex }] : [];
  });
}
