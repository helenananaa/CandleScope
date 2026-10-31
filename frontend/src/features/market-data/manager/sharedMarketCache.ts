import { validateKlineDomain } from "../../../utils/klineDomainPolicy.js";
import type { KlineFetchResult } from "../klineContracts.js";
import type { KlineBar, MarketSeries } from "../marketDataTypes.js";
import {
  assessKlineQuality, assessRealtimeEffect, chooseHttpRow, hasFinalityEvidence, preserveFinalRow,
} from "../quality/klineQualityPolicy.js";
import { MarketHealthState, parseMarketVersion, sameStream, type HealthReadFence, type MarketHealth } from "./marketHealth.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";

export interface MarketRange { from?: number; to?: number; before?: number; limit?: number; finalOnly?: boolean }
export interface MarketCacheOptions { maxSeries?: number; maxBars?: number; maxBarsPerSeries?: number; now?: () => number; freshMs?: number }
export class MarketCacheCapacityError extends Error {
  constructor() { super("Market cache series capacity is in use"); this.name = "MarketCacheCapacityError"; }
}
export interface MarketCacheChange {
  readonly key: string;
  readonly version: number;
  readonly commitRevision: number;
  readonly source: "http" | "realtime";
  readonly eventType?: string;
  readonly rows: readonly KlineBar[];
}
export interface MarketCacheSnapshot {
  readonly key: string;
  readonly version: number;
  readonly commitRevision: number;
  readonly rows: readonly KlineBar[];
  readonly complete: boolean;
  isCurrent(): boolean;
}
export interface MarketReadToken { readonly key: string; release(): void }
/** A dependency stamp retains no row arrays and owns no cache lease. */
export interface MarketInputVersion {
  readonly key: string;
  readonly version: number;
  readonly from: number | undefined;
  readonly to: number | undefined;
  isCurrent(): boolean;
}
interface Mutation { row: KlineBar; version: number; authoritative: boolean }
interface Proof { from: number; to: number }
interface Entry {
  generation: number;
  metaRevision: number;
  lastAccessMs: number;
  lastUpdatedMs: number;
  key: string;
  series: MarketSeries;
  rows: Map<number, KlineBar>;
  rowVersions: Map<number, number>;
  inputInvalidation: number;
  times: number[];
  version: number;
  commitRevision: number;
  realtimeVersion: number;
  mutations: Map<number, Mutation>;
  reads: Set<MarketReadToken>;
  leases: Map<symbol, MarketRange>;
  proofs: Proof[];
  health: MarketHealthState;
  expectedClosedTime: number | null;
  historyDemand: number;
  serverRowVersions: Map<number, number>;
  invalidations: Array<Proof & { version: number }>;
}
interface ReadState { entry: Entry; version: number; health: HealthReadFence }

function immutableCopy<T>(value: T): T {
  if (Array.isArray(value)) return Object.freeze(value.map(immutableCopy)) as T;
  if (value !== null && typeof value === "object") {
    return Object.freeze(Object.fromEntries(Object.entries(value).map(([key, item]) => [key, immutableCopy(item)]))) as T;
  }
  return value;
}

function equal(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  const a = Object.keys(left), b = Object.keys(right);
  return a.length === b.length && a.every(key => Object.hasOwn(right, key)
    && equal((left as Record<string, unknown>)[key], (right as Record<string, unknown>)[key]));
}

function lowerBound(times: readonly number[], time: number): number {
  let low = 0, high = times.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (times[middle]! < time) low = middle + 1;
    else high = middle;
  }
  return low;
}

function selectedTimes(entry: Entry, range: MarketRange): number[] {
  const start = range.from === undefined ? 0 : lowerBound(entry.times, range.from);
  const end = range.before !== undefined ? lowerBound(entry.times, range.before)
    : range.to === undefined ? entry.times.length : lowerBound(entry.times, range.to + 1);
  if (!range.finalOnly) return entry.times.slice(Math.max(start, range.limit === undefined ? start : end - Math.max(0, range.limit)), end);
  const candidates: number[] = [];
  for (let index = end - 1; index >= start && (range.limit === undefined || candidates.length < range.limit); index -= 1) {
    const time = entry.times[index]!;
    if (entry.rows.get(time)?.is_closed === true) candidates.push(time);
  }
  return candidates.reverse();
}

