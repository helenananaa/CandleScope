import { act, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { normalizeChartAccountOverlay } from "../chart-workspace/chartAccountOverlaySettings.js";
import ChartAccountOverlayMenu from "./ChartAccountOverlayMenu.js";
import { tradingAccountDataPool } from "./tradingAccountDataPool.js";
import { tradingAccountsStore } from "./tradingAccountsStore.js";
import { useTradingChartOverlay, type TradingChartOverlay } from "./useTradingChartOverlay.js";
import type { AccountSummary, JournalEntry, Trade, TradingAccount } from "./tradingTypes.js";

const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };
const start = 1_800_000_000;
const instrument = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" };
const account = (id: string): TradingAccount => ({ id, kind: "manual", name: `Account ${id}`, quoteCurrency: "USDT",
  settings: {}, createdAtMs: start * 1000, archived: false, capabilities: { placeOrders: false, manualFills: true, sync: false } });
const trade = (id: string): Trade => ({ id: `${id}-trade`, accountId: id, ...instrument, direction: "long", status: "open",
  openedAtMs: (start + 600) * 1000, closedAtMs: null, openQty: "1", maxQty: "1", entryQty: "1", exitQty: "0",
  avgEntryPrice: id === "a" ? "105" : "110", avgExitPrice: null, realizedPnl: "0", fees: "0", netPnl: "0",
  markPrice: "112", unrealizedPnl: "7", legs: [{ fillId: `${id}-fill`, side: "buy", role: "open", qty: "1",
    price: id === "a" ? "105" : "110", fee: "0", tsMs: (start + 600) * 1000, liquidity: "manual", orderId: null }] });
const summary = (id: string): AccountSummary => ({ account: account(id), balance: "10000", equity: "10007", unrealizedPnl: "7",
  usedMargin: "105", available: "9902", positions: [trade(id)], workingOrders: [], feeds: [], closedTrades: 0 });
const note = (id: string, suffix: string, time: number): JournalEntry => ({ id: `${id}-${suffix}`, accountId: id,
  ...instrument, kind: "note", tradeId: null, createdAtMs: time * 1000, updatedAtMs: time * 1000, marketTimeMs: null,
  templateId: null, templateVersion: null, tags: [], fields: {}, body: "Chart note", revisionCount: 1,
  stage: "pre", reviewNote: false, fieldTiming: {}, plan: null, snapshots: [] });

const journal = (id: string) => [
  { ...note(id, "visible", start + 1200), tradeId: `${id}-trade` },
  { ...note(id, "hole", start + 1800), marketTimeMs: (start + 1800) * 1000, reviewNote: true,
    snapshots: [{ id: "screenshot", createdAtMs: (start + 2400) * 1000, hasImage: true, state: {} }] },
  note(id, "outside", start - 60),
];

