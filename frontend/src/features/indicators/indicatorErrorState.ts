import { ChartWorkDroppedError } from "../market-data/chartWorkScheduler.js";
import type { IndicatorDefinition } from "./indicatorTypes.js";

/** Hidden/minimized work is deliberately skipped, not an indicator failure. */
export function indicatorRangeFailureMessage(error: unknown): string | null {
  if (error instanceof ChartWorkDroppedError) return null;
  return error instanceof Error ? error.message : "Indicator range request failed";
}

export function updateIndicatorErrorState(
  indicators: IndicatorDefinition[],
  indicatorId: string,
  error: string,
): IndicatorDefinition[] {
  const index = indicators.findIndex((indicator) => indicator.id === indicatorId);
  const indicator = indicators[index];
  if (!indicator || indicator.error === error) return indicators;
  const next = [...indicators];
  next[index] = { ...indicator, error };
  return next;
}