/** Workspace-owned immutable facts. No navigation boundary, React state or IO.
 * Reads capture immutable rows; windows retain their own bounded navigation view.
 * Proof describes retained ranges, never the union of unrelated responses. */
export class SharedMarketCache {
  private readonly entries = new Map<string, Entry>();
  private readonly reads = new WeakMap<MarketReadToken, ReadState>();
  private readonly listeners = new Map<string, Set<(change: MarketCacheChange) => void>>();
  private readonly maxSeries: number;
  private readonly maxBars: number;
  private readonly maxBarsPerSeries: number;
  private bars = 0;
  private revision = 0;
  private metadataRevision = 0;
  private generation = 0;
  private publishing = false;
  private listenerErrors = 0;
  private capacityRejects = 0;
  private readonly pendingRealtime: Array<() => void> = [];

  constructor(private readonly options: MarketCacheOptions = {}) {
    this.maxSeries = Math.max(1, options.maxSeries ?? 128);
    this.maxBars = Math.max(1, options.maxBars ?? 200_000);
    this.maxBarsPerSeries = Math.max(1, options.maxBarsPerSeries ?? 30_000);
  }

  beginRead(series: MarketSeries): MarketReadToken {
    const entry = this.entry(series);
    const token: MarketReadToken = Object.freeze({ key: entry.key, release: () => this.releaseRead(token) });
    entry.reads.add(token);
    this.reads.set(token, { entry, version: entry.realtimeVersion, health: entry.health.fence() });
    return token;
  }

  admitResponse(token: MarketReadToken, response: KlineFetchResult): KlineFetchResult {
    if (this.publishing) throw new Error("HTTP admission cannot reenter a cache publication");
    const state = this.reads.get(token);
    if (!state || this.entries.get(token.key) !== state.entry) throw new Error("Market read expired");
    const { entry } = state;
    const incoming = response.data ?? [];
    // Validate the entire batch before changing rows, fences or range evidence.
    for (const row of incoming) {
      const issue = validateKlineDomain(row);
      if (issue) throw new TypeError(`Invalid market row ${issue.field}: ${issue.reason}`);
    }
    const parsedVersion = parseMarketVersion(response.stream_version, entry.series);
    const serverVersion = parsedVersion?.stable === true ? parsedVersion : null;
    if (response.stream_version != null && !parsedVersion) throw new Error("Invalid market snapshot version scope");
    const previousVersion = entry.health.version;
    if (!entry.health.snapshot(serverVersion, state.health)) throw new Error("Obsolete market snapshot; fresh read required");
    if (previousVersion && (!entry.health.version || (serverVersion && !sameStream(previousVersion, serverVersion)))) {
      entry.proofs = []; entry.serverRowVersions.clear(); entry.expectedClosedTime = null; entry.inputInvalidation += 1;
    } else if (previousVersion && serverVersion && serverVersion.barrier > previousVersion.barrier) {
      // A newer snapshot can cross a critical event that this client never
      // received. It proves only its returned range, not older cached history
      // or indicator inputs outside that range. Keep rows as provisional.
      entry.proofs = []; entry.inputInvalidation += 1;
    }
    const endpoint = response.endpoint ?? "history";
    const inputQuality = assessKlineQuality(response, endpoint);
    const trustedFinal = hasFinalityEvidence(response);
    const rows = incoming.map(row => {
      if (serverVersion && (entry.serverRowVersions.get(row.time) ?? -1) > serverVersion.sequence) return entry.rows.get(row.time)!;
      const mutation = entry.mutations.get(row.time);
      const decision = serverVersion ? "http" : chooseHttpRow(row, mutation, state.version, trustedFinal);
      let accepted = decision === "realtime" && mutation ? mutation.row : row;
      accepted = preserveFinalRow(accepted, entry.rows.get(row.time));
      if (decision === "promote-http") this.recordMutation(entry, accepted, true);
      return accepted;
    });
    const changed = this.merge(entry, rows);
    if (serverVersion) for (const row of rows) entry.serverRowVersions.set(row.time,
      Math.max(entry.serverRowVersions.get(row.time) ?? 0, serverVersion.sequence));
    const result = { ...response, data: rows.map(row => entry.rows.get(row.time) ?? immutableCopy(row)) };
    const quality = assessKlineQuality(result, endpoint);
    if (incoming.length) {
      const times = incoming.map(row => Number(row.time));
      const from = Math.min(...times), to = Math.max(...times);
      // Latest is a tail observation, not a history claim. A contradictory
      // history response invalidates overlapping proof even if OHLCV is equal.
      if (endpoint !== "latest" && endpoint !== "seed") {
        entry.proofs = entry.proofs.filter(proof => proof.to < from || proof.from > to);
        if (inputQuality.complete && quality.complete) { entry.proofs.push({ from, to }); entry.historyDemand = Math.min(1500, Math.max(entry.historyDemand, incoming.length)); }
        entry.proofs = entry.proofs.slice(-128);
      }
    }
    if (!inputQuality.complete) entry.health.invalidate();
    this.finish(entry, changed, "http");
    return { ...result, quality, cacheRevision: entry.version };
  }