/** Real menu + hook + chart: account pinning must never switch the panel or sibling. */
export async function checkChartAccountOverlays() {
  const originalFetch = window.fetch;
  const requests: { path: string; method: string }[] = [];
  window.fetch = async (input, init) => {
    const path = new URL(input instanceof Request ? input.url : String(input), location.href).pathname;
    const method = init?.method ?? (input instanceof Request ? input.method : "GET");
    requests.push({ path, method });
    assert(method === "GET", `overlay attempted a write: ${method} ${path}`);
    let data: unknown;
    if (path.endsWith("/trading/accounts")) data = { accounts: [account("a"), account("b"), account("broken")], kinds: ["manual"], plannedKinds: [] };
    else {
      const match = path.match(/\/trading\/accounts\/([^/]+)\/(summary|trades|journal|events)$/);
      assert(match, `unexpected read: ${path}`);
      const [, id, endpoint] = match!;
      if (id === "broken") return Response.json({ detail: "Account source unavailable" }, { status: 503 });
      if (endpoint === "events") {
        const epoch = "a".repeat(32);
        const event = { schema: "candlescope.trading-account-state/1", type: "snapshot", replacement: true,
          identity: { accountId: id, ledgerEpoch: epoch }, connectionEpoch: "b".repeat(32), sequence: 1,
          state: { cursor: { epoch, sequence: 1 }, summary: summary(id!), trades: [trade(id!)],
            entries: journal(id!), journalError: null } };
        return new Response(new ReadableStream({ start(controller) {
          controller.enqueue(new TextEncoder().encode(JSON.stringify(event) + "\n"));
          init?.signal?.addEventListener("abort", () => controller.close(), { once: true });
        } }), { headers: { "content-type": "application/x-ndjson" } });
      }
      data = endpoint === "summary" ? summary(id!) : endpoint === "trades" ? { trades: [trade(id!)] }
        : { entries: journal(id!) };
    }
    return Response.json(data);
  };
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-account-overlays";
  style.textContent = ".qa-account-overlays{display:flex;width:1200px;height:400px}.qa-account-overlays section{width:600px;display:flex;flex-direction:column}.qa-account-overlays .chart-area{position:relative;flex:1;min-width:0}.qa-account-overlays .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host), overlays = new Map<string, TradingChartOverlay>();
  const store = new SeriesWindowStore({ seriesKey: "account-overlays" });
  const rows: KlineBar[] = Array.from({ length: 100 }, (_, i) => ({ time: (start + i * 60) as KlineBar["time"],
    open: 100 + i / 10, high: 102 + i / 10, low: 99 + i / 10, close: 101 + i / 10, volume: 10 }));
  store.replace(rows.filter((_, i) => i !== 30));
  function Cell({ id }: { id: string }) {
    const [settings, setSettings] = useState(() => normalizeChartAccountOverlay(undefined));
    const overlay = useTradingChartOverlay({ enabled: true, settings, ...instrument, interval: "1m", seriesStore: store,
      upColor: "#00aa00", downColor: "#aa0000", themeKey: "dark" });
    useLayoutEffect(() => { overlays.set(id, overlay); return () => { overlays.delete(id); }; }, [id, overlay]);
    return <section data-cell={id}><ChartAccountOverlayMenu cellId={id} settings={settings} error={overlay.error} onChange={setSettings} />
      <SingleChartPanes seriesStore={store} symbol="BTCUSDT" interval="1m" datasetKey="account-overlays" theme="dark"
        customBg="" upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false}
        externalMarkerSource={overlay.markerSource} externalPriceLineSource={overlay.priceLineSource} />
    </section>;
  }
  const waitFor = async (check: () => boolean, message: string) => {
    for (let i = 0; i < 100; i++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
      if (check()) return;
    }
    throw new Error(message);
  };
  const markers = (id: string) => overlays.get(id)!.markerSource.getSnapshot().markers;
  const lines = (id: string) => overlays.get(id)!.priceLineSource.getSnapshot().lines;
  const openLeft = async () => { await act(async () => { (host.querySelector('[data-cell="cell-1"] button') as HTMLButtonElement).click(); }); };
  const choose = async (id: string, field = 0) => { await act(async () => {
    const select = document.querySelectorAll<HTMLSelectElement>(".chart-account-overlay-menu select")[field]!;
    select.value = id; select.dispatchEvent(new Event("change", { bubbles: true }));
  }); };
  const toggle = async (index: number) => { await act(async () => {
    (document.querySelectorAll('.chart-account-overlay-menu input[type="checkbox"]')[index] as HTMLInputElement).click();
  }); };
  try {
    await act(async () => root.render(<><Cell key="left" id="cell-1" /><Cell key="right" id="cell-2" /></>));
    await waitFor(() => lines("cell-1")[0]?.id === "trading:entry:a-trade" && markers("cell-2").length === 1, "default panel account did not reach both actual charts");
    assert(host.querySelectorAll("canvas").length >= 4, "real chart surfaces were not mounted");
    assert(requests.filter(r => r.path.endsWith("/a/events")).length === 1, "panel and charts opened duplicate account streams");
    for (const endpoint of ["summary", "trades", "journal"]) assert(requests.filter(r => r.path.endsWith(`/a/${endpoint}`)).length === 0, `unexpected account ${endpoint} polling`);
    await openLeft(); await choose("b");
    await waitFor(() => lines("cell-1")[0]?.id === "trading:entry:b-trade", "pinned account did not replace prior position");
    assert(tradingAccountsStore.getSnapshot().selected?.id === "a" && lines("cell-2")[0]?.id === "trading:entry:a-trade", "pinning a chart changed panel or sibling");
    assert(markers("cell-1").every(marker => marker.text?.includes("110")), "prior account fill remained after switch");
    await toggle(2);
    assert(markers("cell-1").length === 2 && markers("cell-2").length === 1, "note visibility leaked to sibling or admitted an unloaded bar");
    await act(async () => { store.applyRange([rows[30]!]); });
    await waitFor(() => markers("cell-1").length === 3, "filling an axis hole did not reveal its correctly anchored note");
    await choose("screenshots", 2);
    assert(markers("cell-1").some(marker => marker.id.endsWith(":b-hole"))
      && !markers("cell-1").some(marker => marker.id.endsWith(":b-visible")), "screenshot filter did not use the pinned account images");
    await choose("original", 1);
    assert(markers("cell-1").length === 1 && markers("cell-2").length === 1, "combined note filters changed fills or sibling");
    await choose("linked", 2);
    assert(markers("cell-1").some(marker => marker.id.endsWith(":b-visible")), "linked original was not shown");
    await choose("all", 1); await choose("all", 2);
    await toggle(0); await toggle(1);
    assert(markers("cell-1").length === 2 && lines("cell-1").length === 0, "trade and position switches did not leave notes independent");
    await toggle(0); await toggle(1);
    await act(async () => tradingAccountsStore.select("b"));
    await waitFor(() => lines("cell-2")[0]?.id === "trading:entry:b-trade", "follow-panel sibling did not follow new selection");
    await act(async () => tradingAccountsStore.select("a"));
    await waitFor(() => lines("cell-2")[0]?.id === "trading:entry:a-trade", "panel selection did not return");
    assert(lines("cell-1")[0]?.id === "trading:entry:b-trade", "pinned chart followed panel unexpectedly");
    await choose("broken");
    await waitFor(() => !!document.querySelector('.chart-account-overlay-menu [role="status"]'), "account read failure was not visible");
    assert(markers("cell-1").length === 0 && lines("cell-1").length === 0 && lines("cell-2").length === 1, "failed source retained prior account overlays or cleared sibling");
    await choose("b");
    await waitFor(() => lines("cell-1").length === 1, "account source could not recover by selection");
    await act(async () => root.render(<><Cell key="right" id="cell-2" /></>));
    assert(tradingAccountDataPool.account("b").getSnapshot().summary === null, "closed chart retained unused account data");
    assert(tradingAccountDataPool.account("a").getSnapshot().summary?.account.id === "a", "closing pinned chart released sibling account");
    await act(async () => root.unmount());
    assert(tradingAccountDataPool.account("a").getSnapshot().summary === null, "last chart retained account data");
    return { name: "real chart account pinning, visibility, note holes, source errors and release", status: "PASS", requests };
  } finally { await act(async () => root.unmount()); window.fetch = originalFetch; host.remove(); style.remove(); }
}
