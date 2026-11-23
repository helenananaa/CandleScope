import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useLayoutEffect } from "react";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import MarketChartSurface from "../../features/market-chart-platform/MarketChartSurface.js";
import { createFrozenSnapshotSource, createRunResultSource, type MarketChartSourceRuntime } from "../../features/market-chart-platform/marketChartSourceRuntime.js";
import { MarketDataWorkspaceProvider } from "../../features/market-data/MarketDataWorkspaceProvider.js";
import { SYNTHETIC_TRANSFORMS, type BackendSyntheticSource, type SyntheticOrigin, type SyntheticTransform } from "../../features/market-data/synthetic/syntheticSeries.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { replaySyntheticSource } from "../../features/replay/replaySyntheticSource.js";
import { API_BASE } from "../../services/apiConfig.js";
import { useChartSurfaceRuntime } from "../useChartSurfaceRuntime.js";
import { RenkoProjector } from "../../features/chart-representation/projectors/renkoProjector.js";
import { HeikinAshiProjector } from "../../features/chart-representation/projectors/heikinAshiProjector.js";
import { PointFigureProjector } from "../../features/chart-representation/projectors/pointFigureProjector.js";
import { KagiProjector } from "../../features/chart-representation/projectors/kagiProjector.js";
import { LineBreakProjector } from "../../features/chart-representation/projectors/lineBreakProjector.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import type { BacktestChartData, BacktestReport, BacktestRunRecord } from "../../features/backtest/backtestTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean, message: string) {
  const deadline = performance.now() + 20_000;
  while (!predicate()) { assert(performance.now() < deadline, message); await sleep(25); }
}
interface Capture { origin: Extract<SyntheticOrigin, { kind: "REPLAY" }>; rows: KlineBar[] }

