import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { combineChartLayerSources, type ChartLayerSource } from "../../../plugins/pluginChartLayerSource.js";
import { setLocale } from "../../../../i18n/index.js";
import { SeriesWindowStore } from "../../../market-data/window/seriesWindowStore.js";
import { parseRunResult, type RunResult } from "../runResult.js";
import { boundVisibleConnectors, buildStrategyOverlay, fillActions, StrategyOverlaySource, type StrategyOverlayLabels } from "../strategyOverlay.js";
import { overlayRunForNative, shownOverlayRun } from "../useStrategyRunOverlay.js";
import type { StrategyMarkerEvidence } from "../strategyOverlay.js";

function fixture(name: string): RunResult {
  const raw: unknown = JSON.parse(readFileSync(new URL(`../../../../../tests/fixtures/run-result/${name}.run-result.json`, import.meta.url), "utf8"));
  return parseRunResult(raw);
}

const LABELS: StrategyOverlayLabels = {
  actions: { OPEN_LONG: "open long", ADD_LONG: "add long", REDUCE_LONG: "reduce long", CLOSE_LONG: "close long",
    REVERSE_TO_SHORT: "reverse short", OPEN_SHORT: "open short", ADD_SHORT: "add short", REDUCE_SHORT: "reduce short",
    CLOSE_SHORT: "close short", REVERSE_TO_LONG: "reverse long" },
  long: "Long", short: "Short", workingOrder: "Order", rejection: "Rejected",
};

function fill(side: "BUY" | "SELL", qty: string) {
  return { time_ms: 0, bar_time_ms: 0, side, qty, price: "1", fee: null, order_id: null, tag: null, explanation: null };
}

test("fill actions follow the running position through adds, reductions and reversals", () => {
  assert.deepEqual(fillActions([fill("BUY", "1"), fill("BUY", "1"), fill("SELL", "1"), fill("SELL", "3"), fill("BUY", "2")]),
    ["OPEN_LONG", "ADD_LONG", "REDUCE_LONG", "REVERSE_TO_SHORT", "CLOSE_SHORT"]);
  assert.deepEqual(fillActions([fill("SELL", "2"), fill("BUY", "3")]), ["OPEN_SHORT", "REVERSE_TO_LONG"]);
});

test("the host oracle run overlays one marker per fill, a connector per round trip and the open position", () => {
  const result = fixture("host-bar-builtin");
  const overlay = buildStrategyOverlay(result, { labels: LABELS, idPrefix: "run:host:a" });
  assert.equal(overlay.markers.length, result.fills.length);
  assert.deepEqual(overlay.markers[0], { id: "run:host:a:fill:0", time: 660, position: "belowBar", color: "#22c55e",
    shape: "arrowUp", text: "open long 107.0107", size: 1.2 });
  assert.equal(overlay.markers[1]?.text, "close long 99.99");
  const connectors = overlay.connectors;
  assert.equal(connectors.length, result.trades.length);
  assert.equal(overlay.entries.filter((entry) => entry.id.includes(":trade:")).length, 0, "connectors are bounded separately");
  assert.ok(connectors.every((entry) => entry.item.type === "polyline" && entry.item.style === "dashed"));
  const position = overlay.entries.find((entry) => entry.id === "run:host:a:position");
  assert.deepEqual(position?.item, { id: "run:host:a:position", type: "price-line", price: 107.0107, color: "#3b82f6",
    width: 1, style: "dashed", text: "Long 1 @ 107.0107" });
  assert.equal(overlay.entries.filter((entry) => entry.id.includes(":plot:")).length, 0, "host runs have no plots yet");
});

