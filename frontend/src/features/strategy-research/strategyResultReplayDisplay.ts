import { BACKTEST_REPLAY_EXTRA_SLOTS, type BacktestReplayChartOptions, type BacktestReplayExtraCharts, type BacktestReplayExtraSlot } from "../backtest/backtestTypes.js";
import type { BacktestResultReplayBar, BacktestResultReplayCursor, BacktestResultReplayFrame, BacktestResultReplayNote } from "../backtest/backtestTypes.js";
import { readReplayDrawings, type ReplayDrawings } from "./strategyResultReplayDrawings.js";

export type ReplayChartSlot = "primary" | "comparison" | BacktestReplayExtraSlot;
export type ReplayChartDisplay = {
  candleStyle: "solid" | "hollow";
  upColor: string;
  downColor: string;
  fills: boolean;
  notes: boolean;
  showMa: boolean;
  showDrawings: boolean;
};
type DisplayLink = "chartStyle" | "fills" | "notes" | "indicatorVisibility" | "drawings" | "drawingVisibility";
export type ReplayDisplay = Record<"primary" | "comparison", ReplayChartDisplay> &
  Partial<Record<BacktestReplayExtraSlot, ReplayChartDisplay>> & {
  references?: BacktestReplayExtraCharts;
  layout?: { primary: BacktestReplayChartOptions; comparison?: BacktestReplayChartOptions };
    drawings?: ReplayDrawings;
  links: Record<DisplayLink, boolean>;
};

const defaultChart: ReplayChartDisplay = {
  candleStyle: "solid", upColor: "#159b84", downColor: "#df595e", fills: true, notes: true, showMa: true, showDrawings: true,
};
export const DEFAULT_REPLAY_DISPLAY: ReplayDisplay = {
  primary: defaultChart,
  comparison: defaultChart,
  links: { chartStyle: false, fills: false, notes: false, indicatorVisibility: false, drawings: false, drawingVisibility: false },
};

