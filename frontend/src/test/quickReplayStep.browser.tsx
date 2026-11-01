import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import QuickReplayOverlay from "../features/trading-accounts/QuickReplayOverlay.js";
import { MarketDataWorkspaceContext, type MarketDataWorkspaceResources } from "../features/market-data/marketDataWorkspaceContext.js";
import type { MarketDataManager } from "../features/market-data/manager/marketDataManager.js";
import type { KlineFetchResult } from "../features/market-data/klineContracts.js";
import type { Trade } from "../features/trading-accounts/tradingTypes.js";
import { epochSeconds, partialMock, structuralMock } from "./testHelpers.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(requestAnimationFrame); };
const entry = Math.floor(1_700_000_000 / 3600) * 3600;

export async function checkQuickReplayStep() {
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  let resolveMinute: ((response: KlineFetchResult) => void) | undefined;
  const response = (step: number, start: number, end: number): KlineFetchResult => partialMock<KlineFetchResult>({
    data: Array.from({ length: Math.floor((end - start) / step) + 1 }, (_, i) => ({
      time: epochSeconds(start + i * step), open: 100, high: step === 300 ? 999 : 102,
      low: 99, close: step === 300 ? 998 : 101, volume: 1, is_closed: true,
    })), complete: true, all_rows_final: true, history_state: "ready",
  });
  let minuteRange: [number, number] | undefined;
  const manager = partialMock<MarketDataManager>({
    read: () => partialMock<ReturnType<MarketDataManager["read"]>>({ complete: false }),
    fetchKlinesRange: async (_symbol, interval, start, end) => {
      if (interval === "1m") { minuteRange = [start, end]; return new Promise<KlineFetchResult>((resolve) => { resolveMinute = resolve; }); }
      return response(interval === "5m" ? 300 : 3600, start, end);
    },
  });
  const trade: Trade = { id: "step-test", accountId: "qa", exchange: "binance", marketType: "spot", symbol: "BTCUSDT",
    direction: "long", status: "closed", openedAtMs: entry * 1000, closedAtMs: (entry + 3600) * 1000,
    openQty: "0", maxQty: "1", entryQty: "1", exitQty: "1", avgEntryPrice: "100", avgExitPrice: "101",
    realizedPnl: "1", fees: "0", netPnl: "1", markPrice: null, unrealizedPnl: null, legs: [],
  };
  const request = { accountId: "qa", trade, interval: "1h", api: {
    trade: async () => ({ ...trade, entries: [], linkSuggestions: [] }),
    createEntry: async () => { throw new Error("No note writes expected"); },
  } };
  // Read the actual rendered surface's input, without changing component state.
  function renderedBars(): Array<{ time: number; high: number }> {
    const element = host.firstElementChild;
    assert(element, "missing overlay");
    const key = Object.keys(element).find((k) => k.startsWith("__reactFiber$"));
    assert(key, "missing React surface");
    type Fiber = { return?: Fiber; child?: Fiber; sibling?: Fiber; memoizedProps?: { datasetKey?: string; seriesStore?: { snapshot(): Array<{ time: number; high: number }> } } };
    let fiber = structuralMock<Record<string, Fiber>>(element)[key]!;
    while (fiber.return) fiber = fiber.return;
    function find(node?: Fiber): Array<{ time: number; high: number }> | undefined {
      if (!node) return undefined;
      if (node.memoizedProps?.datasetKey?.startsWith("quick-replay:") && node.memoizedProps.seriesStore) return node.memoizedProps.seriesStore.snapshot();
      return find(node.child) ?? find(node.sibling);
    }
    const bars = find(fiber); assert(bars, "missing replay store"); return bars;
  }
  function select(step: string) {
    const input = host.querySelector(".quick-replay-step select"); assert(input instanceof HTMLSelectElement, "step input missing");
    flushSync(() => { input.value = step; input.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  try {
    flushSync(() => root.render(<MarketDataWorkspaceContext.Provider value={partialMock<MarketDataWorkspaceResources>({ dataManager: manager })}>
      <QuickReplayOverlay request={request} style={{ theme: "dark", customBg: "", upColor: "green", downColor: "red" }} indicatorDefinitions={[]} onExit={() => undefined} />
    </MarketDataWorkspaceContext.Provider>));
    await settle(); select("5m"); await settle();
    assert(renderedBars().length > 0, "hourly history missing");
    select("1m"); await settle(); assert(resolveMinute && minuteRange, "minute load not pending");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); await settle();
    const pending = renderedBars();
    assert(!pending.some((bar) => bar.time >= entry), `old 5m bar leaked at the 1m cursor: ${JSON.stringify(pending.at(-1))}`);
    resolveMinute(response(60, ...minuteRange)); await settle();
    const resolved = renderedBars();
    assert(resolved.at(-1)?.time === entry && resolved.at(-1)?.high === 102, "current 1m reconstruction missing");
    return { passed: true, scope: "Actual QuickReplayOverlay and chart input with deferred controlled history transport; not installed native acceptance", pendingLast: pending.at(-1), resolvedLast: resolved.at(-1) };
  } finally { flushSync(() => root.unmount()); host.remove(); }
}
