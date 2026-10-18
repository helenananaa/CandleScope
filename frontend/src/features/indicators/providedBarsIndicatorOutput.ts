import { createIndicatorOutputState } from "./indicatorOutputReducer.js";
import type {
  IndicatorAnnotationPoint, IndicatorBarColor, IndicatorBgColor, IndicatorDefinition,
  IndicatorFill, IndicatorHLine, IndicatorLine, IndicatorMarker, IndicatorOutputState,
  IndicatorSignal,
} from "./indicatorTypes.js";

function clampAnnotationPoints(
  points: readonly IndicatorAnnotationPoint[],
  visibleThroughSeconds: number,
): IndicatorAnnotationPoint[] {
  return points.flatMap((point) => {
    if (point.time !== undefined && point.time > visibleThroughSeconds) return [];
    return [{
      ...point,
      ...(point.endTime !== undefined && point.endTime > visibleThroughSeconds
        ? { endTime: visibleThroughSeconds }
        : {}),
    }];
  });
}

function clampLine(
  line: IndicatorLine,
  visibleThroughSeconds: number,
): IndicatorLine {
  return {
    ...line,
    data: line.data.filter((point) => point.time <= visibleThroughSeconds),
    ...(line.colorData === undefined || line.colorData === null
      ? {}
      : {
          colorData: line.colorData.filter(
            (point) => point.time <= visibleThroughSeconds,
          ),
        }),
  };
}

function clampMarkers(
  items: readonly IndicatorMarker[],
  visibleThroughSeconds: number,
): IndicatorMarker[] {
  return items.map((item) => ({
    ...item,
    data: clampAnnotationPoints(item.data, visibleThroughSeconds),
  }));
}

function clampFills(
  items: readonly IndicatorFill[],
  visibleThroughSeconds: number,
): IndicatorFill[] {
  return items.map((item) => ({
    ...item,
    ...(item.data === undefined
      ? {}
      : { data: clampAnnotationPoints(item.data, visibleThroughSeconds) }),
  }));
}

function clampHlines(
  items: readonly IndicatorHLine[],
  visibleThroughSeconds: number,
): IndicatorHLine[] {
  return items.map((item) => ({
    ...item,
    ...(item.data === undefined
      ? {}
      : { data: clampAnnotationPoints(item.data, visibleThroughSeconds) }),
  }));
}

function clampBgcolors(
  items: readonly IndicatorBgColor[],
  visibleThroughSeconds: number,
): IndicatorBgColor[] {
  return items.map((item) => ({
    ...item,
    ...(item.regions === undefined
      ? {}
      : { regions: clampAnnotationPoints(item.regions, visibleThroughSeconds) }),
    ...(item.data === undefined
      ? {}
      : { data: clampAnnotationPoints(item.data, visibleThroughSeconds) }),
  }));
}

function clampBarcolors(
  items: readonly IndicatorBarColor[],
  visibleThroughSeconds: number,
): IndicatorBarColor[] {
  return items.map((item) => ({
    ...item,
    data: item.data.filter((point) => point.time <= visibleThroughSeconds),
  }));
}

function clampSignals(
  items: readonly IndicatorSignal[],
  visibleThroughSeconds: number,
): IndicatorSignal[] {
  return items.map((item) => ({
    ...item,
    data: clampAnnotationPoints(item.data, visibleThroughSeconds),
  }));
}

