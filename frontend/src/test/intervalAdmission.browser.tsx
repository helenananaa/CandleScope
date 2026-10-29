import { useCallback, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useChartSession } from "../features/chart-session/useChartSession.js";
import type { ChartSession, ChartSessionRuntime } from "../features/chart-session/chartSessionTypes.js";
import { USER_PREFS_KEY } from "../features/chart-session/chartSessionModel.js";
import { ChartIntervalUnavailable } from "../app/ChartIntervalUnavailable.js";
import StatusBar from "../app/StatusBar.js";
import { t } from "../i18n/index.js";
import fixture from "../../../backend/tests/fixtures/interval_admission.json";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
async function until(predicate: () => boolean, message: string) {
  const deadline = performance.now() + 5000;
  while (!predicate()) {
    assert(performance.now() < deadline, message);
    await new Promise(requestAnimationFrame);
  }
}
const nextFrame = () => new Promise(requestAnimationFrame);

/** Real React lifecycle and DOM events, with the exchange HTTP boundary controlled. */
export async function checkIntervalAdmission() {
  const originalFetch = window.fetch;
  const priorPrefs = localStorage.getItem(USER_PREFS_KEY);
  const prefs = JSON.stringify({ lastExchange: "minute", lastMarketType: "spot", lastSymbol: "BTCUSDT", lastInterval: "7s" });
  localStorage.setItem(USER_PREFS_KEY, prefs);
  const capabilities = fixture.documents.map(document => document.capability);
  const secondSource = structuredClone(capabilities.find(item => item.exchange === "minute")!);
  secondSource.exchange = "seconds";
  secondSource.native_intervals = ["1s"];
  secondSource.channels[0]!.params.interval = ["1s"];
  const requests: string[] = [];
  window.fetch = async (input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requests.push(url);
    assert(new URL(url, location.href).pathname.endsWith("/exchanges/"), `Unexpected request: ${url}`);
    return new Response(JSON.stringify({ exchanges: [...capabilities, secondSource] }), {
      headers: { "content-type": "application/json" },
    });
  };
  const runtimes: Record<string, ChartSessionRuntime> = {};
  const published: Record<string, ChartSession[]> = {};
  const controllers: Record<string, (session: ChartSession) => void> = {};
  function Cell({ id, initial }: { id: string; initial?: ChartSession }) {
    const [controlled, setControlled] = useState(initial ?? null);
    const onSessionChange = useCallback((session: ChartSession) => {
      (published[id] ??= []).push(session);
      setControlled(session);
    }, [id]);
    const runtime = useChartSession({
      initialSession: initial ?? null,
      controlledSession: controlled,
      onSessionChange,
      visibleRangeScope: `interval-admission:${id}`,
    });
    useLayoutEffect(() => {
      runtimes[id] = runtime;
      controllers[id] = setControlled;
    }, [id, runtime]);
    const { view, status, actions } = runtime;
    return <section data-cell={id}>
      <h2>{id}: {view.exchange} / {view.marketType} / {view.interval}</h2>
      {!status.historyIntervalAvailable && status.exchangeCatalogStatus === "ready" &&
        <ChartIntervalUnavailable session={view} nativeIntervals={view.nativeIntervals} onSelectInterval={actions.selectInterval} />}
      <button data-reject onClick={() => actions.selectInterval("90s")}>90s</button>
      <button data-source onClick={() => actions.selectSymbol({ exchange: "minute", marketType: "spot", symbol: "ETHUSDT" })}>ETHUSDT</button>
      {status.historyIntervalAvailable && !status.realtimeIntervalAvailable && <StatusBar status={{
        historyOnly: true, connectionStatus: "connected", dataSource: "cache", exchangeLabel: view.exchange,
        marketLabel: view.marketType, wsStatus: "live", wsStatusLabel: "live", barCount: 20,
        loadingMoreLeft: false, hasMoreLeft: true, exchangeCatalogStatus: "ready",
      }} />}
    </section>;
  }
  const host = document.createElement("main");
  document.body.append(host);
  const root = createRoot(host);
  const session = (exchange: string, interval: string, marketType = "spot"): ChartSession => ({
    exchange, interval, marketType, symbol: "BTCUSDT",
  });
  const checks: string[] = [];
  try {
    flushSync(() => root.render(<>
      <Cell id="restored" />
      <Cell id="unsaved" initial={session("minute", "89m")} />
      <Cell id="source" initial={session("seconds", "7s")} />
      <Cell id="history" initial={session("history-only", "1m")} />
      <Cell id="market" initial={session("minute", "1m", "missing")} />
    </>));
    await until(() => Object.values(runtimes).length === 5 && Object.values(runtimes).every(r => r.status.exchangeCatalogStatus === "ready"), "capabilities did not load");
    await nextFrame(); await nextFrame();
    assert(runtimes.restored!.view.interval === "7s", "restore silently changed 7s");
    assert(!runtimes.restored!.status.marketDataReady && !runtimes.restored!.status.webSocketReady, "unavailable restore admitted data work");
    assert(localStorage.getItem(USER_PREFS_KEY) === prefs, "capability loading rewrote preferences");
    assert(runtimes.market!.view.marketType === "missing" && !runtimes.market!.status.marketDataReady, "unknown market was silently substituted");
    checks.push("restored interval and market preserved; data and WebSocket gates closed; preferences untouched");
    assert(runtimes.unsaved!.view.interval === "89m" && runtimes.unsaved!.status.marketDataReady && runtimes.unsaved!.status.webSocketReady, "unsaved 89m did not resolve from 1m");
    assert(!runtimes.unsaved!.view.savedCustomIntervals.includes("89m"), "test requires no 89m favorite");
    checks.push("unsaved exact custom interval admitted independently of favorites");
    const select = host.querySelector<HTMLSelectElement>('[data-cell="restored"] select')!;
    assert(select && host.querySelector('[data-cell="restored"] [data-interval-admission="unavailable"]'), "restore rejection has no actionable UI");
    flushSync(() => { select.value = "1m"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    await until(() => runtimes.restored!.view.interval === "1m" && runtimes.restored!.status.marketDataReady, "native alternative did not recover");
    flushSync(() => host.querySelector<HTMLButtonElement>('[data-cell="restored"] [data-reject]')!.click());
    assert(String(runtimes.restored!.view.interval) === "1m" && Boolean(runtimes.restored!.view.intervalNotice), "invalid 90s action was not rejected");
    checks.push("explicit native selection recovers; non-divisible action leaves current interval intact");
    assert(runtimes.source!.status.marketDataReady, "seconds source was not initially available");
    flushSync(() => host.querySelector<HTMLButtonElement>('[data-cell="source"] [data-source]')!.click());
    await until(() => runtimes.source!.view.exchange === "minute", "source selection did not apply");
    await nextFrame();
    assert(runtimes.source!.view.interval === "7s" && !runtimes.source!.status.marketDataReady, "source change silently replaced interval or admitted it");
    assert(runtimes.unsaved!.view.interval === "89m" && runtimes.unsaved!.status.marketDataReady, "other cell changed with active cell");
    checks.push("source switch preserves unavailable period; sibling cell stays ready and unchanged");
    flushSync(() => controllers.restored!(session("minute", "30s")));
    await until(() => runtimes.restored!.view.interval === "30s", "controlled restore was not applied");
    await nextFrame(); await nextFrame();
    assert(!runtimes.restored!.status.marketDataReady && !runtimes.restored!.status.webSocketReady, "controlled unavailable interval admitted data work");
    assert(published.restored!.at(-1)!.interval === "30s", "parent received a substituted interval");
    checks.push("controlled workspace restore publishes the requested identity unchanged");
    assert(runtimes.history!.status.marketDataReady && !runtimes.history!.status.webSocketReady, "history-only gates are wrong");
    assert(host.querySelector('[data-cell="history"]')!.textContent!.includes(t("interval.historyOnly")), "history-only label is absent");
    checks.push("history-only mode remains ready and visibly discloses unavailable realtime");
    assert(requests.length === 1, "concurrent cells did not share the capability read");
    return { passed: true, checks, requests, scope: "Real session hooks and UI with controlled capabilities; not live provider or packaged native acceptance" };
  } finally {
    flushSync(() => root.unmount()); host.remove(); window.fetch = originalFetch;
    if (priorPrefs === null) localStorage.removeItem(USER_PREFS_KEY);
    else localStorage.setItem(USER_PREFS_KEY, priorPrefs);
  }
}
