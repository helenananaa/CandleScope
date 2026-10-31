import { getCachedIndicatorResult } from "./indicatorResultCacheStore.js";
import { buildIndicatorOhlcvSignature } from "./indicatorComputeRuntime.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { IndicatorCacheContext, IndicatorComputeBatchItem, IndicatorComputeBatchJob, IndicatorDefinition } from "./indicatorTypes.js";

/** A viewport-only builtin must not inherit a result computed from the larger
 * script window. Replay passes no cache context; force explicitly bypasses it. */
export function cachedIndicatorComputeResult(job: IndicatorComputeBatchJob, indicator: IndicatorDefinition | undefined,
  context: IndicatorCacheContext | null, force: boolean): IndicatorComputeBatchItem | null {
  if (force || !context?.localInputKey || context.localInputKey !== buildIndicatorOhlcvSignature(job.request.ohlcv as KlineBar[], { limit: job.request.ohlcv.length })) return null;
  const cached = getCachedIndicatorResult(indicator, context);
  if (!cached || cached.staleSegments.length) return null;
  return { clientId: job.clientId, jobKey: job.jobKey, payload: {
    ok: true, ...cached.normalized, series: [], annotations: [], legacyFills: [], param_schema: cached.schema,
  } };
}
