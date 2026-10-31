import { computeFrontendScript } from "../../features/indicators/frontendScriptRuntime.js";
import { FRONTEND_SCRIPT_STARTER } from "../../features/indicators/frontendScriptContract.js";
import type { IndicatorComputeRequest } from "../../features/indicators/indicatorTypes.js";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useLayoutEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useProvidedBarsIndicatorRuntime } from "../../features/indicators/useProvidedBarsIndicatorRuntime.js";
import { createActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import { epochSeconds } from "../testHelpers.js";
import IndicatorPanel from "../../features/indicators/IndicatorPanel.js";
import type { IndicatorDefinition } from "../../features/indicators/indicatorTypes.js";
import { useIndicatorRuntime } from "../../features/indicators/useIndicatorRuntime.js";
import { MarketWindowRegistry } from "../../features/market-data/window/marketWindowSession.js";
import type { MarketDataRuntime } from "../../features/market-data/useMarketDataRuntime.js";
import { structuralMock } from "../testHelpers.js";
import { klineDependencyKey, registerCacheResource, unregisterCacheResource } from "../../features/cache-gc/cacheRegistry.js";
import { getCachedIndicatorMetadata } from "../../features/indicators/indicatorResultCacheStore.js";
import { buildIndicatorOhlcvSignature } from "../../features/indicators/indicatorComputeRuntime.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const bars = Array.from({ length: 30 }, (_, index) => ({ time: epochSeconds(1_700_000_000 + 60 * index), open: index + 1, high: index + 2, low: index, close: index + 1, volume: 1 }));
const request: IndicatorComputeRequest = { language: "frontend-js", script: FRONTEND_SCRIPT_STARTER, ohlcv: bars, params: { length: 3 } };

export async function checkFrontendScripts() {
  const checks: string[] = [], before = JSON.stringify(bars);
  const result = await computeFrontendScript(request);
  assert(result.ok && result.lines[0]?.data.length === 28, `starter failed: ${JSON.stringify(result)}`);
  assert(result.lines[0]?.data.at(-1)?.value === 29, "SMA differs from independent arithmetic");
  checks.push("real isolated worker computes starter SMA");

  const isolation = await computeFrontendScript({ ...request, script: `
    if (typeof document !== "undefined" || typeof window !== "undefined" || typeof localStorage !== "undefined"
      || typeof fetch !== "undefined" || typeof Worker !== "undefined" || typeof WebSocket !== "undefined"
      || typeof importScripts !== "undefined" || typeof process !== "undefined" || typeof require !== "undefined") throw new Error("unexpected capability");
    let denied = false;
    try { indexedDB.open("should-not-exist"); } catch (_) { denied = true; }
    if (!denied) throw new Error("storage allowed");
    bars[0].close = 999;
    plot("isolated", bars.map(() => 1));
  ` });
  assert(isolation.ok && JSON.stringify(bars) === before, `isolation failed: ${JSON.stringify(isolation)}`);
  checks.push("opaque worker cannot use DOM, Node, storage, network or child workers; input copy preserved");

  for (const script of ['throw new Error("example failure")', 'const = broken', 'plot("bad", bars.map(() => NaN))', 'postMessage({lines: []})']) {
    const error = await computeFrontendScript({ ...request, script });
    assert(error.ok === false && error.lines.length === 0, `failed closed: ${script}`);
  }
  checks.push("runtime, syntax, nonfinite and forged output errors clear plots");

  let beats = 0;
  const heartbeat = setInterval(() => beats++, 20);
  const start = performance.now();
  const timeout = await computeFrontendScript({ ...request, script: "while (true) {}" });
  clearInterval(heartbeat);
  assert(timeout.ok === false && timeout.error?.includes("execution limit") && beats >= 10 && performance.now() - start < 5_000, "infinite loop blocked UI or failed termination");
  checks.push("infinite loop times out while parent event loop remains responsive");

  const first = new AbortController(), second = new AbortController(), queued = new AbortController();
  const tasks = [first, second, queued].map(controller => computeFrontendScript({ ...request, script: "while (true) {}" }, controller.signal)
    .then(() => "unexpected", (error: unknown) => error instanceof Error ? error.name : String(error)));
  queued.abort();
  assert(await tasks[2] === "AbortError", "queued cancellation waited behind running jobs");
  first.abort(); second.abort();
  assert((await Promise.all(tasks)).every(value => value === "AbortError"), "running cancellation did not reject");
  const final = await computeFrontendScript(request);
  assert(final.ok && document.querySelectorAll("iframe").length === 0, "cancelled work leaked owners or prevented next compute");
  checks.push("queued/running cancellation releases both slots and all frames; new work succeeds");
  checks.push(...await checkReactReplayLifecycle());
  checks.push(...await checkLiveWindowTicks());
  return { checks, parentTimerBeats: beats, remainingFrames: document.querySelectorAll("iframe").length };
}

async function checkLiveWindowTicks(): Promise<string[]> {
  const context = { exchange: "fixture", marketType: "spot", symbol: "TEST", interval: "1m", candleUpColor: "#22c55e", candleDownColor: "#ef4444" };
  // Successful live work is acknowledged only when its market dependency is
  // registered. Omitting it creates repeated unacknowledged attempts, which
  // can accidentally refresh a stale signature and conceal the native bug.
  registerCacheResource("chart-data-cache", "frontend-js-live-fixture", { type: "kline", dependencyKey: klineDependencyKey(context), bars: bars.length });
  const owner = new MarketWindowRegistry().createWindow("live-js");
  const selection = owner.prepareSelection("live-js-ticks"); owner.activate(selection);
  owner.transact(selection, () => {
    owner.getOrCreate("live-js-ticks");
    owner.apply("live-js-ticks", { type: "replace", rows: bars });
  });
  const store = owner.get("live-js-ticks")!;
  const replace = (rows: typeof bars) => owner.transact(selection, () => owner.apply("live-js-ticks", { type: "replace", rows }));
  const stableSnapshot = store.snapshot();
  const storage = new Map<string, string>();
  const persistence = createActiveIndicatorPersistence("live-js", {
    getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, value); },
  });
  persistence.save([{ id: "live", language: "frontend-js", script: 'plot("close",bars.map(bar=>bar.close))', visible: true }]);
  let latest: IndicatorRuntime | null = null;
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (input, options) => {
    if (!new URL(String(input), location.href).pathname.startsWith("/api/")) return oldFetch(input, options);
    throw new Error("Live frontend-only fixture must not call a backend");
  };
  // Native ticks keep these identities stable; replacing the metadata object
  // each render would accidentally force a refresh and conceal the defect.
  const marketData = structuralMock<MarketDataRuntime>({ view: {
    bars: store.snapshot(), seriesStore: store, meta: { status: "ready", version: 1 }, wsStatus: "live",
  }, status: { activeChartReady: true, initialHistoryPending: false }, actions: {} });
  function View() {
    const runtime = useIndicatorRuntime({ marketData, autoAddVolume: false, indicatorPersistence: persistence,
      symbol: "TEST", interval: "1m", exchange: "fixture", marketType: "spot", datasetKey: "live", sessionKey: "live" });
    useLayoutEffect(() => { latest = runtime; });
    return <span>{runtime.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value}</span>;
  }
  const value = () => latest?.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value;
  // Production caches identify the exact provided window, including its origin.
  // Observe the same key instead of accidentally checking the pre-#159 key.
  const cacheContext = () => ({ ...context, localInputKey: buildIndicatorOhlcvSignature(store.snapshot()) });
  const tick = (close: number) => owner.transact(selection, () => owner.apply("live-js-ticks", { type: "tick", row: { ...bars.at(-1)!, close, high: close + 1, is_closed: false } }));
  async function until(predicate: () => boolean) {
    for (let i = 0; i < 150; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 20)); }
    throw new Error(`Live stable-window tick failed: ${host.textContent}`);
  }
  try {
    flushSync(() => root.render(<View />));
    await until(() => value() === 30);
    assert(getCachedIndicatorMetadata(latest!.view.activeIndicators[0]!, cacheContext()), "fixture did not establish native-style cache ownership");
    tick(34);
    assert(store.snapshot() === stableSnapshot, "fixture must exercise the real O(1) in-place tail replacement");
    await until(() => value() === 34);
    let intermediate = false;
    for (let i = 0; i < 30; i++) {
      tick(35 + i); await new Promise(resolve => setTimeout(resolve, 20));
      if (Number(value()) > 34 && Number(value()) < 64) intermediate = true;
    }
    await until(() => value() === 64);
    assert(intermediate, "continuous ticks starved browser calculation until the stream stopped");
    flushSync(() => latest!.actions.updateIndicatorScript("live", "while(true) {}", "frontend-js"));
    let feedSequence = 0;
    const feed = setInterval(() => tick(100 + ++feedSequence / 100), 20);
    try {
      await until(() => Boolean(latest?.view.activeIndicators[0]?.error?.includes("execution limit")));
      await new Promise(resolve => setTimeout(resolve, 500));
      assert(document.querySelectorAll("iframe").length === 0, "live ticks continually retried a failed program");
    } finally { clearInterval(feed); }
    const recoveredClose = store.last()!.close;
    flushSync(() => latest!.actions.updateIndicatorScript("live", 'plot("close",bars.map(bar=>bar.close))', "frontend-js"));
    await until(() => value() === recoveredClose);
    flushSync(() => latest!.actions.updateIndicatorScript("live", 'const until=Date.now()+400; while(Date.now()<until) {} plot("close",bars.map(bar=>bar.close));', "frontend-js"));
    await new Promise(resolve => setTimeout(resolve, 100));
    registerCacheResource("chart-data-cache", "frontend-js-live-fixture", { type: "kline", dependencyKey: klineDependencyKey(context), bars: 5 });
    replace(bars.slice(0, 5));
    await until(() => value() === 5);
    assert(latest!.view.activeIndicators[0]?.lines?.every(line => line.data.every(point => point.time <= bars[4]!.time)), "busy sampling retained the replaced source's future rows");
    const hiddenCacheContext = cacheContext();
    const cachedBeforeHide = getCachedIndicatorMetadata(latest!.view.activeIndicators[0]!, hiddenCacheContext)?.contentVersion;
    assert(cachedBeforeHide !== undefined, "replacement window did not establish its own cache identity");
    flushSync(() => latest!.actions.toggleVisibility("live"));
    tick(80);
    await new Promise(resolve => setTimeout(resolve, 500));
    assert(document.querySelectorAll("iframe").length === 0
      && getCachedIndicatorMetadata(latest!.view.activeIndicators[0]!, hiddenCacheContext)?.contentVersion === cachedBeforeHide, "hidden script kept running on ticks");
    flushSync(() => latest!.actions.toggleVisibility("live"));
    await until(() => value() === 80);
    flushSync(() => latest!.actions.updateIndicatorScript("live", 'const until=Date.now()+400; while(Date.now()<until) {} plot("stale-owner",bars.map(bar=>bar.close+1000));', "frontend-js"));
    await until(() => document.querySelectorAll("iframe").length > 0);
    // Deliberately leave the React context unchanged: lifecycle-only fencing
    // cannot observe this same-reader ownership ABA before its next render.
    owner.activate(owner.prepareSelection("other"));
    owner.activate(owner.prepareSelection("live-js-ticks"));
    await until(() => document.querySelectorAll("iframe").length === 0);
    assert(value() !== 1080 && !getCachedIndicatorMetadata(latest!.view.activeIndicators[0]!, cacheContext()),
      "an old owned input published or populated shared cache after selection ABA");
    return ["real live runtime follows stable-identity store ticks and makes progress during a continuous stream",
      "continuous ticks cannot starve timeout; failed program stays idle and corrected source recovers",
      "source replacement fences busy old work immediately and keeps only the new window's timestamps",
      "hidden script stays idle and resumes from the latest source window when shown",
      "owner ABA rejects the delayed result and cache write without a React context change"];
  } finally { flushSync(() => root.unmount()); owner.close(); host.remove(); globalThis.fetch = oldFetch; unregisterCacheResource("chart-data-cache", "frontend-js-live-fixture"); }
}

