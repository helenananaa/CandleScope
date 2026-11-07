import type { IndicatorSubscribeMessage } from "./indicatorTypes.js";

export function resolvePineChartTransport(value: unknown = "calculation"): "calculation" | "snapshot" {
  if (value !== "calculation" && value !== "snapshot") {
    throw new Error("VITE_PINE_CHART_TRANSPORT must be calculation or snapshot");
  }
  return value;
}

export const PINE_CHART_TRANSPORT = resolvePineChartTransport(
  globalThis.window?.candlescopeDesktop?.pineChartTransport ?? import.meta.env?.VITE_PINE_CHART_TRANSPORT,
);

type ScriptSubscription = Pick<IndicatorSubscribeMessage, "kind" | "language">;

export function isPineScriptSubscription(message: ScriptSubscription): boolean {
  return message.kind === "script" && (message.language || "pine").trim().toLowerCase() === "pine";
}

export function usesChartCalculation(message: ScriptSubscription): boolean {
  return PINE_CHART_TRANSPORT === "calculation" && isPineScriptSubscription(message);
}