export function replayDisplayKey(replay: Pick<BacktestResultReplayCursor, "runId" | "snapshotHash" | "reportHash">): string {
  return `${replay.runId}:${replay.snapshotHash}:${replay.reportHash}`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function chartDisplay(value: unknown): ReplayChartDisplay {
  const chart = record(value);
  const color = (candidate: unknown, fallback: string) =>
    typeof candidate === "string" && /^#[a-f0-9]{6}$/i.test(candidate) ? candidate : fallback;
  return {
    candleStyle: chart.candleStyle === "hollow" ? "hollow" : "solid",
    upColor: color(chart.upColor, defaultChart.upColor),
    downColor: color(chart.downColor, defaultChart.downColor),
    fills: typeof chart.fills === "boolean" ? chart.fills : defaultChart.fills,
    notes: typeof chart.notes === "boolean" ? chart.notes : defaultChart.notes,
    showMa: typeof chart.showMa === "boolean" ? chart.showMa : defaultChart.showMa,
    showDrawings: typeof chart.showDrawings === "boolean" ? chart.showDrawings : defaultChart.showDrawings,
  };
}

function readChartOptions(value: unknown): BacktestReplayChartOptions | undefined {
  const entry = record(value);
  if (typeof entry.interval !== "string" || entry.interval.length < 2 || entry.interval.length > 64) return;
  const dataset = record(entry.dataset);
  if (entry.dataset !== undefined && (typeof dataset.datasetId !== "string" || !/^local-[0-9a-f]{32}$/.test(dataset.datasetId)
    || typeof dataset.dataEpoch !== "string" || !/^sha256:[a-f0-9]{64}$/.test(dataset.dataEpoch))) return;
  return { interval: entry.interval,
    ...(typeof dataset.datasetId === "string" && typeof dataset.dataEpoch === "string"
      ? { dataset: { datasetId: dataset.datasetId, dataEpoch: dataset.dataEpoch } } : {}),
    ...(typeof entry.maPeriod === "number" && Number.isInteger(entry.maPeriod) && entry.maPeriod >= 1 && entry.maPeriod <= 500
      ? { maPeriod: entry.maPeriod } : {}),
  };
}

function readReferences(value: unknown): BacktestReplayExtraCharts {
  const settings = record(value);
  const charts: BacktestReplayExtraCharts = {};
  for (const slot of BACKTEST_REPLAY_EXTRA_SLOTS) {
    const chart = readChartOptions(settings[slot]);
    if (chart) charts[slot] = chart;
  }
  return charts;
}

export function replayLayout(request: BacktestResultReplayCursor): NonNullable<ReplayDisplay["layout"]> {
  return {
    primary: { interval: request.interval, ...(request.maPeriod === undefined ? {} : { maPeriod: request.maPeriod }) },
    ...(request.comparisonInterval ? { comparison: { interval: request.comparisonInterval,
      ...(request.comparisonDataset ? { dataset: request.comparisonDataset } : {}),
      ...(request.comparisonMaPeriod === undefined ? {} : { maPeriod: request.comparisonMaPeriod }),
    } } : {}),
  };
}

export function restoreReplayLayout(initial: BacktestResultReplayCursor, display: ReplayDisplay): BacktestResultReplayCursor {
  const request = { ...initial, ...(display.references ? { additionalCharts: display.references } : {}) };
  if (!display.layout) return request;
  const { primary, comparison } = display.layout;
  request.interval = primary.interval;
  delete request.maPeriod;
  delete request.comparisonInterval;
  delete request.comparisonDataset;
  delete request.comparisonMaPeriod;
  if (primary.maPeriod !== undefined) request.maPeriod = primary.maPeriod;
  if (comparison) {
    request.comparisonInterval = comparison.interval;
    if (comparison.dataset) request.comparisonDataset = comparison.dataset;
    if (comparison.maPeriod !== undefined) request.comparisonMaPeriod = comparison.maPeriod;
  }
  return request;
}

export function replayChartDisplay(display: ReplayDisplay, slot: ReplayChartSlot): ReplayChartDisplay {
  return display[slot] ?? defaultChart;
}

export function readReplayDisplays(value: unknown): Record<string, ReplayDisplay> | undefined {
  const entries = Object.entries(record(value)).filter(([key]) => /^bt_[\w-]+:sha256:[a-f0-9]{64}:sha256:[a-f0-9]{64}$/.test(key));
  if (entries.length === 0) return undefined;
  return Object.fromEntries(entries.map(([key, raw]) => {
    const display = record(raw);
    const links = record(display.links);
    const references = readReferences(display.references);
    const drawings = readReplayDrawings(display.drawings);
    const layout = record(display.layout);
    const primary = readChartOptions(layout.primary);
    const comparison = readChartOptions(layout.comparison);
    return [key, { primary: chartDisplay(display.primary), comparison: chartDisplay(display.comparison),
      ...(primary ? { layout: { primary, ...(comparison ? { comparison } : {}) } } : {}),
      ...(Object.keys(references).length ? { references } : {}),
      ...(Object.keys(drawings).length ? { drawings } : {}),
      ...Object.fromEntries(BACKTEST_REPLAY_EXTRA_SLOTS.filter(slot => display[slot] !== undefined)
        .map(slot => [slot, chartDisplay(display[slot])])),
      links: { chartStyle: links.chartStyle === true, fills: links.fills === true, notes: links.notes === true,
        indicatorVisibility: links.indicatorVisibility === true, drawings: links.drawings === true,
        drawingVisibility: links.drawingVisibility === true } }];
  }));
}

export function changeReplayChartDisplay<K extends keyof ReplayChartDisplay>(
  display: ReplayDisplay, slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K],
  activeSlots: readonly ReplayChartSlot[] = ["primary", "comparison"],
): ReplayDisplay {
  if (replayChartDisplay(display, slot)[field] === value) return display;
  const channel: DisplayLink = field === "showMa" ? "indicatorVisibility"
    : field === "showDrawings" ? "drawingVisibility" : field === "fills" || field === "notes" ? field : "chartStyle";
  const targets = display.links[channel] ? activeSlots : [slot];
  const next = { ...display };
  for (const target of targets) next[target] = { ...replayChartDisplay(display, target), [field]: value };
  return next;
}

type Fill = BacktestResultReplayFrame["fills"][number];
type Markers = { fills: Fill[]; notes: BacktestResultReplayNote[] };

export function replayChartMarkers(
  frame: BacktestResultReplayFrame,
  bars: readonly BacktestResultReplayBar[],
  belongsToRun: boolean,
  display: Pick<ReplayChartDisplay, "fills" | "notes">,
): Map<number, Markers> {
  const markers = new Map<number, Markers>();
  const boundary = frame.time_ms;
  if (!belongsToRun || boundary === null) return markers;
  const at = (time: number, cursor: number): Markers | undefined => {
    if (!Number.isSafeInteger(time) || !Number.isSafeInteger(cursor) || cursor < 1
      || cursor > frame.cursor || time > boundary) return undefined;
    const index = bars.findIndex(bar => bar.close_time_ms !== undefined
      && bar.open_time_ms <= time && time <= bar.close_time_ms);
    if (index === -1) return undefined;
    const existing = markers.get(index);
    if (existing) return existing;
    const next: Markers = { fills: [], notes: [] };
    markers.set(index, next);
    return next;
  };
  if (display.fills) for (const fill of frame.fills) at(fill.event_time_ms, fill.cursor)?.fills.push(fill);
  if (display.notes) for (const note of frame.notes ?? []) {
    if (note.time_ms !== null) at(note.time_ms, note.cursor)?.notes.push(note);
  }
  return markers;
}
