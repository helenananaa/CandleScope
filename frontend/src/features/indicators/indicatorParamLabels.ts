import { t, type MessageKey } from "../../i18n/index.js";

const LABELS: Record<string, MessageKey> = {
  period: "indicator.param.period", source: "indicator.param.source", color: "local.color",
  fast: "indicator.param.fast", slow: "indicator.param.slow", signal: "indicator.param.signal",
  mult: "indicator.param.mult", hist_up_color: "indicator.param.histUp", hist_down_color: "indicator.param.histDown",
  up_color: "indicator.param.upColor", down_color: "indicator.param.downColor",
  color_middle: "indicator.param.middleColor", color_upper: "indicator.param.upperColor", color_lower: "indicator.param.lowerColor",
};

export function indicatorParamLabel(key: string, fallback: string, builtin: boolean): string {
  const message = builtin && Object.hasOwn(LABELS, key) ? LABELS[key] : undefined;
  return message ? t(message) : fallback;
}

export function indicatorSourceLabel(value: string): string {
  const prices: Record<string, string> = {
    open: t("alert.field.open"), high: t("alert.field.high"), low: t("alert.field.low"), close: t("alert.field.close"),
  };
  const formulas: Record<string, string> = {
    hl2: `(${prices.high} + ${prices.low}) / 2`,
    hlc3: `(${prices.high} + ${prices.low} + ${prices.close}) / 3`,
    ohlc4: `(${prices.open} + ${prices.high} + ${prices.low} + ${prices.close}) / 4`,
    hlcc4: `(${prices.high} + ${prices.low} + 2 × ${prices.close}) / 4`,
  };
  return Object.hasOwn(prices, value) ? prices[value]!
    : Object.hasOwn(formulas, value) ? formulas[value]! : value;
}