  admitRealtime(series: MarketSeries, row: KlineBar, eventType?: string, wireVersion?: unknown, previousOpenMs?: unknown): { accepted: boolean; row?: KlineBar; changed?: boolean } {
    if (this.publishing) {
      this.pendingRealtime.push(() => { this.admitRealtime(series, row, eventType, wireVersion, previousOpenMs); });
      return { accepted: false };
    }
    const issue = validateKlineDomain(row);
    if (issue) return { accepted: false };
    let entry: Entry;
    try { entry = this.entry(series); }
    catch (error) { if (error instanceof MarketCacheCapacityError) { this.capacityRejects += 1; return { accepted: false }; } throw error; }
    const effect = assessRealtimeEffect(row, eventType, entry.rows.get(row.time), entry.times.at(-1) ?? null);
    if (!effect.accepted) return { accepted: false };
    const version = parseMarketVersion(wireVersion, series);
    if (wireVersion != null && !version) { entry.health.invalidate(); return { accepted: false }; }
    const decision = entry.health.event(version, eventType !== "bar.updated", effect.updatesFreshness);
    if (!decision.accept) return { accepted: false };
    if (decision.reset || decision.gap) {
      entry.proofs = []; entry.inputInvalidation += 1;
      if (decision.reset) { entry.serverRowVersions.clear(); entry.expectedClosedTime = null; }
    }
    const incoming = version && (entry.serverRowVersions.get(row.time) ?? -1) >= version.sequence
      ? entry.rows.get(row.time) ?? row : row;
    const changed = this.merge(entry, [incoming]);
    if (version) entry.serverRowVersions.set(row.time, version.sequence);
    const accepted = entry.rows.get(row.time)!;
    if (version && effect.updatesFreshness && typeof previousOpenMs === "number" && Number.isSafeInteger(previousOpenMs)) {
      const expected = row.is_closed === true ? Number(row.time) : previousOpenMs / 1000;
      entry.expectedClosedTime = Math.max(entry.expectedClosedTime ?? expected, expected);
    }
    if (eventType === "bar.amended" && changed.length && !version) {
      entry.proofs = entry.proofs.filter(proof => row.time < proof.from || row.time > proof.to);
    }
    // Only the backend calendar's predecessor and an unbroken barrier chain
    // can extend coverage. A timestamp jump never supplies its own proof.
    if (version && eventType === "bar.closed" && entry.health.status(true).continuous
      && typeof previousOpenMs === "number" && Number.isSafeInteger(previousOpenMs)) {
      for (const proof of entry.proofs) if (proof.to === previousOpenMs / 1000) proof.to = Number(row.time);
    }
    // Record every observed event, including equal duplicates, while a request
    // is in flight. Duplicate delivery is not a second published data revision.
    this.recordMutation(entry, accepted, row.is_closed === true);
    if (changed.length) this.finish(entry, changed, "realtime", eventType);
    return { accepted: true, row: accepted, changed: changed.length > 0 };
  }

