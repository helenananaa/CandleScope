export const chartBookModes = ["BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"] as const;
export const chartBookMode = (value: unknown): boolean => chartBookModes.some((mode) => mode === value);

export function chartSourceKind(mode: string): string {
  return mode === "BAR_APPROX" ? "BAR" : chartBookMode(mode) ? "TRADE_AND_L2" : "AGG_TRADE";
}

export function selectChartExecutionMode(draft: Record<string, unknown>, mode: string): Record<string, unknown> {
  const next: Record<string, unknown> = { ...draft, fidelity_mode: mode, source_event_kind: chartSourceKind(mode) };
  if (mode !== draft.fidelity_mode) delete next.execution_data;
  for (const field of ["signal_clock", "signal_interval", "execution_clock", "bar_builder", "timezone"])
    delete next[field];
  if (chartBookMode(mode)) Object.assign(next, { execution_model_revision: null, participation_rate: null,
    latency_ms: 0, latency_events: 0, bar_path_scenario: null, metrics_version: null, output_mode: "ORDER_INTENT" });
  return next;
}

export function parseChartBookFile(text: string): Record<string, unknown> {
  const data: unknown = JSON.parse(text);
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("invalid book file");
  const value = data as Record<string, unknown>;
  if (!["symbol", "exchange", "market_type"].every((key) => typeof value[key] === "string" && value[key] !== "")
    || !value.provenance || typeof value.provenance !== "object" || Array.isArray(value.provenance)
    || !Object.keys(value.provenance).length || !Array.isArray(value.events)
    || !value.events.length || value.events.length > 500_000) throw new Error("invalid book file");
  for (const raw of value.events) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("invalid book event");
    const row = raw as Record<string, unknown>;
    if (!Number.isSafeInteger(row.time_ms) || !["TRADES", "ORDER_BOOK"].includes(String(row.role))
      || !row.payload || typeof row.payload !== "object" || Array.isArray(row.payload)) throw new Error("invalid book event");
    const payload = row.payload as Record<string, unknown>;
    if (row.role === "TRADES" && (payload.source_event_kind !== "AGG_TRADE"
      || !Number.isSafeInteger(payload.source_sequence))) throw new Error("invalid chart print");
  }
  return value;
}
