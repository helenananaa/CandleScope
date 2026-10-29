import { useEffect, useMemo, useRef } from "react";
import { symbolKey } from "../../utils/symbolKey.js";
import {
  buildFullCachePreloadJobs,
  buildWatchlistFullSocketTargets,
  buildWatchlistFullCacheTargets,
} from "./watchlistFullCachePolicy.js";
import { createWatchlistMarketDataConsumer } from "./watchlistMarketDataConsumer.js";
import type { MarketDataService } from "../market-data/marketDataService.js";
import type {
  FullCacheTarget,
  FullCacheTargetOptions,
} from "./watchlistFullCacheTypes.js";

const MAX_PRELOAD_JOBS = 16;

export interface UseWatchlistFullCacheRuntimeOptions extends FullCacheTargetOptions {
  data: MarketDataService | null;
  enabled?: boolean;
}

export interface WatchlistFullCacheRuntime {
  targets: FullCacheTarget[];
}

export function useWatchlistFullCacheRuntime({
  watchlists = [],
  subscriptionTiers = {},
  exchangeCatalog = null,
  exchangeCatalogStatus = "loading",
  customIntervalRecords = [],
  currentSession = {},
  enabled = true,
  data,
}: UseWatchlistFullCacheRuntimeOptions): WatchlistFullCacheRuntime {
  const consumerRef = useRef<ReturnType<typeof createWatchlistMarketDataConsumer> | null>(null);
  const {
    symbol: currentSymbol,
    exchange: currentExchange,
    marketType: currentMarketType,
    interval: currentInterval,
  } = currentSession;
  const currentSymbolKey = useMemo(
    () => symbolKey(currentSymbol, currentMarketType, currentExchange),
    [currentExchange, currentMarketType, currentSymbol],
  );

  const targets = useMemo(
    () => buildWatchlistFullCacheTargets({
      watchlists,
      subscriptionTiers,
      exchangeCatalog,
      exchangeCatalogStatus,
      customIntervalRecords,
      currentSession: {
        ...(currentExchange === undefined ? {} : { exchange: currentExchange }),
        ...(currentInterval === undefined ? {} : { interval: currentInterval }),
        ...(currentMarketType === undefined ? {} : { marketType: currentMarketType }),
        ...(currentSymbol === undefined ? {} : { symbol: currentSymbol }),
        symbolKey: currentSymbolKey,
      },
    }),
    [
      currentExchange,
      currentInterval,
      currentMarketType,
      currentSymbol,
      currentSymbolKey,
      customIntervalRecords,
      exchangeCatalog,
      exchangeCatalogStatus,
      subscriptionTiers,
      watchlists,
    ],
  );

  const socketTargets = useMemo(
    () => buildWatchlistFullSocketTargets({
      watchlists,
      subscriptionTiers,
      exchangeCatalog,
      exchangeCatalogStatus,
      customIntervalRecords,
      currentSession: {
        ...(currentExchange === undefined ? {} : { exchange: currentExchange }),
        interval: null,
        ...(currentMarketType === undefined ? {} : { marketType: currentMarketType }),
        symbol: null,
        symbolKey: null,
      },
    }),
    [
      currentExchange,
      currentMarketType,
      customIntervalRecords,
      exchangeCatalog,
      exchangeCatalogStatus,
      subscriptionTiers,
      watchlists,
    ],
  );

  useEffect(() => {
    if (!data) return undefined;
    const manager = createWatchlistMarketDataConsumer({
      data,
    });
    consumerRef.current = manager;
    return () => {
      manager.dispose();
      if (consumerRef.current === manager) consumerRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    consumerRef.current?.syncTargets(socketTargets, enabled);
  }, [data, enabled, socketTargets]);

  const preloadJobs = useMemo(
    () => buildFullCachePreloadJobs(targets, {
      currentSymbolKey,
      excludeSeries: {
        symbolKey: currentSymbolKey,
        ...(currentInterval === undefined ? {} : { interval: currentInterval }),
      },
      maxJobs: MAX_PRELOAD_JOBS,
    }),
    [currentInterval, currentSymbolKey, targets],
  );

  useEffect(() => {
    consumerRef.current?.syncJobs(preloadJobs, enabled);
  }, [data, enabled, preloadJobs]);

  return {
    targets,
  };
}
