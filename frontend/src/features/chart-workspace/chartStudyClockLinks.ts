import { resolveChartLinkTargetsForChannel } from "./chartWorkspaceLinkModel.js";
import { visibleCellIds } from "./chartWorkspaceLayout.js";
import type { ChartWorkspaceDocument } from "./chartWorkspaceTypes.js";
import type { WorkspaceBusClient, WorkspaceBusLinkEvent } from "./workspaceBus.js";

export interface ChartStudyClockState {
  active: boolean; pending: boolean; committing: boolean; editing: boolean; followReady: boolean;
  studyId: string | null; revision: number; cursorMs: number | null;
  minimumMs: number | null; maximumMs: number | null;
}
export interface ChartStudyClockPort {
  read(): ChartStudyClockState;
  move(cursorMs: number): Promise<boolean>;
  setMode(active: boolean, cursorMs?: number): Promise<boolean>;
}
export type ChartStudyClockStatus = "moved" | "inactive" | "unprepared" | "out-of-range" | "editing" | "unavailable" | "failed" | "superseded";
export interface ChartStudyClockIssue { sourceCellId: string; operation: "mode" | "cursor"; failed: Array<{ cellId: string; status: ChartStudyClockStatus }> }
type Operation = "cursor" | "tick" | "mode";
interface Intent {
  scope: string; epoch: number; cellId: string; generation: number;
  operation: Operation; leaderOrder: number;
  settled: Promise<void>; release(): void;
}
interface Payload { requestId: string; cursorMs: number; studyId: string; revision: number; configurationRevision: number; configurationKey: string; operation: Operation; leaderOrder: number; active?: boolean }
interface Registration { scope: string; port: ChartStudyClockPort }
interface Pending {
  scope: string; sourceCellId: string; order: number | null; operation: "mode" | "cursor";
  results: Map<string, { order: number; status: ChartStudyClockStatus } | null>;
  resolve(value: boolean): void; timer: ReturnType<typeof setTimeout>;
}
const statuses: readonly string[] = ["moved", "inactive", "unprepared", "out-of-range", "editing", "unavailable", "failed", "superseded"];
function payload(value: unknown): Payload | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Partial<Payload>;
  return typeof row.requestId === "string" && row.requestId.length <= 128
    && typeof row.studyId === "string" && row.studyId.length <= 128
    && Number.isSafeInteger(row.cursorMs) && row.cursorMs! >= 0
    && Number.isSafeInteger(row.revision) && row.revision! >= 0
    && Number.isSafeInteger(row.configurationRevision) && row.configurationRevision! >= 0
    && typeof row.configurationKey === "string" && row.configurationKey.length <= 32_768
    && (row.operation === "cursor" || row.operation === "tick" || row.operation === "mode")
    && (row.operation !== "mode" || typeof row.active === "boolean")
    && Number.isSafeInteger(row.leaderOrder) && row.leaderOrder! >= 0
    && (row.operation !== "tick" || row.leaderOrder! > 0) ? row as Payload : null;
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
  private leaderOrder = new Map<string, number>();
  private leaderSource = new Map<string, string>();
  private generations = new Map<string, number>();
  private pending = new Map<string, Pending>();
  private issues = new Map<string, ChartStudyClockIssue>();
  private latestRequest = new Map<string, string>();
  private userIntents = new Map<string, Intent>();
  private uncertainOrder = new Map<string, Operation>();
  private listeners = new Set<() => void>();
  private bus: WorkspaceBusClient | null = null;
  private localOrder = 0;
  private scopeEpoch = 0;
  private documentWaiters = new Set<() => void>();
  constructor(private document: ChartWorkspaceDocument, private scope: string) {}

  updateDocument(document: ChartWorkspaceDocument, scope: string) {
    if (scope !== this.scope) {
      this.scopeEpoch += 1;
      for (const intent of this.userIntents.values()) intent.release();
      this.userIntents.clear(); this.uncertainOrder.clear();
      for (const requestId of [...this.pending.keys()]) this.finish(requestId, false);
      this.lastOrder.clear(); this.leaderOrder.clear(); this.leaderSource.clear(); this.generations.clear(); this.latestRequest.clear();
      this.issues.clear(); this.emit();
    }
    this.document = document; this.scope = scope;
    for (const waiter of [...this.documentWaiters]) waiter();
  }
  private waitForDocumentRevision(revision: number, sourceCellId: string, key: string, epoch: number, timeoutMs = 5_000): Promise<void> {
    return new Promise((resolve, reject) => {
      const check = () => {
        if (epoch === this.scopeEpoch && (this.document.revision < revision || this.configurationKey(sourceCellId) !== key)) return;
        this.documentWaiters.delete(check); clearTimeout(timer);
        if (epoch !== this.scopeEpoch) reject(new Error("Study workspace changed")); else resolve();
      };
      const timer = setTimeout(() => { this.documentWaiters.delete(check); reject(new Error("Study configuration did not reach this chart")); }, timeoutMs);
      this.documentWaiters.add(check); check();
    });
  }
  private async committedConfiguration(intent: Intent): Promise<{ revision: number; key: string }> {
    const bus = this.bus;
    if (!bus?.isNative()) return { revision: this.document.revision, key: this.configurationKey(intent.cellId) };
    const deadline = Date.now() + 5_000;
    const remaining = () => { const value = deadline - Date.now(); if (value <= 0) throw new Error("Study configuration timed out"); return value; };
    for (;;) {
      const revision = this.document.revision;
      const key = this.configurationKey(intent.cellId);
      await bus.waitForWorkspaceRevision(intent.scope, revision, remaining(), document => this.configurationKey(intent.cellId, document) === key);
      await this.waitForDocumentRevision(Math.max(revision, bus.current.revisions[intent.scope] ?? revision), intent.cellId, key, intent.epoch, remaining());
      if (intent.scope !== this.scope || intent.epoch !== this.scopeEpoch || bus !== this.bus) throw new Error("Study configuration owner changed");
      if (this.document.revision <= (bus.current.revisions[intent.scope] ?? -1)) return { revision: this.document.revision, key };
    }
  }
  connectWorkspaceBus(bus: WorkspaceBusClient | null): () => void {
    this.bus = bus;
    const release = bus?.subscribeLink(event => {
      if (event.workspaceId !== this.scope) return;
      if (event.kind === "studyCursor" || event.kind === "studyMode") void this.receive(event);
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
      this.latestRequest.delete(this.issueKey(cellId, "mode")); this.latestRequest.delete(this.issueKey(cellId, "cursor"));
      const modeIssue = this.issues.delete(this.issueKey(cellId, "mode"));
      if (this.issues.delete(this.issueKey(cellId, "cursor")) || modeIssue) this.emit();
      for (const [id, pending] of this.pending) if (pending.sourceCellId === cellId) this.finish(id, false);
    };
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private issueKey(cellId: string, operation: Operation) { return JSON.stringify([cellId, operation === "mode" ? "mode" : "cursor"]); }
  getIssue(cellId: string, scope: string): ChartStudyClockIssue | null {
    return scope === this.scope ? this.issues.get(this.issueKey(cellId, "mode")) ?? this.issues.get(this.issueKey(cellId, "cursor")) ?? null : null;
  }
  private emit() { for (const listener of this.listeners) listener(); }
  private targets(sourceCellId: string, operation: Operation = "cursor", document = this.document): string[] {
    const visible = new Set(Object.values(document.windows).flatMap(window => visibleCellIds(window.layoutTree)));
    return resolveChartLinkTargetsForChannel(document, sourceCellId, operation === "mode" ? "studyMode" : "studyCursor")
      .filter(target => visible.has(target.cellId)).map(target => target.cellId);
  }
  private configurationKey(sourceCellId: string, document = this.document): string {
    // Revisions can coincide between optimistic edits in different windows.
    // Compare the effective routing too, without coupling clocks to styles or
    // copying another chart's data/configuration into the recipient.
    return JSON.stringify([this.targets(sourceCellId, "mode", document).sort(), this.targets(sourceCellId, "cursor", document).sort()]);
  }
  canStartAutomatic(cellId: string, scope: string): boolean {
    if (scope !== this.scope || this.registrations.get(cellId)?.scope !== scope || this.userIntents.has(cellId)) return false;
    if (!this.targets(cellId).length) return true;
    return !this.uncertainOrder.has(cellId) && (this.leaderOrder.get(cellId) ?? 0) > 0
      && this.leaderSource.get(cellId) === `${this.bus?.windowId ?? "local-window"}\u0000${cellId}`;
  }
  beginUserAction(cellId: string, scope: string, operation: Operation = "cursor"): Intent {
    this.userIntents.get(cellId)?.release();
    const generation = (this.generations.get(cellId) ?? 0) + 1;
    this.generations.set(cellId, generation);
    this.latestRequest.delete(this.issueKey(cellId, operation));
    if (this.issues.delete(this.issueKey(cellId, operation))) this.emit();
    let release = () => {};
    const settled = new Promise<void>(resolve => { release = resolve; });
    const intent = { scope, epoch: this.scopeEpoch, cellId, generation, operation, leaderOrder: this.leaderOrder.get(cellId) ?? 0, settled, release };
    this.userIntents.set(cellId, intent);
    return intent;
  }
  cancelUserAction(intent: Intent): void {
    const ownsIntent = this.userIntents.get(intent.cellId) === intent;
    if (ownsIntent) this.userIntents.delete(intent.cellId);
    // Exiting a study is independent from cursor following. A confirmed live
    // target must not inherit an old study's unconfirmed ordering fence.
    try {
      const state = this.registrations.get(intent.cellId)?.port.read();
      if (ownsIntent && intent.operation !== "mode" && state && !state.active && !state.pending) this.uncertainOrder.delete(intent.cellId);
    } catch { /* A closing owner remains unavailable. */ }
    intent.release();
  }
  async publishUserMove(intent: Intent): Promise<boolean> {
    try { return await this.publishCommittedUserMove(intent); }
    finally { this.cancelUserAction(intent); }
  }
  private async publishCommittedUserMove(intent: Intent): Promise<boolean> {
    if (intent.scope !== this.scope || intent.epoch !== this.scopeEpoch || intent.generation !== this.generations.get(intent.cellId)) return false;
    const registration = this.registrations.get(intent.cellId);
    if (!registration || registration.scope !== this.scope) return false;
    let state: ChartStudyClockState;
    try { state = registration.port.read(); } catch { return false; }
    if ((intent.operation !== "mode" && !state.active) || state.pending || state.committing || state.editing || !state.studyId || state.cursorMs === null) return false;
    const targets = this.targets(intent.cellId, intent.operation);
    if (!targets.length) return true;
    if (intent.operation === "tick" && (intent.leaderOrder <= 0
      || this.leaderSource.get(intent.cellId) !== `${this.bus?.windowId ?? "local-window"}\u0000${intent.cellId}`)) return false;
    const requestId = crypto.randomUUID();
    this.latestRequest.set(this.issueKey(intent.cellId, intent.operation), requestId);
    const result = new Promise<boolean>(resolve => {
      const timer = setTimeout(() => this.finish(requestId, true), 5_000);
      this.pending.set(requestId, { scope: this.scope, sourceCellId: intent.cellId, order: null, operation: intent.operation === "mode" ? "mode" : "cursor",
        results: new Map(targets.map(cellId => [cellId, null])), resolve, timer });
    });
    const event: WorkspaceBusLinkEvent & { kind: "studyCursor" | "studyMode" } = { workspaceId: this.scope, sourceCellId: intent.cellId,
      sourceWindowId: this.bus?.windowId ?? "local-window", kind: intent.operation === "mode" ? "studyMode" : "studyCursor",
      payload: { requestId, cursorMs: state.cursorMs, studyId: state.studyId, revision: state.revision,
        configurationRevision: this.document.revision,
        configurationKey: this.configurationKey(intent.cellId),
        operation: intent.operation, leaderOrder: intent.operation === "tick" ? intent.leaderOrder : 0,
        ...(intent.operation === "mode" ? { active: state.active } : {}) } satisfies Payload };
    try {
      const configuration = await this.committedConfiguration(intent);
      if (intent.scope !== this.scope || intent.epoch !== this.scopeEpoch || intent.generation !== this.generations.get(intent.cellId)
        || this.registrations.get(intent.cellId) !== registration || !this.pending.has(requestId)) {
        this.finish(requestId, false); return result;
      }
      const currentTargets = this.targets(intent.cellId, intent.operation);
      if (!currentTargets.length) { this.finish(requestId, false); return result; }
      this.pending.get(requestId)!.results = new Map(currentTargets.map(cellId => [cellId, null]));
      (event.payload as Payload).configurationRevision = configuration.revision;
      (event.payload as Payload).configurationKey = configuration.key;
      // Browser pages have no central clock ordering authority. Only this
      // renderer is supported there; desktop windows use the main-process stamp.
      const ordered = this.bus?.isNative() ? await boundedOrderReply(this.bus.publishOrderedLink(event))
        : { ...event, eventId: `link-${++this.localOrder}` };
      const pending = this.pending.get(requestId);
      if (intent.scope !== this.scope || intent.epoch !== this.scopeEpoch || this.registrations.get(intent.cellId) !== registration) {
        this.finish(requestId, false); return result;
      }
      const order = orderOf(ordered);
      const acknowledged = payload(ordered.payload);
      if (order === null || acknowledged?.requestId !== requestId || acknowledged.cursorMs !== state.cursorMs
        || acknowledged.studyId !== state.studyId || acknowledged.revision !== state.revision
        || acknowledged.operation !== intent.operation
        || acknowledged.configurationRevision !== configuration.revision || acknowledged.configurationKey !== configuration.key
        || (intent.operation === "mode" && acknowledged.active !== state.active)
        || acknowledged.leaderOrder !== (intent.operation === "tick" ? intent.leaderOrder : 0)) throw new Error("Invalid clock acknowledgement");
      if (pending) {
        pending.order = order;
        for (const [cellId, value] of pending.results) if (value && value.order !== order) pending.results.set(cellId, null);
      }
      const leader = intent.operation === "tick" ? intent.leaderOrder : order;
      const previousLeader = this.leaderOrder.get(intent.cellId) ?? 0;
      if (leader > previousLeader || (leader === previousLeader && order > (this.lastOrder.get(intent.cellId) ?? 0))) {
        this.leaderOrder.set(intent.cellId, leader); this.lastOrder.set(intent.cellId, order);
        this.leaderSource.set(intent.cellId, `${event.sourceWindowId}\u0000${intent.cellId}`);
      }
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
      if (intent.epoch === this.scopeEpoch && this.generations.get(intent.cellId) === intent.generation) this.uncertainOrder.set(intent.cellId, intent.operation);
      this.finish(requestId, true);
    }
    return result;
  }
  private async receive(event: WorkspaceBusLinkEvent) {
    const epoch = this.scopeEpoch;
    const body = payload(event.payload), order = orderOf(event);
    if (!body || order === null || event.workspaceId !== this.scope) return;
    if ((body.operation === "mode") !== (event.kind === "studyMode")) return;
    try { await this.waitForDocumentRevision(body.configurationRevision, event.sourceCellId, body.configurationKey, epoch); } catch { return; }
    if (epoch !== this.scopeEpoch || event.workspaceId !== this.scope) return;
    const leader = body.operation === "tick" ? body.leaderOrder : order;
    if (leader > order) return;
    const targets = this.targets(event.sourceCellId, body.operation);
    await Promise.all(targets.map(async cellId => {
      // A local operation orders itself only after durable commit. Await its
      // order (not peer acknowledgements) before comparing an incoming event.
      while (this.userIntents.has(cellId)) {
        if (epoch !== this.scopeEpoch) return;
        const local = this.userIntents.get(cellId)!;
        // A new explicit leader supersedes an unfinished automatic tick. The
        // tick keeps its old leader stamp even if its commit arrives later.
        if (local.operation === "tick" && leader > (this.leaderOrder.get(cellId) ?? 0)) {
          this.cancelUserAction(local); break;
        }
        await local.settled;
      }
      if (event.workspaceId !== this.scope || epoch !== this.scopeEpoch) return;
      const registration = this.registrations.get(cellId);
      if (!registration || registration.scope !== this.scope) {
        if (!this.bus?.isNative()) this.result(event, body, cellId, order, "unavailable");
        return; // A native peer may be owned by another renderer; await its ack.
      }
      let status: ChartStudyClockStatus;
      const previousLeader = this.leaderOrder.get(cellId) ?? 0;
      const source = `${event.sourceWindowId}\u0000${event.sourceCellId}`;
      if ((this.uncertainOrder.has(cellId) && this.uncertainOrder.get(cellId) !== "tick")
        || (this.uncertainOrder.has(cellId) && leader <= previousLeader)) status = "unavailable";
      else if (leader < previousLeader || (leader === previousLeader && order <= (this.lastOrder.get(cellId) ?? 0))) status = "superseded";
      else if (body.operation === "tick" && leader === previousLeader && this.leaderSource.get(cellId) !== source) status = "superseded";
      else {
        this.leaderOrder.set(cellId, leader); this.uncertainOrder.delete(cellId);
        this.leaderSource.set(cellId, source);
        this.lastOrder.set(cellId, order);
        this.generations.set(cellId, (this.generations.get(cellId) ?? 0) + 1);
        this.latestRequest.delete(this.issueKey(cellId, body.operation));
        if (this.issues.delete(this.issueKey(cellId, body.operation))) this.emit();
        let state: ChartStudyClockState | null = null;
        try { state = registration.port.read(); } catch { /* Report an unavailable owner below. */ }
        const withCursor = body.operation !== "mode" || (body.active && this.targets(event.sourceCellId).includes(cellId));
        if (!state || state.pending) status = "unavailable";
        else if (body.operation === "mode") {
          if (state.editing) status = "editing";
          else if (state.active && !state.followReady) status = "unavailable";
          else if (body.active && !state.studyId) status = "unprepared";
          else if (withCursor && (state.minimumMs === null || state.maximumMs === null
            || body.cursorMs < state.minimumMs || body.cursorMs > state.maximumMs)) status = "out-of-range";
          else {
            try {
              const changed = await registration.port.setMode(body.active!, withCursor ? body.cursorMs : undefined);
              const current = registration.port.read();
              status = epoch !== this.scopeEpoch || this.scope !== event.workspaceId || this.registrations.get(cellId) !== registration
                || this.lastOrder.get(cellId) !== order ? "superseded"
                : changed && !current.pending && current.active === body.active
                  && (!body.active || (current.studyId === state.studyId && (!withCursor || current.cursorMs === body.cursorMs))) ? "moved" : "failed";
            } catch { status = "failed"; }
          }
        }
        else if (!state.active || !state.studyId) status = "inactive";
        else if (!state.followReady) status = "unavailable";
        else if (state.editing) status = "editing";
        else if (state.minimumMs === null || state.maximumMs === null || body.cursorMs < state.minimumMs || body.cursorMs > state.maximumMs) status = "out-of-range";
        else {
          try {
            const moved = await registration.port.move(body.cursorMs);
            const current = registration.port.read();
            status = epoch !== this.scopeEpoch || this.scope !== event.workspaceId || this.registrations.get(cellId) !== registration
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
    const key = this.issueKey(pending.sourceCellId, pending.operation);
    if (report && pending.scope === this.scope && this.latestRequest.get(key) === requestId) {
      if (failed.length) this.issues.set(key, { sourceCellId: pending.sourceCellId, operation: pending.operation, failed });
      else this.issues.delete(key);
      this.emit();
    }
    pending.resolve(report && failed.length === 0);
  }
}
