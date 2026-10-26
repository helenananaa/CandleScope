import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { CHART_WORKSPACE_TEMPLATE_IDS } from "../chart-workspace/chartWorkspaceTypes.js";
import type { ChartLinkGroupSettingsPatch } from "../chart-workspace/chartWorkspaceLinkModel.js";
import { chartWorkspaceTemplateCellCount } from "../chart-workspace/chartWorkspaceLayout.js";
import { CHART_WORKSPACE_FEATURE_FLAGS } from "../chart-workspace/chartWorkspaceCapacity.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { canonicalizeIntervalValue } from "../../utils/intervals.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, nullable, number, object, optional, schema, text } from "./commandSchema.js";

const id = text(96);
const sessionInput = object({ exchange: id, marketType: id, symbol: text(96), interval: text(24),
    providerId: optional(id), venue: optional(id), assetClass: optional(id), seriesVariant: optional(id),
    priceAdjustment: optional(id), sessionVariant: optional(id), volumeSemantics: optional(id) });
export const sessionSchema = schema<ChartSession>(sessionInput.jsonSchema, (v) => {
  const parsed = sessionInput.parse(v);
  if (canonicalizeIntervalValue(parsed.interval) !== parsed.interval) throw new Error("INVALID_INTERVAL");
  return parsed;
});
const policyInput = object({ market: optional(bool), interval: optional(bool), crosshair: optional(bool), timeAnchor: optional(bool), dateRange: optional(bool), drawings: optional(bool),
    indicators: optional(object({ definitions: optional(bool), parameters: optional(bool), visual: optional(bool), paneLayout: optional(bool) })) });
const policy = schema<ChartLinkGroupSettingsPatch>(policyInput.jsonSchema, (v) => policyInput.parse(v) as ChartLinkGroupSettingsPatch);

