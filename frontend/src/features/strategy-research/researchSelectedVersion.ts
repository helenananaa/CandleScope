import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { ChartStrategyAttachmentRecord } from "../chart-workspace/chartWorkspaceTypes.js";
import { getStrategyStorage, type StrategyStorage } from "../../shared/strategyStorage.js";
import { isPythonBarOutputMode, validExecutionOverrides } from "../../shared/strategyRunSettings.js";
import { chartStrategyQuickPresetIdForMarket } from "../backtest/chart-tester/chartStrategyRunRequest.js";

export interface ResearchSelectedVersion {
  schema: "candlescope.research-selected-version/1";
  run_id: string; config_hash: string; strategy_revision_id: string; version_hash: string;
  program: { language: "pine" | "python"; name: string; source_text: string; source_hash: string;
    revision_source_hash: string; compiled_hash: string; parameter_schema: Array<Record<string, unknown>>;
    libraries: Record<string, string>; bundle_hash: string | null };
  configuration: Record<string, unknown>;
}
export interface ResearchReturnReference {
  schema: 1; runId: string; versionHash: string;
  origin: { workspaceId: string; cellId: string } | null;
}
const PREFIX = "candlescope:research-return:";
const hash = /^sha256:[a-f0-9]{64}$/;
export class ResearchReturnUnsupported extends Error {
  constructor(readonly field: string) { super(field); }
}
function requireValue(condition: unknown, field: string): asserts condition {
  if (!condition) throw new ResearchReturnUnsupported(field);
}
function decimal(value: unknown): string | null {
  const text = typeof value === "string" ? value : Number.isSafeInteger(value) ? String(value) : "";
  if (!/^\d+(?:\.\d+)?$/.test(text)) return null;
  const [integer, fraction = ""] = text.split(".");
  const tail = fraction.replace(/0+$/, "");
  return integer!.replace(/^0+(?=\d)/, "") + (tail ? "." + tail : "");
}

/** Only the currently qualified chart/continuation profile is admitted. An
 * advanced research execution must never be silently flattened into this UI. */
