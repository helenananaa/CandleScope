import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import QuickReplayOverlay from "../features/trading-accounts/QuickReplayOverlay.js";
import { MarketDataWorkspaceContext, type MarketDataWorkspaceResources } from "../features/market-data/marketDataWorkspaceContext.js";
import type { MarketDataManager } from "../features/market-data/manager/marketDataManager.js";
import type { KlineFetchResult } from "../features/market-data/klineContracts.js";
import type { ExternalMarkerSource } from "../chart-adapter/externalMarkerSource.js";
import { normalizeChartAccountOverlay } from "../features/chart-workspace/chartAccountOverlaySettings.js";
import type { JournalEntry, Trade } from "../features/trading-accounts/tradingTypes.js";
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
  const original: JournalEntry = { id: "original", accountId: "qa", exchange: trade.exchange, marketType: trade.marketType, symbol: trade.symbol,
    kind: "quick", tradeId: trade.id, tradeLinkedAtMs: (entry + 90) * 1000, createdAtMs: (entry + 1) * 1000,
    updatedAtMs: (entry + 90) * 1000, marketTimeMs: null, templateId: null, templateVersion: null, tags: [], fields: {},
    body: "original", revisionCount: 1, stage: "open", reviewNote: false, fieldTiming: {}, plan: null,
    snapshots: [{ id: "image", createdAtMs: (entry + 90) * 1000, hasImage: true, state: {} }],
    revisions: [{ revision: 1, savedAtMs: (entry + 1) * 1000, fields: {}, body: "original", historyComplete: true }] };
  const review = { ...original, id: "review", reviewNote: true, marketTimeMs: (entry + 1) * 1000 };
  const request = { accountId: "qa", trade, interval: "1h", api: {
    trade: async () => ({ ...trade, entries: [original, review, { ...original, id: "foreign", accountId: "wrong" }], linkSuggestions: [] }),
    createEntry: async () => { throw new Error("No note writes expected"); },
  } };
  // Read the actual rendered surface's input, without changing component state.
  function renderedSurface() {
    const element = host.firstElementChild;
    assert(element, "missing overlay");
    const key = Object.keys(element).find((k) => k.startsWith("__reactFiber$"));
    assert(key, "missing React surface");
    type Surface = { datasetKey?: string; seriesStore?: { snapshot(): Array<{ time: number; high: number }> }; externalMarkerSource?: ExternalMarkerSource };
    type Fiber = { return?: Fiber; child?: Fiber; sibling?: Fiber; memoizedProps?: Surface };
    let fiber = structuralMock<Record<string, Fiber>>(element)[key]!;
    while (fiber.return) fiber = fiber.return;
    function find(node?: Fiber): Surface | undefined {
      if (!node) return undefined;
      if (node.memoizedProps?.datasetKey?.startsWith("quick-replay:") && node.memoizedProps.seriesStore) return node.memoizedProps;
      return find(node.child) ?? find(node.sibling);
    }
    const surface = find(fiber); assert(surface?.seriesStore && surface.externalMarkerSource, "missing replay chart sources"); return surface;
  }
  const renderedBars = () => renderedSurface().seriesStore!.snapshot();
  const markerIds = () => renderedSurface().externalMarkerSource!.getSnapshot().markers.map(marker => marker.id.split(":").at(-1));
  const move = async (key: string) => { window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true })); await settle(); };
  function select(step: string) {
    const input = host.querySelector(".quick-replay-step select"); assert(input instanceof HTMLSelectElement, "step input missing");
    flushSync(() => { input.value = step; input.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  let lastProgress: { cursorSec: number; step: string } | undefined;
  const recordProgress = (cursorSec: number, step: string) => { lastProgress = { cursorSec, step }; };
  function render(noteSource = "original", active = true, saved?: typeof lastProgress) {
    flushSync(() => root.render(<MarketDataWorkspaceContext.Provider value={partialMock<MarketDataWorkspaceResources>({ dataManager: manager })}>
      <QuickReplayOverlay key={saved ? "restored" : "initial"} request={request} active={active}
        savedCursorSec={saved?.cursorSec} savedStep={saved?.step} onProgress={recordProgress} style={{ theme: "dark", customBg: "", upColor: "green", downColor: "red" }} indicatorDefinitions={[]} accountOverlay={normalizeChartAccountOverlay({ accountId: "other-chart-account", notes: true, noteSource, noteFilter: "screenshots" })} onExit={() => undefined} />
    </MarketDataWorkspaceContext.Provider>));
  }
  try {
    render();
    await settle(); select("5m"); await settle();
    assert(renderedBars().length > 0, "hourly history missing");
    select("1m"); await settle(); assert(resolveMinute && minuteRange, "minute load not pending");
    await move("ArrowRight");
    const pending = renderedBars();
    assert(!pending.some((bar) => bar.time >= entry), `old 5m bar leaked at the 1m cursor: ${JSON.stringify(pending.at(-1))}`);
    resolveMinute(response(60, ...minuteRange)); await settle();
    const resolved = renderedBars();
    assert(resolved.at(-1)?.time === entry && resolved.at(-1)?.high === 102, "current 1m reconstruction missing");
    assert(markerIds().length === 0, "original screenshot leaked before its capture time");
    render("review"); await settle();
    assert(markerIds().join() === "review", "review supplement missing or a foreign account leaked");
    render(); await settle(); await move("ArrowRight");
    assert(markerIds().join() === "original", "captured original screenshot missing");
    await move("ArrowLeft");
    assert(markerIds().length === 0, "rewind retained a future screenshot");
    const saved = lastProgress;
    assert(saved?.step === "1m" && saved.cursorSec === entry + 60, "rewind did not publish exact cursor and step");
    render("original", false); await settle(); await move("ArrowRight");
    assert(lastProgress?.cursorSec === saved.cursorSec, "inactive chart consumed the replay shortcut");
    render("original", true, saved); await settle();
    assert(lastProgress?.step === "1m" && lastProgress.cursorSec === saved.cursorSec, "remount discarded the saved cursor or step");
    assert(markerIds().length === 0, "restore admitted a future screenshot");
    return { passed: true, restored: lastProgress, noteFilters: "original screenshot cutoff, review supplement, trade account, rewind", scope: "Actual QuickReplayOverlay and chart input with deferred controlled history transport; not installed native acceptance", pendingLast: pending.at(-1), resolvedLast: resolved.at(-1) };
  } finally { flushSync(() => root.unmount()); host.remove(); }
}
