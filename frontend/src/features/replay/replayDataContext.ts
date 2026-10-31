import { createContext, useContext } from "react";
import { MarketDataManagerCore } from "../market-data/manager/marketDataManagerCore.js";

/** Replay composition cannot import or call a live transport through the core. */
export const createReplayMarketDataManager = () => new MarketDataManagerCore();

export const ReplayDataContext = createContext<MarketDataManagerCore | null>(null);
export const useReplayDataManager = () => useContext(ReplayDataContext);
