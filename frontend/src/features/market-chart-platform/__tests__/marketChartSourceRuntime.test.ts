import assert from "node:assert/strict";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import test from "node:test";

import type { ChartSession } from "../../chart-session/chartSessionTypes.js";
import {
  assertExecutableMarketChartSource,
  createFrozenSnapshotSource,
  createLiveReferenceSource,
  createRunResultSource,
} from "../marketChartSourceRuntime.js";
import { MarketChartSourceSlot } from "../marketChartSourceSlot.js";
import { MarketChartSourceEffectGuard } from "../marketChartSourceLifecycle.js";
import { backendSyntheticSourceFor, bindMarketChartSurfaceProps } from "../marketChartSurfaceModel.js";
import { localChartMarketData } from "../../local-data/localChartMarketData.js";
import { buildLocalChartDataMeta } from "../../local-data/useLocalChartRuntime.js";

const session: ChartSession = {
  exchange: "binance",
  marketType: "spot",
  symbol: "BTCUSDT",
  interval: "1h",
};

function frozenSource(sourceId = "frozen:test") {
  return createFrozenSnapshotSource({
    sourceId,
    session,
    datasetId: "dataset-1",
    dataEpoch: "epoch-1",
    snapshotHash: "snapshot-1",
    bars: [
      { time: 1_000, open: 10, high: 12, low: 9, close: 11, volume: 5 },
      { time: 4_600, open: 11, high: 13, low: 10, close: 12, volume: 6 },
    ],
  });
}

test("LIVE_REFERENCE delegates lifecycle and fails closed as execution input", () => {
  const marketData = frozenSource("live-backing").marketData;
  const calls: string[] = [];
  const source = createLiveReferenceSource({
    sourceId: "live:workspace:cell-1",
    session,
    datasetKey: "binance:spot:BTCUSDT:1h",
    marketData,
    onPause: () => calls.push("pause"),
    onResume: () => calls.push("resume"),
    onDispose: () => calls.push("dispose"),
  });

  assert.throws(
    () => assertExecutableMarketChartSource(source),
    /LIVE_REFERENCE_IS_NOT_IMMUTABLE_EXECUTION_INPUT/,
  );
  source.pause();
  source.pause();
  source.resume();
  source.resume();
  source.dispose();
  source.dispose();
  assert.deepEqual(calls, ["pause", "resume", "dispose"]);
  assert.equal(source.lifecycle, "DISPOSED");
  assert.throws(() => source.update({ session, datasetKey: "next", marketData }), /disposed/);
});

test("FROZEN_SNAPSHOT copies bars, stays offline, and survives pause/resume", () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: async () => {
      fetchCalls += 1;
      throw new Error("network access is forbidden");
    },
  });
  const bars = [{ time: 1_000, open: 1, high: 2, low: 0.5, close: 1.5 }];
  try {
    const source = createFrozenSnapshotSource({
      session,
      datasetId: "dataset-offline",
      dataEpoch: "epoch-offline",
      snapshotHash: "hash-offline",
      bars,
    });
    bars[0]!.close = 99;
    assert.equal(source.marketData.view.bars[0]?.close, 1.5);
    assert.equal(source.marketData.status.barCount, 1);
    source.pause();
    assert.equal(source.lifecycle, "PAUSED");
    assert.equal(source.marketData.view.bars[0]?.close, 1.5);
    source.resume();
    assert.equal(source.lifecycle, "ACTIVE");
    assert.deepEqual(assertExecutableMarketChartSource(source), {
      kind: "FROZEN_SNAPSHOT",
      datasetId: "dataset-offline",
      dataEpoch: "epoch-offline",
      snapshotHash: "hash-offline",
    });
    assert.equal(fetchCalls, 0);
  } finally {
    if (originalFetch) Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: originalFetch,
    });
    else Reflect.deleteProperty(globalThis, "fetch");
  }
});

test("RUN_RESULT is isolated from later live-store changes", () => {
  const liveBacking = frozenSource("live-backing");
  const result = createRunResultSource({
    session,
    runId: "run-1",
    configHash: "config-1",
    reportHash: "report-1",
    chartHash: "chart-1",
    bars: liveBacking.marketData.view.bars,
  });

  // Test-only mutation of the separately owned offline backing fixture.
  (liveBacking.marketData.view.seriesStore as SeriesWindowStore).applyTick(
    { time: 4_600, open: 11, high: 99, low: 10, close: 98 },
    { source: "live-test" },
  );
  assert.equal(result.marketData.view.bars.at(-1)?.close, 12);
  assert.deepEqual(assertExecutableMarketChartSource(result), {
    kind: "RUN_RESULT",
    runId: "run-1",
    configHash: "config-1",
    reportHash: "report-1",
    chartHash: "chart-1",
  });
});

test("source slot disposes the old series before switching", () => {
  const first = frozenSource("first");
  const second = frozenSource("second");
  const slot = new MarketChartSourceSlot();

  slot.activate(first);
  slot.activate(second);
  assert.equal(first.lifecycle, "DISPOSED");
  assert.equal(first.marketData.status.barCount, 0);
  assert.equal(first.marketData.view.seriesStore, null);
  assert.equal(slot.source, second);

  slot.dispose();
  assert.equal(second.lifecycle, "DISPOSED");
  assert.equal(slot.source, null);
});

