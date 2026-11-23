/**
 * The frozen builtin RSI (Wilder) long/short template (M9), saved as a strategy revision of language
 * BUILTIN_TEMPLATE, and its parameters. The research workspace runs it as a saved strategy (ADR-BACKTEST-015 P5c4b).
 */
export const BUILTIN_RSI_REVISION = "builtin-rsi-wilder-long-short-v1";

export const BUILTIN_RSI_PARAMETERS: ReadonlyArray<Record<string, unknown>> = Object.freeze([
  Object.freeze({ name: "length", type: "integer", default: 24, minimum: 2 }),
  Object.freeze({ name: "oversold", type: "number", default: 30 }),
  Object.freeze({ name: "overbought", type: "number", default: 70 }),
]);

/** The parameters a revision declares, at their defaults. */
export function defaultParameters(schema: ReadonlyArray<Record<string, unknown>>): Record<string, unknown> {
  return Object.fromEntries(schema.filter((item) => typeof item.name === "string" && Object.hasOwn(item, "default"))
    .map((item) => [item.name as string, item.default]));
}