  read(series: MarketSeries, range: MarketRange = {}): MarketCacheSnapshot {
    const key = String(buildSeriesWindowKey(series));
    const entry = this.entries.get(key);
    if (!entry) return Object.freeze({ key, version: 0, commitRevision: 0, rows: Object.freeze([]), complete: false, isCurrent: () => false });
    this.touch(entry);
    const times = selectedTimes(entry, range);
    const rows = Object.freeze(times.map(time => entry.rows.get(time)!));
    const version = entry.version;
    const from = range.from ?? times[0], to = range.to ?? times.at(-1);
    const proofTo = range.before ?? to;
    const covered = from !== undefined && to !== undefined && rows.length > 0
      && entry.proofs.some(proof => proof.from <= from && proof.to >= proofTo!);
    // A proof spanning an evicted hole cannot survive: eviction removes any
    // proof containing that timestamp. Unknown intervals require no arithmetic.
    const complete = covered && rows.every(row => row.is_closed === true)
      && (range.limit === undefined || rows.length >= range.limit);
    return Object.freeze({ key, version, commitRevision: entry.commitRevision, rows, complete,
      isCurrent: () => {
        if (this.entries.get(key) !== entry) return false;
        if (complete && !entry.proofs.some(proof => proof.from <= from! && proof.to >= proofTo!)) return false;
        if (range.to === undefined && range.before === undefined) return entry.version === version;
        const current = selectedTimes(entry, range);
        return current.length === times.length && current.every((time, index) => time === times[index] && entry.rows.get(time) === rows[index]);
      },
    });
  }

  planHistory(series: MarketSeries, limit: number): { snapshot: MarketCacheSnapshot; health: MarketHealth; action: "reuse" | "load" | "subscribe-and-verify" | "verify" } {
    const snapshot = this.read(series, { limit, finalOnly: true });
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    const health = (entry?.health ?? new MarketHealthState(this.options.now, this.options.freshMs)).status(snapshot.complete && entry?.expectedClosedTime != null && Number(snapshot.rows.at(-1)?.time) >= entry.expectedClosedTime);
    return { snapshot, health, action: health.healthy ? "reuse" : !snapshot.complete ? "load"
      : !health.subscribed ? "subscribe-and-verify" : "verify" };
  }

  verificationDemand(series: MarketSeries): number {
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    if (!entry?.historyDemand || !entry.health.version) return 0;
    const status = entry.health.status(true);
    // The tick hot path inspects bounded proof metadata, not a 1,500-row
    // snapshot. Requested count/range sufficiency is checked only on reads.
    const expected = entry.expectedClosedTime;
    const covered = expected !== null && entry.proofs.some(proof => proof.from <= expected && proof.to >= expected);
    return status.subscribed && (!status.continuous || !covered) ? entry.historyDemand : 0;
  }

  connect(series: MarketSeries): void {
    try { this.entry(series).health.connect(); }
    catch (error) { if (!(error instanceof MarketCacheCapacityError)) throw error; }
  }

