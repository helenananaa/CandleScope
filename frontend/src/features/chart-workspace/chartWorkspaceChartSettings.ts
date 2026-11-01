import { normalizeSettings, type ChartSettings } from "../settings/chartAppearanceSettings.js";
import { CELL_CHART_APPEARANCE_KEYS, CELL_CHART_SETTING_KEYS, type ChartCellChartSettings } from "./chartWorkspaceTypes.js";

export const ALL_CELL_CHART_SETTING_KEYS = [...CELL_CHART_SETTING_KEYS, ...CELL_CHART_APPEARANCE_KEYS] as const;

export function pickCellChartSettings(settings: Partial<ChartSettings>): ChartCellChartSettings {
  const normalized = normalizeSettings(settings);
  return Object.fromEntries([
    ...CELL_CHART_SETTING_KEYS.map(key => [key, normalized[key]]),
    ...CELL_CHART_APPEARANCE_KEYS.filter(key => {
      const value = settings[key];
      return typeof value === "string" && (key === "theme"
        ? ["dark", "light", "system", "custom"].includes(value)
        : value.trim().length > 0 && value.length <= 256);
    })
      .map(key => [key, normalized[key]]),
  ]) as ChartCellChartSettings;
}

export function nextCellChartSettings(
  cell: ChartCellChartSettings, current: ChartSettings, next: ChartSettings,
): ChartCellChartSettings {
  return pickCellChartSettings(Object.fromEntries([
    ...CELL_CHART_SETTING_KEYS.map(key => [key, next[key]]),
    ...CELL_CHART_APPEARANCE_KEYS.filter(key => cell[key] !== undefined || current[key] !== next[key])
      .map(key => [key, next[key]]),
  ]) as Partial<ChartSettings>);
}

export function sameCellChartSettings(left: ChartCellChartSettings, right: ChartCellChartSettings): boolean {
  return ALL_CELL_CHART_SETTING_KEYS.every(key => left[key] === right[key]);
}

export function applicationSettingsPatch(current: ChartSettings, next: ChartSettings): Partial<ChartSettings> {
  const cellKeys = new Set<string>(ALL_CELL_CHART_SETTING_KEYS);
  return Object.fromEntries(Object.entries(next).filter(([key, value]) => {
    if (cellKeys.has(key)) return false;
    // Normalization reconstructs row limits even during a color-only edit.
    if (key === "cacheLimits") return next.cacheLimits.minutes !== current.cacheLimits.minutes
      || next.cacheLimits.hours !== current.cacheLimits.hours || next.cacheLimits.daily !== current.cacheLimits.daily;
    return value !== current[key];
  }));
}