async function checkReactReplayLifecycle(): Promise<string[]> {
  const storage = new Map<string, string>();
  const persistence = createActiveIndicatorPersistence("frontend-js", {
    getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, value); },
  });
  const source = 'plot("tail", bars.map(() => bars.at(-1).close))';
  persistence.save([{ id: "script", language: "frontend-js", script: source, visible: true }]);
  let latest: IndicatorRuntime | null = null, backendCalls = 0;
  const host = document.createElement("div"); document.body.append(host);
  let root = createRoot(host);
  function View({ count }: { count: number }) {
    const runtime = useProvidedBarsIndicatorRuntime({
      bars: bars.slice(0, count), datasetKey: `fixture-${count}`, exchange: "fixture", marketType: "spot", symbol: "TEST", interval: "1m",
      sourceOrdinal: count, sourceScopeKey: "frozen", visibleThroughSeconds: bars[count - 1]!.time, persistence,
      computeBatch: async () => { backendCalls++; throw new Error("Frontend source reached backend executor"); },
    });
    useLayoutEffect(() => { latest = runtime; });
    return <span>{runtime.view.activeIndicators[0]?.error || runtime.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value}</span>;
  }
  const current = () => { assert(latest, "runtime not mounted"); return latest; };
  async function until(predicate: () => boolean) {
    for (let i = 0; i < 150; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 20)); }
    throw new Error(`React condition did not converge: ${host.textContent}`);
  }
  const last = () => current().view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value;
  try {
    flushSync(() => root.render(<View count={30} />));
    await until(() => last() === 30);
    flushSync(() => current().actions.updateIndicatorScript("script", 'const until=Date.now()+400; while(Date.now()<until) {} plot("old", bars.map(()=>999));', "frontend-js"));
    await new Promise(resolve => setTimeout(resolve, 100));
    flushSync(() => { current().actions.updateIndicatorScript("script", source, "frontend-js"); root.render(<View count={10} />); });
    await until(() => last() === 10);
    await new Promise(resolve => setTimeout(resolve, 500));
    const lines = current().view.activeIndicators[0]?.lines ?? [];
    assert(last() === 10 && lines.every(line => line.data.every(point => point.time <= bars[9]!.time && point.value !== 999)), "obsolete worker republished future input after rewind");
    flushSync(() => current().actions.updateIndicatorScript("script", 'const = broken', "frontend-js"));
    await until(() => Boolean(current().view.activeIndicators[0]?.error));
    assert(current().view.activeIndicators[0]?.lines?.every(line => !line.data.length), "error retained stale plotted data");
    flushSync(() => current().actions.updateIndicatorScript("script", source, "frontend-js"));
    await until(() => last() === 10);
    flushSync(() => root.unmount());
    latest = null;
    root = createRoot(host);
    flushSync(() => root.render(<View count={10} />));
    await until(() => last() === 10);
    assert(backendCalls === 0 && persistence.load()[0]?.script === source, "saved source was lost or sent to backend");
    return ["real React replay rewind cancels stale worker and excludes unrevealed input/output", "syntax error clears old curves; corrected source and remounted persistence restore without backend execution"];
  } finally { flushSync(() => root.unmount()); host.remove(); }
}