test("native plots become main-chart polylines that break at gaps", () => {
  const result = fixture("native-pine");
  const overlay = buildStrategyOverlay(result, { labels: LABELS, idPrefix: "run:native:b" });
  const plots = overlay.entries.filter((entry) => entry.id.includes(":plot:"));
  assert.equal(plots.length, 2, "two SMA plots, each one continuous segment after its warm-up gap");
  for (const plot of plots) {
    assert.equal(plot.item.type, "polyline");
    if (plot.item.type !== "polyline") continue;
    assert.ok(plot.item.points.length > 2 && plot.item.points.every((point) => Number.isFinite(point.price)));
  }
  assert.equal(overlay.markers.length, result.fills.length);
  const gap = { ...result, plots: [{ id: "p", title: null, kind: "line" as const, pane: "main",
    points: [[0, 1], [60_000, 2], [120_000, null], [180_000, 3], [240_000, 4], [300_000, null], [360_000, 5]] as Array<[number, number | null]> }] };
  const split = buildStrategyOverlay(gap, { labels: LABELS, idPrefix: "g" }).entries.filter((entry) => entry.id.includes(":plot:"));
  assert.deepEqual(split.map((entry) => entry.id), ["g:plot:p:0", "g:plot:p:1"], "a lone point is not drawn as a line");
});

test("the overlay source holds markers back until their bars load and bounds them to the visible range", () => {
  const result = fixture("host-bar-builtin");
  const overlay = buildStrategyOverlay(result, { labels: LABELS, idPrefix: "r" });
  let axis = 1;
  const loaded = new Set<number>([660]);
  const listeners: Array<() => void> = [];
  const series = {
    get axisRevision() { return axis; },
    hasTime: (time: number) => loaded.has(time),
    subscribe: (listener: () => void) => { listeners.push(listener); return () => true; },
  };
  const source = new StrategyOverlaySource();
  let notified = 0;
  source.markers.subscribe(() => { notified += 1; });
  source.setSeries(series as never);
  source.setOverlay(overlay, result.interval);
  assert.deepEqual(source.markers.getSnapshot().markers.map((marker) => marker.time), [660]);
  assert.equal(source.layer.getSnapshot().entries.length, overlay.entries.length + overlay.connectors.length);
  for (const marker of overlay.markers) loaded.add(Number(marker.time));
  listeners.forEach((listener) => listener());
  assert.equal(source.markers.getSnapshot().markers.length, 1, "same axis: nothing to republish");
  axis = 2;
  listeners.forEach((listener) => listener());
  assert.equal(source.markers.getSnapshot().markers.length, overlay.markers.length);
  source.setVisibleRange({ time: { from: 0, to: 600 } });
  assert.ok(source.markers.getSnapshot().markers.length < overlay.markers.length, "far markers are outside the overscan");
  source.setOverlay(null, null);
  assert.deepEqual([source.markers.getSnapshot().markers.length, source.layer.getSnapshot().entries.length], [0, 0]);
  assert.ok(notified >= 4);
  source.dispose();
});

test("combined chart layers keep every source's entries and refresh when any source changes", () => {
  let revision = 1;
  const plugin: ChartLayerSource = {
    getSnapshot: () => ({ entries: [{ id: "plugin", zOrder: "below-series", item: { id: "plugin", type: "price-line", price: 1, color: "#000", width: 1, style: "solid" } }], revision }),
    subscribe: () => () => undefined,
  };
  const strategy = new StrategyOverlaySource();
  strategy.setOverlay(buildStrategyOverlay(fixture("native-pine"), { labels: LABELS, idPrefix: "n" }), "1m");
  const combined = combineChartLayerSources([plugin, null, strategy.layer])!;
  const first = combined.getSnapshot();
  assert.equal(first.entries[0]?.id, "plugin");
  assert.equal(first.entries.length, 1 + strategy.layer.getSnapshot().entries.length);
  assert.ok(strategy.layer.getSnapshot().entries.some((entry) => entry.id.includes(":trade:")), "connectors are drawn");
  assert.equal(combined.getSnapshot(), first, "unchanged sources return the same snapshot");
  revision += 1;
  assert.notEqual(combined.getSnapshot(), first);
  assert.equal(combineChartLayerSources([null, plugin]), plugin);
});

