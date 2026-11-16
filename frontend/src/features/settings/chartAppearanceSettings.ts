import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getExtensionState, subscribeExtensions } from "../extensions/state.js";
import {
  DEFAULT_LOCALE,
  setLocaleAsync,
  normalizeLocale,
  type LocaleId,
} from "../../i18n/index.js";
import { normalizeMainChartType } from "../../shared/mainChartTypes.js";
import { CHART_THEME_COLORS, chartSchemeForBackground } from "../../chart-adapter/chartPalette.js";
import type { Dispatch, SetStateAction } from "react";
import type { MainChartType } from "../../shared/mainChartTypes.js";

const SETTINGS_STORAGE_KEY = "candlescope-settings";
const PRICE_BOX_SIZE_MODES = new Set(["atr", "traditional"]);
export type ChartTheme = "dark" | "light" | "system" | "custom";
/** The app theme never takes "custom"; custom backgrounds belong to individual charts. */
export type ApplicationTheme = Exclude<ChartTheme, "custom">;
export type PriceBoxSizeMode = "atr" | "traditional";

export interface CacheRowLimits {
  seconds: number;
  minutes: number;
  hours: number;
  daily: number;
}

export interface ChartSettings extends Record<string, unknown> {
  theme: ChartTheme;
  customBg: string;
  upColor: string;
  downColor: string;
  chartType: MainChartType;
  renkoBoxSizeMode: PriceBoxSizeMode;
  renkoAtrLength: number;
  renkoBoxSize: number;
  pointFigureBoxSizeMode: PriceBoxSizeMode;
  pointFigureAtrLength: number;
  pointFigureBoxSize: number;
  pointFigureReversalAmount: number;
  kagiReversalMode: PriceBoxSizeMode;
  kagiAtrLength: number;
  kagiReversalAmount: number;
  lineBreakNumberOfLines: number;
  cachePreset: string;
  cacheLimits: CacheRowLimits;
  ephemeralCacheBars: number;
  frontendCacheBudgetBytes: number;
  sqliteStorageBudgetBytes: number | null;
  storageRowLimitsEnabled: boolean;
  timezone?: string;
  locale: LocaleId;
}