  invalidateRange(series: MarketSeries, range?: { from: number; to: number }, wireVersion?: unknown): void {
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    if (!entry) return;
    const version = parseMarketVersion(wireVersion, series);
    if (version) {
      const decision = entry.health.event(version, true, false);
      if (!decision.accept) return;
      if (decision.reset || decision.gap) range = undefined;
    }
    entry.health.invalidate();
    if (!range) { entry.proofs = []; entry.inputInvalidation += 1; }
    else {
      const left = entry.times[lowerBound(entry.times, range.from) - 1];
      const right = entry.times[lowerBound(entry.times, range.to + 1)];
      entry.proofs = entry.proofs.flatMap(proof => {
        if (proof.to < range.from || proof.from > range.to) return [proof];
        const retained: Proof[] = [];
        if (left !== undefined && left >= proof.from) retained.push({ from: proof.from, to: Math.min(left, proof.to) });
        if (right !== undefined && right <= proof.to) retained.push({ from: Math.max(right, proof.from), to: proof.to });
        return retained;
      }).slice(-128);
      entry.version = ++this.revision;
      entry.invalidations.push({ ...range, version: entry.version });
      if (entry.invalidations.length > 128) { entry.invalidations = []; entry.inputInvalidation += 1; }
    }
    this.finish(entry, [], "http");
  }

  captureVersion(series: MarketSeries, range: Pick<MarketRange, "from" | "to"> = {}): MarketInputVersion {
    const key = String(buildSeriesWindowKey(series));
    const { from, to } = range;
    const entry = this.entries.get(key);
    const version = entry?.version ?? 0, invalidation = entry?.inputInvalidation, generation = entry?.generation;
    let checkedVersion = version, valid = Boolean(entry);
    return Object.freeze({ key, version, from, to, isCurrent: () => {
      const current = this.entries.get(key);
      if (!valid || !current || current.generation !== generation || current.inputInvalidation !== invalidation) return false;
      if (current.version === checkedVersion) return true;
      if (current.invalidations.some(change => change.version > version
        && (to === undefined || change.from <= to) && (from === undefined || change.to >= from))) { valid = false; return false; }
      const start = from === undefined ? 0 : lowerBound(current.times, from);
      const end = to === undefined ? current.times.length : lowerBound(current.times, to + 1);
      for (let index = start; index < end; index += 1) {
        if ((current.rowVersions.get(current.times[index]!) ?? 0) > version) { valid = false; return false; }
      }
      checkedVersion = current.version;
      return true;
    } });
  }

  /** Retention prioritizes active ranges; hard memory limits still win. */
  retain(series: MarketSeries, range: MarketRange): { release(): void; isCurrent(): boolean } {
    const entry = this.entry(series), id = Symbol(entry.key);
    entry.leases.set(id, { ...range });
    this.touch(entry);
    return { release: () => { entry.leases.delete(id); }, isCurrent: () => this.entries.get(entry.key) === entry && entry.leases.has(id) };
  }

  subscribe(series: MarketSeries, listener: (change: MarketCacheChange) => void): () => void {
    const key = String(buildSeriesWindowKey(series));
    let subscribers = this.listeners.get(key);
    if (!subscribers) { subscribers = new Set(); this.listeners.set(key, subscribers); }
    subscribers.add(listener);
    const entry = this.entries.get(key);
    if (entry) this.touch(entry);
    return () => {
      subscribers.delete(listener);
      if (!subscribers.size) this.listeners.delete(key);
    };
  }

  invalidate(series: MarketSeries): void {
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    if (entry) this.remove(entry);
  }

  disconnectSeries(series: MarketSeries): void {
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    if (!entry) return;
    entry.health.disconnect(false); entry.proofs = []; entry.inputInvalidation += 1;
  }

  markDisconnected(instrument: Pick<MarketSeries, "exchange" | "marketType" | "symbol">, revokeReads = true): void {
    for (const entry of this.entries.values()) {
      if (entry.series.exchange.toLowerCase() !== instrument.exchange.toLowerCase()
        || entry.series.marketType.toLowerCase() !== instrument.marketType.toLowerCase()
        || entry.series.symbol.toUpperCase() !== instrument.symbol.toUpperCase()) continue;
      entry.proofs = [];
      entry.health.disconnect(revokeReads);
      entry.inputInvalidation += 1;
      entry.metaRevision = ++this.metadataRevision;
      entry.commitRevision = ++this.revision;
    }
  }

  clear(): void {
    for (const entry of this.entries.values()) this.remove(entry);
    this.listeners.clear();
    this.pendingRealtime.length = 0;
  }

