import { validateKlineDomain } from "../../../utils/klineDomainPolicy.js";
import { preserveFinalRow, type KlineQualityEvidence } from "../quality/klineQualityPolicy.js";
import type { SeriesWindowView, WindowCommitState } from "./seriesWindowView.js";
import type { EpochSeconds, KlineBar, KlineBarInput } from "../marketDataTypes.js";
import type { WindowDelta, WindowDeltaDetail } from "../klineContracts.js";
import { SeriesWindowStore } from "./seriesWindowStore.js";
import { createWindowDelta, WINDOW_DELTA_TYPES } from "./windowDeltas.js";

/** Synchronous live view. capture() is the stable input for asynchronous work. */
export type MarketWindowReader = SeriesWindowView & {
  readonly commitState: WindowCommitState;
  subscribe(listener: (delta: WindowDelta, reader: SeriesWindowView) => void): () => boolean;
  capture(): { state: WindowCommitState; rows: readonly Readonly<KlineBar>[] };
};

export type WindowCommand = (
  | { type: "replace" | "range" | "correct"; rows: readonly KlineBarInput[] }
  | { type: "forward"; rows: readonly KlineBarInput[]; reachedLatest?: boolean }
  | { type: "tick"; row: KlineBarInput }
  | { type: "clear" }
) & { source?: string; quality?: KlineQualityEvidence };

export interface WindowSelection {
  readonly windowId: string;
  readonly seriesKey: string;
  readonly epoch: number;
}

interface WindowEntry {
  store: SeriesWindowStore;
  rejectedRange?: { from: number; to: number };
  reader: MarketWindowReader;
  meta: Record<string, unknown>;
  state: WindowCommitState;
  listeners: Set<(delta: WindowDelta, reader: SeriesWindowView) => void>;
}

interface WindowSeed {
  rows: KlineBar[];
  provenance: Record<string, unknown>;
}

interface WindowOptions {
  maxBars?: number;
  sharedSnapshot?: {
    read(key: string): KlineBar[];
    publish(key: string, rows: readonly KlineBar[]): void;
  } | null;
}

// Market rows and proof are JSON records. Copy nested values so callers retain
// ownership of their input while published rows/proof cannot be mutated by alias.
function immutableCopy(value: unknown): unknown {
  if (Array.isArray(value)) return Object.freeze(value.map(immutableCopy));
  if (value !== null && typeof value === "object") {
    return Object.freeze(Object.fromEntries(Object.entries(value).map(([key, item]) => [key, immutableCopy(item)])));
  }
  return value;
}

// A proxy retains the live array identity and O(1) tail replacement, while
// preventing callers from sorting/splicing/assigning into the owned window.
function protectArray<T>(rows: T[]): T[] {
  return new Proxy(rows, {
    set: () => { throw new TypeError("Market window is read-only"); },
    deleteProperty: () => { throw new TypeError("Market window is read-only"); },
    defineProperty: () => { throw new TypeError("Market window is read-only"); },
    setPrototypeOf: () => { throw new TypeError("Market window is read-only"); },
  });
}

function protectSet<T>(source: ReadonlySet<T>): ReadonlySet<T> {
  const view = new Proxy(source, {
    get(target, property) {
      if (property === "add" || property === "delete" || property === "clear") return undefined;
      if (property === "valueOf") return () => view;
      if (property === "forEach") return (callback: (value: T, key: T, set: ReadonlySet<T>) => void, thisArg?: unknown) => {
        target.forEach((value) => callback.call(thisArg, value, value, view));
      };
      const value: unknown = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) as unknown : value;
    },
    set: () => { throw new TypeError("Market window is read-only"); },
  });
  return view;
}

let nextWindowId = 0;

/** The only writer of a live chart's bounded windows (including warm intervals). */
export class MarketWindowSession {
  readonly windowId: string;
  #entries = new Map<string, WindowEntry>();
  #selection: WindowSelection | null = null;
  #nextEpoch = 0;
  #closed = false;
  #inTransaction = false;
  #publishing = false;
  #pending = new Map<WindowEntry, WindowDelta>();
  #queue: Array<() => void> = [];
  #afterCommit: Array<() => void> = [];
  #registry: MarketWindowRegistry;

  constructor(windowId: string, registry: MarketWindowRegistry) {
    this.windowId = windowId;
    this.#registry = registry;
  }