/** Real editor/panel, with deterministic failed and successful persistence HTTP responses. */
export async function checkFrontendScriptEditor() {
  const originalFetch = globalThis.fetch, originalAlert = window.alert;
  const alerts: string[] = [], added: IndicatorDefinition[] = [], saved: Record<string, unknown>[] = [];
  let rejectSave = true;
  let finishPreview: (() => Promise<void>) | undefined;
  let previewBars = bars;
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), location.href);
    if (!url.pathname.startsWith("/api/")) return originalFetch(input, options);
    if (url.pathname.endsWith("/custom") && options?.method === "POST") {
      const data = JSON.parse(String(options.body)) as Record<string, unknown>;
      if (rejectSave) return Response.json({ detail: "fixture storage unavailable" }, { status: 503 });
      saved.push(data);
      return Response.json(data);
    }
    if (url.pathname.endsWith("/custom") || url.pathname.endsWith("/presets")) return Response.json([]);
    // Even a failed plugin discovery must leave the independent frontend language usable.
    return Response.json({ detail: "fixture runtime catalog unavailable" }, { status: 503 });
  };
  window.alert = message => { alerts.push(String(message)); };
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  function View() {
    const [active, setActive] = useState<IndicatorDefinition[]>([]);
    const stagePreview = (value: IndicatorDefinition) => {
      const pending = { ...value, visible: true, lines: [], error: null };
      setActive([pending]);
      // Hold publication independently of execution speed. The real worker's
      // result is the only event that can turn the pending preview into success.
      finishPreview = async () => {
        const result = await computeFrontendScript({ ...request, script: pending.script || "", params: pending.params || {}, ohlcv: previewBars });
        setActive([{ ...pending, lines: result.lines, error: result.error || null }]);
      };
    };
    return <IndicatorPanel isOpen onClose={() => {}} activeIndicators={active}
      onAddIndicator={value => { added.push(value); stagePreview(value); }}
      onRemoveIndicator={() => {}} onToggleVisibility={() => {}} onUpdateParams={() => {}}
      onUpdateScript={(id, script, language, securityMode) => {
        const value = active.find(item => item.id === id);
        assert(value, "editor updated a missing preview");
        stagePreview({ ...value, script, ...(language ? { language } : {}), ...(securityMode ? { securityMode } : {}) });
      }} computing={false} />;
  }
  async function until(predicate: () => boolean) {
    for (let i = 0; i < 150; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 20)); }
    throw new Error(`Editor condition did not converge: ${host.textContent?.slice(-1000)}`);
  }
  try {
    flushSync(() => root.render(<View />));
    (host.querySelector(".indicator-tab-create") as HTMLButtonElement).click();
    await until(() => Boolean(host.querySelector<HTMLButtonElement>(".indicator-editor-run")?.disabled === false));
    assert(host.querySelector<HTMLSelectElement>("select")?.value === "frontend-js", "frontend language unavailable after catalog failure");
    (host.querySelector(".indicator-editor-run") as HTMLButtonElement).click();
    await until(() => added.length === 1);
    assert(added[0]?.language === "frontend-js" && added[0]?.script === FRONTEND_SCRIPT_STARTER, "editor did not preview JS starter");
    const consoleText = () => host.querySelector(".indicator-editor-console")?.textContent;
    assert(consoleText() === t("indicator.editor.computingData"), "new preview claimed success before worker output");
    await finishPreview!();
    await until(() => consoleText() === t("indicator.editor.runOk"));
    previewBars = bars.slice(0, 2); // A valid all-null SMA warm-up still finishes.
    finishPreview = undefined;
    (host.querySelector(".indicator-editor-run") as HTMLButtonElement).click();
    await until(() => Boolean(finishPreview));
    assert(consoleText() === t("indicator.editor.computingData"), "updated preview reused old success before worker output");
    await finishPreview!();
    await until(() => consoleText() === t("indicator.editor.runOk"));
    (host.querySelector(".indicator-editor-save") as HTMLButtonElement).click();
    await until(() => alerts.length === 1);
    assert(Boolean(host.querySelector(".indicator-editor")) && added.length === 1 && saved.length === 0, "failed save closed/lost draft or claimed persistence");
    rejectSave = false;
    (host.querySelector(".indicator-editor-save") as HTMLButtonElement).click();
    await until(() => saved.length === 1 && !host.querySelector(".indicator-editor"));
    assert(saved[0]?.language === "frontend-js" && saved[0]?.script === FRONTEND_SCRIPT_STARTER, "retry changed saved source/language");
    return { checks: ["real panel/editor offers frontend JS when plugin catalog fails", "new and updated previews stay pending until worker output; all-null warm-up completes", "preview retains exact starter, failed HTTP save keeps draft open, successful retry preserves source/language"] };
  } finally {
    flushSync(() => root.unmount()); host.remove(); globalThis.fetch = originalFetch; window.alert = originalAlert;
  }
}