  diagnostics() {
    return { series: this.entries.size, bars: this.bars, maxSeries: this.maxSeries, maxBars: this.maxBars,
      listenerErrors: this.listenerErrors, capacityRejects: this.capacityRejects,
      requests: Array.from(this.entries.values()).reduce((sum, entry) => sum + entry.reads.size, 0),
      retainedRanges: Array.from(this.entries.values()).reduce((sum, entry) => sum + entry.leases.size, 0) };
  }

  /** Metadata only: inspection must not refresh LRU or invalidate a GC plan. */
  diagnosticEntries() {
    return [...this.entries.values()].map(entry => ({ key: entry.key, series: entry.series,
      generation: entry.generation, metaRevision: entry.metaRevision, bars: entry.rows.size,
      lastAccessMs: entry.lastAccessMs, lastUpdatedMs: entry.lastUpdatedMs,
      protected: entry.reads.size > 0 || entry.leases.size > 0 || Boolean(this.listeners.get(entry.key)?.size),
    }));
  }

  evictIfUnchanged(key: string, generation: number, metaRevision: number, bars: number): boolean {
    const entry = this.entries.get(key);
    if (!entry || entry.generation !== generation || entry.metaRevision !== metaRevision || entry.rows.size !== bars
      || entry.reads.size || entry.leases.size || this.listeners.get(key)?.size) return false;
    this.remove(entry);
    return true;
  }

  private entry(series: MarketSeries): Entry {
    const key = String(buildSeriesWindowKey(series));
    let entry = this.entries.get(key);
    if (!entry) {
      if (this.entries.size >= this.maxSeries) {
        const victim = [...this.entries.values()].find(item => !item.reads.size && !item.leases.size && !this.listeners.get(item.key)?.size);
        if (!victim) throw new MarketCacheCapacityError();
        this.remove(victim);
      }
      entry = { key, series: { ...series }, generation: ++this.generation, metaRevision: 0, lastAccessMs: 0, lastUpdatedMs: 0,
        rows: new Map(), rowVersions: new Map(), inputInvalidation: 0, times: [], version: 0, commitRevision: 0, realtimeVersion: 0,
        mutations: new Map(), reads: new Set(), leases: new Map(), proofs: [],
        health: new MarketHealthState(this.options.now, this.options.freshMs), expectedClosedTime: null, historyDemand: 0, serverRowVersions: new Map(), invalidations: [] };
      this.entries.set(key, entry);
    }
    this.touch(entry);
    return entry;
  }

  private touch(entry: Entry): void {
    entry.metaRevision = ++this.metadataRevision;
    entry.lastAccessMs = Date.now();
    this.entries.delete(entry.key); this.entries.set(entry.key, entry);
  }

  private recordMutation(entry: Entry, row: KlineBar, authoritative: boolean): void {
    entry.realtimeVersion += 1;
    if (!entry.reads.size) return;
    const previous = entry.mutations.get(row.time);
    entry.mutations.set(row.time, { row, version: entry.realtimeVersion, authoritative: authoritative || previous?.authoritative === true });
    // A stalled request cannot retain an unbounded second copy of live history.
    // Revoke its fence rather than silently discard ordering evidence.
    if (entry.mutations.size > this.maxBarsPerSeries) {
      for (const token of [...entry.reads]) this.releaseRead(token);
    }
  }

  private releaseRead(token: MarketReadToken): void {
    const state = this.reads.get(token);
    if (!state) return;
    const { entry } = state;
    this.reads.delete(token);
    entry.reads.delete(token);
    if (!entry.reads.size) entry.mutations.clear();
    else {
      const oldest = Math.min(...Array.from(entry.reads, item => this.reads.get(item)!.version));
      for (const [time, mutation] of entry.mutations) if (mutation.version <= oldest) entry.mutations.delete(time);
    }
  }

