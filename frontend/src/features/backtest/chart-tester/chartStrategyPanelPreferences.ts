import { normalizeChartStrategyAttachment } from "../../chart-workspace/chartWorkspaceStorage.js";
import type { ChartStrategyAttachmentRecord } from "../../chart-workspace/chartWorkspaceTypes.js";
import type { ContinuousMode } from "../continuous/continuousTypes.js";

export type ChartStrategyPanelTab = "script" | "overview" | "trades" | "settings";

export interface ChartStrategyPanelPreferences {
  height: number;
  activeTab: ChartStrategyPanelTab;
  runMode?: ContinuousMode;
  runModeDraftId?: string;
}

export const CHART_STRATEGY_MIN_PANEL_HEIGHT = 260;
export const CHART_STRATEGY_MAX_PANEL_HEIGHT = 520;

function panelPreferenceKey(cellScope: string): string {
  return `candlescope.chart-strategy-panel.v1.${encodeURIComponent(cellScope)}`;
}

export function clampChartStrategyPanelHeight(value: number): number {
  const viewportLimit = typeof window === "undefined"
    ? CHART_STRATEGY_MAX_PANEL_HEIGHT
    : Math.max(CHART_STRATEGY_MIN_PANEL_HEIGHT, Math.floor(window.innerHeight * 0.68));
  return Math.min(
    CHART_STRATEGY_MAX_PANEL_HEIGHT,
    viewportLimit,
    Math.max(CHART_STRATEGY_MIN_PANEL_HEIGHT, Math.round(value)),
  );
}

export function loadChartStrategyPanelPreferences(
  cellScope: string,
  storage: Pick<Storage, "getItem"> | null = typeof localStorage === "undefined" ? null : localStorage,
): ChartStrategyPanelPreferences {
  const fallback: ChartStrategyPanelPreferences = {
    height: clampChartStrategyPanelHeight(383),
    activeTab: "script",
  };
  if (!storage) return fallback;
  try {
    const parsed = JSON.parse(storage.getItem(panelPreferenceKey(cellScope)) ?? "null") as Partial<ChartStrategyPanelPreferences> | null;
    const tab = parsed?.activeTab;
    return {
      height: clampChartStrategyPanelHeight(Number(parsed?.height ?? fallback.height)),
      activeTab: tab === "script" || tab === "overview" || tab === "trades" || tab === "settings"
        ? tab
        : fallback.activeTab,
      ...(parsed?.runMode === "HISTORY_LIVE" || parsed?.runMode === "LIVE_ONLY" ? { runMode: parsed.runMode } : {}),
      ...(typeof parsed?.runModeDraftId === "string" && parsed.runModeDraftId.length > 0
        && parsed.runModeDraftId.length <= 160 ? { runModeDraftId: parsed.runModeDraftId } : {}),
    };
  } catch {
    return fallback;
  }
}

export function saveChartStrategyPanelPreferences(
  cellScope: string,
  preferences: ChartStrategyPanelPreferences,
  storage: Pick<Storage, "setItem"> | null = typeof localStorage === "undefined" ? null : localStorage,
): void {
  if (!storage) return;
  try {
    storage.setItem(panelPreferenceKey(cellScope), JSON.stringify({
      height: clampChartStrategyPanelHeight(preferences.height),
      activeTab: preferences.activeTab,
      ...(preferences.runMode ? { runMode: preferences.runMode } : {}),
      ...(preferences.runModeDraftId ? { runModeDraftId: preferences.runModeDraftId } : {}),
    }));
  } catch {
    // Preference storage is best-effort and must not block a Run or its result.
  }
}

export function resolveChartStrategyRunMode(
  preference: Pick<ChartStrategyPanelPreferences, "runMode" | "runModeDraftId">,
  attachment: ChartStrategyAttachmentRecord | null,
): ContinuousMode {
  const preferred = attachment?.initialization?.preferredRunMode;
  if (preferred && (!attachment.strategyDraftId || preference.runModeDraftId !== attachment.strategyDraftId)) return preferred;
  return preference.runMode ?? "HISTORY";
}

function detachedAttachmentKey(cellScope: string): string {
  return `candlescope.chart-strategy-detached.v1.${encodeURIComponent(cellScope)}`;
}

export function loadDetachedChartStrategy(cellScope: string): ChartStrategyAttachmentRecord | null {
  try {
    const raw = localStorage.getItem(detachedAttachmentKey(cellScope));
    const attachment = raw ? normalizeChartStrategyAttachment(JSON.parse(raw)) : null;
    return attachment?.strategyDraftId ? attachment : null;
  } catch {
    return null;
  }
}

export function saveDetachedChartStrategy(cellScope: string, value: ChartStrategyAttachmentRecord): boolean {
  const attachment = normalizeChartStrategyAttachment(value);
  if (!attachment?.strategyDraftId) return false;
  try {
    localStorage.setItem(detachedAttachmentKey(cellScope), JSON.stringify(attachment));
    return true;
  } catch {
    return false;
  }
}
