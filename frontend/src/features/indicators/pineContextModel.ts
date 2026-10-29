import type { IndicatorParams } from "./indicatorTypes.js";
import { validatePineContractMetadata, type PineContractMetadata } from "./pineContractMetadata.js";

export interface PineRequestedContext { symbol: string; timeframe: string; marketType?: string;
  metadata?: PineContractMetadata }

export function parsePineContexts(text: string): PineRequestedContext[] {
  const value: unknown = JSON.parse(text || "[]");
  if (!Array.isArray(value) || value.length > 16) throw new Error("Declare at most 16 contexts");
  const seen = new Map<string, string | undefined>();
  for (const candidate of value as unknown[]) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate))
      throw new Error("Use symbol, Pine timeframe and optional marketType");
    const item = candidate as Record<string, unknown>;
    if (Object.keys(item).some((key) => !["symbol", "timeframe", "marketType", "metadata"].includes(key))
      || typeof item.symbol !== "string" || !/^[A-Za-z0-9._:/!-]{1,120}$/.test(item.symbol)
      || typeof item.timeframe !== "string" || !/^(?:[1-9][0-9]*[SDWM]?|[SDWM])$/.test(item.timeframe)
      || (item.marketType !== undefined && (typeof item.marketType !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(item.marketType))))
      throw new Error("Use symbol, Pine timeframe and optional marketType");
    if (item.metadata !== undefined) {
      validatePineContractMetadata(item.metadata);
    }
    const key = JSON.stringify([item.symbol, item.timeframe]);
    if (seen.has(key) && seen.get(key) !== item.marketType) throw new Error("Conflicting market types for one context");
    seen.set(key, item.marketType);
  }
  return value as PineRequestedContext[];
}

export function pineContextParams(params: IndicatorParams, text: string): IndicatorParams {
  const contexts = parsePineContexts(text);
  const result = { ...params };
  delete result.__pineContexts;
  return contexts.length ? { ...result, __pineContexts: contexts } : result;
}
