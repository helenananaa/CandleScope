import { buildChartSessionKey } from "../chart-session/chartSessionTransition.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { indicatorSignature, parseControlConfiguration, type ControlCellObservation, type ControlRequest, type ControlResult } from "./controlModel.js";

export interface ControlRuntimePort {
  read(): Pick<ChartWorkspaceRuntime, "view" | "status">;
  apply(command: Parameters<ChartWorkspaceRuntime["actions"]["applyControlCommand"]>[0]): void;
}

export class AppControlController {
  private readonly cells = new Map<string, ControlCellObservation>();
  private disposed = false;
  constructor(private readonly port: ControlRuntimePort, readonly windowId: string, private readonly waitMs = 25_000) {}

  reportCell = (cellId: string, observation: ControlCellObservation | null): void => {
    if (observation) this.cells.set(cellId, observation);
    else this.cells.delete(cellId);
  };

  inspect(): Record<string, unknown> {
    const { view, status } = this.port.read();
    return { workspaceId: view.activeWorkspaceId, windowId: this.windowId, name: view.activeWorkspaceName,
      revision: view.document.revision, ready: view.ready, layout: view.layout, layoutLocked: view.layoutLocked,
      maxCellsPerWindow: view.maxCellsPerWindow, activeCellId: view.activeCellId,
      persistence: { state: status.saveState, mode: status.persistenceMode, error: status.error },
      cells: view.layoutCellIds.map((cellId) => {
        const cell = view.document.cells[cellId]!;
        const runtime = this.cells.get(cellId) ?? null;
        return { cellId, session: runtime?.mode === "history-study" ? runtime.session : cell.session,
          ...(runtime?.mode === "history-study" ? { configuredLiveSession: cell.session } : {}), linkGroupId: cell.linkGroupId,
          indicators: cell.indicators.map(({ id, engineName, params, executionTarget }) => ({ id, engineName, params, executionTarget })),
          runtime };
      }) };
  }

  async execute(request: ControlRequest, progress: (result: ControlResult) => void): Promise<ControlResult> {
    if (this.disposed) return { state: "failed", code: "WINDOW_UNAVAILABLE" };
    if (request.method === "workspace.inspect") return { state: "ready", snapshot: this.inspect() };
    if (request.method !== "workspace.configure") return { state: "failed", code: "UNKNOWN_METHOD" };
    let command;
    try {
      command = parseControlConfiguration(request.params);
      if (command.windowId !== this.windowId || command.requestId !== request.id) throw new Error("Request target mismatch");
    } catch (error) {
      return { state: "failed", code: "INVALID_PARAMS", message: error instanceof Error ? error.message : String(error) };
    }
    const affected = command.layout ? this.port.read().view.layoutCellIds : command.charts.map(chart => chart.cellId!);
    if (affected.some(id => this.cells.get(id)?.mode === "quick-replay")) {
      return { state: "failed", code: "QUICK_REPLAY_ACTIVE", message: "Exit quick replay before replacing its live chart configuration." };
    }
    if (affected.some(id => {
      const mode = this.cells.get(id)?.mode;
      return mode === "history-study" || mode === "restoring-study";
    })) return { state: "failed", code: "HISTORICAL_STUDY_ACTIVE",
      message: "Discover the study:<cellId> commands. Save and exit the study before replacing its live chart configuration." };
    this.port.apply(command);
    const deadline = Date.now() + this.waitMs;
    let applied = false;
    let appliedRevision: number | null = null;
    let targets: { cellId: string; session: string; indicators: string }[] = [];
    while (!this.disposed && Date.now() < deadline) {
      const { view, status } = this.port.read();
      const receipt = status.controlReceipt;
      if (receipt?.requestId === request.id) {
        if (!receipt.ok) return { state: "failed", code: receipt.code ?? "CONFIGURATION_REJECTED", message: receipt.message ?? "Configuration rejected" };
        appliedRevision ??= receipt.revision;
        if (!applied) {
          applied = true;
          targets = receipt.cellIds.map((cellId, index) => ({ cellId, session: buildChartSessionKey(command.charts[index]!.session),
            indicators: indicatorSignature(command.charts[index]!.indicators) }));
          progress({ state: "applied", revision: appliedRevision, cellIds: receipt.cellIds });
        }
      }
      if (applied) {
        if (view.activeWorkspaceId !== command.workspaceId || (command.layout && view.layout !== command.layout)
          || targets.some((target) => !view.layoutCellIds.includes(target.cellId)
            || !view.document.cells[target.cellId] || buildChartSessionKey(view.document.cells[target.cellId]!.session) !== target.session
            || indicatorSignature(view.document.cells[target.cellId]?.indicators ?? []) !== target.indicators)) {
          return { state: "applied", code: "TARGET_CHANGED", readiness: "superseded", revision: appliedRevision };
        }
        if (status.saveState === "error") return { state: "applied", code: "PERSISTENCE_FAILED", readiness: "failed", message: status.error ?? "Workspace could not be saved" };
        if (targets.some(({ cellId }) => this.cells.get(cellId)?.mode === "history-study")) {
          return { state: "applied", code: "HISTORICAL_STUDY_ACTIVE", readiness: "unverified", revision: appliedRevision,
            message: "The visible chart entered historical study; its live configuration is not the displayed study input.", snapshot: this.inspect() };
        }
        if (targets.some(({ cellId }) => this.cells.get(cellId)?.mode === "quick-replay")) {
          return { state: "applied", code: "QUICK_REPLAY_ACTIVE", readiness: "unverified", revision: appliedRevision, snapshot: this.inspect() };
        }
        const allReady = targets.every(({ cellId }) => {
          const cell = view.document.cells[cellId];
          const runtime = this.cells.get(cellId);
          return cell && runtime && buildChartSessionKey(runtime.session) === buildChartSessionKey(cell.session)
            && runtime.mode !== "restoring-study"
            && runtime.indicatorSignature === indicatorSignature(cell.indicators) && runtime.marketReady && runtime.indicatorsReady && !runtime.error;
        });
        if (status.saveState === "saved" && allReady) return { state: "ready", revision: appliedRevision, cellIds: targets.map(({ cellId }) => cellId), snapshot: this.inspect() };
      }
      await new Promise<void>((resolve) => setTimeout(resolve, 50));
    }
    return applied
      ? { state: "applied", code: this.disposed ? "WINDOW_UNAVAILABLE" : "READINESS_TIMEOUT", readiness: "unverified", revision: appliedRevision, snapshot: this.inspect() }
      : { state: "failed", code: "OUTCOME_UNKNOWN", message: "Inspect state before retrying; the request may have applied" };
  }

  dispose(): void { this.disposed = true; this.cells.clear(); }
  resume(): void { this.disposed = false; }
}
