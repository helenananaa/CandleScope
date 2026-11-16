import { DEFAULT_SETTINGS, type ChartSettings } from "../../settings/chartAppearanceSettings.js";
import { chartIndicatorSelection } from "../../indicators/chartIndicatorInput.js";
import type { ChartSignalDefinition } from "../../../shared/strategyRunSettings.js";

/** Freeze current appearance into the causal close-only strategy input contract. */
export function chartStrategySignalInput(appearance: Partial<ChartSettings>): ChartSignalDefinition | undefined {
  const selection = chartIndicatorSelection(null, null, { ...DEFAULT_SETTINGS, ...appearance });
  if (!["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"].includes(selection.chartType)) return undefined;
  const names: Record<string, string> = { boxSize: "box_size", minTick: "min_tick", atrLength: "atr_length",
    reversalAmount: "reversal_amount", numberOfLines: "number_of_lines", mode: "mode" };
  return { contract: "candlescope.chart-signal-input/1", algorithm: "causal-close-source/1",
    mode: "traditional", box_size: 1, min_tick: null, atr_length: 14, reversal_amount: 3, number_of_lines: 3,
    transform: selection.chartType, ...Object.fromEntries(Object.entries(selection.settings)
    .map(([key, value]) => [names[key] ?? key, value])) } as ChartSignalDefinition;
}

export function sameChartSignalInput(left: ChartSignalDefinition | null | undefined, right: ChartSignalDefinition | null | undefined): boolean {
  if (!left || !right) return !left && !right;
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].every(key => left[key as keyof ChartSignalDefinition] === right[key as keyof ChartSignalDefinition]);
}

export function withChartSignalInput<T extends { signalChart?: ChartSignalDefinition | undefined }>(settings: T, appearance: Partial<ChartSettings>): T {
  const next = { ...settings };
  delete next.signalChart;
  const selected = chartStrategySignalInput(appearance);
  if (selected) next.signalChart = selected;
  return next;
}
