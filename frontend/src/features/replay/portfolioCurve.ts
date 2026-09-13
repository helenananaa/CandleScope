export interface PortfolioCurveResponse {
  readonly run_id: string;
  readonly available: boolean;
  readonly span_ms: number;
  readonly samples: ReadonlyArray<{ readonly offset_ms: number; readonly equity: string }>;
  readonly summary: { readonly max_drawdown: string } | null;
}

export function parsePortfolioCurve(value: unknown): PortfolioCurveResponse {
  const object = (v: unknown): Record<string, unknown> => {
    if (v === null || typeof v !== "object" || Array.isArray(v)) throw new TypeError("invalid portfolio curve");
    return v as Record<string, unknown>;
  };
  const integer = (v: unknown): number => {
    if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0) throw new TypeError("invalid portfolio curve boundary");
    return v;
  };
  const decimal = (v: unknown): string => {
    if (typeof v !== "string" || v.length > 2048 || !/^[+-]?\d+(?:\.\d+)?$/.test(v)) throw new TypeError("invalid portfolio equity");
    return v;
  };
  const raw = object(value);
  if (raw.protocol !== "replay.v3" || raw.scope !== "RECORDED_PORTFOLIO_INTERVALS"
    || raw.complete_training_history !== false || typeof raw.run_id !== "string"
    || typeof raw.available !== "boolean" || !Array.isArray(raw.samples) || raw.samples.length > 5000) {
    throw new TypeError("invalid portfolio curve contract");
  }
  const span = integer(raw.span_ms);
  let previous = -1;
  const samples = raw.samples.map((item) => {
    const row = object(item);
    const at = integer(row.offset_ms);
    if (at < previous || at > span) throw new TypeError("portfolio curve escaped its coverage");
    previous = at;
    return { offset_ms: at, equity: decimal(row.equity) };
  });
  const summary = raw.summary === null ? null : { max_drawdown: decimal(object(raw.summary).max_drawdown) };
  if (raw.available !== (summary !== null)) throw new TypeError("portfolio curve availability mismatch");
  return { run_id: raw.run_id, available: raw.available, span_ms: span, samples, summary };
}
