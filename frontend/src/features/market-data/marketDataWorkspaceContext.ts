import type { ChartDataFlowManager } from "./manager/chartDataFlowManager.js";
import type { IndicatorDataManager } from "../indicators/indicatorDataManager.js";
import { createContext, useContext } from "react";
import type { SharedKlineRequestCoordinator } from "./feed/sharedKlineRequestCoordinator.js";
import type { MarketWindowRegistry } from "./window/marketWindowSession.js";
import type { KlineApi } from "./klineContracts.js";
import type { SharedIndicatorStreamCoordinator } from "../indicators/sharedIndicatorStreamCoordinator.js";
import type { ChartWorkScheduler } from "./chartWorkScheduler.js";
import type { MarketDataManager } from "./manager/marketDataManager.js";

export interface KlineStreamCoordinator {
  subscribe: import("./klineContracts.js").KlineStreamFactory;
  diagnostics(): object;
  closeAll(): void;
}

export interface MarketDataWorkspaceResources {
  brokerEnabled: boolean;
  dataManager: MarketDataManager;
  indicatorDataManager: IndicatorDataManager;
  dataFlow: ChartDataFlowManager;
  indicatorStreamCoordinator: SharedIndicatorStreamCoordinator | null;
  klineApi: KlineApi;
  requestCoordinator: SharedKlineRequestCoordinator | null;
  streamCoordinator: KlineStreamCoordinator;
  workScheduler: ChartWorkScheduler | null;
  windowRegistry: MarketWindowRegistry;
}

export const MarketDataWorkspaceContext = createContext<MarketDataWorkspaceResources | null>(null);

export function useMarketDataWorkspaceResources(): MarketDataWorkspaceResources | null {
  return useContext(MarketDataWorkspaceContext);
}
