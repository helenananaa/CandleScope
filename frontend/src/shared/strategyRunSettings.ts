export interface ChartSignalDefinition {
  contract?: "candlescope.chart-signal-input/1";
  algorithm?: "causal-close-source/1";
  transform: "heikin-ashi" | "renko" | "point-and-figure" | "kagi" | "line-break";
  mode?: "traditional" | "atr";
  box_size?: number;
  min_tick?: number | null;
  atr_length?: number;
  reversal_amount?: number;
  number_of_lines?: number;
}

export interface StrategyExecutionOverrides {
  initialBalance: string;
  equityPercent: string;
  leverage: string;
  feeBps: string;
  slippageBps: string;
}

export type PythonBarOutputMode = "SIGNAL" | "TARGET_POSITION" | "ORDER_INTENT";
export interface PythonBarExecution {
  outputMode: PythonBarOutputMode;
  executionModel: "LEGACY" | "V2";
  warmupBars: number;
}

export function isPythonBarOutputMode(value: unknown): value is PythonBarOutputMode {
  return value === "SIGNAL" || value === "TARGET_POSITION" || value === "ORDER_INTENT";
}

function validWarmup(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0 && value <= 200000;
}

export function validPythonBarExecution(value: unknown): value is PythonBarExecution {
  if (!value || typeof value !== "object") return false;
  const profile = value as PythonBarExecution;
  return isPythonBarOutputMode(profile.outputMode) && validWarmup(profile.warmupBars)
    && (profile.executionModel === "LEGACY" || profile.executionModel === "V2");
}

export interface StrategyRunSettings {
  signalChart?: ChartSignalDefinition | undefined;
  parameters?: Record<string, unknown>;
  fidelityPreference?: "FAST" | "PRECISE";
  rangeMode: "ALL_AVAILABLE" | "CUSTOM";
  customRange: { startMs: number; endMs: number } | null;
  executionOverrides?: StrategyExecutionOverrides;
  pythonBarExecution?: PythonBarExecution;
}

export interface StrategyInitializationSettings {
  runId: string; versionHash: string; outputMode: PythonBarOutputMode; warmupBars: number; executionModel?: "LEGACY" | "V2";
  preferredRunMode?: "HISTORY_LIVE";
}
export function validStrategyInitialization(value: unknown): value is StrategyInitializationSettings {
  if (!value || typeof value !== "object") return false;
  const v = value as StrategyInitializationSettings;
  return typeof v.runId === "string" && /^bt_[\w-]+$/.test(v.runId)
    && typeof v.versionHash === "string" && /^sha256:[a-f0-9]{64}$/.test(v.versionHash)
    && isPythonBarOutputMode(v.outputMode) && validWarmup(v.warmupBars)
    && (v.executionModel === undefined || v.executionModel === "LEGACY" || v.executionModel === "V2")
    && (v.preferredRunMode === undefined || v.preferredRunMode === "HISTORY_LIVE");
}

export const DEFAULT_STRATEGY_RUN_SETTINGS: StrategyRunSettings = { rangeMode: "ALL_AVAILABLE", customRange: null };

export function validExecutionOverrides(value: unknown): value is StrategyExecutionOverrides {
  if (value === null || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  for (const field of ["initialBalance", "equityPercent", "leverage", "feeBps", "slippageBps"]) {
    if (typeof record[field] !== "string" || !/^\d+(?:\.\d+)?$/.test(record[field] as string) || !Number.isFinite(Number(record[field]))) return false;
  }
  return Number(record.initialBalance) > 0 && Number(record.equityPercent) > 0 && Number(record.equityPercent) <= 100
    && Number(record.leverage) >= 1 && Number(record.leverage) <= 125;
}

export function validStrategyRunSettings(value: unknown): value is StrategyRunSettings {
  if (!value || typeof value !== "object") return false;
  const record = value as StrategyRunSettings;
  if (record.fidelityPreference !== undefined && record.fidelityPreference !== "FAST" && record.fidelityPreference !== "PRECISE") return false;
  if (record.parameters !== undefined && (!record.parameters || typeof record.parameters !== "object" || Array.isArray(record.parameters))) return false;
  if (record.executionOverrides !== undefined && !validExecutionOverrides(record.executionOverrides)) return false;
  if (record.pythonBarExecution !== undefined && (!validPythonBarExecution(record.pythonBarExecution)
    || record.fidelityPreference !== "FAST" || record.rangeMode !== "CUSTOM"
    || (record.executionOverrides !== undefined && Number(record.executionOverrides.leverage) !== 1))) return false;
  if (record.rangeMode === "ALL_AVAILABLE") return record.customRange === null;
  const range = record.customRange;
  return record.rangeMode === "CUSTOM" && !!range && Number.isSafeInteger(range.startMs) && Number.isSafeInteger(range.endMs)
    && range.startMs >= 0 && range.endMs > range.startMs;
}
