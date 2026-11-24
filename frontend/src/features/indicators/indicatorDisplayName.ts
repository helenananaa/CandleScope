import { t, type MessageKey } from "../../i18n/index.js";
import type { IndicatorDefinition } from "./indicatorTypes.js";

const NAMES: Record<string, MessageKey> = {
  MA: "indicator.name.ma", SMA: "indicator.name.ma", EMA: "indicator.name.ema",
  BOLL: "indicator.name.boll", RSI: "indicator.name.rsi", MACD: "indicator.name.macd",
  ATR: "indicator.name.atr", VOL: "indicator.name.vol",
};

/** Built-ins whose catalog description says more than their name. */
const DESCRIPTIONS: Record<string, MessageKey> = {
  VOL: "indicator.description.vol",
};

export function indicatorDisplayName(indicator: Pick<IndicatorDefinition, "id" | "name" | "engineName">): string {
  const engine = indicator.engineName?.toUpperCase() || "";
  return Object.hasOwn(NAMES, engine) ? t(NAMES[engine]!) : indicator.name || indicator.id;
}

/** Built-in descriptions come from the app catalogs; the backend copy is a fallback for other indicators. */
export function indicatorDescription(indicator: { engineName?: string | null | undefined; description?: string | undefined }): string {
  const engine = indicator.engineName?.toUpperCase() || "";
  return Object.hasOwn(DESCRIPTIONS, engine) ? t(DESCRIPTIONS[engine]!) : indicator.description || "";
}

/** Computed output owns placement; custom catalog defaults are not execution results. */
export function indicatorDisplayPanes(indicator: Pick<IndicatorDefinition, "lines" | "paneTarget">, builtin: boolean): Array<"main" | "sub"> {
  if (indicator.lines?.length) {
    return [...new Set(indicator.lines.map((line) => !line.pane || line.pane === "main" ? "main" as const : "sub" as const))];
  }
  return builtin ? [indicator.paneTarget === "main" ? "main" : "sub"] : [];
}
