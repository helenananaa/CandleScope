import { useEffect, useLayoutEffect, useRef } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { markPerfOnce, recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import {
  canonicalizeIntervalValue,
  intervalsSemanticallyEquivalent,
} from "../../utils/intervals.js";
import type { IntervalString } from "../../utils/intervals.js";
import type { ExchangeId, MarketType, SymbolCode } from "../../utils/symbolKey.js";
import type {
  BackfillCompletedMessage,
  CommitChartData,
  KlineStreamControlMessage,
  KlineStreamController,
  PatchCacheTick,
} from "./klineContracts.js";
import { observeMarketWindowVisibility } from "./marketWindowVisibility.js";
import type { KlineBar } from "./marketDataTypes.js";
import { KlineConsumerRecovery } from "./feed/klineConsumerRecovery.js";
import type { SeriesDataFeed } from "./feed/seriesDataFeed.js";
import { planTargetBarRequest } from "./intervalRequestBudget.js";
import type { ChartWorkScheduler } from "./chartWorkScheduler.js";

const WS_RECONNECT_BASE_DELAY = 2_000;
const WS_RECONNECT_MAX_DELAY = 60_000;
const WS_MAX_RECONNECT_ATTEMPTS = 20;
const WS_PING_INTERVAL = 30_000;
export const WS_KLINE_FRESHNESS_MS = 30_000;
const WS_INITIAL_FALLBACK_DELAY = 4_000;
const POLLING_INTERVAL_MS = 1_000;
// This timer only checks whether an exact-range repair is due. The feed keeps
// the network backoff and single-flight ownership, so a short scheduler tick
// removes three-second completion quantization without increasing request rate.
const PENDING_REPAIR_POLL_INTERVAL_MS = 500;
const HELD_WINDOW_GAP_SCAN_INTERVAL_MS = 15_000;
const WS_RECOVERY_COUNT_BACK = 1_500;
export const WS_RECOVERY_SOURCE_ROW_BUDGET = 20_000;

export function planKlineRecoveryCountBack(
  interval: IntervalString,
  nativeIntervalValues: readonly IntervalString[],
  desiredCountBack = WS_RECOVERY_COUNT_BACK,
): number {
  return planTargetBarRequest({
    desiredTargetBars: desiredCountBack,
    interval,
    nativeIntervals: nativeIntervalValues,
    sourceRowBudget: WS_RECOVERY_SOURCE_ROW_BUDGET,
  })?.targetBars ?? desiredCountBack;
}

export type KlineWebSocketStatus =
  | "idle"
  | "connecting"
  | "loading"
  | "live"
  | "fallback"
  | "reconnecting";

export interface KlineStreamAcknowledgementState {
  activeIntervals: IntervalString[];
  rejectedIntervals: IntervalString[];
  lastObservedAt: Record<string, number>;
}

function canonicalIntervals(intervals: readonly IntervalString[] = []): IntervalString[] {
  const canonical: IntervalString[] = [];
  const seen = new Set<IntervalString>();
  intervals.forEach((interval) => {
    const value = canonicalizeIntervalValue(interval) || String(interval || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    canonical.push(value);
  });
  return canonical;
}

export function createKlineStreamAcknowledgementState(): KlineStreamAcknowledgementState {
  return { activeIntervals: [], rejectedIntervals: [], lastObservedAt: {} };
}

export function reduceKlineStreamControlMessage(
  previous: KlineStreamAcknowledgementState,
  message: KlineStreamControlMessage,
): KlineStreamAcknowledgementState {
  const active = new Set(canonicalIntervals(previous.activeIntervals));
  const rejected = new Set(canonicalIntervals(previous.rejectedIntervals));
  const accepted = canonicalIntervals(message.intervals);
  const requested = canonicalIntervals(message.requested_intervals);
  const failed = canonicalIntervals(message.failed?.map((failure) => failure.interval));

  if (message.active_intervals !== undefined) {
    active.clear();
    canonicalIntervals(message.active_intervals).forEach((interval) => active.add(interval));
  } else if (message.type === "subscribed") {
    accepted.forEach((interval) => active.add(interval));
  } else if (message.type === "unsubscribed") {
    accepted.forEach((interval) => active.delete(interval));
  }

  accepted.forEach((interval) => rejected.delete(interval));
  failed.forEach((interval) => {
    active.delete(interval);
    rejected.add(interval);
  });

  if (message.type === "subscribed" && message.requested_intervals !== undefined) {
    requested.forEach((interval) => {
      if (!active.has(interval)) rejected.add(interval);
    });
  }

  return {
    activeIntervals: Array.from(active),
    rejectedIntervals: Array.from(rejected),
    lastObservedAt: Object.fromEntries(Object.entries(previous.lastObservedAt)
      .filter(([interval]) => active.has(interval))),
  };
}

export function acknowledgeKlineStreamInterval(
  previous: KlineStreamAcknowledgementState,
  interval: IntervalString,
  nowMs = Date.now(),
): KlineStreamAcknowledgementState {
  const canonical = canonicalizeIntervalValue(interval) || String(interval || "").trim();
  if (!canonical) return previous;
  const active = new Set(canonicalIntervals(previous.activeIntervals));
  const rejected = new Set(canonicalIntervals(previous.rejectedIntervals));
  active.add(canonical);
  rejected.delete(canonical);
  return {
    activeIntervals: Array.from(active),
    rejectedIntervals: Array.from(rejected),
    lastObservedAt: { ...previous.lastObservedAt, [canonical]: nowMs },
  };
}

export function retainTrackedKlineStreamRejections(
  previous: KlineStreamAcknowledgementState,
  trackedIntervals: readonly IntervalString[],
): KlineStreamAcknowledgementState {
  const tracked = new Set(canonicalIntervals(trackedIntervals));
  return {
    activeIntervals: previous.activeIntervals,
    rejectedIntervals: previous.rejectedIntervals.filter((interval) => tracked.has(interval)),
    lastObservedAt: Object.fromEntries(Object.entries(previous.lastObservedAt)
      .filter(([interval]) => tracked.has(interval))),
  };
}

export function getKlineStreamIntervalStatus(
  state: KlineStreamAcknowledgementState,
  interval: IntervalString,
  nowMs = Date.now(),
): Extract<KlineWebSocketStatus, "connecting" | "loading" | "live" | "fallback"> {
  if (state.activeIntervals.some((candidate) => (
    intervalsSemanticallyEquivalent(candidate, interval)
  ))) {
    const canonical = canonicalizeIntervalValue(interval) || interval;
    const observedAt = state.lastObservedAt[canonical];
    return observedAt !== undefined && nowMs - observedAt >= 0 && nowMs - observedAt < WS_KLINE_FRESHNESS_MS
      ? "live" : "loading";
  }
  if (state.rejectedIntervals.some((candidate) => (
    intervalsSemanticallyEquivalent(candidate, interval)
  ))) return "fallback";
  return "connecting";
}

export interface UseKlineStreamRuntimeOptions {
  enabled: boolean;
  webSocketEnabled: boolean;
  symbol: SymbolCode;
  exchange: ExchangeId;
  marketType: MarketType;
  nativeIntervalValues: readonly IntervalString[];
  trackedIntervals: readonly IntervalString[];
  intervalRef: MutableRefObject<IntervalString>;
  seriesDataFeed: SeriesDataFeed;
  commitPatchedChartData: CommitChartData;
  patchCacheTick: PatchCacheTick;
  getCacheRows(series: {
    exchange: ExchangeId;
    marketType: MarketType;
    symbol: SymbolCode;
    interval: IntervalString;
  }): KlineBar[];
  updateLastPrice(candidate: KlineBar, interval: IntervalString): void;
  updateRealtimePrice(closePrice: number): void;
  handleBackfillCompleted(message: BackfillCompletedMessage): boolean;
  setWsStatus: Dispatch<SetStateAction<KlineWebSocketStatus>>;
  schedulerCellId?: string;
  workScheduler?: ChartWorkScheduler | null;
}

export function useKlineStreamRuntime({
  enabled,
  webSocketEnabled,
  symbol,
  exchange,
  marketType,
  nativeIntervalValues,
  trackedIntervals,
  intervalRef,
  seriesDataFeed,
  commitPatchedChartData,
  patchCacheTick,
  getCacheRows,
  updateLastPrice,
  updateRealtimePrice,
  handleBackfillCompleted,
  setWsStatus,
  schedulerCellId,
  workScheduler,
}: UseKlineStreamRuntimeOptions): void {
  const subscriptionRef = useRef<KlineStreamController | null>(null);
  const trackedIntervalsRef = useRef(trackedIntervals);
  const reconcileTrackedIntervalsRef = useRef<((
    intervals: readonly IntervalString[],
  ) => void) | null>(null);

  useEffect(() => {
    trackedIntervalsRef.current = trackedIntervals;
  }, [trackedIntervals]);

  useLayoutEffect(() => {
    if (!enabled) {
      setWsStatus("idle");
      return undefined;
    }
    let active = true;
    const consumerRecovery = new KlineConsumerRecovery();
    let nextConsumerRecoveryAt = 0;
    let windowVisible = true;
    let suspendedAt: number | null = null;
    const suspendedTails = new Map<string, readonly KlineBar[]>();
    const setTransportStatus: typeof setWsStatus = (status) => setWsStatus((previous) => {
      const next = typeof status === "function" ? status(previous) : status;
      return !windowVisible || consumerRecovery.requiredFor(intervalRef.current) ? "reconnecting" : next;
    });
    let subscription: KlineStreamController | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let pendingRepairInterval: ReturnType<typeof setInterval> | null = null;
    let heldWindowGapScanInterval: ReturnType<typeof setInterval> | null = null;
    let pollingInFlight = false;
    let pendingRepairPollingInFlight = false;
    let reconnectDelay = WS_RECONNECT_BASE_DELAY;
    let reconnectAttempts = 0;
    let acknowledgementState = createKlineStreamAcknowledgementState();

    const stopPing = () => {
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
    };

    const startPing = () => {
      stopPing();
      pingTimer = setInterval(() => {
        subscription?.sendPing();
        // A healthy local socket/ACK does not establish a healthy upstream.
        // Recheck observed data on the existing heartbeat, without treating
        // an inactive market as proof that its connection is disconnected.
        applyAcknowledgedStatus();
      }, WS_PING_INTERVAL);
    };

    const stopPolling = () => {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    };

    const startPolling = () => {
      if (pollInterval) return;
      recordPerfEvent("ws.kline.polling.start", { symbol, marketType, exchange });
      pollInterval = setInterval(async () => {
        if (!active) return;
        if (pollingInFlight) return;
        pollingInFlight = true;
        try {
          const currentIntv = intervalRef.current;
          const result = await seriesDataFeed.getLatest(
            { exchange, marketType, symbol, interval: currentIntv },
            { limit: 2, source: "polling-latest", commit: "patch-active" },
          );
          if (
            !active
            || !intervalsSemanticallyEquivalent(currentIntv, intervalRef.current)
            || result.stale
            || result.active === false
            || !result?.data?.length
          ) return;

          const latestTick = result.data[result.data.length - 1];
          if (latestTick) updateLastPrice(latestTick, currentIntv);
          const acknowledgedStatus = getKlineStreamIntervalStatus(
            acknowledgementState,
            currentIntv,
          );
          setTransportStatus((previous) => {
            if (acknowledgedStatus === "live") return "live";
            if (acknowledgedStatus === "fallback") return "fallback";
            if (acknowledgedStatus === "loading") return "loading";
            return previous === "connecting" || previous === "reconnecting"
              ? previous
              : "fallback";
          });
        } catch (pollErr) {
          console.warn("Polling fallback failed:", pollErr);
        } finally {
          pollingInFlight = false;
        }
      }, POLLING_INTERVAL_MS);
    };

    const applyAcknowledgedStatus = () => {
      if (!webSocketEnabled) {
        startPolling();
        setTransportStatus("fallback");
        return;
      }
      const currentIntv = intervalRef.current;
      const status = getKlineStreamIntervalStatus(acknowledgementState, currentIntv);
      if (status === "live") {
        stopPolling();
        setTransportStatus("live");
        markPerfOnce("ws.kline.live", {
          symbol,
          marketType,
          exchange,
          interval: currentIntv,
          source: "observed-kline",
        });
        return;
      }
      startPolling();
      setTransportStatus(status);
    };

    const recoverConsumer = () => {
      if (!active || !consumerRecovery.required || Date.now() < nextConsumerRecoveryAt) return;
      nextConsumerRecoveryAt = Date.now() + 10_000;
      void consumerRecovery.recover(seriesDataFeed, (candidate) => {
        const status = getKlineStreamIntervalStatus(acknowledgementState, candidate);
        // ACK permits a readback. Only observed current data establishes live.
        return !webSocketEnabled || status === "loading" || status === "live";
      }).then((resumed) => {
        if (!active) return;
        for (const result of resumed) {
          if (intervalsSemanticallyEquivalent(result.series.interval, intervalRef.current)) {
            updateLastPrice(result.latest, result.series.interval);
          }
        }
        setTransportStatus(getKlineStreamIntervalStatus(acknowledgementState, intervalRef.current));
      });
    };

    const reconcileTrackedIntervals = (intervals: readonly IntervalString[]) => {
      acknowledgementState = retainTrackedKlineStreamRejections(
        acknowledgementState,
        intervals,
      );
      applyAcknowledgedStatus();
    };
    reconcileTrackedIntervalsRef.current = reconcileTrackedIntervals;

    const scheduleReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }

      reconnectAttempts += 1;
      if (reconnectAttempts > WS_MAX_RECONNECT_ATTEMPTS) {
        console.warn(`WS: exceeded ${WS_MAX_RECONNECT_ATTEMPTS} reconnect attempts, staying on polling fallback`);
        setTransportStatus("fallback");
        return;
      }

      console.log(`WS: scheduling reconnect #${reconnectAttempts} in ${reconnectDelay}ms`);
      setTransportStatus("reconnecting");
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, reconnectDelay);

      reconnectDelay = Math.min(reconnectDelay * 2, WS_RECONNECT_MAX_DELAY);
    };

    const connect = () => {
      if (!active || !webSocketEnabled) return;
      setTransportStatus("connecting");

      if (subscription) {
        subscription.close();
        subscription = null;
      }

      try {
        subscription = seriesDataFeed.subscribeBars(
          { exchange, marketType, symbol },
          {
            intervals: trackedIntervalsRef.current,
            onOpen: () => {
              if (!active) return;
              markPerfOnce("ws.kline.open", { symbol, marketType, exchange });
              acknowledgementState = createKlineStreamAcknowledgementState();

              const isReconnection = reconnectAttempts > 0;
              reconnectDelay = WS_RECONNECT_BASE_DELAY;
              reconnectAttempts = 0;

              setTransportStatus("connecting");
              startPing();

              if (isReconnection) {
                const currentIntv = intervalRef.current;
                const recoveryCountBack = planKlineRecoveryCountBack(
                  currentIntv,
                  nativeIntervalValues,
                );
                console.log(`[WS-Recovery] Reconnected, reloading recent bars for ${symbol}@${currentIntv}`);
                if (recoveryCountBack <= 0) {
                  console.warn(`[WS-Recovery] Skipped ${currentIntv}; source-history budget exceeded`);
                } else seriesDataFeed.getBars(
                  { exchange, marketType, symbol, interval: currentIntv },
                  { countBack: recoveryCountBack, source: "ws-reconnect-history" },
                )
                  .then((result) => {
                    if (
                      !active
                      || result.stale
                      || result.active === false
                      || !result?.data?.length
                    ) return;
                    const latest = result.data[result.data.length - 1];
                    if (latest) updateLastPrice(latest, currentIntv);
                    void seriesDataFeed.repairVisibleGaps(
                      { exchange, marketType, symbol, interval: currentIntv },
                      result.data,
                      null,
                      { source: "ws-reconnect-gap-planner" },
                    );
                    void seriesDataFeed.pollPendingRepairs(
                      { exchange, marketType, symbol, interval: currentIntv },
                      { force: true },
                    );
                    console.log(`[WS-Recovery] Reloaded ${result.data.length} bars after reconnect`);
                  })
                  .catch((err) => {
                    console.warn("[WS-Recovery] Failed to recover after reconnect:", err);
                  });
              }
            },
            onStreamStatus: (msg) => {
              if (!active) return;
              if (intervalsSemanticallyEquivalent(msg.interval, intervalRef.current)) {
                if (
                  msg.status === "live"
                  && getKlineStreamIntervalStatus(
                    acknowledgementState,
                    intervalRef.current,
                  ) === "live"
                ) {
                  stopPolling();
                  setTransportStatus("live");
                }
                if (msg.status === "reconnecting") {
                  const canonical = canonicalizeIntervalValue(msg.interval || "");
                  if (canonical) delete acknowledgementState.lastObservedAt[canonical];
                  startPolling();
                  setTransportStatus("reconnecting");
                }
              }
            },
            onControlMessage: (message) => {
              if (!active) return;
              const previousIntervals = acknowledgementState.activeIntervals;
              acknowledgementState = reduceKlineStreamControlMessage(
                acknowledgementState,
                message,
              );
              applyAcknowledgedStatus();
              if (acknowledgementState.activeIntervals.some((interval) => !previousIntervals.includes(interval))) {
                nextConsumerRecoveryAt = 0;
              }
              recoverConsumer();
            },
            onBackfillCompleted: (msg) => {
              if (!active) return false;
              return handleBackfillCompleted(msg);
            },
            onKline: ({ interval: msgInterval, tick, message }) => {
              if (!active) return;
              const currentIntv = intervalRef.current;

              // Historical corrections are useful data, but cannot establish
              // that the exchange's current candle is still updating.
              if (message.event_type !== "bar.amended") {
                acknowledgementState = acknowledgeKlineStreamInterval(
                  acknowledgementState,
                  msgInterval,
                );
              }

              if (msgInterval === "1m" && tick.close != null) {
                updateRealtimePrice(tick.close);
              }

              // Fence both the rendered interval and background tracked/base
              // intervals before either store path observes the realtime row.
              seriesDataFeed.recordRealtimeRows(
                { exchange, marketType, symbol, interval: msgInterval },
                [tick],
              );

              const currentIntervalTick = intervalsSemanticallyEquivalent(msgInterval, currentIntv);
              const commitTick = () => {
                if (!active) return;
                if (currentIntervalTick) {
                  applyAcknowledgedStatus();
                  // The active interval shares one window store with the cache;
                  // commitPatchedChartData applies the tick and keeps React
                  // meta (barCount, coverage) in sync. Applying it twice via
                  // patchCacheTick first would turn the commit into a NOOP.
                  markPerfOnce("ws.kline.firstTick", { symbol, marketType, exchange, interval: currentIntv });
                  commitPatchedChartData(symbol, currentIntv, [tick], { source: "kline-ws" });
                  updateLastPrice(tick, currentIntv);
                } else {
                  patchCacheTick(symbol, msgInterval, tick, { marketType, exchange });
                }
              };
              const schedulerKey = `${exchange}|${marketType}|${symbol}|${msgInterval}`;
              if (!workScheduler || !schedulerCellId) {
                commitTick();
              } else if (tick.is_closed === true) {
                // Closed rows and later amendments are authoritative and may
                // also supersede a forming callback queued earlier this frame.
                workScheduler.commitAuthoritative(
                  schedulerCellId,
                  commitTick,
                  { lane: "kline-forming", key: schedulerKey },
                );
              } else {
                workScheduler.enqueueFrame(
                  schedulerCellId,
                  "kline-forming",
                  schedulerKey,
                  commitTick,
                );
              }
            },
            onParseError: (parseErr) => {
              console.error("WS parse failed:", parseErr);
            },
            onError: () => {
              if (!active) return;
              startPolling();
            },
            onClose: () => {
              if (!active) return;
              for (const interval of trackedIntervalsRef.current) {
                const series = { exchange, marketType, symbol, interval };
                consumerRecovery.capture(seriesDataFeed, series, getCacheRows(series));
              }
              nextConsumerRecoveryAt = 0;
              acknowledgementState = createKlineStreamAcknowledgementState();
              stopPing();
              startPolling();
              scheduleReconnect();
            },
          },
        );
        subscriptionRef.current = subscription;
      } catch (connectErr) {
        console.warn("WS initialization failed:", connectErr);
        startPolling();
        scheduleReconnect();
      }
    };

    if (webSocketEnabled) {
      connect();
    } else {
      startPolling();
      setTransportStatus("fallback");
    }

    // Query-triggered repairs are intentionally internal backend work and may
    // not emit a browser completion event. Poll only exact ranges already
    // known to be pending; this never rescans or reloads the whole window.
    pendingRepairInterval = setInterval(() => {
      if (!active || pendingRepairPollingInFlight) return;
      recoverConsumer();
      const currentIntv = intervalRef.current;
      const series = { exchange, marketType, symbol, interval: currentIntv };
      if (seriesDataFeed.pendingRepairCount(series) === 0) return;
      pendingRepairPollingInFlight = true;
      void seriesDataFeed.pollPendingRepairs(series, { maxRequests: 2 })
        .finally(() => {
          pendingRepairPollingInFlight = false;
        });
    }, PENDING_REPAIR_POLL_INTERVAL_MS);

    heldWindowGapScanInterval = setInterval(() => {
      if (!active) return;
      const currentIntv = intervalRef.current;
      const series = { exchange, marketType, symbol, interval: currentIntv };
      const heldRows = getCacheRows(series);
      if (heldRows.length < 2) return;
      void seriesDataFeed.repairVisibleGaps(series, heldRows, null, {
        source: "ws-held-window-gap-scan",
      });
    }, HELD_WINDOW_GAP_SCAN_INTERVAL_MS);

    const stopObservingVisibility = observeMarketWindowVisibility((visible) => {
      if (!active || windowVisible === visible) return;
      windowVisible = visible;
      if (!visible) {
        suspendedAt = Date.now();
        for (const interval of trackedIntervalsRef.current) {
          const series = { exchange, marketType, symbol, interval };
          suspendedTails.set(interval, getCacheRows(series).slice(-1));
        }
        setTransportStatus("reconnecting");
        return;
      }
      // Retain the pre-suspension row even if closed ticks advanced the Store.
      // Restore must catch up without requiring another WS tick or a 15s hide.
      for (const interval of trackedIntervalsRef.current) {
        const series = { exchange, marketType, symbol, interval };
        consumerRecovery.capture(seriesDataFeed, series,
          suspendedTails.get(interval) ?? getCacheRows(series).slice(-1),
          { discoverTail: true });
      }
      recordPerfEvent("ws.kline.visibilityRecovery", {
        symbol, marketType, exchange, hiddenMs: suspendedAt === null ? 0 : Date.now() - suspendedAt,
      });
      suspendedAt = null;
      suspendedTails.clear();
      setTransportStatus("reconnecting");
      nextConsumerRecoveryAt = 0;
      recoverConsumer();
    });

    const initialFallbackTimer = webSocketEnabled ? setTimeout(() => {
      if (
        active
        && !pollInterval
        && getKlineStreamIntervalStatus(
          acknowledgementState,
          intervalRef.current,
        ) !== "live"
      ) {
        startPolling();
      }
    }, WS_INITIAL_FALLBACK_DELAY) : null;

    return () => {
      active = false;
      stopObservingVisibility();
      consumerRecovery.close();
      if (initialFallbackTimer) clearTimeout(initialFallbackTimer);
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      stopPing();
      stopPolling();
      if (pendingRepairInterval) clearInterval(pendingRepairInterval);
      if (heldWindowGapScanInterval) clearInterval(heldWindowGapScanInterval);
      if (subscription) {
        subscription.close();
      }
      if (subscriptionRef.current === subscription) {
        subscriptionRef.current = null;
      }
      if (reconcileTrackedIntervalsRef.current === reconcileTrackedIntervals) {
        reconcileTrackedIntervalsRef.current = null;
      }
    };
  }, [
    commitPatchedChartData,
    enabled,
    exchange,
    getCacheRows,
    handleBackfillCompleted,
    intervalRef,
    marketType,
    nativeIntervalValues,
    patchCacheTick,
    seriesDataFeed,
    setWsStatus,
    symbol,
    updateLastPrice,
    updateRealtimePrice,
    webSocketEnabled,
    schedulerCellId,
    workScheduler,
  ]);

  useEffect(() => {
    reconcileTrackedIntervalsRef.current?.(trackedIntervals);
    subscriptionRef.current?.updateIntervals(trackedIntervals);
  }, [trackedIntervals]);
}
