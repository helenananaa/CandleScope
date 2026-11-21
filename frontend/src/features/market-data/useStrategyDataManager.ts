import { useEffect, useState } from "react";
import { useMarketDataWorkspaceResources } from "./marketDataWorkspaceContext.js";
import { StrategyDataManager } from "./manager/strategyDataManager.js";

/**
 * The strategy data manager a surface runs strategies through (ADR-BACKTEST-015 P2c):
 * an explicit one (a page with its own data manager), else the chart workspace's, else
 * one this component owns for its lifetime (pages without a workspace). Null only
 * until an owned manager is created.
 */
export function useStrategyDataManager(explicit?: StrategyDataManager | null): StrategyDataManager | null {
  const workspace = useMarketDataWorkspaceResources()?.dataManager.strategy ?? null;
  const shared = explicit ?? workspace;
  const [owned, setOwned] = useState<StrategyDataManager | null>(null);
  useEffect(() => {
    if (shared) return;
    // Effect ownership also handles React StrictMode's setup/cleanup/setup.
    const manager = new StrategyDataManager();
    setOwned(manager);
    return () => { manager.dispose(); setOwned(null); };
  }, [shared]);
  return shared ?? owned;
}
