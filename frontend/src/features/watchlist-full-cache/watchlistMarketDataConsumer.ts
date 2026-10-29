import { canonicalizeIntervalValue } from "../../utils/intervals.js";
import type { MarketDataService } from "../market-data/marketDataService.js";
import type { KlineStreamController } from "../market-data/klineContracts.js";
import type { MarketSeries } from "../market-data/marketDataTypes.js";
import type { MarketWarmLease } from "../market-data/manager/marketWarmQueue.js";
import type { FullCachePreloadJob, FullCacheSocketTarget } from "./watchlistFullCacheTypes.js";
import { eventRangeFromDetail } from "../market-data/rangeRuntime.js";
import { BackfillRecoveryQueue } from "../market-data/feed/backfillRecoveryQueue.js";

type Timer = ReturnType<typeof setTimeout>;
type IntervalStatus = "connecting" | "waiting" | "live" | "stale" | "error";
interface Connection {
  target: FullCacheSocketTarget;
  controller: KlineStreamController | null;
  generation: number;
  attempts: number;
  reconnect: Timer | null;
  heartbeat: Timer | null;
  status: IntervalStatus;
  intervalStatus: Map<string, IntervalStatus>;
}
interface RunningWarm { lease: MarketWarmLease; job: FullCachePreloadJob }
interface Recovery {
  epoch: number;
  eventKeys: Set<string>;
  series: MarketSeries;
  connection: Connection;
  controller: AbortController;
  from?: number;
  to?: number;
}

export interface WatchlistMarketDataConsumerOptions {
  data: MarketDataService;
  limit?: number;
  schedule?: (callback: () => void, delayMs: number) => Timer;
  cancel?: (handle: Timer) => void;
}

const instrumentKey = (target: FullCacheSocketTarget) => [target.exchange.toLowerCase(), target.marketType.toLowerCase(), target.symbol.toUpperCase()].join(":");
const jobKey = (job: FullCachePreloadJob) => `${job.symbolKey}:${canonicalizeIntervalValue(job.interval) || job.interval}`;

/** Watchlist owns demand intent, not candle storage or wire decoding. The
 * injected service shares the chart transport and admits every response. */
