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
        return { cellId, session: cell.session, linkGroupId: cell.linkGroupId,
          indicators: cell.indicators.map(({ id, engineName, params, executionTarget }) => ({ id, engineName, params, executionTarget })),
          runtime: this.cells.get(cellId) ?? null };
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
          targets = receipt.cellIds.map((cellId, index) => ({ cellId, session: JSON.stringify(command.charts[index]!.session),
            indicators: indicatorSignature(command.charts[index]!.indicators) }));
          progress({ state: "applied", revision: appliedRevision, cellIds: receipt.cellIds });
        }
      }
      if (applied) {
        if (view.activeWorkspaceId !== command.workspaceId || (command.layout && view.layout !== command.layout)
          || targets.some((target) => !view.layoutCellIds.includes(target.cellId)
            || JSON.stringify(view.document.cells[target.cellId]?.session) !== target.session
            || indicatorSignature(view.document.cells[target.cellId]?.indicators ?? []) !== target.indicators)) {
          return { state: "applied", code: "TARGET_CHANGED", readiness: "superseded", revision: appliedRevision };
        }
        if (status.saveState === "error") return { state: "applied", code: "PERSISTENCE_FAILED", readiness: "failed", message: status.error ?? "Workspace could not be saved" };
        const allReady = targets.every(({ cellId }) => {
          const cell = view.document.cells[cellId];
          const runtime = this.cells.get(cellId);
          return cell && runtime && Object.entries(runtime.session).every(([key, value]) => cell.session[key as keyof typeof runtime.session] === value)
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
