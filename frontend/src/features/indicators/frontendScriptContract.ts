import type { IndicatorDefinition, ScriptRuntimeCatalog } from "./indicatorTypes.js";

export const FRONTEND_SCRIPT_LANGUAGE = "frontend-js";
export const FRONTEND_SCRIPT_STARTER = `// bars: the currently loaded chart window; params: your saved parameters.
// plot(name, values, { pane: "main" | "separate", color: "#rrggbb" }).
const length = Number(params.length ?? 20);
if (!Number.isInteger(length) || length < 1) throw new Error("Invalid length");
const values = bars.map((bar, index) => {
  if (index + 1 < length) return null;
  let sum = 0;
  for (let i = index + 1 - length; i <= index; i++) sum += bars[i].close;
  return sum / length;
});
plot("SMA", values, { pane: "main", color: "#f59e0b" });
`;

export function isFrontendScript(indicator: Pick<IndicatorDefinition, "language"> | null | undefined): boolean {
  return indicator?.language?.trim().toLowerCase() === FRONTEND_SCRIPT_LANGUAGE;
}

/** A first-party browser capability, independent of installed engine plugins. */
export function withFrontendScriptRuntime(catalog: ScriptRuntimeCatalog): ScriptRuntimeCatalog {
  const language = {
    id: FRONTEND_SCRIPT_LANGUAGE, name: "JavaScript (Frontend)",
    extensions: [".js"], aliases: [FRONTEND_SCRIPT_LANGUAGE],
  };
  const id = "candlescope.frontend-js";
  return {
    ...catalog,
    languages: [...catalog.languages.filter(item => item.id !== language.id), {
      ...language, runtimeId: id, routeMode: "browser", available: true,
      features: ["window-plots/1"],
    }],
    runtimes: [...catalog.runtimes.filter(item => item.id !== id), {
      id, name: "Frontend JavaScript", version: "1", package: "candlescope-frontend",
      languages: [language], features: ["window-plots/1"], requiredHostFeatures: [],
      meta: { ui: { languages: { [language.id]: {
        monacoLanguage: "javascript", starterSource: FRONTEND_SCRIPT_STARTER,
      } } } },
    }],
  };
}
