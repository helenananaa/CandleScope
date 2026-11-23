import type { SingleChartPanesProps } from "../../components/SingleChartPanes.js";
import type { ChartSettings } from "../settings/chartAppearanceSettings.js";

/** The chart appearance settings both research charts pass to the shared chart surface. */
export function researchChartAppearance(settings: ChartSettings, theme: string): Pick<SingleChartPanesProps,
  "upColor" | "downColor" | "chartType" | "theme" | "customBg" | "renkoBoxSizeMode" | "renkoAtrLength" | "renkoBoxSize"
  | "pointFigureBoxSizeMode" | "pointFigureAtrLength" | "pointFigureBoxSize" | "pointFigureReversalAmount"
  | "kagiReversalMode" | "kagiAtrLength" | "kagiReversalAmount" | "lineBreakNumberOfLines"> {
  return {
    upColor: settings.upColor,
    downColor: settings.downColor,
    chartType: settings.chartType,
    theme,
    customBg: settings.customBg,
    renkoBoxSizeMode: settings.renkoBoxSizeMode,
    renkoAtrLength: settings.renkoAtrLength,
    renkoBoxSize: settings.renkoBoxSize,
    pointFigureBoxSizeMode: settings.pointFigureBoxSizeMode,
    pointFigureAtrLength: settings.pointFigureAtrLength,
    pointFigureBoxSize: settings.pointFigureBoxSize,
    pointFigureReversalAmount: settings.pointFigureReversalAmount,
    kagiReversalMode: settings.kagiReversalMode,
    kagiAtrLength: settings.kagiAtrLength,
    kagiReversalAmount: settings.kagiReversalAmount,
    lineBreakNumberOfLines: settings.lineBreakNumberOfLines,
  };
}
