import type { IndicatorDefinition } from "./indicatorTypes.js";

/**
 * Pyne was removed in PR #105 (2026-10-26). Its scripts are kept as the user
 * saved them, shown as retired, and never run or relabelled as another
 * language.
 */
export const RETIRED_PYNE_LANGUAGE = "pyne";
export const PYNE_RETIRED_ERROR = "PYNE_RETIRED: Pyne is retired. This saved script is kept but never runs.";

const ENGINE_SCRIPT_MARKER = "# __ENGINE__:";

type ScriptIndicatorShape = Pick<
  IndicatorDefinition,
  "engineName" | "script" | "language" | "kind" | "is_builtin"
>;

/** A user-written script: not a builtin engine indicator or builtin preset. */
export function isUserScriptIndicator(indicator: ScriptIndicatorShape | null | undefined): boolean {
  if (!indicator || indicator.engineName) return false;
  if (indicator.kind === "builtin" || indicator.is_builtin === true) return false;
  return typeof indicator.script === "string"
    && indicator.script.trim().length > 0
    && !indicator.script.startsWith(ENGINE_SCRIPT_MARKER);
}

/** The language a script names, or null. Never a default. */
export function explicitScriptLanguage(
  indicator: Pick<IndicatorDefinition, "language"> | null | undefined,
): string | null {
  const language = typeof indicator?.language === "string"
    ? indicator.language.trim().toLowerCase()
    : "";
  return language || null;
}

/**
 * True for a script CandleScope must not run: a Pyne script, or a user
 * script that names no language. Every current creation path writes the
 * language, so a missing one can only mean data from a pre-#105 build, which
 * defaulted to Pyne. It is never read as Pine.
 */
export function isRetiredScriptIndicator(
  indicator: ScriptIndicatorShape | null | undefined,
): boolean {
  if (!indicator) return false;
  if (String(indicator.kind ?? "").trim().toLowerCase() === RETIRED_PYNE_LANGUAGE) return true;
  if (!isUserScriptIndicator(indicator)) return false;
  const language = explicitScriptLanguage(indicator);
  return language === null || language === RETIRED_PYNE_LANGUAGE;
}

/**
 * Upgrades one chart indicator read from storage. Builds before PR #105
 * defaulted script indicators to Pyne and omitted `language` for them, so a
 * stored script without one is a Pyne script. It is marked `language: "pyne"`
 * so every later reader sees the decision; its script, params and id are kept.
 * Anything else is returned unchanged (the same object).
 */
export function upgradePersistedIndicator<T extends IndicatorDefinition>(indicator: T): T {
  if (!isRetiredScriptIndicator(indicator)) return indicator;
  if (explicitScriptLanguage(indicator) === RETIRED_PYNE_LANGUAGE) return indicator;
  return { ...indicator, language: RETIRED_PYNE_LANGUAGE };
}
