import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { IndicatorVisibleRange } from "./indicatorTypes.js";
import { resolveInitialHostedRange } from "./indicatorRangePlanning.js";

/** The server supplies builtin warmup; the client requests visible + padding. */
export function providedBarsViewport(bars: KlineBar[], range: IndicatorVisibleRange | null) {
  const plan = resolveInitialHostedRange(bars, [], range);
  return plan === null ? { bars: [], key: "empty" } : {
    bars: bars.slice(plan.startIndex, plan.endIndex + 1),
    key: `${plan.start}:${plan.end}`,
  };
}
