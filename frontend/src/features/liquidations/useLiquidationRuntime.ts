import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ChartDataCommitMeta } from "../market-data/useChartDataRuntime.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { MarketHistoryRange } from "../advanced-market-data/marketHistoryCoverage.js";
import type {
  AdvancedMarketConnectionStatus,
  AdvancedMarketIdentity,
} from "../advanced-market-data/advancedMarketDataTypes.js";
import { getLiquidationStreamUrl } from "./liquidationApi.js";
import { loadLiquidationHistoryPages } from "./liquidationHistoryLoader.js";
import {
  LiquidationHistoryRequestCoordinator,
  liquidationHistoryRangeForCandles,
  normalizeLiquidationHistoryRange,
  subtractLiquidationHistoryCoverage,
} from "./liquidationHistoryRequests.js";
import { liquidationStore } from "./liquidationStore.js";
import { LiquidationStreamController } from "./liquidationStreamController.js";
import type {
  LiquidationPositionSide,
  LiquidationQualityMetadata,
  LiquidationRuntimeView,
} from "./liquidationTypes.js";

interface UseLiquidationRuntimeOptions {
  identity: AdvancedMarketIdentity;
  identityKey: string;
  interval: string;
  seriesKey: string;
  dataMeta: ChartDataCommitMeta;
  seriesStore: SeriesWindowStore | null;
  added: boolean;
  visible: boolean;
  supported: boolean;
}

export interface LiquidationRuntimeResult {
  view: LiquidationRuntimeView;
  ensureVisibleRange(range: unknown): boolean;
  retry(): void;
}

interface ActiveContext {
  enabled: boolean;
  identity: AdvancedMarketIdentity;
  identityKey: string;
  interval: string;
  seriesReady: boolean;
}