export function clampProvidedBarsIndicatorOutput({
  activeIndicators,
  outputState,
  visibleThroughSeconds,
  outputBarTimes,
}: {
  activeIndicators: readonly IndicatorDefinition[];
  outputState: IndicatorOutputState;
  visibleThroughSeconds: number | null;
  /** The chart's own source times, independent from the calculation prefix. */
  outputBarTimes?: readonly number[];
}): {
  activeIndicators: IndicatorDefinition[];
  outputState: IndicatorOutputState;
} {
  if (visibleThroughSeconds === null || !Number.isFinite(visibleThroughSeconds)) {
    return {
      activeIndicators: activeIndicators.map((indicator) => ({
        ...indicator,
        ...(indicator.lines === undefined ? {} : { lines: [] }),
      })),
      outputState: {
        ...createIndicatorOutputState(),
        paramSchemas: outputState.paramSchemas,
      },
    };
  }
  const clamped = {
    activeIndicators: activeIndicators.map((indicator) => ({
      ...indicator,
      ...(indicator.lines === undefined
        ? {}
        : {
            lines: indicator.lines.map(
              (line) => clampLine(line, visibleThroughSeconds),
            ),
          }),
    })),
    outputState: {
      markers: clampMarkers(outputState.markers, visibleThroughSeconds),
      fills: clampFills(outputState.fills, visibleThroughSeconds),
      hlines: clampHlines(outputState.hlines, visibleThroughSeconds),
      bgcolors: clampBgcolors(outputState.bgcolors, visibleThroughSeconds),
      barcolors: clampBarcolors(outputState.barcolors, visibleThroughSeconds),
      signals: clampSignals(outputState.signals, visibleThroughSeconds),
      paramSchemas: outputState.paramSchemas,
    },
  };
  return outputBarTimes === undefined ? clamped : clipToSourceBars(clamped, outputBarTimes, visibleThroughSeconds);
}

/** Study warmup and shifted script output must not add timestamps to the chart. */
function clipToSourceBars(
  output: { activeIndicators: IndicatorDefinition[]; outputState: IndicatorOutputState },
  barTimes: readonly number[],
  boundary: number,
): typeof output {
  const times = [...new Set(barTimes.filter(time => Number.isFinite(time) && time <= boundary))].sort((a, b) => a - b);
  if (times.length === 0) return {
    activeIndicators: output.activeIndicators.map(indicator => ({ ...indicator, lines: [] })),
    outputState: { ...createIndicatorOutputState(), paramSchemas: output.outputState.paramSchemas },
  };
  const available = new Set(times);
  const contains = (point: { time: number }) => available.has(point.time);
  const lowerBound = (time: number) => {
    let low = 0, high = times.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (times[middle]! < time) low = middle + 1;
      else high = middle;
    }
    return low;
  };
  const annotations = (points: readonly IndicatorAnnotationPoint[]): IndicatorAnnotationPoint[] => points.flatMap(point => {
    const { time, endTime } = point;
    if (endTime === undefined) return time === undefined || available.has(time) ? [point] : [];
    if (!Number.isFinite(endTime) || (time !== undefined && !Number.isFinite(time))) return [];
    const first = time === undefined ? 0 : lowerBound(time);
    const endIndex = lowerBound(endTime);
    const last = times[endIndex] === endTime ? endIndex : endIndex - 1;
    if (first > last || first >= times.length || last < 0) return [];
    return [{ ...point, ...(time === undefined ? {} : { time: times[first]! }), endTime: times[last]! }];
  });
  const optionalAnnotations = <T extends { data?: IndicatorAnnotationPoint[] }>(items: readonly T[]): T[] => items.map(item => ({
    ...item, ...(item.data === undefined ? {} : { data: annotations(item.data) }),
  }));
  return {
    activeIndicators: output.activeIndicators.map(indicator => ({ ...indicator,
      ...(indicator.lines === undefined ? {} : { lines: indicator.lines.map(line => ({ ...line,
        data: line.data.filter(contains),
        ...(line.colorData === undefined || line.colorData === null ? {} : { colorData: line.colorData.filter(contains) }),
      })) }),
    })),
    outputState: {
      ...output.outputState,
      markers: optionalAnnotations(output.outputState.markers),
      fills: optionalAnnotations(output.outputState.fills),
      hlines: optionalAnnotations(output.outputState.hlines),
      bgcolors: optionalAnnotations(output.outputState.bgcolors).map(item => ({ ...item,
        ...(item.regions === undefined ? {} : { regions: annotations(item.regions) }),
      })),
      barcolors: output.outputState.barcolors.map(item => ({ ...item, data: item.data.filter(contains) })),
      signals: optionalAnnotations(output.outputState.signals),
    },
  };
}
