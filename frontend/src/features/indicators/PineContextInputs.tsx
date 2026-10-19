import { useState } from "react";
import { t } from "../../i18n/index.js";
import type { IndicatorParams } from "./indicatorTypes.js";

export interface PineRequestedContext { symbol: string; timeframe: string; marketType?: string;
  metadata?: { priceTickSize: string; currency?: string; quantityPrecision?: number; pointValue?: number } }

export function parsePineContexts(text: string): PineRequestedContext[] {
  const value: unknown = JSON.parse(text || "[]");
  if (!Array.isArray(value) || value.length > 16) throw new Error("Declare at most 16 contexts");
  const seen = new Map<string, string | undefined>();
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)
      || Object.keys(item).some((key) => !["symbol", "timeframe", "marketType", "metadata"].includes(key))
      || typeof item.symbol !== "string" || !/^[A-Za-z0-9._:/!-]{1,120}$/.test(item.symbol)
      || typeof item.timeframe !== "string" || !/^(?:[1-9][0-9]*[SDWM]?|[SDWM])$/.test(item.timeframe)
      || (item.marketType !== undefined && (typeof item.marketType !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(item.marketType))))
      throw new Error("Use symbol, Pine timeframe and optional marketType");
    if (item.metadata !== undefined) {
      const metadata = item.metadata;
      if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)
          || Object.keys(metadata).some((key) => !["priceTickSize", "currency", "quantityPrecision", "pointValue"].includes(key))
          || typeof metadata.priceTickSize !== "string" || !Number.isFinite(Number(metadata.priceTickSize)) || Number(metadata.priceTickSize) <= 0
          || (metadata.currency !== undefined && (typeof metadata.currency !== "string" || !/^[A-Z]{1,20}$/.test(metadata.currency)))
          || (metadata.quantityPrecision !== undefined && (!Number.isInteger(metadata.quantityPrecision) || metadata.quantityPrecision < 0 || metadata.quantityPrecision > 9))
          || (metadata.pointValue !== undefined && metadata.pointValue !== 1))
        throw new Error("Use the actual requested price tick, quote currency and quantity precision");
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

export function PineContextInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <details><summary>{t("indicator.pine.contexts")}</summary>
    <p>{t("indicator.pine.contextsHelp")}</p>
    <textarea aria-label={t("indicator.pine.contexts")} rows={4} value={value} readOnly={readOnly}
      placeholder={'[{"symbol":"OKX:BTC-USDT","timeframe":"60","marketType":"spot"}]'}
      style={{ width: "100%", fontFamily: "monospace", background: "var(--bg-primary)", color: "var(--text-primary)" }}
      onChange={(event) => { onChange(event.target.value); try { parsePineContexts(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
    {error && <p role="alert">{error}</p>}
  </details>;
}
