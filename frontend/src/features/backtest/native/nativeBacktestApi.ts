import { API_BASE } from "../../../services/apiConfig.js";
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
  config?: FrozenExecutionSettings & { source: string; language: "pine"; parameters: Record<string, unknown>; context?: { symbol: string; timeframe: string }; interval?: string };
  result?: NativeResult | null;
  error?: { message: string; details?: unknown } | null;
}
export interface NativeCapabilities {
  engines: Array<{ language: string; available: boolean; external_available?: boolean; external_replay?: string; reason?: string }>;
}
export async function nativeApi<T>(path: string, body?: unknown, key?: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/backtests${path}`, {
    ...(body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }),
    headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
    ...(signal ? { signal } : {}),
  });
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(`${response.statusText}\n${JSON.stringify(value)}`);
  return value as T;
}
export function nativeTimeframe(interval: string): string {
  const match = /^(\d+)([smhdwM])$/.exec(interval);
  if (!match) throw new Error(`Unsupported interval: ${interval}`);
  const amount = Number(match[1]);
  switch (match[2]) {
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