test("only completed native-panel runs become overlay runs", () => {
  assert.equal(overlayRunForNative(null), null);
  assert.equal(overlayRunForNative({ run_id: "a", state: "RUNNING", execution_mode: "NATIVE" }), null);
  assert.equal(overlayRunForNative({ run_id: "a", state: "COMPLETED", execution_mode: "NATIVE" }), null, "no result yet");
  assert.deepEqual(overlayRunForNative({ run_id: "a", state: "COMPLETED", execution_mode: "NATIVE", result: {} }), { family: "native", runId: "a" });
  assert.deepEqual(overlayRunForNative({ run_id: "b", state: "COMPLETED", execution_mode: "CANDLESCOPE", result: {} }), { family: "external", runId: "b" });
});


function withEvidence(): RunResult {
  const result = fixture("host-bar-builtin");
  const explanation = { schema: "TRADE_EXPLANATION_V1" };
  return {
    ...result,
    fills: result.fills.map((item, index) => (index === 0 ? { ...item, explanation } : item)),
    rejections: [
      { time_ms: 900_000, bar_time_ms: 900_000, side: "SELL", reason: "MIN_NOTIONAL", order_id: null, explanation },
      { time_ms: null, bar_time_ms: null, side: null, reason: "INSUFFICIENT_MARGIN", order_id: null, explanation: null },
    ],
  };
}

test("rejections become amber markers and recorded evidence is clickable", () => {
  const overlay = buildStrategyOverlay(withEvidence(), { labels: LABELS, idPrefix: "run:host:x" });
  const rejection = overlay.markers.find((marker) => marker.id === "run:host:x:rejection:0");
  assert.deepEqual(rejection, { id: "run:host:x:rejection:0", time: 900, position: "aboveBar", color: "#f59e0b",
    shape: "square", text: "Rejected" });
  assert.equal(overlay.markers.filter((marker) => marker.id.includes(":rejection:")).length, 1, "unanchored rejections are not drawn");
  assert.deepEqual([...overlay.evidence.keys()], ["run:host:x:fill:0", "run:host:x:rejection:0"]);
  const clicked: StrategyMarkerEvidence[] = [];
  const source = new StrategyOverlaySource((evidence) => clicked.push(evidence));
  source.setOverlay(overlay, "1m", "run:host:x");
  assert.equal(source.markers.activate?.("run:host:x:fill:0"), true);
  assert.equal(source.markers.activate?.("run:host:x:fill:1"), false, "no evidence, nothing to open");
  assert.equal(source.markers.activate?.("run:host:x:rejection:0"), true);
  assert.deepEqual(clicked.map((item) => item.kind), ["FILL", "REJECTION"]);
  assert.equal(new StrategyOverlaySource().markers.activate?.("run:host:x:fill:0"), false, "no handler, not claimed");
});

test("the reviewed trade is highlighted on top of the run's markers, only on loaded bars", () => {
  const loaded = new Set<number>([660, 960]);
  const source = new StrategyOverlaySource();
  source.setSeries({ axisRevision: 1, hasTime: (time: number) => loaded.has(time), subscribe: () => () => true } as never);
  source.setOverlay(buildStrategyOverlay(fixture("host-bar-builtin"), { labels: LABELS, idPrefix: "r" }), "1m", "run:host:r");
  source.setTradeFocus({ id: "trade-1", entryTimeMs: 719_999, exitTimeMs: 959_999, entryPrice: 107, exitPrice: null }, "1m", "Entry", "Exit");
  const focus = source.markers.getSnapshot().markers.filter((marker) => marker.id.startsWith("review:"));
  assert.deepEqual(focus.map((marker) => [marker.id, marker.time, marker.text]),
    [["review:trade-1:entry", 660, "Entry 107"], ["review:trade-1:exit", 900, "Exit"]].filter(([, time]) => loaded.has(time as number)));
  source.setTradeFocus(null, "1m", "Entry", "Exit");
  assert.equal(source.markers.getSnapshot().markers.filter((marker) => marker.id.startsWith("review:")).length, 0);
});

