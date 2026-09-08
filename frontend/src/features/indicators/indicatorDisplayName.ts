import { t, type MessageKey } from "../../i18n/index.js";
import type { IndicatorDefinition } from "./indicatorTypes.js";

const NAMES: Record<string, MessageKey> = {
  MA: "indicator.name.ma", SMA: "indicator.name.ma", EMA: "indicator.name.ema",
  BOLL: "indicator.name.boll", RSI: "indicator.name.rsi", MACD: "indicator.name.macd",
  ATR: "indicator.name.atr", VOL: "indicator.name.vol",
};

export function indicatorDisplayName(indicator: Pick<IndicatorDefinition, "id" | "name" | "engineName">): string {
  const engine = indicator.engineName?.toUpperCase() || "";
  return Object.hasOwn(NAMES, engine) ? t(NAMES[engine]!) : indicator.name || indicator.id;
}
