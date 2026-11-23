import { getIntervalSemanticSpec, type IntervalString } from "../../utils/intervals.js";
import { isLegacyKlineSeriesIdentity, type KlineSeriesIdentityInput } from "./klineSeriesIdentity.js";

export interface ComposedHistoryCapability {
  readonly contractId: string;
  readonly sourceWidthsSeconds: readonly number[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function strings(value: unknown, maximum: number): string[] | null {
  return Array.isArray(value) && value.length > 0 && value.length <= maximum
    && value.every(item => typeof item === "string" && item.length > 0 && item.length <= 256)
    ? value as string[] : null;
}

export function resolveComposedHistoryCapability({ exchange, marketType, identity, capability, nativeIntervals }: {
  exchange: string;
  marketType: string;
  identity?: KlineSeriesIdentityInput;
  capability: unknown;
  nativeIntervals: readonly IntervalString[];
}): ComposedHistoryCapability | null {
  if (!isLegacyKlineSeriesIdentity(exchange, identity)) return null;
  const raw = record(capability);
  if (!raw || raw.exchange !== exchange || !Array.isArray(raw.markets) || !Array.isArray(raw.channels)) return null;
  const markets = raw.markets.map(record).filter(item => item?.market_type === marketType);
  if (markets.length !== 1 || markets[0]?.calendar_id !== "crypto.24x7.utc" || markets[0].timezone !== "UTC") return null;
  const channels = raw.channels.map(record).filter(item => item?.channel === "kline"
    && item.history === true && strings(item.market_types, 32)?.includes(marketType));
  if (channels.length !== 1) return null;
  const policy = record(channels[0]?.history_composition);
  if (!policy || policy.schema_version !== 1 || policy.identity_scope !== "default-trade-base"
    || policy.boundary_scope !== "fixed-epoch-utc" || policy.finality !== "trusted-closed-only"
    || typeof policy.contract_id !== "string" || !policy.contract_id.length || policy.contract_id.length > 128
    || !Number.isSafeInteger(policy.min_width_ms) || !Number.isSafeInteger(policy.max_width_ms)
    || Number(policy.min_width_ms) < 60_000 || Number(policy.max_width_ms) > 86_400_000
    || Number(policy.min_width_ms) > Number(policy.max_width_ms)) return null;
  const declared = strings(policy.native_intervals, 32);
  const fields = strings(policy.fields, 9);
  const evidence = strings(policy.evidence, 16);
  const required = ["open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote"];
  if (!declared || new Set(declared).size !== declared.length || !fields || !evidence
    || fields.length !== required.length || !required.every(field => fields.includes(field))) return null;
  const available = new Set(nativeIntervals.map(interval => getIntervalSemanticSpec(interval)?.canonicalValue));
  const widths: number[] = [];
  for (const interval of declared) {
    const spec = getIntervalSemanticSpec(interval);
    if (!spec || spec.alignment !== "fixed-epoch" || spec.phaseSeconds || spec.timezone
      || spec.widthSeconds == null || !Number.isSafeInteger(spec.widthSeconds)
      || spec.widthSeconds * 1000 < Number(policy.min_width_ms)
      || spec.widthSeconds * 1000 > Number(policy.max_width_ms)
      || !available.has(spec.canonicalValue)) return null;
    widths.push(spec.widthSeconds);
  }
  return Object.freeze({ contractId: policy.contract_id,
    sourceWidthsSeconds: Object.freeze([...new Set(widths)].sort((a, b) => b - a)) });
}

/** A finite target page backed by qualified exact covers and bounded server execution. */
export function planComposedHistoryPage(interval: IntervalString, capability: ComposedHistoryCapability | null | undefined,
  desired: number, sourceRowBudget: number, padding = 3): { targetBars: number; compositionContract: string } | null {
  const target = getIntervalSemanticSpec(interval);
  if (!capability || !target || target.alignment !== "fixed-epoch" || target.phaseSeconds || target.timezone
    || target.widthSeconds == null || !Number.isSafeInteger(desired) || desired <= 0
    || !Number.isFinite(sourceRowBudget) || sourceRowBudget <= 0
    || !Number.isSafeInteger(padding) || padding < 0) return null;
  const widths = capability.sourceWidthsSeconds.filter(width => width < target.widthSeconds!);
  const largest = widths[0], finest = widths.at(-1);
  if (!largest || !finest || target.widthSeconds % finest
    || widths.some((width, index) => index > 0 && widths[index - 1]! % width !== 0)) return null;
  // Whole largest blocks plus bounded head/tail fragments on each nested grid.
  const factor = Math.floor(target.widthSeconds / largest)
    + widths.slice(1).reduce((sum, width, index) => sum + 2 * (widths[index]! / width - 1), 0);
  const budget = Math.min(16_384, Math.floor(sourceRowBudget));
  const targetBars = Math.min(desired, 512, Math.floor(budget / factor) - padding);
  return targetBars > 0 ? { targetBars, compositionContract: capability.contractId } : null;
}
