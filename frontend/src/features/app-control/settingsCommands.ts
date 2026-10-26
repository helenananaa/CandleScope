import { normalizeSettings, type ChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import { LOCALES } from "../../i18n/index.js";
import { MAIN_CHART_TYPES } from "../../shared/mainChartTypes.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, nullable, number, object, optional, text } from "./commandSchema.js";

export const chartSettingsPatch = object({
  chartType: optional(choice(MAIN_CHART_TYPES)), renkoBoxSizeMode: optional(choice(["atr", "traditional"])),
  renkoAtrLength: optional(number(2, 500, true)), renkoBoxSize: optional(number(0.00000001)),
  pointFigureBoxSizeMode: optional(choice(["atr", "traditional"])), pointFigureAtrLength: optional(number(2, 500, true)),
  pointFigureBoxSize: optional(number(0.00000001)), pointFigureReversalAmount: optional(number(1, 100, true)),
  kagiReversalMode: optional(choice(["atr", "traditional"])), kagiAtrLength: optional(number(2, 500, true)),
  kagiReversalAmount: optional(number(0.00000001)), lineBreakNumberOfLines: optional(number(1, 100, true)),
});
const appearancePatch = object({ theme: optional(choice(["dark", "light", "system", "custom"])), customBg: optional(text(64)),
  upColor: optional(text(64)), downColor: optional(text(64)), timezone: optional(text(128)), locale: optional(choice(LOCALES)) });
const cachePatch = object({ cachePreset: optional(text(64)), cacheLimits: optional(object({ minutes: number(0, 100_000_000, true), hours: number(0, 100_000_000, true), daily: number(0, 100_000_000, true) })),
  ephemeralCacheBars: optional(number(1, 10_000_000, true)), frontendCacheBudgetBytes: optional(number(1, 1e12, true)),
  sqliteStorageBudgetBytes: optional(nullable(number(1, 1e15, true))), storageRowLimitsEnabled: optional(bool) });

export function settingsCommands(runtime: ChartSettingsRuntime, id = "settings"): ControlCommandGroup {
  return { id, title: "Appearance, locale and cache preferences", context: () => runtime.settings,
    snapshot: () => ({ settings: runtime.settings, resolvedTheme: runtime.resolvedTheme }), commands: [
      command("appearance", "Patch appearance and locale through the same persisted settings action as the UI.", appearancePatch,
        (patch) => runtime.setSettings((current) => normalizeSettings({ ...current, ...patch }))),
      command("cache", "Patch cache preferences; this does not trigger GC or delete stored data.", cachePatch,
        (patch) => runtime.setSettings((current) => normalizeSettings({ ...current, ...patch }))),
    ] };
}