export function workspaceCommands(runtime: ChartWorkspaceRuntime): ControlCommandGroup {
  const { view, actions: a } = runtime;
  const unlocked = () => view.ready && !view.layoutLocked;
  const cell = (cellId: string) => { if (!view.layoutCellIds.includes(cellId)) throw new Error("CELL_UNAVAILABLE"); return view.document.cells[cellId]!; };
  const template = choice(CHART_WORKSPACE_TEMPLATE_IDS);
  const workspace = (workspaceId: string) => { if (!view.workspaces.some((w) => w.id === workspaceId)) throw new Error("WORKSPACE_UNAVAILABLE"); return workspaceId; };
  return { id: "workspace", title: "Workspaces, layouts, links and windows", context: () => ({ workspaceId: view.activeWorkspaceId, revision: view.document.revision }),
    snapshot: () => ({ ...view, status: runtime.status }), commands: [
      command("switch", "Switch to an existing workspace.", object({ workspaceId: id }), ({ workspaceId }) => a.switchWorkspace(workspace(workspaceId))),
      command("create", "Create a workspace from a built-in template.", object({ templateId: template }), ({ templateId }) => {
        if (chartWorkspaceTemplateCellCount(templateId) > view.maxCellsPerWindow) throw new Error("LAYOUT_UNAVAILABLE"); a.createWorkspace(templateId);
      }),
      command("duplicate", "Duplicate an existing workspace.", object({ workspaceId: id }), ({ workspaceId }) => a.duplicateWorkspace(workspace(workspaceId))),
      command("rename", "Rename an existing workspace.", object({ workspaceId: id, name: text(128) }), ({ workspaceId, name }) => a.renameWorkspace(workspace(workspaceId), name)),
      command("delete", "Delete an existing workspace using the same last-workspace guard as the UI.", object({ workspaceId: id }), ({ workspaceId }) => a.deleteWorkspace(workspace(workspaceId))),
      command("setLayout", "Set any layout supported by current feature flags and capacity.", object({ layout: template }), ({ layout }) => {
        if (chartWorkspaceTemplateCellCount(layout) > view.maxCellsPerWindow) throw new Error("LAYOUT_UNAVAILABLE"); a.setLayout(layout);
      }, { available: unlocked }),
      command("splitCell", "Split a visible cell using copy or blank creation.", object({ cellId: id, direction: choice(["columns", "rows"]), creationMode: choice(["copy", "blank"]), session: optional(sessionSchema) }),
        ({ cellId, direction, creationMode, session }) => { cell(cellId); a.splitCell(cellId, direction, creationMode, session); }, { available: () => unlocked() && view.layoutCellIds.length < view.maxCellsPerWindow }),
      command("closeCell", "Close a visible chart cell.", object({ cellId: id }), ({ cellId }) => { cell(cellId); a.closeCell(cellId); }, { available: () => unlocked() && view.layoutCellIds.length > 1 }),
      command("swapCells", "Swap two visible chart cells.", object({ firstCellId: id, secondCellId: id }), ({ firstCellId, secondCellId }) => { cell(firstCellId); cell(secondCellId); a.swapCells(firstCellId, secondCellId); }, { available: unlocked }),
      command("resetLayout", "Reset the layout using the existing workspace action.", empty, () => a.resetLayout(), { available: unlocked }),
      command("setLayoutLocked", "Lock or unlock structural edits.", object({ locked: bool }), ({ locked }) => a.setLayoutLocked(locked)),
      command("undoLayout", "Undo a layout edit; session and indicator edits are outside layout history.", empty, () => a.undoLayout(), { available: () => unlocked() && view.canUndoLayout }),
      command("redoLayout", "Redo a layout edit.", empty, () => a.redoLayout(), { available: () => unlocked() && view.canRedoLayout }),
      command("setActiveCell", "Activate a visible chart.", object({ cellId: id }), ({ cellId }) => { cell(cellId); a.setActiveCell(cellId); }),
      command("toggleMaximize", "Maximize or restore a visible chart.", object({ cellId: id }), ({ cellId }) => { cell(cellId); a.toggleMaximize(cellId); }),
      command("setLayoutRatio", "Resize a current split.", object({ splitId: id, ratio: number(0.05, 0.95) }), ({ splitId, ratio }) => a.setLayoutRatio(splitId, ratio), { available: unlocked }),
      command("updateSession", "Change a visible chart's session with existing link propagation.", object({ cellId: id, session: sessionSchema }), ({ cellId, session }) => { cell(cellId); a.updateCellSession(cellId, session); }),
      command("updatePriceScale", "Set a visible chart's inverted and linear/logarithmic/percentage/indexed scale.", object({ cellId: id, invertScale: bool, priceScaleMode: choice([0, 1, 2, 3]) }),
        ({ cellId, invertScale, priceScaleMode }) => { cell(cellId); a.updateCellPriceScale(cellId, { invertScale, priceScaleMode }); }),
      command("setLinkGroup", "Assign visible cells to an existing link group or unlink them.", object({ cellIds: array(id, 16), groupId: nullable(id) }), ({ cellIds, groupId }) => {
        cellIds.forEach(cell); if (groupId && !view.document.linkGroups[groupId]) throw new Error("LINK_GROUP_UNAVAILABLE"); a.setCellsLinkGroup(cellIds, groupId);
      }),
      command("createLinkGroup", "Create a link group using visible cells.", object({ parentId: optional(nullable(id)), cellIds: array(id, 16) }), ({ parentId, cellIds }) => { cellIds.forEach(cell); a.createLinkGroup(parentId, cellIds); }),
      command("updateLinkGroup", "Edit a link group's label, color and parent.", object({ groupId: id, patch: object({ name: optional(text(128)), color: optional(text(64)), parentId: optional(nullable(id)) }) }),
        ({ groupId, patch }) => a.updateLinkGroup(groupId, patch)),
      command("deleteLinkGroup", "Delete a link group.", object({ groupId: id }), ({ groupId }) => a.deleteLinkGroup(groupId)),
      command("updateLinkPolicy", "Update peer or parent link behavior.", object({ groupId: id, relationship: choice(["peers", "parent"]), patch: policy }), ({ groupId, relationship, patch }) => a.updateLinkGroupPolicy(groupId, relationship, patch)),
      command("setDrawingLayer", "Select a chart drawing layer set.", object({ cellId: id, layerSet: choice(["1", "2", "3", "4"]) }), ({ cellId, layerSet }) => { cell(cellId); a.setCellDrawingLayerSet(cellId, layerSet); }),
      command("setStrategyTesterMode", "Select native or CandleScope strategy tester.", object({ cellId: id, mode: choice(["NATIVE", "CANDLESCOPE"]) }), ({ cellId, mode }) => { cell(cellId); a.updateCellStrategyTesterMode(cellId, mode); }),
      command("createWindow", "Create a chart window when multi-window is enabled.", empty, () => a.createWindow(), { available: () => CHART_WORKSPACE_FEATURE_FLAGS.multiWindowEnabled }),
      command("closeWindow", "Close an existing workspace window.", object({ windowId: id }), ({ windowId }) => {
        if (!view.document.windows[windowId]) throw new Error("WINDOW_UNAVAILABLE"); a.closeWindow(windowId);
      }, { available: () => CHART_WORKSPACE_FEATURE_FLAGS.multiWindowEnabled && Object.keys(view.document.windows).length > 1 }),
      command("updateWindowPlacement", "Move, resize or change display state of a workspace window.", object({ windowId: id, placement: object({
        boundsDip: nullable(object({ x: number(), y: number(), width: number(320, 16384), height: number(240, 16384) })),
        monitorFingerprint: nullable(text(512)), dpiScale: nullable(number(0.25, 8)), windowState: choice(["normal", "maximized", "minimized"]),
      }) }), ({ windowId, placement }) => { if (!view.document.windows[windowId]) throw new Error("WINDOW_UNAVAILABLE"); a.updateWindowPlacement(windowId, placement); }),
    ] };
}
