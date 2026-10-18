import { MAIN_CHART_TYPES, type MainChartType } from "../../shared/mainChartTypes.js";
import { parseIntervalParts } from "../../utils/intervals.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import type { AiControlBridge, AiControlRequest, AiControlView } from "./aiControlTypes.js";

export interface ReplayControlAdapter {
  /** Private identity only; never returned to clients (may contain hidden time). */
  key: string;
  state: string;
  revision: number;
  busy: boolean;
  execute(viewId: string, action: "pause" | "next_bar"): Promise<void>;
}
const failure = (code: string) => Object.assign(new Error(code), { code });
type Pending = { request: AiControlRequest; done: boolean; test: () => boolean; resolve(): void; reject(error: Error): void };

/** Receipts are generated after React commits the requested chart configuration. */
export class ChartControlAdapter {
  private generation = crypto.randomUUID();
  private version = 0;
  private key = "";
  private workspace: ChartWorkspaceRuntime | null = null;
  private replay: ReplayControlAdapter | undefined;
  private windowId = "";
  private kind: AiControlView["kind"] = "market";
  private pending = new Map<string, Pending>();
  constructor(private bridge: Pick<AiControlBridge, "aiControlPublish" | "aiControlReply">) {}
  update(workspace: ChartWorkspaceRuntime, windowId: string, kind: AiControlView["kind"], replay?: ReplayControlAdapter) {
    if (this.workspace && this.workspace.view.runtimeKey !== workspace.view.runtimeKey) {
      for (const pending of this.pending.values()) pending.reject(failure("CONTROL_VIEW_REPLACED"));
    }
    this.workspace = workspace; this.windowId = windowId; this.kind = kind; this.replay = replay;
    const key = `${workspace.view.runtimeKey}:${workspace.view.document.revision}:${workspace.view.ready}:${replay?.key ?? ""}`;
    if (key !== this.key) {
      this.key = key; this.version++;
      // Publish only semantic changes, before the receipt for this committed state.
      void this.bridge.aiControlPublish(this.views()).catch(() => {});
    }
    for (const pending of this.pending.values()) {
      if (pending.done && pending.test()) pending.resolve();
    }
  }
  private revision() { return `${this.generation}:${this.version}`; }
  views() {
    if (!this.workspace?.view.ready) return [];
    return this.workspace.view.layoutCellIds.map((viewId) => ({ viewId, revision: this.revision(), kind: this.kind }));
  }
  private cell(viewId: string) {
    if (!this.workspace?.view.ready || !this.workspace.view.layoutCellIds.includes(viewId)) throw failure("CONTROL_VIEW_NOT_FOUND");
    const cell = this.workspace.view.document.cells[viewId];
    if (!cell) throw failure("CONTROL_VIEW_NOT_FOUND");
    return cell;
  }
  private read(viewId: string): Record<string, unknown> {
    const cell = this.cell(viewId);
    return { windowId: this.windowId, viewId, revision: this.revision(), kind: this.kind,
      session: { exchange: cell.session.exchange, marketType: cell.session.marketType, symbol: cell.session.symbol, interval: cell.session.interval },
      chartType: cell.chartSettings.chartType, indicatorCount: cell.indicators.length,
      active: this.workspace!.view.activeCellId === viewId, linkGroupId: cell.linkGroupId,
      readiness: "configured", replay: this.replay ? { state: this.replay.state, busy: this.replay.busy } : null };
  }
  async handle(request: AiControlRequest) {
    if (request.type === "cancel") {
      this.pending.get(request.requestId)?.reject(failure("CONTROL_OUTCOME_UNKNOWN_READ_VIEW")); return;
    }
    let pending: Pending | undefined;
    try {
      const args = request.arguments;
      if (!args || args.windowId !== this.windowId) throw failure("CONTROL_WINDOW_MISMATCH");
      const cell = this.cell(args.viewId);
      if (request.name === "candlescope_read_view") {
        this.bridge.aiControlReply({ requestId: request.requestId, ok: true, result: this.read(args.viewId) }); return;
      }
      if (args.expectedRevision !== this.revision()) throw failure("CONTROL_REVISION_CONFLICT");
      if (this.pending.size) throw failure("CONTROL_WINDOW_BUSY");
      const workspace = this.workspace!;
      const before = new Map(workspace.view.layoutCellIds.map((id) => [id, JSON.stringify(this.read(id))]));
      let commit: () => void | Promise<void>;
      let observed: () => boolean;
      if (request.name === "candlescope_set_chart") {
        if (args.interval !== undefined && !parseIntervalParts(args.interval)) throw failure("INVALID_CHART_INTERVAL");
        if (args.chartType !== undefined && !MAIN_CHART_TYPES.includes(args.chartType as MainChartType)) throw failure("INVALID_CHART_TYPE");
        if (args.interval === undefined && args.chartType === undefined) throw failure("EMPTY_CHART_UPDATE");
        if (this.replay?.busy) throw failure("REPLAY_CONTROL_BUSY");
        commit = () => {
          if (args.interval !== undefined) workspace.actions.updateCellSession(cell.id, { ...cell.session, interval: args.interval });
          if (args.chartType !== undefined) workspace.actions.updateCellChartSettings(cell.id, { ...cell.chartSettings, chartType: args.chartType as MainChartType });
        };
        observed = () => { const next = this.cell(args.viewId); return (args.interval === undefined || next.session.interval === args.interval)
          && (args.chartType === undefined || next.chartSettings.chartType === args.chartType); };
      } else if (request.name === "candlescope_replay_control") {
        if (!this.replay) throw failure("NOT_A_REPLAY_VIEW");
        if (args.action !== "pause" && args.action !== "next_bar") throw failure("INVALID_REPLAY_ACTION");
        const replay = this.replay;
        if (replay.busy) throw failure("REPLAY_CONTROL_BUSY");
        commit = () => replay.execute(args.viewId, args.action as "pause" | "next_bar");
        observed = () => Boolean(this.replay && !this.replay.busy
          && (args.action === "pause" ? this.replay.state === "PAUSED" : this.replay.revision > replay.revision
            && ["PAUSED", "ENDED"].includes(this.replay.state)));
      } else throw failure("UNKNOWN_CONTROL_TOOL");
      const committed = new Promise<void>((resolve, reject) => { pending = { request, done: false, test: observed, resolve, reject }; });
      // Attach a rejection handler before dispatch; cancellation can arrive during execute().
      void committed.catch(() => {});
      this.pending.set(request.requestId, pending!);
      await commit();
      pending!.done = true;
      if (observed()) pending!.resolve();
      await committed;
      const view = this.read(args.viewId);
      const affectedViews = this.workspace!.view.layoutCellIds.filter((id) => {
        const value = this.read(id); const old = before.get(id);
        if (!old) return true;
        const previous = JSON.parse(old) as Record<string, unknown>;
        delete previous.revision; delete value.revision;
        return JSON.stringify(previous) !== JSON.stringify(value);
      });
      this.bridge.aiControlReply({ requestId: request.requestId, ok: true,
        result: { view, affectedViews, operationId: args.operationId, scope: this.replay ? "shared_replay_clock" : "workspace_link_policy" } });
    } catch (error) {
      this.bridge.aiControlReply({ requestId: request.requestId, ok: false,
        code: error instanceof Error && "code" in error ? String(error.code) : "CONTROL_REQUEST_FAILED" });
    } finally { if (pending) this.pending.delete(request.requestId); }
  }
  close() {
    this.key = "";
    for (const pending of this.pending.values()) pending.reject(failure("CONTROL_WINDOW_CLOSED"));
    void this.bridge.aiControlPublish([]).catch(() => {});
  }
}
