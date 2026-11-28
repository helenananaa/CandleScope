import { API_BASE } from "../../../services/apiConfig.js";
import { parseIntervalParts } from "../../../utils/intervals.js";
import type { FrozenExecutionSettings } from "./nativeExecutionSettings.js";
import type { NativeCostMatrix } from "./NativeCostSensitivity.js";

export interface NativeResult {
  cost_sensitivity?: NativeCostMatrix;
  account_authority: string;
  account_model?: string;
  evaluation_contract?: string;
  fill_model: string;
  fidelity?: string;
  report_hash: string;
  equity: Array<{ time: number; value: number }>;
  trades: Array<Record<string, unknown>>;
  closed_trades?: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  bars: Array<{ time: number; open: number; high: number; low: number; close: number }>;
  graphics: Array<Record<string, unknown>>;
  raw_output: Record<string, unknown>;
  diagnostics: unknown[];
}
export interface NativeRun {
  replay_contract?: string;
  execution_mode?: "NATIVE" | "CANDLESCOPE";
  run_id: string;
  state: string;
  created_at_ms: number;
  runtime_identity: { engine: { package: string; version: string; code_sha256: string } };
  config?: FrozenExecutionSettings & { signal_chart?: import("../../../shared/strategyRunSettings.js").ChartSignalDefinition; source: string; language: "pine"; parameters: Record<string, unknown>; context?: { symbol: string; timeframe: string }; interval?: string; exchange?: string; market_type?: string };
  result?: NativeResult | null;
  error?: { message: string; details?: unknown } | null;
  /** A FOLLOW rebuild: whether its engine session can be extended with the next bars (B-157a). */
  follow?: { extendable: boolean };
}
export interface NativeCapabilities {
  engines: Array<{ language: string; available: boolean; external_available?: boolean; external_replay?: string; reason?: string }>;
}
export async function nativeApi<T>(path: string, body?: unknown, key?: string, signal?: AbortSignal,
  headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}/backtests${path}`, {
    ...(body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }),
    headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}), ...headers },
    ...(signal ? { signal } : {}),
  });
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(`${response.statusText}\n${JSON.stringify(value)}`);
  return value as T;
}
export type NativeExecutionMode = "NATIVE" | "CANDLESCOPE";

/**
 * Native and CandleScope-matched run endpoints (`/backtests/native|external/runs`).
 * Only the strategy data manager uses this; components go through the manager
 * (ADR-BACKTEST-015 P2c).
 */
/** A FOLLOW rebuild names the user's run it rebuilds; the store keeps only what a chart can show (ADR-BACKTEST-015 O2). */
export const FOLLOW_OF_HEADER = "Strategy-Follow-Of";

export interface NativeRunOptions {
  /** This run rebuilds the user's run `followOf` for FOLLOW; it is not part of the run's input. */
  followOf?: string;
}

export interface NativeRunClient {
  create(mode: NativeExecutionMode, body: Record<string, unknown>, idempotencyKey: string, signal?: AbortSignal,
    options?: NativeRunOptions): Promise<NativeRun>;
  get(mode: NativeExecutionMode, runId: string, signal?: AbortSignal): Promise<NativeRun>;
  list(mode: NativeExecutionMode, signal?: AbortSignal): Promise<NativeRun[]>;
  cancel(mode: NativeExecutionMode, runId: string, signal?: AbortSignal): Promise<NativeRun>;
}

/**
 * Load the run a chart cell shows. A FOLLOW rebuild the store no longer keeps (O2 keeps the results
 * of the 8 most recently active follows) falls back to `own`, the user's latest run in that cell.
 */
export async function loadShownNativeRun(load: (runId: string) => Promise<NativeRun>, shown: string,
  own: string | undefined): Promise<NativeRun> {
  try {
    return await load(shown);
  } catch (reason) {
    if (!own || own === shown || !String(reason).includes('"RUN_NOT_FOUND"')) throw reason;
    return load(own);
  }
}

function nativeRunsPath(mode: NativeExecutionMode | undefined): string {
  return mode === "CANDLESCOPE" ? "/external/runs" : "/native/runs";
}

export const defaultNativeRunClient: NativeRunClient = {
  create: (mode, body, idempotencyKey, signal, options) => nativeApi<NativeRun>(nativeRunsPath(mode), body, idempotencyKey, signal,
    options?.followOf ? { [FOLLOW_OF_HEADER]: options.followOf } : {}),
  get: (mode, runId, signal) => nativeApi<NativeRun>(`${nativeRunsPath(mode)}/${encodeURIComponent(runId)}`, undefined, undefined, signal),
  list: async (mode, signal) => (await nativeApi<{ runs: NativeRun[] }>(nativeRunsPath(mode), undefined, undefined, signal)).runs,
  cancel: (mode, runId, signal) => nativeApi<NativeRun>(`${nativeRunsPath(mode)}/${encodeURIComponent(runId)}/cancel`, {}, undefined, signal),
};

export function nativeTimeframe(interval: string): string {
  const parts = parseIntervalParts(interval);
  if (!parts) throw new Error(`Unsupported interval: ${interval}`);
  const { amount, unit } = parts;
  switch (unit) {
    case "s": return `${amount}S`;
    case "m": return String(amount);
    case "h": return String(amount * 60);
    case "d": return `${amount}D`;
    case "w": return `${amount}W`;
    default: return `${amount}M`;
  }
}
export function nativeExportUrl(id: string, mode = "NATIVE"): string {
  return `${API_BASE}/backtests/${mode === "CANDLESCOPE" ? "external" : "native"}/runs/${encodeURIComponent(id)}/export`;
}
export const nativeTerminal = (state: string) => ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(state);
