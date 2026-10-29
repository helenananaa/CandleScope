import type {
  ExchangeCatalog,
  ExchangeCatalogStatus,
} from "../chart-session/chartSessionTypes.js";
import type {
  IntervalCandidate,
  SubscriptionTier,
  WatchlistGroup,
} from "../watchlist/watchlistTypes.js";

export interface WatchlistSession {
  exchange?: string | null;
  marketType?: string | null;
  symbol?: string | null;
  symbolKey?: string | null;
  interval?: string | null;
}

export interface FullCacheTargetOptions {
  watchlists?: WatchlistGroup[];
  subscriptionTiers?: Record<string, SubscriptionTier>;
  exchangeCatalog?: ExchangeCatalog | null;
  exchangeCatalogStatus?: ExchangeCatalogStatus;
  customIntervalRecords?: IntervalCandidate[];
  currentSession?: WatchlistSession;
}

export interface FullCacheTarget {
  symbolKey: string;
  symbol: string;
  exchange: string;
  marketType: string;
  intervals: string[];
  preloadIntervals: string[];
  nativeIntervals?: string[];
}

export type FullCacheSocketTarget = Omit<FullCacheTarget, "preloadIntervals">;

export interface FullCachePreloadJob extends FullCacheTarget {
  interval: string;
}