export const DEFAULT_SETTINGS: ChartSettings = {
  theme: "dark",
  customBg: CHART_THEME_COLORS.dark.background,
  upColor: "#22c55e",
  downColor: "#ef4444",
  chartType: "candlestick",
  renkoBoxSizeMode: "atr",
  renkoAtrLength: 14,
  renkoBoxSize: 1,
  pointFigureBoxSizeMode: "atr",
  pointFigureAtrLength: 14,
  pointFigureBoxSize: 1,
  pointFigureReversalAmount: 3,
  kagiReversalMode: "atr",
  kagiAtrLength: 14,
  kagiReversalAmount: 1,
  lineBreakNumberOfLines: 3,
  cachePreset: "standard",
  cacheLimits: { seconds: 86400, minutes: 200000, hours: 50000, daily: 0 },
  ephemeralCacheBars: 86400,
  frontendCacheBudgetBytes: 64 * 1024 * 1024,
  sqliteStorageBudgetBytes: null,
  storageRowLimitsEnabled: false,
  locale: DEFAULT_LOCALE,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeBoxSizeMode(value: unknown, fallback: PriceBoxSizeMode): PriceBoxSizeMode {
  return typeof value === "string" && PRICE_BOX_SIZE_MODES.has(value) ? value as PriceBoxSizeMode : fallback;
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number): number {
  if (
    value == null
    || typeof value === "boolean"
    || (typeof value === "string" && value.trim() === "")
  ) return fallback;
  const parsed = Math.trunc(Number(value));
  return Number.isFinite(parsed) && parsed >= minimum && parsed <= maximum ? parsed : fallback;
}

export function normalizeSettings(settings: unknown = {}): ChartSettings {
  const source = isRecord(settings) ? settings : {};
  const normalized = { ...DEFAULT_SETTINGS, ...source };
  normalized.chartType = normalizeMainChartType(source.chartType ?? normalized.chartType);
  normalized.renkoBoxSizeMode = normalizeBoxSizeMode(
    source.renkoBoxSizeMode,
    DEFAULT_SETTINGS.renkoBoxSizeMode,
  );
  const atrLength = Math.trunc(Number(normalized.renkoAtrLength));
  normalized.renkoAtrLength = Number.isFinite(atrLength) && atrLength >= 2 && atrLength <= 500
    ? atrLength
    : DEFAULT_SETTINGS.renkoAtrLength;
  const boxSize = Number(normalized.renkoBoxSize);
  normalized.renkoBoxSize = Number.isFinite(boxSize) && boxSize > 0
    ? boxSize
    : DEFAULT_SETTINGS.renkoBoxSize;
  normalized.pointFigureBoxSizeMode = normalizeBoxSizeMode(
    source.pointFigureBoxSizeMode,
    DEFAULT_SETTINGS.pointFigureBoxSizeMode,
  );
  const pointFigureAtrLength = Math.trunc(Number(normalized.pointFigureAtrLength));
  normalized.pointFigureAtrLength = Number.isFinite(pointFigureAtrLength)
    && pointFigureAtrLength >= 2
    && pointFigureAtrLength <= 500
    ? pointFigureAtrLength
    : DEFAULT_SETTINGS.pointFigureAtrLength;
  const pointFigureBoxSize = Number(normalized.pointFigureBoxSize);
  normalized.pointFigureBoxSize = Number.isFinite(pointFigureBoxSize) && pointFigureBoxSize > 0
    ? pointFigureBoxSize
    : DEFAULT_SETTINGS.pointFigureBoxSize;
  const pointFigureReversalAmount = Math.trunc(Number(normalized.pointFigureReversalAmount));
  normalized.pointFigureReversalAmount = Number.isFinite(pointFigureReversalAmount)
    && pointFigureReversalAmount >= 1
    && pointFigureReversalAmount <= 100
    ? pointFigureReversalAmount
    : DEFAULT_SETTINGS.pointFigureReversalAmount;
  normalized.kagiReversalMode = normalizeBoxSizeMode(
    source.kagiReversalMode,
    DEFAULT_SETTINGS.kagiReversalMode,
  );
  const kagiAtrLength = Math.trunc(Number(normalized.kagiAtrLength));
  normalized.kagiAtrLength = Number.isFinite(kagiAtrLength)
    && kagiAtrLength >= 2
    && kagiAtrLength <= 500
    ? kagiAtrLength
    : DEFAULT_SETTINGS.kagiAtrLength;
  const kagiReversalAmount = Number(normalized.kagiReversalAmount);
  normalized.kagiReversalAmount = Number.isFinite(kagiReversalAmount)
    && kagiReversalAmount > 0
    ? kagiReversalAmount
    : DEFAULT_SETTINGS.kagiReversalAmount;
  const lineBreakNumberOfLines = Math.trunc(Number(normalized.lineBreakNumberOfLines));
  normalized.lineBreakNumberOfLines = Number.isFinite(lineBreakNumberOfLines)
    && lineBreakNumberOfLines >= 1
    && lineBreakNumberOfLines <= 50
    ? lineBreakNumberOfLines
    : DEFAULT_SETTINGS.lineBreakNumberOfLines;
  const cacheLimits = isRecord(source.cacheLimits) ? source.cacheLimits : {};
  normalized.cacheLimits = {
    seconds: boundedInteger(cacheLimits.seconds, source.cachePreset === "unlimited" ? 0 : DEFAULT_SETTINGS.cacheLimits.seconds, 0, 100_000_000),
    minutes: boundedInteger(cacheLimits.minutes, DEFAULT_SETTINGS.cacheLimits.minutes, 0, 100_000_000),
    hours: boundedInteger(cacheLimits.hours, DEFAULT_SETTINGS.cacheLimits.hours, 0, 100_000_000),
    daily: boundedInteger(cacheLimits.daily, DEFAULT_SETTINGS.cacheLimits.daily, 0, 100_000_000),
  };
  normalized.ephemeralCacheBars = boundedInteger(
    source.ephemeralCacheBars,
    DEFAULT_SETTINGS.ephemeralCacheBars,
    1,
    1_000_000,
  );
  normalized.frontendCacheBudgetBytes = boundedInteger(
    source.frontendCacheBudgetBytes,
    DEFAULT_SETTINGS.frontendCacheBudgetBytes,
    16 * 1024 * 1024,
    4 * 1024 * 1024 * 1024,
  );
  normalized.sqliteStorageBudgetBytes = source.sqliteStorageBudgetBytes === null
    ? null
    : boundedInteger(
      source.sqliteStorageBudgetBytes,
      DEFAULT_SETTINGS.sqliteStorageBudgetBytes ?? 0,
      1,
      16 * 1024 * 1024 * 1024 * 1024,
    ) || null;
  normalized.storageRowLimitsEnabled = typeof source.storageRowLimitsEnabled === "boolean"
    ? source.storageRowLimitsEnabled
    : DEFAULT_SETTINGS.storageRowLimitsEnabled;
  normalized.locale = normalizeLocale(source.locale ?? normalized.locale);
  return normalized;
}

function getSystemTheme(): "dark" | "light" {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function subscribeSystemTheme(notify: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
  const query = window.matchMedia("(prefers-color-scheme: light)");
  if (query.addEventListener) {
    query.addEventListener("change", notify);
    return () => query.removeEventListener("change", notify);
  }
  query.addListener(notify);
  return () => query.removeListener(notify);
}

/** Resolve a cell override without changing application/document theme tokens. */
export function useCellChartTheme(theme: ChartTheme | undefined, inheritedTheme: string): string {
  const systemTheme = useSyncExternalStore(subscribeSystemTheme, getSystemTheme, () => "dark");
  return theme === undefined ? inheritedTheme : theme === "system" ? systemTheme : theme;
}

/**
 * Application settings only. Older versions allowed a custom app background; it now
 * becomes dark or light by brightness, and the colour stays as the starting value for
 * charts that get their own background.
 */
export function migrateApplicationSettings(settings: ChartSettings): ChartSettings {
  return settings.theme === "custom" ? { ...settings, theme: chartSchemeForBackground(settings.customBg) } : settings;
}

export function parseStoredSettings(saved: string | null | undefined): ChartSettings {
  if (!saved) return normalizeSettings();
  try {
    return migrateApplicationSettings(normalizeSettings(JSON.parse(saved)));
  } catch {
    return normalizeSettings();
  }
}

export function settingsFromStorageChange(
  key: string | null,
  newValue: string | null,
): ChartSettings | null {
  if (key !== SETTINGS_STORAGE_KEY && key !== null) return null;
  if (newValue) {
    try { JSON.parse(newValue); } catch { return null; }
  }
  return parseStoredSettings(newValue);
}

/** Remembers that the first launch with per-chart appearance was checked for the app theme offer. */
export const CHART_APPEARANCE_OFFER_KEY = "candlescope-chart-appearance-offer-v1";

/**
 * Whether the app theme offer was already considered on this profile, and marks it considered.
 * Unreadable storage counts as considered, so the offer never repeats.
 */
export function takeChartAppearanceOfferCheck(): boolean {
  try {
    if (localStorage.getItem(CHART_APPEARANCE_OFFER_KEY) !== null) return true;
    localStorage.setItem(CHART_APPEARANCE_OFFER_KEY, new Date().toISOString());
    return false;
  } catch {
    return true;
  }
}

function loadSettings(): ChartSettings {
  if (typeof localStorage === "undefined") return normalizeSettings();
  try {
    return parseStoredSettings(localStorage.getItem(SETTINGS_STORAGE_KEY));
  } catch {
    return normalizeSettings();
  }
}

/** Lets the desktop shell fill new and resizing windows with the app background instead of dark. */
function reportDesktopAppearance(root: HTMLElement): void {
  const bridge = typeof window === "undefined" ? undefined : window.candlescopeDesktop;
  if (!bridge?.setAppearance) return;
  const background = getComputedStyle(root).getPropertyValue("--surface-0").trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(background)) bridge.setAppearance({ background });
}

export function readPersistedLocale(): LocaleId {
  return loadSettings().locale;
}

/** A chart's own appearance; keys that are absent follow the application. */
export type ChartAppearanceOverride = Partial<Pick<ChartSettings, "theme" | "customBg" | "upColor" | "downColor">>;

/**
 * Where appearance edits go when Settings is opened from a chart: the app theme and
 * colours always go to the application; the chart's own appearance goes to that chart.
 */
export interface AppearanceTargets {
  application: {
    theme: ChartTheme;
    customBg: string;
    upColor: string;
    downColor: string;
    update(patch: Partial<Pick<ChartSettings, "theme" | "upColor" | "downColor">>): void;
  };
  chart: {
    override: ChartAppearanceOverride;
    set(override: ChartAppearanceOverride | null): void;
    /** Other charts that take this chart's appearance through chart style linking. */
    linkedCharts?: number;
  };
  /**
   * Present where each chart edits its own appearance in its header menu: Settings then only says
   * how many charts have their own appearance and can return them all to the app theme.
   */
  workspace?: {
    overrides: number;
    resetAll(): void;
  };
}

export interface ChartSettingsRuntime {
  appearanceScope?: "chart" | "application";
  appearanceTargets?: AppearanceTargets;
  inheritApplicationTheme?: boolean;
  settings: ChartSettings;
  setSettings: Dispatch<SetStateAction<ChartSettings>>;
  resolvedTheme: string;
}

export function useChartSettingsRuntime(): ChartSettingsRuntime {
  const extension = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const [settings, updateSettings] = useState<ChartSettings>(loadSettings);
  const previousLocale = useRef(settings.locale);
  const persistRequested = useRef(false);
  const setSettings = useCallback<Dispatch<SetStateAction<ChartSettings>>>((action) => {
    persistRequested.current = true;
    updateSettings(action);
  }, []);
  const [systemTheme, setSystemTheme] = useState(getSystemTheme);
  const resolvedTheme = extension.theme?.base ?? (settings.theme === "system" ? systemTheme : settings.theme);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: light)");
    const handleSystemThemeChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "light" : "dark");
    };

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener("change", handleSystemThemeChange);
      return () => mediaQuery.removeEventListener("change", handleSystemThemeChange);
    }

    mediaQuery.addListener(handleSystemThemeChange);
    return () => mediaQuery.removeListener(handleSystemThemeChange);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleStorageChange = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== window.localStorage) return;
      const incoming = settingsFromStorageChange(event.key, event.newValue);
      if (!incoming) return;
      persistRequested.current = false;
      updateSettings((current) => (
        JSON.stringify(current) === JSON.stringify(incoming) ? current : incoming
      ));
    };
    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", resolvedTheme);
    // Older builds painted a custom app background into the chrome; custom backgrounds are chart-only now.
    root.style.removeProperty("--surface-0");
    root.style.removeProperty("--surface-1");
    reportDesktopAppearance(root);
    root.style.setProperty("--candle-up", settings.upColor);
    root.style.setProperty("--candle-down", settings.downColor);
    try {
      if (persistRequested.current) {
        localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
        persistRequested.current = false;
      }
    } catch {
      // Settings persistence failures must not interrupt chart rendering.
    }
  }, [resolvedTheme, settings]);

  useEffect(() => {
    // Entry points hydrate before mounting. A newly mounted research chart
    // must not cancel a user language selection still loading in the shell.
    if (previousLocale.current === settings.locale) return;
    previousLocale.current = settings.locale;
    void setLocaleAsync(settings.locale).catch((error) => {
      console.warn("Saved locale could not be loaded; retaining the current language", error);
    });
  }, [settings.locale]);

  const tokens = extension.theme?.tokens;
  return { settings: tokens ? {
    ...settings,
    customBg: tokens["bg-primary"] ?? settings.customBg,
    upColor: tokens["candle-up"] ?? settings.upColor,
    downColor: tokens["candle-down"] ?? settings.downColor,
  } : settings, setSettings, resolvedTheme };
}