test("a stale host result is cleared by owner without touching a native overlay", () => {
  const source = new StrategyOverlaySource();
  source.setOverlay(buildStrategyOverlay(fixture("native-pine"), { labels: LABELS, idPrefix: "run:native:n" }), "1m", "run:native:n");
  source.clearOwner("run:host:");
  assert.ok(source.layer.getSnapshot().entries.length > 0, "native overlay survives a host STALE");
  source.setOverlay(buildStrategyOverlay(fixture("host-bar-builtin"), { labels: LABELS, idPrefix: "run:host:h" }), "1m", "run:host:h");
  source.clearOwner("run:host:");
  assert.deepEqual([source.markers.getSnapshot().markers.length, source.layer.getSnapshot().entries.length], [0, 0]);
});

test("the dock shows the native run in native mode and the fixed-history result otherwise", () => {
  const native = { family: "native" as const, runId: "n" }, host = { family: "host" as const, runId: "h" };
  assert.equal(shownOverlayRun("NATIVE", native, host), native);
  assert.equal(shownOverlayRun("NATIVE", null, host), null, "an empty native panel never shows the host result");
  assert.equal(shownOverlayRun("CANDLESCOPE", native, host), host);
  assert.equal(shownOverlayRun("CANDLESCOPE", native, null), null);
});


test("connectors are bounded to the visible range and capped, like markers", () => {
  const result = fixture("host-bar-builtin");
  const overlay = buildStrategyOverlay(result, { labels: LABELS, idPrefix: "b" });
  const source = new StrategyOverlaySource();
  source.setOverlay(overlay, "1m", "run:host:b");
  const all = source.layer.getSnapshot().entries.filter((entry) => entry.id.includes(":trade:")).length;
  assert.equal(all, overlay.connectors.length, "no range yet: every connector");
  source.setVisibleRange({ time: { from: 0, to: 300 } });
  const near = source.layer.getSnapshot().entries.filter((entry) => entry.id.includes(":trade:")).length;
  assert.ok(near < all && near > 0, `only round trips near the first minutes (${near} of ${all})`);
  assert.ok(source.layer.getSnapshot().entries.some((entry) => entry.id === "b:position"), "the position line stays");
  const many = Array.from({ length: 30 }, (_, index) => overlay.connectors[index % overlay.connectors.length]!);
  assert.equal(boundVisibleConnectors(many, null, 60, 10).length, 10);
});

test("a forward run is redrawn once per committed revision, reconnects on a new generation and stops with the run", async () => {
  const { followForwardRun } = await import("../useStrategyRunOverlay.js");
  const { StrategyRunStreamError } = await import("../../backtestRunStream.js");
  type Status = Parameters<Parameters<typeof followForwardRun>[0]["watchRun"]>[1] extends ((s: infer S, ...rest: never[]) => void) | undefined ? S : never;
  const status = (state: string, extra: Record<string, unknown> = {}) => ({ run_id: "cs_1", family: "continuous", authority: "HOST",
    clock_policy: "FORWARD", fidelity: "BAR_APPROX", language: null, state, source_state: state, generation: 1, error: null,
    terminal: state === "CANCELLED", result_available: true, ...extra }) as unknown as Status;
  let loads = 0;
  let release: (() => void) | null = null;
  let watches = 0;
  const manager = {
    async loadRunResult() {
      loads += 1;
      if (loads === 1) await new Promise<void>((resolve) => { release = resolve; });
      return { loads } as never;
    },
    async watchRun(_runId: string, onStatus?: (value: Status) => void) {
      watches += 1;
      if (watches === 1) {
        // Three commits while the first read is still in flight coalesce into one more read.
        onStatus?.(status("RUNNING")); onStatus?.(status("RUNNING")); onStatus?.(status("RUNNING"));
        await new Promise((resolve) => setTimeout(resolve, 0));
        (release as (() => void) | null)?.();
        await new Promise((resolve) => setTimeout(resolve, 0));
        throw new StrategyRunStreamError("RUN_IDENTITY_CHANGED", "resumed");
      }
      onStatus?.(status("RUNNING", { result_available: false }));
      return status("CANCELLED");
    },
  };
  const drawn: number[] = [];
  const failures: unknown[] = [];
  await followForwardRun(manager as never, "cs_1", new AbortController().signal,
    (result) => drawn.push((result as unknown as { loads: number }).loads), (failure) => failures.push(failure));
  assert.equal(watches, 2, "a new generation reconnects");
  assert.deepEqual(drawn, [1, 2, 3], "first read, one coalesced read, then the stopped account");
  assert.deepEqual(failures, []);
});

