import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { configureChartWorkspaceCellsCandidate } from "./chartWorkspaceBulkUpdate.js";
import { chartWorkspaceWindow, commitChartWorkspaceDocument } from "./chartWorkspaceDocument.js";
import { setChartWorkspaceDocumentLayout, type ChartWorkspaceEditOptions, type ChartWorkspaceEditResult } from "./chartWorkspaceEditing.js";
import { chartWorkspaceTemplateCellCount, visibleCellIds } from "./chartWorkspaceLayout.js";
import type { ChartWorkspaceDocument, ChartWorkspaceTemplateId } from "./chartWorkspaceTypes.js";

export interface ControlChartConfiguration {
  cellId?: string;
  session: ChartSession;
  indicators: IndicatorDefinition[];
}

export interface ControlWorkspaceCommand {
  requestId: string;
  workspaceId: string;
  windowId: string;
  expectedRevision: number;
  layout?: ChartWorkspaceTemplateId;
  charts: ControlChartConfiguration[];
}

export interface ControlWorkspaceReceipt {
  requestId: string;
  ok: boolean;
  revision: number;
  cellIds: string[];
  code?: string;
  message?: string;
}

/** Pure and atomic: a rejected layout or chart configuration changes nothing. */
export function applyControlWorkspaceCommand(
  document: ChartWorkspaceDocument,
  command: ControlWorkspaceCommand,
  options: ChartWorkspaceEditOptions,
): ChartWorkspaceEditResult {
  if (document.revision !== command.expectedRevision) throw new Error("REVISION_CONFLICT");
  if (!document.windows[command.windowId]) throw new Error("WINDOW_UNAVAILABLE");
  const scoped = { ...document, activeWindowId: command.windowId };
  const window = chartWorkspaceWindow(scoped);
  if (command.layout && window.layoutLocked) throw new Error("LAYOUT_LOCKED");
  if (command.layout && chartWorkspaceTemplateCellCount(command.layout) > (options.maxCellsPerWindow ?? 4)) {
    throw new Error("LAYOUT_UNAVAILABLE");
  }
  const edit = command.layout
    ? setChartWorkspaceDocumentLayout(scoped, command.layout, options)
    : { document: scoped, restoreCellIds: [] };
  const ids = visibleCellIds(chartWorkspaceWindow(edit.document).layoutTree);
  if (command.layout && ids.length !== chartWorkspaceTemplateCellCount(command.layout)) {
    throw new Error("LAYOUT_UNAVAILABLE");
  }
  if (command.layout && command.charts.length !== ids.length) throw new Error("CHART_COUNT_MISMATCH");
  const configurations = command.charts.map((chart, index) => {
    const cellId = chart.cellId ?? (command.layout ? ids[index] : undefined);
    if (!cellId || !ids.includes(cellId)) throw new Error("CELL_UNAVAILABLE");
    return { cellId, session: chart.session, indicators: chart.indicators };
  });
  const configured = configureChartWorkspaceCellsCandidate(edit.document, configurations);
  const changed = edit.document !== scoped || configured !== edit.document;
  return {
    document: changed ? commitChartWorkspaceDocument(document, configured) : document,
    restoreCellIds: edit.restoreCellIds,
  };
}
