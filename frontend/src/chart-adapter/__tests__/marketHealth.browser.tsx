import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { createChart, CandlestickSeries, type UTCTimestamp } from "lightweight-charts";
import { MarketDataManager } from "../../features/market-data/manager/marketDataManager.js";
import { resolveSharedInitialRows } from "../../features/market-data/manager/initialMarketRows.js";
import { bindSharedWindow } from "../../features/market-data/manager/sharedWindowBinding.js";
import { ForegroundPreloadGate } from "../../features/market-data/foregroundPreloadGate.js";
import { SeriesDataFeed } from "../../features/market-data/feed/seriesDataFeed.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { useChartInitialLoad } from "../../features/market-data/useChartInitialLoad.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions, PendingInitialSeries } from "../../features/market-data/klineContracts.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../../features/market-data/marketDataTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
async function until(predicate: () => boolean, message: string) {
  const deadline = performance.now() + 5000;
  while (!predicate()) { assert(performance.now() < deadline, message); await new Promise(requestAnimationFrame); }
}
const instrument = (symbol: string): MarketSeries => ({ exchange: "binance", marketType: "spot", symbol, interval: "1m" });

class BrowserCell {
  readonly store = new SeriesWindowStore();
  symbol = "BTCUSDT";
  loaded = "";
  rendered = 0;
  select(symbol: string) { this.symbol = symbol; }
  settle(symbol: string) { this.loaded = symbol; }
  published(count: number) { this.rendered = count; }
}

/** Actual initial-load hook, Feed, shared manager, private stores and candle
 * renderer. Only the market transport is controlled; no exchange/user profile. */