test("a live run's status frames reach the cell with their progress, before each result read", async () => {
  const { followLiveRun } = await import("../useStrategyRunOverlay.js");
  type Status = Parameters<Parameters<typeof followLiveRun>[0]["watchRun"]>[1] extends ((s: infer S, ...rest: never[]) => void) | undefined ? S : never;
  const status = (state: string, sourceState: string, terminal = false) => ({ run_id: "fl_1", family: "follow", authority: "HOST",
    clock_policy: "FOLLOW", fidelity: "BAR_APPROX", language: "python", state, source_state: sourceState, generation: 1, error: null,
    terminal, result_available: !terminal }) as unknown as Status;
  const events: string[] = [];
  const manager = {
    async loadRunResult() { events.push("read"); return {} as never; },
    async watchRun(_runId: string, onStatus?: (value: Status, progress: { sequence: number; created_at_ms: number } | null) => void) {
      onStatus?.(status("RUNNING", "LIVE"), { sequence: 3, created_at_ms: 1_000 });
      onStatus?.(status("BLOCKED", "WAITING_DATA"), { sequence: 3, created_at_ms: 1_000 });
      await new Promise((resolve) => setTimeout(resolve, 0));
      return status("CANCELLED", "STOPPED", true);
    },
  };
  await followLiveRun(manager as never, "follow", "fl_1", new AbortController().signal, () => undefined, () => undefined,
    (value, progress) => events.push(`${value.source_state}@${progress?.created_at_ms ?? "-"}`));
  assert.equal(events[0], "LIVE@1000", "the frame is reported before its result is read");
  assert.deepEqual(events.filter((event) => event !== "read"), ["LIVE@1000", "WAITING_DATA@1000"]);
  assert.ok(events.includes("read"), "each frame with a result still reads it");
});


function noisyPositionResult(price: string): RunResult {
  const result = fixture("host-bar-builtin");
  return {
    ...result,
    fills: [{ ...result.fills[0]!, price, qty: "2" }],
    trades: [],
    open_position: { side: "LONG", qty: "2", avg_price: price },
  };
}

test("fill and position labels round float noise to the chart's price precision", () => {
  setLocale("en");
  const overlay = buildStrategyOverlay(noisyPositionResult("0.9530000000000001"), { labels: LABELS, idPrefix: "n", pricePrecision: 3 });
  assert.equal(overlay.markers[0]?.text, "open long 0.953");
  const position = overlay.entries.find((entry) => entry.id === "n:position");
  assert.equal(position?.item.type === "price-line" ? position.item.text : null, "Long 2 @ 0.953");
});

test("a deferred overlay is rebuilt for the chart's price precision once its bars load", () => {
  setLocale("en");
  const result = noisyPositionResult("1698.270156");
  const source = new StrategyOverlaySource();
  const store = new SeriesWindowStore({ intervalSeconds: 60, seriesKey: "precision" });
  source.setSeries(store);
  source.setOverlay((pricePrecision) => buildStrategyOverlay(result, { labels: LABELS, idPrefix: "n", pricePrecision }), "1m", "run:host:n");
  const positionText = () => {
    const entry = source.layer.getSnapshot().entries.find((item) => item.id === "n:position");
    return entry?.item.type === "price-line" ? entry.item.text : null;
  };
  assert.equal(positionText(), "Long 2 @ 1,698.270156", "before bars load the price keeps its own digits");
  store.replace([{ time: 660, open: 1698.1, high: 1701.25, low: 1695, close: 1698.3 }], { source: "test" });
  assert.equal(positionText(), "Long 2 @ 1,698.27");
  assert.equal(source.markers.getSnapshot().markers[0]?.text, "open long 1,698.27");
  source.dispose();
});
