import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntime } from "../drawings/useDrawingRuntime.js";
import { indicatorDefinitionSchema } from "./chartCommands.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, empty, nullable, number, object, optional, record, text } from "./commandSchema.js";

/** Explicit-bars charts retain their own backend compute and visibility boundaries. */
export function providedChartCommands(id: string, identity: unknown, indicators: IndicatorRuntime, surface: ChartSurfaceActions, drawings: DrawingRuntime, writable = true): ControlCommandGroup {
  const existing = (id: string) => { if (!indicators.view.activeIndicators.some((row) => row.id === id)) throw new Error("INDICATOR_UNAVAILABLE"); return id; };
  const enabled = () => writable;
  return { id: `chart:${id}`, title: "Imported/replay chart indicators and navigation", context: () => ({ identity, writable, indicators: indicators.view.activeIndicators.map(({ lines, ...definition }) => { void lines; return definition; }) }),
    snapshot: () => ({ identity, writable, computing: indicators.status.computing, indicators: indicators.view.activeIndicators.map(({ lines, ...definition }) => ({ ...definition, outputPointCount: lines?.reduce((n, line) => n + line.data.length, 0) ?? 0 })), visibleRange: surface.getVisibleRange() }), commands: [
      command("addIndicator", "Add an indicator through this chart's provided-bars runtime and capability policy.", indicatorDefinitionSchema, (definition) => {
        if (indicators.view.activeIndicators.some((row) => row.id === definition.id)) throw new Error("INDICATOR_ID_CONFLICT"); indicators.actions.addIndicator(definition);
      }, { available: enabled }),
      command("removeIndicator", "Remove an indicator and its drawing scopes.", object({ indicatorId: text(96) }), ({ indicatorId }) => { existing(indicatorId); drawings.actions.handleIndicatorRemoved(indicatorId); indicators.actions.removeIndicator(indicatorId); }, { available: enabled }),
      command("indicatorVisibility", "Toggle an existing indicator.", object({ indicatorId: text(96) }), ({ indicatorId }) => indicators.actions.toggleVisibility(existing(indicatorId)), { available: enabled }),
      command("indicatorParams", "Edit existing indicator parameters.", object({ indicatorId: text(96), params: record }), ({ indicatorId, params }) => indicators.actions.updateIndicatorParams(existing(indicatorId), params), { available: enabled }),
      command("recomputeIndicators", "Recompute using the chart's own data/visibility authority.", object({ force: optional(bool) }), ({ force }) => indicators.actions.recompute(force), { available: enabled }),
      command("indicatorScript", "Edit an existing script through the provided-bars indicator policy.", object({ indicatorId: text(96), script: text(48000, 0), language: choice(["pine", "pyne"]), securityMode: choice(["safe", "research"]) }), ({ indicatorId, script, language, securityMode }) => indicators.actions.updateIndicatorScript(existing(indicatorId), script, language, securityMode), { available: enabled }),
      command("visibleTimeRange", "Set a linked visible time range.", object({ from: number(0), to: number(0) }), ({ from, to }) => { if (to <= from || !surface.setLinkedVisibleTimeRange({ from, to })) throw new Error("VIEWPORT_UNAVAILABLE"); }),
      command("timeAnchor", "Navigate to a visible time anchor.", object({ time: number(0) }), ({ time }) => { if (!surface.setLinkedVisibleTimeAnchor(time)) throw new Error("VIEWPORT_UNAVAILABLE"); }),
      command("crosshair", "Set/clear the linked crosshair.", object({ time: nullable(number(0)) }), ({ time }) => surface.setLinkedCrosshairTime(time)),
      command("viewport", "Read the currently visible range.", empty, () => surface.getVisibleRange(), { readOnly: true }),
    ] };
}