export async function checkPinnedSynthetic() {
  const data = await (await fetch(`${API_BASE}/fixture/pinned`)).json() as {
    saved: { run: BacktestRunRecord; report: BacktestReport; chart: BacktestChartData };
    replay: Capture;
  };
  const { run, report, chart } = data.saved;
  const bars = chart.bars.map(row => ({ ...row }));
  const market = { exchange: "binance", marketType: "usdm", symbol: chart.symbol, interval: chart.interval };
  const frozen = createFrozenSnapshotSource({ session: market, datasetId: run.dataset_id!, dataEpoch: run.data_epoch!,
    snapshotHash: run.snapshot_hash!, runId: run.run_id, chartHash: chart.chart_hash, bars });
  const result = createRunResultSource({ session: market, runId: run.run_id, configHash: run.config_hash,
    reportHash: report.hashes.report!, chartHash: chart.chart_hash, bars });
  const captured = createFrozenSnapshotSource({ session: market, datasetId: "browser-owned", dataEpoch: "fixed",
    snapshotHash: "browser-fixed-input", bars });
  const local = new SeriesWindowStore({ seriesKey: "pinned-imported" }); local.replace(bars);
  const replay = new SeriesWindowStore({ seriesKey: "pinned-replay" }); replay.replace(data.replay.rows);
  const replayMarket = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const bindReplay = (capture: Capture) => replaySyntheticSource({ market: replayMarket, seriesKey: replay.seriesKey,
    sessionId: capture.origin.session_id, trackId: capture.origin.track_id, dataEpoch: capture.origin.data_epoch,
    sourceSequence: capture.origin.source_sequence, revealedBoundaryMs: capture.origin.revealed_boundary_ms,
    historyEpoch: capture.origin.history_epoch! });
  let source: MarketChartSourceRuntime | null = frozen;
  let override: BackendSyntheticSource | null = null, reader = replay;
  let chartType: SyntheticTransform = "renko";
  let surface: ReturnType<typeof useChartSurfaceRuntime> | null = null;
  const messages: Array<Record<string, unknown>> = [];
  const NativeSocket = window.WebSocket;
  window.WebSocket = class extends NativeSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      this.addEventListener("message", event => messages.push(JSON.parse(String(event.data)) as Record<string, unknown>));
    }
  };
  const originals = [RenkoProjector.prototype.projectWithState, HeikinAshiProjector.prototype.project,
    PointFigureProjector.prototype.projectWithState, KagiProjector.prototype.projectWithState, LineBreakProjector.prototype.projectWithState] as const;
  const forbidden = () => { throw new Error("pinned chart invoked browser mathematics"); };
  RenkoProjector.prototype.projectWithState = forbidden; HeikinAshiProjector.prototype.project = forbidden;
  PointFigureProjector.prototype.projectWithState = forbidden; KagiProjector.prototype.projectWithState = forbidden;
  LineBreakProjector.prototype.projectWithState = forbidden;
  const host = document.createElement("div"), style = document.createElement("style");
  host.style.cssText = "width:900px;height:500px;position:relative;display:flex";
  style.textContent = ".chart-area{position:relative;flex:1;height:100%;min-width:0}.chart-pane{position:absolute;inset:0}";
  document.body.append(host); document.head.append(style);
  const root = createRoot(host);
  function Probe() {
    const runtime = useChartSurfaceRuntime(); useLayoutEffect(() => { surface = runtime; });
    const props = { ref: runtime.ref, symbol: "BTCUSDT", interval: source?.session.interval ?? override!.interval,
      datasetKey: source?.datasetKey ?? String(reader.seriesKey), chartType,
      renkoBoxSizeMode: "traditional" as const, renkoBoxSize: .1,
      pointFigureBoxSizeMode: "traditional" as const, pointFigureBoxSize: .1, pointFigureReversalAmount: 2,
      kagiReversalMode: "traditional" as const, kagiReversalAmount: .1, lineBreakNumberOfLines: 2,
      theme: "dark" as const, customBg: "", upColor: "#00aa00", downColor: "#aa0000", drawingReadOnly: true };
    return source ? <MarketChartSurface source={source} chartProps={props} />
      : <SingleChartPanes {...props} seriesStore={reader} backendSyntheticSource={override} />;
  }
  const render = () => flushSync(() => root.render(<MarketDataWorkspaceProvider><Probe /></MarketDataWorkspaceProvider>));
  async function ready(kind: string) {
    const start = messages.length; render();
    const matching = () => messages.slice(start).find(message => {
      const definition = message["definition"] as { origin?: SyntheticOrigin; config?: { transform: string } } | undefined;
      return definition?.origin?.kind === kind && definition.config?.transform === chartType
        && message["status"] === "ready" && (message["type"] === "snapshot" || message["complete"] === true);
    });
    await until(() => Boolean(matching()), `${kind}/${chartType} backend snapshot missing`);
    await until(() => Boolean((surface as ReturnType<typeof useChartSurfaceRuntime> | null)?.actions.captureViewportTransfer()),
      `${kind}/${chartType} did not render`);
    return matching()!;
  }
  const cases: unknown[] = [];
  try {
    for (const kind of ["FROZEN_SNAPSHOT", "RUN_RESULT", "LOCAL_DATASET", "CAPTURED_WINDOW", "REPLAY"] as const) {
      source = kind === "FROZEN_SNAPSHOT" ? frozen : kind === "RUN_RESULT" ? result : kind === "CAPTURED_WINDOW" ? captured : null;
      reader = kind === "LOCAL_DATASET" ? local : replay;
      override = kind === "REPLAY" ? bindReplay(data.replay) : { ...market, exchange: "local", marketType: "local_dataset",
        syntheticSeriesKey: String(local.seriesKey), syntheticOrigin: { kind: "LOCAL_DATASET", dataset_id: run.dataset_id!, data_epoch: run.data_epoch! } };
      for (const transform of SYNTHETIC_TRANSFORMS) {
        chartType = transform;
        const snapshot = await ready(kind);
        assert(Number(snapshot["total"]) > 0, `${kind}/${transform} empty unexpected result`);
        cases.push({ kind, transform, outputs: snapshot["total"] });
      }
    }
    // Forward and back to a captured prefix while its source window changes.
    chartType = "heikin-ashi";
    const before = await ready("REPLAY");
    const advanced = await (await fetch(`${API_BASE}/fixture/pinned/step`, { method: "POST" })).json() as Capture;
    replay.replace(advanced.rows); override = bindReplay(advanced);
    const after = await ready("REPLAY");
    assert(before["series_id"] !== after["series_id"], "forward replay reused an old cursor identity");
    replay.replace(data.replay.rows); override = bindReplay(data.replay);
    const rewound = await ready("REPLAY");
    assert(before["series_id"] === rewound["series_id"] && before["generation"] === rewound["generation"],
      "captured replay identity changed after forward playback");
    assert(JSON.stringify(before["rows"]) === JSON.stringify(rewound["rows"]), "rewound replay consumed future prices");
    flushSync(() => root.unmount());
    let state = { instances: -1, leases: -1 };
    for (let i = 0; i < 100; i++) {
      state = await (await fetch(`${API_BASE}/fixture/state`)).json() as typeof state;
      if (!state.instances && !state.leases) break;
      await sleep(30);
    }
    assert(!state.instances && !state.leases, "pinned chart leaked an instance or acquired a live stream");
    return { status: "PASS", cases, forwardReplay: true, capturedRewind: true, browserComputation: 0, state,
      scope: "default frozen/result surfaces and replay/imported chart bindings; real saved/local/replay backend owners" };
  } finally {
    RenkoProjector.prototype.projectWithState = originals[0]; HeikinAshiProjector.prototype.project = originals[1];
    PointFigureProjector.prototype.projectWithState = originals[2]; KagiProjector.prototype.projectWithState = originals[3];
    LineBreakProjector.prototype.projectWithState = originals[4];
    window.WebSocket = NativeSocket; flushSync(() => root.unmount());
    frozen.dispose(); result.dispose(); captured.dispose(); host.remove(); style.remove();
  }
}
