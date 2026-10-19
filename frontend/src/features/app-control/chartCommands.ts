import type { ChartSessionRuntime } from "../chart-session/chartSessionTypes.js";
import type { ChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import { normalizeSettings } from "../settings/chartAppearanceSettings.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import type { MarketDataRuntime } from "../market-data/useMarketDataRuntime.js";
import type { ChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntime } from "../drawings/useDrawingRuntime.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, empty, nullable, number, object, optional, record, schema, text } from "./commandSchema.js";
import { chartSettingsPatch } from "./settingsCommands.js";
import { sessionSchema } from "./workspaceCommands.js";

const id = text(96);
const indicatorInput = object({ id, name: text(256), engineName: optional(nullable(text(256))), params: optional(record),
    kind: optional(choice(["builtin", "script", "custom", "pyne"])), executionTarget: optional(choice(["local", "hosted"])),
    script: optional(text(48_000, 0)), language: optional(text(64)), securityMode: optional(choice(["safe", "research"])),
    visible: optional(bool), paneTarget: optional(text(96)), description: optional(text(2048, 0)), category: optional(text(96)),
    renderHints: optional(record), bindingId: optional(id) });
export const indicatorDefinitionSchema = schema<IndicatorDefinition>(indicatorInput.jsonSchema, (v) => indicatorInput.parse(v) as IndicatorDefinition);

export function chartCommands(input: { cellId: string; session: ChartSessionRuntime; indicators: IndicatorRuntime;
  settings: ChartSettingsRuntime; marketData: MarketDataRuntime; surface: ChartSurfaceRuntime; drawings: DrawingRuntime }): ControlCommandGroup {
  const { cellId, session, indicators, settings, marketData, surface, drawings } = input;
  const indicator = (indicatorId: string) => { if (!indicators.view.activeIndicators.some((item) => item.id === indicatorId)) throw new Error("INDICATOR_UNAVAILABLE"); return indicatorId; };
  return { id: `chart:${cellId}`, title: `Chart ${cellId}: data, settings and indicators`,
    context: () => ({ session: session.view.sessionKey, settings: settings.settings, indicators: indicators.view.activeIndicators.map((item) => ({
      id: item.id, bindingId: item.bindingId, name: item.name, engineName: item.engineName, kind: item.kind, executionTarget: item.executionTarget,
      params: item.params, script: item.script, language: item.language, securityMode: item.securityMode, visible: item.visible, paneTarget: item.paneTarget, renderHints: item.renderHints,
    })) }),
    snapshot: () => ({ session: { exchange: session.view.exchange, marketType: session.view.marketType, symbol: session.view.symbol, interval: session.view.interval },
      settings: settings.settings, barCount: marketData.status.barCount, loading: marketData.view.loading,
      sessionCapabilities: session.status, nativeIntervals: session.view.nativeIntervals, customIntervals: session.view.customIntervalRecords,
      exchangeMarketTypes: session.view.exchangeMarketTypes,
      error: marketData.view.error ? String(marketData.view.error) : null, status: {
        initialHistoryPending: marketData.status.initialHistoryPending, activeChartReady: marketData.status.activeChartReady,
        hasMoreLeft: marketData.status.hasMoreLeft, loadingMoreLeft: marketData.status.loadingMoreLeft, loadingMoreRight: marketData.status.loadingMoreRight,
        canLoadMoreLeft: marketData.status.canLoadMoreLeft, canLoadMoreRight: marketData.status.canLoadMoreRight,
        canRestoreLatestWindow: marketData.status.canRestoreLatestWindow,
      },
      visibleRange: surface.actions.getVisibleRange(), indicators: indicators.view.activeIndicators.map(({ lines, ...definition }) => ({
        ...definition, outputPointCount: lines?.reduce((count, line) => count + line.data.length, 0) ?? 0,
      })), computing: indicators.status.computing }), commands: [
      command("session", "Select market, symbol and interval using UI chart-session actions.", sessionSchema, (next) => { session.actions.selectSymbol(next); session.actions.selectInterval(next.interval); }),
      command("interval", "Select a canonical interval, including available custom periods.", object({ interval: text(24) }), ({ interval }) => session.actions.selectInterval(interval)),
      command("refresh", "Refresh the chart dataset.", empty, () => session.actions.refreshDataset()),
      command("retry", "Retry current market loading through the runtime action.", empty, () => marketData.actions.retry()),
      command("loadMoreLeft", "Load earlier history through the existing pagination owner.", empty, () => marketData.actions.loadMoreLeft(), { available: () => marketData.status.canLoadMoreLeft }),
      command("loadMoreRight", "Load later history through the existing pagination owner.", empty, () => {
        if (!marketData.actions.loadMoreRight) throw new Error("PAGINATION_UNAVAILABLE"); return marketData.actions.loadMoreRight();
      }, { available: () => !!marketData.actions.loadMoreRight && !!marketData.status.canLoadMoreRight }),
      command("restoreLatestWindow", "Return the current chart to the latest data window.", empty, () => {
        if (!marketData.actions.restoreLatestWindow) throw new Error("PAGINATION_UNAVAILABLE"); return marketData.actions.restoreLatestWindow();
      }, { available: () => !!marketData.actions.restoreLatestWindow && marketData.status.canRestoreLatestWindow }),
      command("cacheDiagnostics", "Read the existing chart cache diagnostics.", empty, () => marketData.status.cacheDiagnostics(), { readOnly: true }),
      command("settings", "Patch the current chart type/derived-chart parameters.", chartSettingsPatch, (patch) => settings.setSettings((current) => normalizeSettings({ ...current, ...patch }))),
      command("customIntervalCreate", "Create a custom interval using the normal composition guard.", object({ interval: text(24) }), ({ interval }) => session.actions.createCustomInterval(interval)),
      command("customIntervalRemove", "Remove an existing custom interval.", object({ interval: text(24) }), ({ interval }) => session.actions.removeCustomInterval(interval)),
      command("customIntervalsRestore", "Restore custom interval preferences.", empty, () => session.actions.restoreCustomInterval()),
      command("customIntervalsClear", "Clear custom intervals.", empty, () => session.actions.clearCustomIntervals()),
      command("customIntervalPin", "Toggle a custom interval pin.", object({ interval: text(24) }), ({ interval }) => session.actions.togglePinCustomInterval(interval)),
      command("visibleTimeRange", "Navigate the viewport to a time range through the chart adapter.", object({ from: number(0), to: number(0) }), ({ from, to }) => {
        if (to <= from || !surface.actions.setLinkedVisibleTimeRange({ from, to })) throw new Error("VIEWPORT_UNAVAILABLE");
      }),
      command("timeAnchor", "Scroll to a time anchor through the chart adapter.", object({ time: number(0) }), ({ time }) => { if (!surface.actions.setLinkedVisibleTimeAnchor(time)) throw new Error("VIEWPORT_UNAVAILABLE"); }),
      command("crosshair", "Set/clear the linked crosshair time.", object({ time: nullable(number(0)) }), ({ time }) => surface.actions.setLinkedCrosshairTime(time)),
      command("addIndicator", "Add an indicator through the same runtime as the UI. Unsafe execution cannot be enabled by this command.", indicatorDefinitionSchema, (definition) => {
        if (indicators.view.activeIndicators.some((item) => item.id === definition.id)) throw new Error("INDICATOR_ID_CONFLICT"); indicators.actions.addIndicator(definition);
      }),
      command("removeIndicator", "Remove an indicator and clear its associated drawing scopes.", object({ indicatorId: id }), ({ indicatorId }) => { indicator(indicatorId); indicators.actions.removeIndicator(indicatorId); drawings.actions.handleIndicatorRemoved(indicatorId); }),
      command("indicatorVisibility", "Toggle an existing indicator's visibility.", object({ indicatorId: id }), ({ indicatorId }) => indicators.actions.toggleVisibility(indicator(indicatorId))),
      command("indicatorParams", "Update indicator parameters using domain computation and link behavior.", object({ indicatorId: id, params: record }), ({ indicatorId, params }) => indicators.actions.updateIndicatorParams(indicator(indicatorId), params)),
      command("indicatorScript", "Update script source in safe/research mode using the UI runtime; cannot grant unsafe trust.", object({ indicatorId: id, script: text(48_000, 0), language: text(64), securityMode: choice(["safe", "research"]) }),
        ({ indicatorId, script, language, securityMode }) => indicators.actions.updateIndicatorScript(indicator(indicatorId), script, language, securityMode)),
      command("recomputeIndicators", "Request indicator recomputation; inspect computing/error/output state for completion.", object({ force: optional(bool) }), ({ force }) => indicators.actions.recompute(force)),
      command("bars", "Read a bounded tail of currently loaded chart bars.", object({ limit: number(1, 500, true) }), ({ limit }) => marketData.view.bars.slice(-limit), { readOnly: true }),
    ] };
}
