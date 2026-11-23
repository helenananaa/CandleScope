import { isFrontendScript } from "./frontendScriptContract.js";
import { isBuiltinIndicator } from "./indicatorPayloadRuntime.js";
import type { IndicatorCacheContext, IndicatorDefinition } from "./indicatorTypes.js";
import { explicitScriptLanguage, isRetiredScriptIndicator } from "./retiredScriptIndicator.js";

/** Describes ownership, not a new language router. Community runtimes retain
 * their descriptor-declared language and hosted execution contract. */
export function indicatorRuntimeAdapter(indicator: IndicatorDefinition, context: Partial<IndicatorCacheContext>) {
  // A retired script never runs; it has no runtime and shares nothing.
  if (isRetiredScriptIndicator(indicator)) {
    return { runtime: "retired", input: "hosted-series" as const, origin: null,
      owner: context.projectionOwner ?? "standalone", sharing: "private-session" as const };
  }
  const runtime = isBuiltinIndicator(indicator) ? "builtin" : isFrontendScript(indicator) ? "frontend-js"
    : explicitScriptLanguage(indicator) ?? "";
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
