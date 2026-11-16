import type { Dispatch, SetStateAction } from "react";
import {
  normalizeSettings,
  type AppearanceTargets,
  type ChartAppearanceOverride,
  type ChartSettings,
} from "../settings/chartAppearanceSettings.js";
import { CELL_CHART_APPEARANCE_KEYS, CELL_CHART_SETTING_KEYS, type ChartCellChartSettings, type ChartCellId, type ChartWorkspaceDocument } from "./chartWorkspaceTypes.js";

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
export function buildAppearanceTargets({ application, setApplication, cell, setCell, linkedCharts, workspace }: {
  application: ChartSettings;
  setApplication: Dispatch<SetStateAction<ChartSettings>>;
  cell: ChartCellChartSettings;
  setCell(next: ChartCellChartSettings): void;
  linkedCharts?: number;
  workspace?: AppearanceTargets["workspace"];
}): AppearanceTargets {
  return {
    ...(workspace ? { workspace } : {}),
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
      ...(linkedCharts ? { linkedCharts } : {}),
    },
  };
}

/** Whether a chart has its own appearance (any appearance key set). */
export function hasCellAppearanceOverride(cell: ChartCellChartSettings): boolean {
  return CELL_CHART_APPEARANCE_KEYS.some(key => cell[key] !== undefined);
}

/** The listed charts that use their own appearance. */
export function cellsWithAppearanceOverride(document: ChartWorkspaceDocument, cellIds: readonly ChartCellId[]): ChartCellId[] {
  return cellIds.filter(cellId => {
    const cell = document.cells[cellId];
    return cell !== undefined && hasCellAppearanceOverride(cell.chartSettings);
  });
}

/** Every listed chart follows the application again. Returns the same document when nothing changes. */
export function withoutCellAppearanceOverrides(document: ChartWorkspaceDocument, cellIds: readonly ChartCellId[]): ChartWorkspaceDocument {
  const targets = cellsWithAppearanceOverride(document, cellIds);
  if (!targets.length) return document;
  const cells = { ...document.cells };
  for (const cellId of targets) {
    const cell = cells[cellId]!;
    cells[cellId] = { ...cell, chartSettings: withCellAppearanceOverride(cell.chartSettings, null) };
  }
  return { ...document, cells };
}

/**
 * The theme every listed chart sets on its own, when all of them set the same dark or light theme
 * and nothing else (no custom background or colours). Such a layout was most likely made with the
 * old chart-scoped theme picker, so the app theme can take that value instead. Null otherwise.
 */
export function sharedCellAppearanceTheme(document: ChartWorkspaceDocument, cellIds: readonly ChartCellId[]): "dark" | "light" | null {
  let shared: "dark" | "light" | null = null;
  for (const cellId of cellIds) {
    const cell = document.cells[cellId];
    if (!cell) return null;
    const override = cellAppearanceOverride(cell.chartSettings);
    const keys = Object.keys(override);
    if (keys.length !== 1 || (override.theme !== "dark" && override.theme !== "light")) return null;
    if (shared !== null && shared !== override.theme) return null;
    shared = override.theme;
  }
  return shared;
}
