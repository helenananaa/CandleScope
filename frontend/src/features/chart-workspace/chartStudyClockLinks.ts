import { resolveChartLinkTargetsForChannel } from "./chartWorkspaceLinkModel.js";
import { visibleCellIds } from "./chartWorkspaceLayout.js";
import type { ChartWorkspaceDocument } from "./chartWorkspaceTypes.js";
import type { WorkspaceBusClient, WorkspaceBusLinkEvent } from "./workspaceBus.js";

export interface ChartStudyClockState {
  active: boolean; pending: boolean; committing: boolean; editing: boolean;
  studyId: string | null; revision: number; cursorMs: number | null;
  minimumMs: number | null; maximumMs: number | null;
}
export interface ChartStudyClockPort {
  read(): ChartStudyClockState;
  move(cursorMs: number): Promise<boolean>;
}
export type ChartStudyClockStatus = "moved" | "inactive" | "out-of-range" | "editing" | "unavailable" | "failed" | "superseded";
export interface ChartStudyClockIssue { sourceCellId: string; failed: Array<{ cellId: string; status: ChartStudyClockStatus }> }
interface Intent {
  scope: string; cellId: string; generation: number;
  settled: Promise<void>; release(): void;
}
interface Payload { requestId: string; cursorMs: number; studyId: string; revision: number }
interface Registration { scope: string; port: ChartStudyClockPort }
interface Pending {
  scope: string; sourceCellId: string; order: number | null;
  results: Map<string, { order: number; status: ChartStudyClockStatus } | null>;
  resolve(value: boolean): void; timer: ReturnType<typeof setTimeout>;
}
const statuses: readonly string[] = ["moved", "inactive", "out-of-range", "editing", "unavailable", "failed", "superseded"];
function payload(value: unknown): Payload | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Partial<Payload>;
  return typeof row.requestId === "string" && row.requestId.length <= 128
    && typeof row.studyId === "string" && row.studyId.length <= 128
    && Number.isSafeInteger(row.cursorMs) && row.cursorMs! >= 0
    && Number.isSafeInteger(row.revision) && row.revision! >= 0 ? row as Payload : null;
}
function orderOf(event: WorkspaceBusLinkEvent): number | null {
  const match = /^link-([1-9][0-9]*)$/.exec(event.eventId ?? "");
  const order = match ? Number(match[1]) : NaN;
  return Number.isSafeInteger(order) ? order : null;
}
function boundedOrderReply(reply: Promise<WorkspaceBusLinkEvent>): Promise<WorkspaceBusLinkEvent> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Clock ordering reply timed out")), 5_000);
    reply.then(value => { clearTimeout(timer); resolve(value); }, error => {
      clearTimeout(timer); reject(error instanceof Error ? error : new Error("Clock ordering reply failed"));
    });
  });
}

/** Optional durable study-clock actions, separate from viewport links and
 * formal replay clocks. Targets retain their own immutable inputs and refuse
 * out-of-range cuts. No received action is republished as a user operation. */
export class ChartStudyClockLinks {
  private registrations = new Map<string, Registration>();
  private lastOrder = new Map<string, number>();
  private generations = new Map<string, number>();
  private pending = new Map<string, Pending>();
  private issues = new Map<string, ChartStudyClockIssue>();
  private latestRequest = new Map<string, string>();
  private userIntents = new Map<string, Intent>();
  private uncertainOrder = new Set<string>();
  private listeners = new Set<() => void>();
  private bus: WorkspaceBusClient | null = null;
  private localOrder = 0;
  constructor(private document: ChartWorkspaceDocument, private scope: string) {}