  private merge(entry: Entry, rows: readonly KlineBar[]): KlineBar[] {
    const changed: KlineBar[] = [];
    let needsSort = false;
    for (const row of rows) {
      const held = entry.rows.get(row.time);
      if (held && equal(held, row)) continue;
      const owned = immutableCopy(row);
      entry.rows.set(row.time, owned);
      changed.push(owned);
      if (!held) {
        if (entry.times.length && row.time < entry.times.at(-1)!) needsSort = true;
        entry.times.push(row.time);
        this.bars += 1;
      }
    }
    if (needsSort) entry.times.sort((left, right) => left - right);
    return changed;
  }

  private finish(entry: Entry, changed: KlineBar[], source: MarketCacheChange["source"], eventType?: string): void {
    entry.metaRevision = ++this.metadataRevision;
    entry.lastUpdatedMs = Date.now();
    if (changed.length) entry.version = ++this.revision;
    for (const row of changed) entry.rowVersions.set(row.time, entry.version);
    entry.commitRevision = ++this.revision;
    this.trim(entry);
    const event: MarketCacheChange = Object.freeze({ key: entry.key, version: entry.version,
      commitRevision: entry.commitRevision, source, ...(eventType === undefined ? {} : { eventType }), rows: Object.freeze(changed) });
    this.publishing = true;
    try {
      for (const listener of [...(this.listeners.get(entry.key) ?? [])]) {
        try { listener(event); } catch { this.listenerErrors += 1; }
      }
    } finally {
      this.publishing = false;
      while (this.pendingRealtime.length) this.pendingRealtime.shift()!();
    }
  }

  private trim(entry: Entry): void {
    const pinned = (time: number) => [...entry.leases.values()].some(range => (range.from === undefined || time >= range.from)
      && (range.to === undefined || time <= range.to) && (range.before === undefined || time < range.before));
    if (entry.times.length > this.maxBarsPerSeries) {
      // Evict a small block at capacity, amortizing the ordered-index update
      // across subsequent appends rather than filtering all history per bar.
      const headroom = Math.min(512, Math.floor(this.maxBarsPerSeries / 10));
      const overflow = entry.times.length - this.maxBarsPerSeries + headroom;
      const candidates = [...entry.times.filter(time => !pinned(time)), ...entry.times.filter(pinned)];
      this.dropTimes(entry, new Set(candidates.slice(0, overflow)));
    }
    if (this.bars > this.maxBars) {
      for (const candidate of this.entries.values()) {
        if (this.bars <= this.maxBars) break;
        if (candidate === entry || candidate.reads.size || candidate.leases.size || this.listeners.get(candidate.key)?.size) continue;
        this.remove(candidate);
      }
      if (this.bars > this.maxBars) this.dropTimes(entry, new Set(entry.times.slice(0, this.bars - this.maxBars)));
    }
  }

  private dropTimes(entry: Entry, times: Set<number>): void {
    if (!times.size) return;
    const retainedProofs: Proof[] = [];
    for (const proof of entry.proofs) {
      let from: number | undefined, to: number | undefined;
      for (let index = lowerBound(entry.times, proof.from); index < entry.times.length && entry.times[index]! <= proof.to; index += 1) {
        const time = entry.times[index]!;
        if (times.has(time)) {
          if (from !== undefined && to !== undefined) retainedProofs.push({ from, to });
          from = undefined; to = undefined;
        } else { from ??= time; to = time; }
      }
      if (from !== undefined && to !== undefined) retainedProofs.push({ from, to });
    }
    entry.inputInvalidation += 1;
    for (const time of times) {
      if (entry.rows.delete(time)) this.bars -= 1;
      entry.rowVersions.delete(time);
      entry.serverRowVersions.delete(time);
    }
    entry.times = entry.times.filter(time => !times.has(time));
    entry.proofs = retainedProofs.slice(-128);
  }

  private remove(entry: Entry): void {
    this.bars -= entry.rows.size;
    this.entries.delete(entry.key);
    for (const token of entry.reads) this.reads.delete(token);
    entry.reads.clear(); entry.mutations.clear(); entry.leases.clear();
  }
}
