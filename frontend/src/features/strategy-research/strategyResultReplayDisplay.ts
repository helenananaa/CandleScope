import type { BacktestResultReplayBar, BacktestResultReplayCursor, BacktestResultReplayFrame, BacktestResultReplayNote } from "../backtest/backtestTypes.js";

export type ReplayChartSlot = "primary" | "comparison";
export type ReplayChartDisplay = {
  candleStyle: "solid" | "hollow";
  upColor: string;
  downColor: string;
  fills: boolean;
  notes: boolean;
};
type DisplayLink = "chartStyle" | "fills" | "notes";
export type ReplayDisplay = Record<ReplayChartSlot, ReplayChartDisplay> & {
  links: Record<DisplayLink, boolean>;
};

const defaultChart: ReplayChartDisplay = { candleStyle: "solid", upColor: "#159b84", downColor: "#df595e", fills: true, notes: true };
export const DEFAULT_REPLAY_DISPLAY: ReplayDisplay = {
  primary: defaultChart,
  comparison: defaultChart,
  links: { chartStyle: false, fills: false, notes: false },
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
  };
}

export function readReplayDisplays(value: unknown): Record<string, ReplayDisplay> | undefined {
  const entries = Object.entries(record(value)).filter(([key]) => /^bt_[\w-]+:sha256:[a-f0-9]{64}:sha256:[a-f0-9]{64}$/.test(key));
  if (entries.length === 0) return undefined;
  return Object.fromEntries(entries.map(([key, raw]) => {
    const display = record(raw);
    const links = record(display.links);
    return [key, { primary: chartDisplay(display.primary), comparison: chartDisplay(display.comparison),
      links: { chartStyle: links.chartStyle === true, fills: links.fills === true, notes: links.notes === true } }];
  }));
}

export function changeReplayChartDisplay<K extends keyof ReplayChartDisplay>(
  display: ReplayDisplay, slot: ReplayChartSlot, field: K, value: ReplayChartDisplay[K],
): ReplayDisplay {
  if (display[slot][field] === value) return display;
  const other = slot === "primary" ? "comparison" : "primary";
  const channel: DisplayLink = field === "fills" ? "fills" : field === "notes" ? "notes" : "chartStyle";
  return { ...display, [slot]: { ...display[slot], [field]: value },
    ...(display.links[channel] ? { [other]: { ...display[other], [field]: value } } : {}) };
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