export async function checkMarketHealth() {
  const start = Math.floor(Date.now() / 60_000) * 60 - 500 * 60;
  const bars = (symbol: string) => Array.from({ length: 500 }, (_, index): KlineBar => ({
    time: (start + index * 60) as EpochSeconds, open: 10, high: 30, low: 0, close: symbol === "BTCUSDT" ? 10 : 20,
    volume: 1, is_closed: true,
  }));
  const corpus = new Map(["BTCUSDT", "ETHUSDT"].map(symbol => [symbol, bars(symbol)]));
  const revisions = new Map<string, { sequence: number; barrier: number }>();
  const wire = (symbol: string) => ({ protocol: 1, epoch: "browser-server", generation: 1,
    sequence: revisions.get(symbol)?.sequence ?? 0, barrier: revisions.get(symbol)?.barrier ?? 0,
    observed_at_ms: Date.now(), stable: true,
    series: { exchange: "binance", market_type: "spot", symbol, interval: "1m", provider_id: "binance", venue: "binance",
      asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } });
  const calls: string[] = [];
  const result = (symbol: string): KlineFetchResult => ({ data: corpus.get(symbol)!.map(row => ({ ...row })), stream_version: wire(symbol),
    all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
    missing_ranges: [], has_tail_gap: false, truncated: false });
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://owned-market-fixture",
    fetchKlinesHistory: async symbol => { calls.push(`history:${symbol}`); await new Promise(resolve => setTimeout(resolve, 10)); return result(symbol); },
    fetchKlinesBefore: async () => { throw new Error("unexpected before"); },
    fetchKlinesRange: async symbol => { calls.push(`range:${symbol}`); return result(symbol); },
    fetchLatestKlines: async symbol => { calls.push(`latest:${symbol}`); return result(symbol); },
  };
  const physical: Array<{ symbol: string; options: KlineStreamOptions; controller: KlineStreamController; closed: boolean }> = [];
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const manager = new MarketDataManager({ api, foregroundPreloadGate: gate, streams: {
    subscribe: (series, options = {}) => {
      const state = { symbol: series.symbol, options, closed: false, controller: null as unknown as KlineStreamController };
      state.controller = { isOpen: () => !state.closed, readyState: () => state.closed ? 3 : 1,
        send: () => true, sendPing: () => true, updateIntervals() {}, close: () => { state.closed = true; } };
      physical.push(state); queueMicrotask(() => options.onOpen?.(state.controller)); return state.controller;
    }, closeAll() {}, diagnostics: () => ({ physicalStreams: physical.filter(stream => !stream.closed).length }),
  } });
  const emit = (symbol: string, row: KlineBar, type: string, skipBarrier = false) => {
    const previous = revisions.get(symbol) ?? { sequence: 0, barrier: 0 };
    revisions.set(symbol, { sequence: previous.sequence + 1, barrier: previous.barrier + (type === "bar.updated" ? 0 : 1) + (skipBarrier ? 1 : 0) });
    const stream = physical.find(item => item.symbol === symbol && !item.closed)!;
    stream.options.onKline?.({ interval: "1m", tick: row, message: { type: "kline", interval: "1m", data: row,
      event_type: type, stream_version: wire(symbol), previous_open_ms: (row.time - 60) * 1000 } }, stream.controller);
  };
  const cells = new Map<string, BrowserCell>();
  function Cell({ id }: { id: string }) {
    const [symbol, setSymbol] = useState("BTCUSDT"), [status, setStatus] = useState("loading"), [source, setSource] = useState<string | null>(null);
    const canvas = useRef<HTMLDivElement>(null), pending = useRef<PendingInitialSeries | null>(null);
    const model = useMemo(() => new BrowserCell(), []);
    useLayoutEffect(() => { model.select(symbol); cells.set(id, model); }, [id, model, symbol]);
    const bindings = useMemo(() => {
      const merge = (_symbol: string, _interval: string, rows: KlineBar[]) => { model.store.applyRange(rows); };
      const feed = new SeriesDataFeed({ api: manager, streamFactory: manager.subscribe, getActiveSeries: () => instrument(model.symbol),
        commitMergedChartData: merge, commitPatchedChartData: merge });
      const noop = () => undefined;
      return { feed, merge, noop, get: (sym: string) => model.loaded === sym ? model.store.snapshot() : [],
        replace: (_symbol: string, _interval: string, rows: KlineBar[]) => { model.store.replace(rows); },
        resolve: (sym: string) => resolveSharedInitialRows(instrument(sym), model.loaded === sym ? model.store.snapshot() : [], manager.cache, 500) };
    }, [model]);
    const load = useChartInitialLoad({ enabled: true, sharedCacheOwnsHealth: true, exchange: "binance", marketType: "spot",
      nativeIntervalValues: ["1m"], getFromCache: bindings.get, resolveInitialRows: bindings.resolve, seriesDataFeed: bindings.feed,
      activateCachedChartData: () => null, detachActiveChartData: bindings.noop, replaceChartData: bindings.replace,
      markChartDataTransition: bindings.noop, commitMergedChartData: bindings.merge, commitPatchedChartData: bindings.merge,
      pendingInitialHistoryRef: pending, setInitialHistoryPending: bindings.noop, updateLastPrice: bindings.noop,
      setConnectionStatus: setStatus, setLoading: bindings.noop, setError: value => { if (value instanceof Error) throw value; },
      setLoadingMoreLeft: bindings.noop, setHasMoreLeft: bindings.noop, setCrosshairData: bindings.noop, setDataSource: setSource,
    });
    const loadRef = useRef(load); loadRef.current = load;
    useEffect(() => {
      const chart = createChart(canvas.current!, { width: 600, height: 280 });
      const candles = chart.addSeries(CandlestickSeries);
      const paint = () => {
        candles.setData(model.store.snapshot().map(row => ({ time: Number(row.time) as UTCTimestamp,
          open: row.open!, high: row.high!, low: row.low!, close: row.close! })));
        model.published(candles.data().length);
      };
      const unsubscribe = model.store.subscribe(paint); paint();
      return () => { unsubscribe(); chart.remove(); };
    }, [model]);
    useEffect(() => {
      const series = instrument(symbol);
      const stream = manager.subscribe(series, { intervals: ["1m"], onKline: event => { model.store.applyTick(event.tick); } });
      const release = bindSharedWindow(manager.cache, series, { read: () => model.store.snapshot(),
        commit: rows => { model.store.applyRange(rows); } });
      void loadRef.current(symbol, "1m").then(() => { model.settle(symbol); });
      return () => { stream.close(); release(); };
    }, [symbol, model]);
    return <section><h2>{id}: {symbol}</h2><button data-switch={id} onClick={() => setSymbol("ETHUSDT")}>ETHUSDT</button>
      <p>{status} / {source}</p><div ref={canvas} /></section>;
  }
  const host = document.createElement("main"); document.body.append(host); const root = createRoot(host);
  const checks: string[] = [];
  try {
    flushSync(() => root.render(<><Cell id="A" /><Cell id="B" /></>));
    await until(() => [...cells.values()].length === 2 && [...cells.values()].every(cell => cell.loaded === "BTCUSDT" && cell.rendered === 500), "BTC cells did not load");
    const other = JSON.stringify(cells.get("B")!.store.snapshot());
    const warm = manager.warm(instrument("ETHUSDT"), { owner: "next-symbol", reason: "hover", nativeIntervals: ["1m"] });
    assert(await warm.done === "warmed", "ETH did not warm");
    const forming = { ...corpus.get("ETHUSDT")!.at(-1)!, time: (start + 500 * 60) as EpochSeconds, is_closed: false, close: 21 };
    emit("ETHUSDT", forming, "bar.created");
    assert(manager.cache.planHistory(instrument("ETHUSDT"), 500).action === "reuse", "warm ETH is not healthy");
    const requests = calls.length, sockets = physical.length;
    flushSync(() => host.querySelector<HTMLButtonElement>('[data-switch="A"]')!.click());
    await until(() => cells.get("A")?.loaded === "ETHUSDT" && cells.get("A")!.rendered === 501, "ETH switch lost the forming tail or did not publish");
    assert(calls.length === requests && physical.length === sockets, "healthy switch issued IO or resubscribed");
    assert(JSON.stringify(cells.get("B")!.store.snapshot()) === other, "sibling chart changed");
    checks.push("actual initial-load hook switches BTC → warm ETH with zero HTTP/physical subscribe, 500 final bars plus forming tail, sibling unchanged");
    const corrected = { ...corpus.get("ETHUSDT")![10]!, close: 25 };
    corpus.get("ETHUSDT")![10] = corrected;
    emit("ETHUSDT", { ...forming, close: 22 }, "bar.updated", true);
    await until(() => cells.get("A")!.store.snapshot().find(row => row.time === corrected.time)?.close === 25, "critical gap did not read back historical correction");
    assert(calls.length === requests + 1, "gap recovery was not one coalesced history read");
    checks.push("lost critical barrier triggers one bounded read; shared HTTP correction updates the actual candle window");
    flushSync(() => root.unmount());
    manager.closeAll(); gate.dispose();
    assert(physical.every(stream => stream.closed), "owned streams leaked");
    return { passed: true, checks, requests: calls, physicalStreamsCreated: sockets,
      scope: "Production-minified Chromium fixture with real React, initial-load hook and candle renderer; controlled market transport, not installed release acceptance" };
  } finally { if (host.hasChildNodes()) flushSync(() => root.unmount()); host.remove(); manager.closeAll(); gate.dispose(); }
}
