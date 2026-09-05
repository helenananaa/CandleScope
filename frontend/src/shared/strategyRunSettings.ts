export interface StrategyExecutionOverrides {
  initialBalance: string;
  equityPercent: string;
  leverage: string;
  feeBps: string;
  slippageBps: string;
}

export interface StrategyRunSettings {
  parameters?: Record<string, unknown>;
  fidelityPreference?: "FAST" | "PRECISE";
  rangeMode: "ALL_AVAILABLE" | "CUSTOM";
  customRange: { startMs: number; endMs: number } | null;
  executionOverrides?: StrategyExecutionOverrides;
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
  if (record.rangeMode === "ALL_AVAILABLE") return record.customRange === null;
  const range = record.customRange;
  return record.rangeMode === "CUSTOM" && !!range && Number.isSafeInteger(range.startMs) && Number.isSafeInteger(range.endMs)
    && range.startMs >= 0 && range.endMs > range.startMs;
}