test("StrictMode effect replay preserves a remounted source and real unmount disposes it", () => {
  const queued: Array<() => void> = [];
  const guard = new MarketChartSourceEffectGuard((callback) => queued.push(callback));
  const source = frozenSource("strict-mode");

  const firstCleanup = guard.mount(source);
  firstCleanup();
  const secondCleanup = guard.mount(source);
  queued.shift()?.();
  assert.equal(source.lifecycle, "ACTIVE");
  assert.equal(source.marketData.status.barCount, 2);

  secondCleanup();
  queued.shift()?.();
  assert.equal(source.lifecycle, "DISPOSED");
  assert.equal(source.marketData.status.barCount, 0);
});

test("surface binding takes session, series, status, and paging only from source", () => {
  const source = frozenSource();
  const ownPane = { id: "source-pane", label: "Source", lines: [] };
  const chartPane = { id: "chart-pane", label: "Chart", lines: [] };
  const bound = bindMarketChartSurfaceProps({
    source,
    chartProps: {
      symbol: "WRONG",
      interval: "5m",
      datasetKey: "wrong",
      upColor: "#00ff00",
      downColor: "#ff0000",
      theme: "dark",
      customBg: "#000000",
      seriesStore: null,
      loading: true,
      dataMeta: {
        version: 0,
        status: "loading",
        source: "wrong",
        committedAt: null,
      },
      canLoadMoreLeft: true,
      canRestoreLatestWindow: true,
      subPanes: [chartPane],
    },
    supplementalPanes: [ownPane],
    paused: true,
  });

  assert.equal(bound.symbol, "BTCUSDT");
  assert.equal(bound.interval, "1h");
  assert.equal(bound.datasetKey, "dataset-1:epoch-1");
  assert.equal(bound.seriesStore, source.marketData.view.seriesStore);
  assert.equal(bound.loading, false);
  assert.equal(bound.onNeedMoreRight, source.marketData.actions.loadMoreRight);
  assert.equal(bound.onRestoreLatestWindow, source.marketData.actions.restoreLatestWindow);
  assert.equal(bound.canLoadMoreLeft, false);
  assert.equal(bound.canLoadMoreRight, false);
  assert.equal(bound.canRestoreLatestWindow, false);
  assert.equal(bound.suspended, true);
  assert.deepEqual(bound.subPanes, [ownPane, chartPane]);
});

test("an imported dataset is an offline reference that keeps its dataset origin (P5d3)", () => {
  const store = new SeriesWindowStore({ intervalSeconds: 900, seriesKey: "local:local-1:epoch-1:15m" });
  store.applyRange([
    { time: 900, open: 1, high: 2, low: 0.5, close: 1.5, volume: 3 },
    { time: 1_800, open: 1.5, high: 2.5, low: 1, close: 2, volume: 4 },
  ], { source: "local_dataset" });
  const imported: ChartSession = { exchange: "local", marketType: "local_dataset", symbol: "BTC-USDT", interval: "15m" };
  const loadMoreLeft = async () => {};
  const marketData = localChartMarketData(
    { seriesStore: store, loading: false, loadingMore: true, error: null, hasMoreLeft: true, loadMoreLeft, retry() {} },
    { session: imported, bars: store.snapshot({ force: true }), dataMeta: buildLocalChartDataMeta(store, "ready") },
  );
  const origin = { kind: "LOCAL_DATASET", dataset_id: "local-1", data_epoch: "epoch-1" } as const;
  const source = createLiveReferenceSource({ sourceId: "research-imported", session: imported,
    datasetKey: "local:local-1:epoch-1:15m", marketData, syntheticOrigin: origin });

  assert.throws(() => assertExecutableMarketChartSource(source), /LIVE_REFERENCE_IS_NOT_IMMUTABLE_EXECUTION_INPUT/);
  assert.deepEqual(backendSyntheticSourceFor(source), { ...imported, syntheticOrigin: origin, syntheticSeriesKey: store.seriesKey });
  assert.equal(marketData.view.display.displayData?.close, 2);
  const bound = bindMarketChartSurfaceProps({ source, chartProps: {
    symbol: "WRONG", interval: "5m", datasetKey: "wrong", upColor: "#00ff00", downColor: "#ff0000", theme: "dark", customBg: "#000000",
  } });
  assert.equal(bound.symbol, "BTC-USDT");
  assert.equal(bound.datasetKey, "local:local-1:epoch-1:15m");
  assert.equal(bound.seriesStore, store);
  assert.equal(bound.loading, true, "paging older bars shows as loading");
  assert.equal(bound.onNeedMoreLeft, loadMoreLeft);
  assert.equal(bound.canLoadMoreLeft, true);
  assert.equal(bound.canLoadMoreRight, false);
  assert.equal("onNeedMoreRight" in bound, false, "an imported dataset has no newer bars to follow");

  source.update({ session: imported, datasetKey: "local:local-1:epoch-1:15m", marketData });
  assert.equal(backendSyntheticSourceFor(source), source.session, "without an origin the reference is a live series");
});