  updateDocument(document: ChartWorkspaceDocument, scope: string) {
    if (scope !== this.scope) {
      for (const intent of this.userIntents.values()) intent.release();
      this.userIntents.clear(); this.uncertainOrder.clear();
      for (const requestId of [...this.pending.keys()]) this.finish(requestId, false);
      this.lastOrder.clear(); this.generations.clear(); this.latestRequest.clear();
      this.issues.clear(); this.emit();
    }
    this.document = document; this.scope = scope;
  }
  connectWorkspaceBus(bus: WorkspaceBusClient | null): () => void {
    this.bus = bus;
    const release = bus?.subscribeLink(event => {
      if (event.workspaceId !== this.scope) return;
      if (event.kind === "studyCursor") void this.receive(event);
      else if (event.kind === "studyCursorResult") this.receiveResult(event);
    }) ?? (() => {});
    return () => {
      release();
      if (this.bus === bus) {
        this.bus = null;
        for (const id of [...this.pending.keys()]) this.finish(id, true);
      }
    };
  }
  register(cellId: string, port: ChartStudyClockPort, scope: string): () => void {
    const registration = { port, scope }; this.registrations.set(cellId, registration);
    return () => {
      if (this.registrations.get(cellId) !== registration) return;
      this.registrations.delete(cellId);
      const intent = this.userIntents.get(cellId);
      if (intent) this.cancelUserAction(intent);
      this.uncertainOrder.delete(cellId);
      this.generations.set(cellId, (this.generations.get(cellId) ?? 0) + 1);
      this.latestRequest.delete(cellId);
      if (this.issues.delete(cellId)) this.emit();
      for (const [id, pending] of this.pending) if (pending.sourceCellId === cellId) this.finish(id, false);
    };
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getIssue(cellId: string, scope: string): ChartStudyClockIssue | null { return scope === this.scope ? this.issues.get(cellId) ?? null : null; }
  private emit() { for (const listener of this.listeners) listener(); }
  private targets(sourceCellId: string): string[] {
    const visible = new Set(Object.values(this.document.windows).flatMap(window => visibleCellIds(window.layoutTree)));
    return resolveChartLinkTargetsForChannel(this.document, sourceCellId, "studyCursor")
      .filter(target => visible.has(target.cellId)).map(target => target.cellId);
  }
  beginUserAction(cellId: string, scope: string): Intent {
    this.userIntents.get(cellId)?.release();
    const generation = (this.generations.get(cellId) ?? 0) + 1;
    this.generations.set(cellId, generation);
    this.latestRequest.delete(cellId);
    if (this.issues.delete(cellId)) this.emit();
    let release = () => {};
    const settled = new Promise<void>(resolve => { release = resolve; });
    const intent = { scope, cellId, generation, settled, release };
    this.userIntents.set(cellId, intent);
    return intent;
  }
  cancelUserAction(intent: Intent): void {
    if (this.userIntents.get(intent.cellId) === intent) this.userIntents.delete(intent.cellId);
    // Exiting a study is independent from cursor following. A confirmed live
    // target must not inherit an old study's unconfirmed ordering fence.
    try {
      const state = this.registrations.get(intent.cellId)?.port.read();
      if (state && !state.active && !state.pending) this.uncertainOrder.delete(intent.cellId);
    } catch { /* A closing owner remains unavailable. */ }
    intent.release();
  }
  async publishUserMove(intent: Intent): Promise<boolean> {
    try { return await this.publishCommittedUserMove(intent); }
    finally { this.cancelUserAction(intent); }
  }
  private async publishCommittedUserMove(intent: Intent): Promise<boolean> {
    if (intent.scope !== this.scope || intent.generation !== this.generations.get(intent.cellId)) return false;
    const registration = this.registrations.get(intent.cellId);
    if (!registration || registration.scope !== this.scope) return false;
    let state: ChartStudyClockState;
    try { state = registration.port.read(); } catch { return false; }
    if (!state.active || state.pending || state.committing || state.editing || !state.studyId || state.cursorMs === null) return false;
    const targets = this.targets(intent.cellId);
    if (!targets.length) return true;
    const requestId = crypto.randomUUID();
    this.latestRequest.set(intent.cellId, requestId);
    const result = new Promise<boolean>(resolve => {
      const timer = setTimeout(() => this.finish(requestId, true), 5_000);
      this.pending.set(requestId, { scope: this.scope, sourceCellId: intent.cellId, order: null,
        results: new Map(targets.map(cellId => [cellId, null])), resolve, timer });
    });
    const event: WorkspaceBusLinkEvent & { kind: "studyCursor" } = { workspaceId: this.scope, sourceCellId: intent.cellId,
      sourceWindowId: this.bus?.windowId ?? "local-window", kind: "studyCursor",
      payload: { requestId, cursorMs: state.cursorMs, studyId: state.studyId, revision: state.revision } satisfies Payload };
    try {
      // Browser pages have no central clock ordering authority. Only this
      // renderer is supported there; desktop windows use the main-process stamp.
      const ordered = this.bus?.isNative() ? await boundedOrderReply(this.bus.publishOrderedLink(event))
        : { ...event, eventId: `link-${++this.localOrder}` };
      const pending = this.pending.get(requestId);
      if (intent.scope !== this.scope) return result;
      const order = orderOf(ordered);
      const acknowledged = payload(ordered.payload);
      if (order === null || acknowledged?.requestId !== requestId || acknowledged.cursorMs !== state.cursorMs
        || acknowledged.studyId !== state.studyId || acknowledged.revision !== state.revision) throw new Error("Invalid clock acknowledgement");
      if (pending) {
        pending.order = order;
        for (const [cellId, value] of pending.results) if (value && value.order !== order) pending.results.set(cellId, null);
      }
      this.lastOrder.set(intent.cellId, Math.max(this.lastOrder.get(intent.cellId) ?? 0, order));
      if (this.generations.get(intent.cellId) === intent.generation) this.uncertainOrder.delete(intent.cellId);
      // Peers may have sent an older clock while this local write/IPC was in
      // flight. Stamp the source before releasing those queued deliveries.
      this.cancelUserAction(intent);
      void this.receive(ordered);
      this.completeIfReady(requestId);
    } catch {
      // The host may have broadcast our committed operation before losing its
      // reply. Until an explicit retry confirms an order, don't apply queued
      // older clocks over the known local committed cut.
      if (this.generations.get(intent.cellId) === intent.generation) this.uncertainOrder.add(intent.cellId);
      this.finish(requestId, true);
    }
    return result;
  }
  private async receive(event: WorkspaceBusLinkEvent) {
    const body = payload(event.payload), order = orderOf(event);
    if (!body || order === null || event.workspaceId !== this.scope) return;
    const targets = this.targets(event.sourceCellId);
    await Promise.all(targets.map(async cellId => {
      // A local operation orders itself only after durable commit. Await its
      // order (not peer acknowledgements) before comparing an incoming event.
      while (this.userIntents.has(cellId)) await this.userIntents.get(cellId)!.settled;
      if (event.workspaceId !== this.scope) return;
      const registration = this.registrations.get(cellId);
      if (!registration || registration.scope !== this.scope) {
        if (!this.bus?.isNative()) this.result(event, body, cellId, order, "unavailable");
        return; // A native peer may be owned by another renderer; await its ack.
      }
      let status: ChartStudyClockStatus;
      if (this.uncertainOrder.has(cellId)) status = "unavailable";
      else if (order <= (this.lastOrder.get(cellId) ?? 0)) status = "superseded";
      else {
        this.lastOrder.set(cellId, order);
        this.generations.set(cellId, (this.generations.get(cellId) ?? 0) + 1);
        this.latestRequest.delete(cellId);
        if (this.issues.delete(cellId)) this.emit();
        let state: ChartStudyClockState | null = null;
        try { state = registration.port.read(); } catch { /* Report an unavailable owner below. */ }
        if (!state || state.pending) status = "unavailable";
        else if (!state.active || !state.studyId) status = "inactive";
        else if (state.editing) status = "editing";
        else if (state.minimumMs === null || state.maximumMs === null || body.cursorMs < state.minimumMs || body.cursorMs > state.maximumMs) status = "out-of-range";
        else {
          try {
            const moved = await registration.port.move(body.cursorMs);
            const current = registration.port.read();
            status = this.scope !== event.workspaceId || this.registrations.get(cellId) !== registration
              || this.lastOrder.get(cellId) !== order ? "superseded"
              : moved && current.active && !current.pending && current.studyId === state.studyId
                && current.cursorMs === body.cursorMs ? "moved" : "failed";
          } catch { status = "failed"; }
        }
      }
      this.result(event, body, cellId, order, status);
    }));
  }
  private result(event: WorkspaceBusLinkEvent, body: Payload, cellId: string, order: number, status: ChartStudyClockStatus) {
    if (event.workspaceId !== this.scope) return;
    if (event.sourceWindowId === (this.bus?.windowId ?? "local-window")) this.recordResult(body.requestId, cellId, order, status);
    else this.bus?.publishLink({ workspaceId: this.scope, sourceCellId: cellId, kind: "studyCursorResult",
      payload: { requestId: body.requestId, originWindowId: event.sourceWindowId, originCellId: event.sourceCellId, cellId, order, status } });
  }
  private receiveResult(event: WorkspaceBusLinkEvent) {
    if (!event.payload || typeof event.payload !== "object") return;
    const row = event.payload as Record<string, unknown>;
    const pending = typeof row.requestId === "string" ? this.pending.get(row.requestId) : null;
    if (!pending || row.originWindowId !== this.bus?.windowId || row.originCellId !== pending.sourceCellId
      || row.cellId !== event.sourceCellId || typeof row.cellId !== "string" || !Number.isSafeInteger(row.order)
      || !statuses.includes(String(row.status))) return;
    this.recordResult(row.requestId as string, row.cellId, row.order as number, row.status as ChartStudyClockStatus);
  }
  private recordResult(requestId: string, cellId: string, order: number, status: ChartStudyClockStatus) {
    const pending = this.pending.get(requestId);
    if (!pending || pending.scope !== this.scope || !pending.results.has(cellId)
      || (pending.order !== null && pending.order !== order)) return;
    pending.results.set(cellId, { order, status }); this.completeIfReady(requestId);
  }
  private completeIfReady(requestId: string) {
    const pending = this.pending.get(requestId);
    if (pending?.order !== null && pending && [...pending.results.values()].every(Boolean)) this.finish(requestId, true);
  }
  private finish(requestId: string, report: boolean) {
    const pending = this.pending.get(requestId); if (!pending) return;
    clearTimeout(pending.timer); this.pending.delete(requestId);
    const failed = [...pending.results].flatMap(([cellId, value]) => {
      const status = pending.order === null ? "unavailable" : value?.status ?? "unavailable";
      return status === "moved" || status === "inactive" ? [] : [{ cellId, status }];
    });
    if (report && pending.scope === this.scope && this.latestRequest.get(pending.sourceCellId) === requestId) {
      if (failed.length) this.issues.set(pending.sourceCellId, { sourceCellId: pending.sourceCellId, failed });
      else this.issues.delete(pending.sourceCellId);
      this.emit();
    }
    pending.resolve(report && failed.length === 0);
  }
}