export function createWatchlistMarketDataConsumer(options: WatchlistMarketDataConsumerOptions) {
  const { data } = options;
  const schedule = options.schedule ?? ((callback, delay) => setTimeout(callback, delay));
  const cancel = options.cancel ?? clearTimeout;
  const limit = Math.max(1, options.limit ?? 500);
  const connections = new Map<string, Connection>();
  const running = new Map<string, RunningWarm>();
  let desiredJobs = new Map<string, FullCachePreloadJob>();
  const attempted = new Set<string>();
  const recovering = new Set<Recovery>();
  let disposed = false, generation = 0, errors = 0, completedWarm = 0;
  const owner = (key: string) => `watchlist-warm:${key}`;
  const owns = (connection: Connection, captured: number) => !disposed
    && connection.generation === captured && connections.get(instrumentKey(connection.target)) === connection;

  const recovery = new BackfillRecoveryQueue<Recovery>({
    merge: (queued, incoming) => {
      if (queued.series.interval !== incoming.series.interval || queued.connection !== incoming.connection) return false;
      if (queued.from !== undefined && queued.to !== undefined && incoming.from !== undefined && incoming.to !== undefined) {
        queued.from = Math.min(queued.from, incoming.from); queued.to = Math.max(queued.to, incoming.to);
      } else { delete queued.from; delete queued.to; }
      incoming.eventKeys.forEach(key => queued.eventKeys.add(key));
      return true;
    },
    read: async job => {
      if (!owns(job.connection, job.epoch) || job.controller.signal.aborted) return false;
      recovering.add(job);
      try {
        const result = await data.recover(job.series, { limit, signal: job.controller.signal,
          ...(job.from === undefined ? {} : { from: job.from }), ...(job.to === undefined ? {} : { to: job.to }) });
        // A recovery read never converts transport ACK into live freshness.
        return result.complete === true && result.retryable === false;
      } finally { recovering.delete(job); }
    },
    verify: async () => {}, needsVerification: () => false,
    isCurrent: job => owns(job.connection, job.epoch) && !job.controller.signal.aborted,
    cooldown: () => 1_000, onError: error => { if (!(error instanceof DOMException && error.name === "AbortError")) errors += 1; },
  });

  function cancelRecovery(connection: Connection): void {
    for (const job of recovering) if (job.connection === connection) job.controller.abort();
    for (const interval of connection.target.intervals) recovery.cancel(`${instrumentKey(connection.target)}:${interval}`);
  }

  function releaseConnection(connection: Connection): void {
    connection.generation = ++generation;
    if (connection.reconnect) cancel(connection.reconnect);
    if (connection.heartbeat) cancel(connection.heartbeat);
    connection.controller?.close();
    connection.controller = null;
    cancelRecovery(connection);
  }

  function scheduleReconnect(connection: Connection, captured: number): void {
    if (!owns(connection, captured) || connection.reconnect) return;
    connection.status = "stale";
    connection.intervalStatus.forEach((_, interval) => connection.intervalStatus.set(interval, "stale"));
    if (connection.heartbeat) { cancel(connection.heartbeat); connection.heartbeat = null; }
    cancelRecovery(connection);
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(connection.attempts++, 5));
    connection.reconnect = schedule(() => {
      connection.reconnect = null;
      if (!owns(connection, captured)) return;
      connection.controller?.close();
      connect(connection);
    }, delay);
  }

  function heartbeat(connection: Connection, captured: number): void {
    if (!owns(connection, captured)) return;
    connection.controller?.sendPing();
    connection.heartbeat = schedule(() => heartbeat(connection, captured), 15_000);
  }

  function connect(connection: Connection): void {
    if (disposed) return;
    const captured = connection.generation = ++generation;
    connection.status = "connecting";
    connection.intervalStatus = new Map(connection.target.intervals.map(interval => [interval, "connecting"]));
    try { connection.controller = data.subscribe(connection.target, {
      intervals: connection.target.intervals,
      onOpen: () => {
        if (!owns(connection, captured)) return;
        connection.status = "waiting";
        connection.intervalStatus.forEach((_, interval) => connection.intervalStatus.set(interval, "waiting"));
        const wasReconnect = connection.attempts > 0;
        connection.attempts = 0;
        if (connection.heartbeat) cancel(connection.heartbeat);
        heartbeat(connection, captured);
        if (wasReconnect) {
          for (const [key, job] of desiredJobs) if (job.symbolKey === connection.target.symbolKey) attempted.delete(key);
          pump();
        }
      },
      onKline: event => {
        if (!owns(connection, captured)) return;
        const tail = data.read({ ...connection.target, interval: event.interval }, { limit: 1 }).rows.at(-1);
        if (event.message.event_type !== "bar.amended" && event.tick.time === tail?.time) {
          connection.intervalStatus.set(event.interval, "live");
          connection.status = "live";
        }
      },
      onControlMessage: message => {
        if (!owns(connection, captured)) return;
        for (const interval of message.intervals ?? []) {
          if (connection.intervalStatus.has(interval) && connection.intervalStatus.get(interval) !== "live") {
            connection.intervalStatus.set(interval, message.type === "unsubscribed" ? "stale" : "waiting");
          }
        }
        for (const failure of message.failed ?? []) {
          if (connection.intervalStatus.has(failure.interval)) connection.intervalStatus.set(failure.interval, "error");
        }
      },
      onStreamStatus: message => {
        if (!owns(connection, captured) || !message.interval || !connection.intervalStatus.has(message.interval)) return;
        if (["error", "failed", "stale", "reconnecting"].includes(message.status ?? "")) {
          connection.intervalStatus.set(message.interval, "stale");
        }
      },
      onBackfillCompleted: message => {
        if (!owns(connection, captured)) return false;
        const intervals = message.interval ? [message.interval] : connection.target.intervals;
        for (const interval of intervals) {
          if (!connection.target.intervals.includes(interval)) continue;
          const series = { ...connection.target, interval };
          const retained = data.read(series).rows;
          const range = eventRangeFromDetail(message.detail);
          const from = range && retained.length ? Math.max(range.start / 1_000, retained[0]!.time) : undefined;
          const to = range && retained.length ? Math.min(range.end / 1_000, retained.at(-1)!.time) : undefined;
          if (from !== undefined && to !== undefined && from > to) continue;
          recovery.enqueue(`${instrumentKey(connection.target)}:${interval}`, {
            series, connection, epoch: captured, controller: new AbortController(),
            eventKeys: new Set([JSON.stringify([interval, message.detail?.request_id, from, to])]),
            ...(from === undefined ? {} : { from }), ...(to === undefined ? {} : { to }),
          });
        }
        return true;
      },
      onError: () => {
        if (!owns(connection, captured)) return;
        connection.status = "stale";
        connection.intervalStatus.forEach((_, interval) => connection.intervalStatus.set(interval, "stale"));
      },
      onClose: () => scheduleReconnect(connection, captured),
    }); } catch { errors += 1; scheduleReconnect(connection, captured); }
  }

  function pump(): void {
    if (disposed) return;
    for (const [key, job] of desiredJobs) {
      if (running.has(key) || attempted.has(key)) continue;
      attempted.add(key);
      const lease = data.warm(job, { owner: owner(key), reason: "watchlist", limit, nativeIntervals: job.nativeIntervals ?? [] });
      const active: RunningWarm = { lease, job };
      running.set(key, active);
      void lease.done
        .then(outcome => { if (!disposed && outcome === "warmed") completedWarm += 1; else if (outcome === "failed") errors += 1; })
        .finally(() => {
          if (running.get(key) === active) running.delete(key);
        });
    }
  }

  return {
    syncTargets(targets: readonly FullCacheSocketTarget[], enabled = true): void {
      const wanted = new Map((enabled ? targets : []).map(target => [instrumentKey(target), {
        ...target, intervals: [...new Set(target.intervals.map(value => canonicalizeIntervalValue(value) || value))],
      }]));
      for (const [key, connection] of connections) if (!wanted.has(key)) {
        connections.delete(key); releaseConnection(connection);
      }
      if (disposed) return;
      for (const [key, target] of wanted) {
        const current = connections.get(key);
        if (current) {
          for (const interval of current.target.intervals) if (!target.intervals.includes(interval)) {
            current.intervalStatus.delete(interval);
            recovery.cancel(`${key}:${interval}`);
            for (const job of recovering) if (job.connection === current && job.series.interval === interval) job.controller.abort();
          }
          for (const interval of target.intervals) if (!current.intervalStatus.has(interval)) current.intervalStatus.set(interval, "waiting");
          current.target = target; current.controller?.updateIntervals(target.intervals);
        }
        else {
          const connection: Connection = { target, controller: null, generation: 0, attempts: 0,
            reconnect: null, heartbeat: null, status: "connecting", intervalStatus: new Map() };
          connections.set(key, connection); connect(connection);
        }
      }
    },
    syncJobs(jobs: readonly FullCachePreloadJob[], enabled = true): void {
      if (disposed) return;
      desiredJobs = new Map((enabled ? jobs.slice(0, 16) : []).map(job => [jobKey(job), job]));
      for (const key of attempted) if (!desiredJobs.has(key)) attempted.delete(key);
      for (const [key, active] of running) if (!desiredJobs.has(key)) { running.delete(key); active.lease.release(); }
      pump();
    },
    diagnostics: () => ({ streams: [...connections.values()].map(item => ({ symbolKey: item.target.symbolKey,
      intervals: item.target.intervals, status: [...item.intervalStatus.values()].every(status => status === "live") ? "live"
        : [...item.intervalStatus.values()].some(status => status === "error") ? "partial" : item.status === "live" ? "waiting" : item.status,
      intervalStatus: Object.fromEntries(item.intervalStatus) })), activeWarm: running.size,
      desiredWarm: desiredJobs.size, completedWarm, errors }),
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const connection of connections.values()) releaseConnection(connection);
      connections.clear();
      desiredJobs.clear(); attempted.clear();
      for (const active of running.values()) active.lease.release();
    },
  };
}
