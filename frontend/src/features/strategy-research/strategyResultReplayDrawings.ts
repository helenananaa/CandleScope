import type { BacktestResultReplayBar } from "../backtest/backtestTypes.js";
import type { ReplayChartSlot } from "./strategyResultReplayDisplay.js";

export type ReplayDrawingPoint = { timeMs: number; price: number };
export type ReplayDrawing = {
  id: string;
  cursor: number;
  points: readonly [ReplayDrawingPoint] | readonly [ReplayDrawingPoint, ReplayDrawingPoint];
};
export type ReplayDrawings = Record<string, readonly ReplayDrawing[]>;
export type ReplayDrawingEdit = { add: ReplayDrawing } | { remove: string };

const MAX_SCOPES = 24;
const MAX_DRAWINGS = 64;
const ownerPattern = /^(?:run|local-[a-f0-9]{32}:sha256:[a-f0-9]{64})$/;
const scopePattern = /^(?:primary|comparison|extra1|extra2)\|(.+)$/;
const idPattern = /^[a-f0-9-]{36}$/;

export function replayDrawingOwner(chart: { dataset_id?: string; data_epoch?: string }): string | null {
  if (chart.dataset_id === undefined) return "run";
  const owner = `${chart.dataset_id}:${chart.data_epoch ?? ""}`;
  return ownerPattern.test(owner) ? owner : null;
}

export function replayDrawingScope(slot: ReplayChartSlot, owner: string): string {
  return `${slot}|${owner}`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readPoint(value: unknown): ReplayDrawingPoint | null {
  const { timeMs, price } = record(value);
  return typeof timeMs === "number" && Number.isSafeInteger(timeMs) && timeMs >= 0
    && typeof price === "number" && Number.isFinite(price) && price > 0 ? { timeMs, price } : null;
}

function readDrawing(value: unknown): ReplayDrawing | null {
  const { id, cursor, points } = record(value);
  if (typeof id !== "string" || !idPattern.test(id) || typeof cursor !== "number" || !Number.isSafeInteger(cursor)
    || cursor < 0 || !Array.isArray(points) || (points.length !== 1 && points.length !== 2)) return null;
  const first = readPoint(points[0]);
  if (!first) return null;
  if (points.length === 1) return { id, cursor, points: [first] };
  const second = readPoint(points[1]);
  return second ? { id, cursor, points: [first, second] } : null;
}

export function readReplayDrawings(value: unknown): ReplayDrawings {
  const documents: ReplayDrawings = {};
  for (const [scope, entries] of Object.entries(record(value))) {
    const owner = scopePattern.exec(scope)?.[1];
    if (!owner || !ownerPattern.test(owner) || !Array.isArray(entries)) continue;
    const drawings = new Map<string, ReplayDrawing>();
    for (const raw of entries.slice(0, MAX_DRAWINGS)) {
      const drawing = readDrawing(raw);
      if (drawing) drawings.set(drawing.id, drawing);
    }
    if (drawings.size) documents[scope] = [...drawings.values()];
    if (Object.keys(documents).length === MAX_SCOPES) break;
  }
  return documents;
}

export function editReplayDrawings(
  documents: ReplayDrawings, scopes: readonly string[], edit: ReplayDrawingEdit,
): ReplayDrawings | null {
  const next = { ...documents };
  for (const scope of new Set(scopes)) {
    const current = documents[scope] ?? [];
    if ("add" in edit) {
      if (current.length >= MAX_DRAWINGS) return null;
      next[scope] = [...current, edit.add];
    } else {
      const remaining = current.filter(drawing => drawing.id !== edit.remove);
      if (remaining.length) next[scope] = remaining;
      else delete next[scope];
    }
  }
  return Object.keys(next).length <= MAX_SCOPES ? next : null;
}

export function revealedReplayDrawings(
  drawings: readonly ReplayDrawing[], cursor: number, timeMs: number | null,
): readonly ReplayDrawing[] {
  return timeMs === null ? [] : drawings.filter(drawing =>
    drawing.cursor <= cursor && drawing.points.every(point => point.timeMs <= timeMs));
}

export function replayDrawingBarIndex(bars: readonly BacktestResultReplayBar[], timeMs: number): number {
  return bars.findIndex(bar => bar.open_time_ms <= timeMs && timeMs <= (bar.close_time_ms ?? bar.open_time_ms));
}