const LIQUIDATION_SIDES: readonly LiquidationPositionSide[] = ["long", "short"];
const HISTORY_RETRY_DELAY_MS = 30_000;
const MINUTE_MS = 60_000;
const LIVE_HISTORY_RECONCILE_MS = 60_000;
const LIVE_HISTORY_RECONCILE_WINDOW_MS = 5 * MINUTE_MS;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseVisibleRange(value: unknown, interval: string): MarketHistoryRange | null {
  if (!isRecord(value) || !isRecord(value.time)) return null;
  const from = Number(value.time.from);
  const to = Number(value.time.to);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  return liquidationHistoryRangeForCandles(from, to, interval);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useLiquidationRuntime({
  identity,
  identityKey,
  interval,
  seriesKey,
  dataMeta,
  seriesStore,
  added,
  visible,
  supported,
}: UseLiquidationRuntimeOptions): LiquidationRuntimeResult {
  const enabled = added && supported;
  const seriesReady = String(seriesStore?.seriesKey || "") === seriesKey
    && String(dataMeta.seriesKey || "") === seriesKey;
  const [streamToken, setStreamToken] = useState(0);
  const [historyToken, setHistoryToken] = useState(0);
  const [connectionStatus, setConnectionStatus] = useState<AdvancedMarketConnectionStatus>(
    enabled ? "connecting" : "disabled",
  );
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [quality, setQuality] = useState<LiquidationQualityMetadata | null>(null);
  const disposedRef = useRef(false);
  const generationRef = useRef(0);
  const activeRef = useRef<ActiveContext>({
    enabled,
    identity,
    identityKey,
    interval,
    seriesReady,
  });
  const requestCoordinatorRef = useRef(new LiquidationHistoryRequestCoordinator());
  const abortControllersRef = useRef(new Set<AbortController>());
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const automaticRangeRef = useRef<MarketHistoryRange | null>(null);
  const automaticTokenRef = useRef(historyToken);

  useLayoutEffect(() => {
    activeRef.current = { enabled, identity, identityKey, interval, seriesReady };
  }, [enabled, identity, identityKey, interval, seriesReady]);

  useLayoutEffect(() => enabled ? liquidationStore.retain(identity) : undefined, [enabled, identity]);

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current === null) return;
    clearTimeout(retryTimerRef.current);
    retryTimerRef.current = null;
  }, []);

  const invalidateHistory = useCallback(() => {
    generationRef.current += 1;
    for (const controller of abortControllersRef.current) controller.abort();
    abortControllersRef.current = new Set();
    requestCoordinatorRef.current.clear();
    clearRetryTimer();
  }, [clearRetryTimer]);

  const scheduleHistoryRetry = useCallback((expectedGeneration: number) => {
    if (disposedRef.current
      || generationRef.current !== expectedGeneration
      || retryTimerRef.current !== null) return;
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      if (disposedRef.current || generationRef.current !== expectedGeneration) return;
      setHistoryToken((value) => value + 1);
    }, HISTORY_RETRY_DELAY_MS);
  }, []);

  useLayoutEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      invalidateHistory();
    };
  }, [invalidateHistory]);

  const loadHistory = useCallback((rawRange: MarketHistoryRange): boolean => {
    const context = activeRef.current;
    if (!context.enabled || !context.seriesReady) return false;
    const requested = normalizeLiquidationHistoryRange(rawRange);
    if (!requested) return false;
    const expectedGeneration = generationRef.current;
    let scheduled = false;
    for (const side of LIQUIDATION_SIDES) {
      const claims = requestCoordinatorRef.current.claim(
        side,
        requested,
        liquidationStore.historyCoverage(context.identity, side),
      );
      if (claims.length > 0) scheduled = true;
      for (const claim of claims) {
        const uncovered = claim.range;
        const controller = new AbortController();
        abortControllersRef.current.add(controller);
        const isCurrent = (): boolean => {
          const current = activeRef.current;
          return !disposedRef.current
            && !controller.signal.aborted
            && generationRef.current === expectedGeneration
            && current.enabled
            && current.seriesReady
            && current.identityKey === context.identityKey
            && current.interval === context.interval;
        };
        void (async () => {
          try {
            setHistoryError(null);
            await loadLiquidationHistoryPages({
              identity: context.identity,
              side,
              range: uncovered,
              signal: controller.signal,
              isCurrent,
              onPage: (payload, covered) => {
                liquidationStore.mergeHistory(context.identity, payload.data, payload.quality, { side, range: covered });
                setQuality(payload.quality);
              },
            });
          } catch (caught: unknown) {
            if (isAbortError(caught) || !isCurrent()) return;
            console.warn(`Liquidation ${side} history failed:`, caught);
            setHistoryError(caught instanceof Error ? caught.message : String(caught));
            scheduleHistoryRetry(expectedGeneration);
          } finally {
            requestCoordinatorRef.current.release(claim);
            abortControllersRef.current.delete(controller);
          }
        })();
      }
    }
    return scheduled;
  }, [scheduleHistoryRetry]);

  const ensureVisibleRange = useCallback((range: unknown): boolean => {
    const requested = parseVisibleRange(range, activeRef.current.interval);
    return requested ? loadHistory(requested) : false;
  }, [loadHistory]);

  const reloadHistory = useCallback((clearUnconfirmed: boolean) => {
    if (clearUnconfirmed) liquidationStore.clearUnconfirmed(identity);
    liquidationStore.invalidateHistoryCoverage(identity);
    invalidateHistory();
    setHistoryError(null);
    setHistoryToken((value) => value + 1);
  }, [identity, invalidateHistory]);

  const retry = useCallback(() => {
    reloadHistory(true);
    setError(null);
    setConnectionStatus(enabled ? "connecting" : "disabled");
    setStreamToken((value) => value + 1);
  }, [enabled, reloadHistory]);

  useEffect(() => {
    invalidateHistory();
    automaticRangeRef.current = null;
    setHistoryError(null);
    setQuality(null);
  }, [enabled, identityKey, interval, invalidateHistory]);

  useEffect(() => {
    if (!enabled || !seriesReady) return undefined;
    const reconcileTail = () => {
      const cutoffMs = Math.max(0, Date.now() - LIVE_HISTORY_RECONCILE_WINDOW_MS);
      const range = { startMs: cutoffMs, endMs: Date.now() };
      liquidationStore.invalidateHistoryCoverage(identity, range);
      loadHistory(range);
    };
    const timer = window.setInterval(reconcileTail, LIVE_HISTORY_RECONCILE_MS);
    return () => { window.clearInterval(timer); };
  }, [enabled, identity, identityKey, loadHistory, seriesReady]);

  useEffect(() => {
    if (!enabled) {
      setConnectionStatus("disabled");
      setError(null);
      liquidationStore.setConnectionStatus(identity, "disabled");
      return undefined;
    }
    let current = true;
    setConnectionStatus("connecting");
    setError(null);
    liquidationStore.setConnectionStatus(identity, "connecting");
    const stream = new LiquidationStreamController({
      url: getLiquidationStreamUrl(),
      identity,
      onEvents: (events, nextQuality) => {
        if (!current) return;
        liquidationStore.applyEvents(identity, events, nextQuality);
        setQuality(nextQuality);
      },
      onQuality: (nextQuality) => {
        if (!current) return;
        setQuality(nextQuality);
      },
      onStatus: (status) => {
        if (!current) return;
        setConnectionStatus(status);
        if (status === "live") setError(null);
        liquidationStore.setConnectionStatus(identity, status);
      },
      onError: (caught) => {
        if (!current) return;
        console.warn("Liquidation stream error:", caught);
        setError(caught instanceof Error ? caught.message : String(caught));
      },
      onResyncRequired: () => {
        if (current) reloadHistory(true);
      },
      onSubscribed: () => {
        if (current) reloadHistory(false);
      },
    });
    stream.start();
    return () => {
      current = false;
      stream.close();
      liquidationStore.setConnectionStatus(identity, "disconnected");
    };
  }, [enabled, identity, reloadHistory, streamToken]);

  useEffect(() => {
    if (!enabled || !seriesReady) return;
    const firstTime = Number(dataMeta.firstTime);
    const lastTime = Number(dataMeta.lastTime);
    if (!Number.isFinite(firstTime) || !Number.isFinite(lastTime)) return;
    const range = liquidationHistoryRangeForCandles(firstTime, lastTime, interval);
    if (!range) return;
    const previous = automaticRangeRef.current;
    const force = automaticTokenRef.current !== historyToken;
    automaticTokenRef.current = historyToken;
    automaticRangeRef.current = range;
    // Automatic candle growth only requests newly exposed boundaries. Explicit
    // viewport demand may reload evicted history, but a new candle must not
    // continuously repopulate the entire evicted prefix of a large window.
    const additions = previous && !force
      ? subtractLiquidationHistoryCoverage(range, [previous])
      : [range];
    for (const addition of additions) loadHistory(addition);
  }, [
    dataMeta.firstTime,
    dataMeta.lastTime,
    enabled,
    historyToken,
    interval,
    loadHistory,
    seriesReady,
  ]);

  const view = useMemo<LiquidationRuntimeView>(() => ({
    enabled,
    visible,
    identityKey,
    connectionStatus: enabled ? connectionStatus : "disabled",
    error: enabled ? error : null,
    historyError: enabled ? historyError : null,
    quality,
  }), [connectionStatus, enabled, error, historyError, identityKey, quality, visible]);

  return useMemo(() => ({ view, ensureVisibleRange, retry }), [ensureVisibleRange, retry, view]);
}
