import { isFrontendScript } from "./frontendScriptContract.js";
import { isBuiltinIndicator } from "./indicatorPayloadRuntime.js";
import type { IndicatorCacheContext, IndicatorDefinition } from "./indicatorTypes.js";

/** Describes ownership, not a new language router. Community runtimes retain
 * their descriptor-declared language and hosted execution contract. */
export function indicatorRuntimeAdapter(indicator: IndicatorDefinition, context: Partial<IndicatorCacheContext>) {
  const language = String(indicator.language || "pine").trim().toLowerCase();
  if (language === "pyne") throw new Error("Pyne indicators are retired and cannot publish results");
  const runtime = isBuiltinIndicator(indicator) ? "builtin" : isFrontendScript(indicator) ? "frontend-js" : language;
  const provided = isFrontendScript(indicator) || indicator.executionTarget === "local";
  return {
    runtime,
    input: provided ? "provided-window" as const : "hosted-series" as const,
    origin: provided ? context.localInputKey ?? null : null,
    // Hosted scripts contain private observations and alert state. Sharing a
    // pure JS computation never licenses sharing these calculation sessions.
    owner: provided || runtime === "builtin" ? context.inputSource?.scope ?? "standalone"
      : context.projectionOwner ?? "standalone",
    sharing: provided ? "exact-input" as const : runtime === "builtin" ? "equivalent-demand" as const : "private-session" as const,
  };
}
