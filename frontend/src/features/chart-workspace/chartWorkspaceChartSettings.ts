import type { Dispatch, SetStateAction } from "react";
import {
  normalizeSettings,
  type AppearanceTargets,
  type ChartAppearanceOverride,
  type ChartSettings,
} from "../settings/chartAppearanceSettings.js";
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

/** The chart's own appearance keys; anything absent follows the application. */
export function cellAppearanceOverride(cell: ChartCellChartSettings): ChartAppearanceOverride {
  return Object.fromEntries(CELL_CHART_APPEARANCE_KEYS
    .filter(key => cell[key] !== undefined)
    .map(key => [key, cell[key]])) as ChartAppearanceOverride;
}

/** Replaces the chart's own appearance; null returns the chart to following the application. */
export function withCellAppearanceOverride(
  cell: ChartCellChartSettings, override: ChartAppearanceOverride | null,
): ChartCellChartSettings {
  const next: Record<string, unknown> = { ...cell };
  for (const key of CELL_CHART_APPEARANCE_KEYS) {
    delete next[key];
    if (override?.[key] !== undefined) next[key] = override[key];
  }
  return next as ChartCellChartSettings;
}

/** Routes Settings appearance edits: app theme and colours to the app, own appearance to the chart. */
export function buildAppearanceTargets({ application, setApplication, cell, setCell }: {
  application: ChartSettings;
  setApplication: Dispatch<SetStateAction<ChartSettings>>;
  cell: ChartCellChartSettings;
  setCell(next: ChartCellChartSettings): void;
}): AppearanceTargets {
  return {
    application: {
      theme: application.theme,
      customBg: application.customBg,
      upColor: application.upColor,
      downColor: application.downColor,
      update: (patch) => setApplication(previous => ({ ...previous, ...patch })),
    },
    chart: {
      override: cellAppearanceOverride(cell),
      set: (override) => setCell(withCellAppearanceOverride(cell, override)),
    },
  };
}
