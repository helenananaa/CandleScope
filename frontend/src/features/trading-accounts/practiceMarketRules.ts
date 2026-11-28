import { useEffect, useState } from "react";
import { tradingApi } from "./tradingApi.js";
import type { PracticeMarketRules } from "./tradingTypes.js";

interface MarketRef {
  exchange: string;
  marketType: string;
  symbol: string;
}

/**
 * The rules practice accounts used before markets declared an account model
 * (ADR-DATA-002 D5b): futures are linear contracts, anything else is cash. The
 * backend applies the same fallback, so the ticket agrees with it while the
 * declared rules load.
 */
export function fallbackMarketRules(marketType: string): PracticeMarketRules {
  const contract = marketType === "futures";
  return {
    accountModel: contract ? "crypto_linear" : "cash",
    declared: false,
    leverage: contract,
    shorting: contract,
    hedge: contract,
    opensPositions: true,
  };
}

function marketKey(market: MarketRef): string {
  return `${market.exchange}\u0000${market.marketType}\u0000${market.symbol}`;
}

/** The practice rules of the chart's market, from the backend's view of its catalog row. */
export function usePracticeMarketRules(market: MarketRef): PracticeMarketRules {
  const key = marketKey(market);
  const [loaded, setLoaded] = useState<{ key: string; rules: PracticeMarketRules } | null>(null);
  const { exchange, marketType, symbol } = market;
  useEffect(() => {
    if (!exchange || !marketType || !symbol) return undefined;
    const controller = new AbortController();
    tradingApi.marketRules({ exchange, marketType, symbol }, controller.signal)
      .then((rules) => { if (!controller.signal.aborted) setLoaded({ key, rules }); })
      .catch(() => { /* keep the fallback; the backend still decides when the order is placed */ });
    return () => controller.abort();
  }, [exchange, key, marketType, symbol]);
  return loaded?.key === key ? loaded.rules : fallbackMarketRules(marketType);
}
