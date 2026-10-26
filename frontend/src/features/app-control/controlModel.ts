import { canonicalizeIntervalValue } from "../../utils/intervals.js";
import type { ControlWorkspaceCommand } from "../chart-workspace/chartWorkspaceControl.js";

export interface ControlCellObservation {
  session: { exchange: string; marketType: string; symbol: string; interval: string };
  indicatorSignature: string;
  marketReady: boolean;
  indicatorsReady: boolean;
  barCount: number;
  loading: boolean;
  initialHistoryPending: boolean;
  loadingMoreLeft: boolean;
  paused: boolean;
  computing: boolean;
  indicatorErrors: string[];
  indicatorOutputPoints: number[];
  error: string | null;
}

export interface ControlRequest { id: string; instanceId?: string; method: string; params: unknown }
export interface ControlResult { state: "applied" | "ready" | "failed"; code?: string; message?: string; [key: string]: unknown }

export const CONTROL_INDICATORS = ["MA", "EMA", "RSI"] as const;
const layouts = ["single", "split-vertical", "split-horizontal", "quad"] as const;

function object(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected an object");
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => !allowed.includes(key))) throw new Error("Unknown parameter");
  return record;
}
function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/.test(value)) throw new Error("Invalid identifier");
  return value;
}

export function indicatorSignature(indicators: readonly { id: string; engineName?: string | null; params?: Record<string, unknown>; kind?: string; executionTarget?: string; visible?: boolean }[]): string {
  return JSON.stringify(indicators.map(({ id, engineName, params, kind, executionTarget, visible }) => [id, engineName, params ?? {}, kind, executionTarget, visible]));
}

/** Accepts only data, never scripts, paths, application settings or ambient capabilities. */
export function parseControlConfiguration(value: unknown): ControlWorkspaceCommand {
  const input = object(value, ["requestId", "workspaceId", "windowId", "expectedRevision", "layout", "charts"]);
  if (!Number.isSafeInteger(input.expectedRevision) || (input.expectedRevision as number) < 0) throw new Error("Invalid expectedRevision");
  if (input.layout !== undefined && !layouts.includes(input.layout as typeof layouts[number])) throw new Error("Unsupported layout");
  if (!Array.isArray(input.charts) || input.charts.length < 1 || input.charts.length > 4) throw new Error("Expected 1 to 4 charts");
  const requestId = identifier(input.requestId);
  const charts = input.charts.map((raw: unknown, index: number) => {
    const chart = object(raw, ["cellId", "session", "indicators"]);
    if (input.layout !== undefined && chart.cellId !== undefined) throw new Error("Layout charts are addressed by their ordered position");
    const session = object(chart.session, ["exchange", "marketType", "symbol", "interval"]);
    if (!["binance", "okx"].includes(String(session.exchange))) throw new Error("Unsupported exchange");
    if (!["spot", "futures"].includes(String(session.marketType))) throw new Error("Unsupported marketType");
    if (typeof session.symbol !== "string" || !/^[A-Z0-9][A-Z0-9_-]{0,63}$/.test(session.symbol)) throw new Error("Invalid symbol");
    const interval = canonicalizeIntervalValue(session.interval);
    if (!interval || interval !== session.interval) throw new Error("Use a canonical interval");
    if (!Array.isArray(chart.indicators) || chart.indicators.length > 8) throw new Error("Expected at most 8 indicators per chart");
    const indicators = chart.indicators.map((rawIndicator: unknown, indicatorIndex: number) => {
      const indicator = object(rawIndicator, ["name", "period"]);
      if (!CONTROL_INDICATORS.includes(indicator.name as typeof CONTROL_INDICATORS[number])) throw new Error("Unsupported indicator");
      if (!Number.isSafeInteger(indicator.period) || (indicator.period as number) < 1 || (indicator.period as number) > 5000) throw new Error("Invalid indicator period");
      return { id: `control-${requestId}-${index}-${indicatorIndex}`, name: String(indicator.name),
        engineName: String(indicator.name), kind: "builtin" as const, executionTarget: "local" as const,
        params: { period: indicator.period }, visible: true };
    });
    return {
      ...(chart.cellId === undefined ? {} : { cellId: identifier(chart.cellId) }),
      session: { exchange: String(session.exchange), marketType: String(session.marketType), symbol: session.symbol, interval },
      indicators,
    };
  });
  if (input.layout === undefined && charts.some((chart) => !chart.cellId)) throw new Error("cellId is required without a layout");
  return { requestId, workspaceId: identifier(input.workspaceId), windowId: identifier(input.windowId),
    expectedRevision: input.expectedRevision as number,
    ...(input.layout === undefined ? {} : { layout: input.layout as typeof layouts[number] }), charts };
}