export function projectSelectedVersion(version: ResearchSelectedVersion): {
  session: ChartSession; attachment: Omit<ChartStrategyAttachmentRecord, "strategyDraftId">;
} {
  requireValue(version.schema === "candlescope.research-selected-version/1" && hash.test(version.version_hash)
    && /^bt_[\w-]+$/.test(version.run_id), "version");
  const p = version.program, c = version.configuration;
  requireValue(p?.language === "python", "language");
  requireValue(typeof p.source_text === "string" && p.source_text.trim() && new TextEncoder().encode(p.source_text).length <= 2 * 1024 * 1024, "source");
  requireValue(typeof p.name === "string" && p.name.trim() && hash.test(p.source_hash), "source");
  requireValue(c && typeof c === "object" && !Array.isArray(c), "configuration");
  requireValue(c.strategy_revision_id === version.strategy_revision_id, "strategy_revision_id");
  requireValue(c.fidelity_mode === "BAR_APPROX" && c.source_event_kind === "BAR", "fidelity_mode");
  requireValue(typeof c.exchange === "string" && /^[a-z0-9_-]{1,64}$/.test(c.exchange)
    && typeof c.symbol === "string" && c.symbol.length > 0 && c.symbol.length <= 128, "market");
  requireValue(c.interval === "1m" && (c.market_type === "spot" || (c.exchange === "binance" && c.market_type === "futures")), "market");
  const session: ChartSession = { exchange: c.exchange, symbol: c.symbol, marketType: c.market_type, interval: "1m" };
  const exact: Record<string, unknown> = {
    account_model: c.market_type === "spot" ? "SPOT_CASH_V1" : "LINEAR_PERP_ONE_WAY_V1",
    contract_data_mode: "LEGACY_FIXED_V1", funding_mode: "OFF", sizing_policy: "EQUITY_PERCENT_V1",
    gap_policy: "REJECT", quick_preset_id: chartStrategyQuickPresetIdForMarket(c.market_type),
    quick_preset_revision: c.market_type === "spot" ? "2" : "1",
  };
  for (const [field, value] of Object.entries(exact)) requireValue(c[field] === value, field);
  for (const field of ["funding_rate", "latency_ms", "latency_events", "cooldown_events"]) requireValue(c[field] == null || decimal(c[field]) === "0", field);
  requireValue(decimal(c.leverage) === "1", "leverage");
  const outputMode = c.output_mode;
  requireValue(isPythonBarOutputMode(outputMode), "output_mode");
  const legacy = c.execution_model_revision == null;
  requireValue(legacy || c.execution_model_revision === "EXECUTION_REALISM_V2", "execution_model_revision");
  requireValue(legacy ? c.participation_rate == null : decimal(c.participation_rate) === "0.1", "participation_rate");
  requireValue(c.bar_path_scenario == null || (!legacy && c.bar_path_scenario === "OHLC_WORST_CASE_STOP_FIRST_V1"), "bar_path_scenario");
  requireValue(c.fill_policy == null || (!legacy && c.fill_policy === "BAR_VOLUME_PARTICIPATION_WORST_CASE_V2"), "fill_policy");
  requireValue((legacy && c.order_end_policy == null) || c.order_end_policy === "CANCEL_AT_END", "order_end_policy");
  // These fields are not editable by the quick chart conditions. Retain the
  // selected research result and refuse rather than discard its risk rules.
  for (const field of ["fixed_qty", "fixed_notional", "risk_per_stop_percent", "stop_distance", "max_abs_position_qty", "max_notional",
    "max_leverage", "max_order_risk", "max_active_orders", "max_cumulative_fees", "max_drawdown_percent", "daily_loss_limit",
    "price_tick", "qty_step", "min_notional", "pine_contexts", "chart_book_data_hash"]) requireValue(c[field] == null, field);
  requireValue(decimal(c.maker_fee_bps) !== null && decimal(c.maker_fee_bps) === decimal(c.taker_fee_bps), "maker_fee_bps");
  const executionOverrides = { initialBalance: String(c.initial_balance), equityPercent: String(c.equity_percent),
    leverage: String(c.leverage), feeBps: String(c.taker_fee_bps), slippageBps: String(c.slippage_bps) };
  requireValue(validExecutionOverrides(executionOverrides), "execution");
  const startMs = c.start_time_ms, endMs = c.end_time_ms, warmupBars = c.warmup_bars ?? 0;
  requireValue(Number.isSafeInteger(startMs) && Number(startMs) >= 0 && Number(startMs) % 60000 === 0
    && Number.isSafeInteger(endMs) && Number(endMs) > Number(startMs) && Number(endMs) <= 8640000000000000, "range");
  requireValue(Number.isSafeInteger(warmupBars) && Number(warmupBars) >= 0 && Number(warmupBars) <= 200000, "warmup_bars");
  requireValue(c.parameters && typeof c.parameters === "object" && !Array.isArray(c.parameters), "parameters");
  return { session, attachment: {
    schemaVersion: 1, strategyRevisionId: version.strategy_revision_id, displayName: p.name, language: "python",
    parameters: structuredClone(c.parameters) as Record<string, unknown>, rangeMode: "CUSTOM",
    customRange: { startMs: Number(startMs), endMs: Number(endMs) }, fidelityPreference: "FAST",
    quickPresetId: String(c.quick_preset_id), autoRun: false, executionOverrides,
    initialization: { runId: version.run_id, versionHash: version.version_hash, outputMode, warmupBars: Number(warmupBars),
      preferredRunMode: "HISTORY_LIVE", ...(legacy ? { executionModel: "LEGACY" } : {}) },
  } };
}

export async function saveResearchReturn(reference: ResearchReturnReference, storage: StrategyStorage | null = getStrategyStorage()): Promise<string> {
  if (!storage) throw new Error("RESEARCH_RETURN_STORAGE_UNAVAILABLE");
  const id = crypto.randomUUID();
  await storage.setItem(PREFIX + id, JSON.stringify(reference));
  return `/?research-version=${encodeURIComponent(id)}`;
}
export function readResearchReturn(id: string, storage: StrategyStorage | null = getStrategyStorage()): ResearchReturnReference | null {
  try {
    if (!storage || !/^[\w-]{8,80}$/.test(id)) return null;
    const raw = storage.getItem(PREFIX + id);
    if (!raw || raw.length > 2048) return null;
    const value = JSON.parse(raw) as ResearchReturnReference;
    if (value?.schema !== 1 || !/^bt_[\w-]+$/.test(value.runId) || !hash.test(value.versionHash)
      || (value.origin !== null && (!value.origin || typeof value.origin.workspaceId !== "string"
        || typeof value.origin.cellId !== "string"))) return null;
    return value;
  } catch { return null; }
}