  get closed(): boolean { return this.#closed; }

  prepareSelection(seriesKey: string): WindowSelection {
    return Object.freeze({ windowId: this.windowId, seriesKey, epoch: ++this.#nextEpoch });
  }

  activate(selection: WindowSelection): void {
    if (this.#closed || selection.windowId !== this.windowId) return;
    this.#selection = selection;
    this.#registry.attach(this);
  }

  revoke(selection: WindowSelection): void {
    if (this.#selection !== selection) return;
    this.#selection = null;
    this.#queue = [];
    // React StrictMode replays setup synchronously. Revoke writes immediately,
    // but retain warm data until that replay has had a chance to reacquire it.
    queueMicrotask(() => { if (!this.#selection) this.close(); });
  }

  close(): void {
    if (this.#closed) return;
    this.#closed = true;
    this.#selection = null;
    this.#queue = [];
    for (const entry of this.#entries.values()) entry.listeners.clear();
    this.#entries.clear();
    this.#registry.detach(this);
  }

  transact<T>(selection: WindowSelection, action: () => T): T | undefined {
    if (this.#closed || this.#selection !== selection) return undefined;
    if (this.#publishing) {
      this.#queue.push(() => { this.transact(selection, action); });
      return undefined;
    }
    if (this.#inTransaction) return action();
    this.#inTransaction = true;
    try {
      return action();
    } catch (error) {
      // An adapter failed after a mutation. Never publish inherited successful
      // proof for a partially completed adapter; retain the rows for recovery.
      for (const entry of this.#pending.keys()) {
        entry.meta = { ...entry.meta, historyComplete: false, historyRepairPending: true,
          historyValidatedCountBack: null, lastValidatedMs: null, commitError: "adapter-failed" };
      }
      this.#afterCommit = [];
      throw error;
    } finally {
      this.#inTransaction = false;
      this.#publish();
    }
  }

  afterCommit(action: () => void): void {
    this.#requireTransaction();
    this.#afterCommit.push(action);
  }

  #requireTransaction(): void {
    if (!this.#inTransaction || !this.#selection) throw new Error("Window writes require an active commit owner");
  }

  get(key: string): MarketWindowReader | null { return this.#entries.get(key)?.reader ?? null; }
  has(key: string): boolean { return Boolean(this.get(key)?.barCount); }
  activateCached(key: string): { rows: KlineBar[]; store: MarketWindowReader } | null {
    const store = this.get(key);
    return store && !store.isEmpty() ? { rows: store.snapshot(), store } : null;
  }

  getOrCreate(key: string, options: { intervalSeconds?: number | null; meta?: Record<string, unknown> } = {}): MarketWindowReader {
    this.#requireTransaction();
    let entry = this.#entries.get(key);
    if (!entry) {
      const store = new SeriesWindowStore({
        seriesKey: key,
        maxBars: this.#registry.maxBars,
        intervalSeconds: options.intervalSeconds ?? null,
        rightTruncatedFuturePolicy: "reject",
      });
      const arrays = new WeakMap<KlineBar[], KlineBar[]>();
      const timeSets = new WeakMap<ReadonlySet<EpochSeconds>, ReadonlySet<EpochSeconds>>();
      const snapshot = () => {
        const rows = store.snapshot();
        let protectedRows = arrays.get(rows);
        if (!protectedRows) { protectedRows = protectArray(rows); arrays.set(rows, protectedRows); }
        return protectedRows;
      };
      const state = Object.freeze({ windowId: this.windowId, sessionEpoch: this.#selection!.epoch, seriesKey: key,
        commitRevision: 0, dataRevision: 0, axisRevision: 0, bars: 0, firstTime: null, lastTime: null });
      const owned: WindowEntry = { store, meta: {}, state, listeners: new Set(), reader: null as unknown as MarketWindowReader };
      owned.reader = Object.freeze({
        get seriesKey() { return store.seriesKey; },
        get maxBars() { return store.maxBars; },
        get intervalSeconds() { return store.intervalSeconds; },
        get version() { return store.version; },
        get axisRevision() { return store.axisRevision; },
        get rightTruncated() { return store.rightTruncated; },
        get barCount() { return store.barCount; },
        get segments() { return store.segments; },
        get commitState() { return owned.state; },
        snapshot,
        isEmpty: () => store.isEmpty(),
        hasTime: (time: unknown) => store.hasTime(time),
        getByTime: (time: unknown) => store.getByTime(time),
        indexOfTime: (time: unknown) => store.indexOfTime(time),
        first: () => store.first(), last: () => store.last(),
        coverage: () => store.coverage(), describe: () => store.describe(),
        timeSet: () => {
          const times = store.timeSet();
          let view = timeSets.get(times);
          if (!view) { view = protectSet(times); timeSets.set(times, view); }
          return view;
        },
        subscribe: (listener: (delta: WindowDelta, reader: SeriesWindowView) => void) => {
          owned.listeners.add(listener);
          return () => owned.listeners.delete(listener);
        },
        capture: () => ({ state: owned.state, rows: Object.freeze(store.snapshot().slice()) }),
      });
      entry = owned;
      this.#entries.set(key, entry);
      const seed = this.#registry.readSeed(key);
      if (seed) {
        this.apply(key, { type: "replace", rows: seed.rows, source: "shared-window-seed" });
        this.touchMeta(key, { seed: Object.freeze(seed.provenance), historyComplete: false,
          historyRepairPending: false, historyValidatedCountBack: null, lastValidatedMs: null });
      }
    }
    if (options.meta) this.touchMeta(key, options.meta);
    return entry.reader;
  }

  apply(key: string, command: WindowCommand): WindowDelta {
    this.#requireTransaction();
    const entry = this.#entries.get(key);
    if (!entry) throw new Error(`Missing owned window: ${key}`);
    const { store } = entry;
    if (command.type !== "clear") {
      const incoming = command.type === "tick" ? [command.row] : command.rows;
      for (let index = 0; index < incoming.length; index += 1) {
        const issue = validateKlineDomain(incoming[index]!);
        if (!issue) continue;
        const times = incoming.map((row) => Number(row.time)).filter(Number.isFinite);
        entry.rejectedRange = { from: Math.min(...times), to: Math.max(...times) };
        this.touchMeta(key, { admission: { status: "rejected", source: command.source ?? command.type, index, ...issue } });
        return createWindowDelta(WINDOW_DELTA_TYPES.NOOP, { rejection: issue });
      }
      if (entry.rejectedRange && command.type !== "tick" && incoming.length
        && (command.type === "replace" || (command.quality?.coverage === "verified" && Math.min(...incoming.map((row) => Number(row.time))) <= entry.rejectedRange.from
          && Math.max(...incoming.map((row) => Number(row.time))) >= entry.rejectedRange.to))) {
        delete entry.rejectedRange;
        this.touchMeta(key, { admission: { status: "accepted", source: command.source ?? command.type } });
      }
      // Preserve finality at the single writer, including cache/seed/navigation
      // adapters that do not traverse an HTTP request fence.
      if (command.type === "tick") {
        const row = preserveFinalRow(command.row, store.getByTime(command.row.time));
        command = { ...command, row };
      } else {
        command = { ...command, rows: incoming.map((row) => preserveFinalRow(row, store.getByTime(row.time))) };
      }
    } else delete entry.rejectedRange;
    const detail: WindowDeltaDetail = command.source === undefined ? {} : { source: command.source };
    let delta: WindowDelta;
    switch (command.type) {
      case "replace": delta = store.replace(command.rows, detail); break;
      case "range": delta = store.applyRange(command.rows, detail); break;
      case "correct": delta = store.correctWindow(command.rows, detail); break;
      case "forward":
        delta = store.applyForwardPage(command.rows, detail);
        if (command.reachedLatest && store.markRightEdgeCurrent()) this.#pending.set(entry, delta);
        break;
      case "tick": delta = store.applyTick(command.row, detail); break;
      case "clear": delta = store.clear(detail); break;
    }
    if (delta.changed) {
      // Store replaces row objects; freezing only incoming retained rows is
      // O(1) for a tail tick and prevents mutation through first/getByTime too.
      const incoming = command.type === "clear" ? [] : command.type === "tick" ? [command.row] : command.rows;
      for (const row of incoming) {
        const retained = store.getByTime(row.time);
        if (retained && !Object.isFrozen(retained)) {
          for (const [field, value] of Object.entries(retained)) {
            if (value !== null && typeof value === "object") retained[field] = immutableCopy(value);
          }
          Object.freeze(retained);
        }
      }
      const previous = this.#pending.get(entry);
      this.#pending.set(entry, previous?.changed ? createWindowDelta(WINDOW_DELTA_TYPES.REPLACE, {
        source: command.source, changedRanges: [...(previous.changedRanges || []), ...(delta.changedRanges || [])],
      }) : delta);
    }
    const acceptedRows = command.type === "clear" ? [] : command.type === "tick" ? [command.row] : command.rows;
    if (delta.changed || command.quality) {
      this.touchMeta(key, { admission: { status: "accepted", source: command.source ?? command.type,
        rows: acceptedRows.length, dataRevision: Number(store.version),
        inputQuality: command.quality ?? null } });
    }
    return delta;
  }

  touchMeta(key: string, patch: Record<string, unknown> = {}): void {
    const entry = this.#entries.get(key);
    if (!entry) return;
    if (Object.keys(patch).length > 0) this.#requireTransaction();
    entry.meta = { ...entry.meta, ...immutableCopy(patch) as Record<string, unknown>, lastAccessMs: Date.now(), metaRevision: Number(entry.meta.metaRevision || 0) + 1 };
    if (entry.rejectedRange) entry.meta = { ...entry.meta, historyComplete: false,
      historyRepairPending: true, historyValidatedCountBack: null, lastValidatedMs: null };
    if (Object.keys(patch).length > 0 && !this.#pending.has(entry)) {
      this.#pending.set(entry, createWindowDelta(WINDOW_DELTA_TYPES.NOOP));
    }
  }
  meta(key: string): Record<string, unknown> { return { ...this.#entries.get(key)?.meta }; }
  entries(): Array<{ key: string; store: MarketWindowReader; meta: Record<string, unknown> }> {
    return Array.from(this.#entries, ([key, entry]) => ({ key, store: entry.reader, meta: { ...entry.meta } }));
  }
  evict(key: string): ({ key: string } & ReturnType<SeriesWindowStore["describe"]>) | null {
    this.#requireTransaction();
    const entry = this.#entries.get(key);
    if (!entry) return null;
    const description = entry.store.describe();
    entry.listeners.clear();
    this.#pending.delete(entry);
    this.#entries.delete(key);
    return { key, ...description };
  }

  #publish(): void {
    const pending = Array.from(this.#pending);
    this.#pending.clear();
    // Seal ALL touched windows before running any consumer callback.
    for (const [entry] of pending) {
      const { store } = entry;
      entry.state = Object.freeze({ ...entry.meta, windowId: this.windowId,
        sessionEpoch: this.#selection!.epoch, seriesKey: String(store.seriesKey),
        commitRevision: entry.state.commitRevision + 1, dataRevision: Number(store.version),
        axisRevision: Number(store.axisRevision), bars: store.barCount,
        firstTime: store.first()?.time ?? null, lastTime: store.last()?.time ?? null });
    }
    this.#publishing = true;
    try {
      for (const [entry, delta] of pending) {
        this.#registry.publishSeed(entry.reader, delta);
        for (const listener of Array.from(entry.listeners)) listener(delta, entry.reader);
      }
      const callbacks = this.#afterCommit;
      this.#afterCommit = [];
      for (const callback of callbacks) callback();
    } finally {
      this.#publishing = false;
      while (this.#queue.length) this.#queue.shift()!();
    }
  }
}

/** Shared resources retain bounded seeds, never a mutable navigation store. */
export class MarketWindowRegistry {
  readonly maxBars: number;
  #windows = new Set<MarketWindowSession>();
  #seeds = new Map<string, WindowSeed>();
  #options: WindowOptions;
  #counts = { hydrations: 0, hydratedBars: 0, publishes: 0, publishErrors: 0 };
  constructor(options: WindowOptions = {}) { this.#options = options; this.maxBars = options.maxBars ?? 10_000; }
  createWindow(label = "chart"): MarketWindowSession {
    return new MarketWindowSession(`${label}:${++nextWindowId}`, this);
  }
  attach(session: MarketWindowSession): void { this.#windows.add(session); }
  detach(session: MarketWindowSession): void { this.#windows.delete(session); }
  entries(): ReturnType<MarketWindowSession["entries"]> { return Array.from(this.#windows).flatMap((session) => session.entries()); }
  sharedSnapshotDiagnostics() { return { ...this.#counts }; }
  readSeed(key: string): WindowSeed | null {
    const local = this.#seeds.get(key);
    const rows = local?.rows ?? this.#options.sharedSnapshot?.read(key) ?? [];
    if (!rows.length) return null;
    this.#counts.hydrations += 1;
    this.#counts.hydratedBars += rows.length;
    return { rows, provenance: local?.provenance ?? { source: "desktop-shared-snapshot", quality: "unknown",
      seriesKey: key, from: rows[0]?.time, to: rows.at(-1)?.time } };
  }
  publishSeed(reader: MarketWindowReader, delta: WindowDelta): void {
    if (!delta.changed || delta.type === WINDOW_DELTA_TYPES.TICK || !reader.barCount) return;
    const key = String(reader.seriesKey);
    const rows = reader.snapshot().slice(-256).map((row) => ({ ...row }));
    this.#seeds.delete(key);
    this.#seeds.set(key, { rows, provenance: { ...reader.commitState, source: "window-seed", from: rows[0]?.time, to: rows.at(-1)?.time } });
    while (this.#seeds.size > 64) this.#seeds.delete(this.#seeds.keys().next().value!);
    try {
      this.#options.sharedSnapshot?.publish(key, rows);
      this.#counts.publishes += 1;
    } catch { this.#counts.publishErrors += 1; }
  }
}

export function createDetachedWindowReader(key: string, options: { maxBars?: number; intervalSeconds?: number | null } = {}): MarketWindowReader {
  const session = new MarketWindowRegistry(options).createWindow("detached");
  const selection = session.prepareSelection(key);
  session.activate(selection);
  return session.transact(selection, () => session.getOrCreate(key, options))!;
}
