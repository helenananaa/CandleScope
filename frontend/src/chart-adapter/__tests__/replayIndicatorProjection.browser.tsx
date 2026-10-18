import { act, useLayoutEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useProvidedBarsIndicatorRuntime } from "../../features/indicators/useProvidedBarsIndicatorRuntime.js";
import { parseIndicatorPayloadEnvelope } from "../../features/indicators/indicatorContracts.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { ActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { createReplayBuiltinCompute } from "../../features/replay/replayBuiltinCompute.js";
import fixture from "../../features/replay/__tests__/fixtures/builtin-parity.json";

/** Real hooks and chart engine, with the transport replaced by Python reference data. */
export async function checkReplayIndicatorProjection() {
  const reference = fixture.cases.find(item => item.name === "RSI" && Object.keys(item.params).length === 0)!;
  const template = parseIndicatorPayloadEnvelope(reference.seed);
  const points = reference.outputs.rsi!;
  const persistence: ActiveIndicatorPersistence = { controlled: true,
    load: () => [{ id: "rsi", engineName: "RSI", visible: true, params: { period: 14 } }], save: () => undefined };
  const host = document.createElement("div"), canvas = document.createElement("div");
  document.body.append(host, canvas);
  const root = createRoot(host), chart = createChart(canvas, { width: 600, height: 240 });
  const main = chart.addSeries(LineSeries), study = chart.addSeries(LineSeries);
  let latest: IndicatorRuntime | null = null, remoteCalls = 0;
  type Props = { count: number; first: number; last: number; scope: string };
  function Probe({ count, first, last, scope }: Props) {
    const bars = useMemo(() => fixture.bars.slice(0, count).map(bar => ({ ...bar, time: bar.time as KlineBar["time"] })), [count]);
    const outputBarTimes = useMemo(() => fixture.bars.slice(first, last).map(bar => bar.time), [first, last]);
    const computeBatch = useMemo(() => {
      void scope;
      return createReplayBuiltinCompute(async ({ jobs }) => {
        remoteCalls++;
        return { ok: true, results: jobs.map(job => {
          const end = job.request.ohlcv.at(-1)?.time ?? 0;
          const data = points.filter(point => point.time <= end);
          return { clientId: job.clientId, jobKey: job.jobKey, payload: { ...template,
            lines: template.lines.map(line => ({ ...line, data })),
            series: template.series.map(series => ({ ...series, data })),
          } };
        }) };
      });
    }, [scope]);
    const meta = useMemo(() => ({ version: count, status: "ready", committedAt: null,
      source: "replay-indicator-revealed-prefix" }), [count]);
    const runtime = useProvidedBarsIndicatorRuntime({ bars, outputBarTimes, computeBatch, persistence,
      chartDataMeta: meta, datasetKey: scope, sourceScopeKey: scope, sourceOrdinal: count,
      seriesReady: count, visibleThroughSeconds: fixture.bars[count - 1]!.time,
      exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m" });
    useLayoutEffect(() => { latest = runtime; });
    return null;
  }
  const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };
  const samples: unknown[] = [];
  const render = async (props: Props) => {
    await act(async () => { root.render(<Probe {...props} />); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
    const result = latest as IndicatorRuntime | null;
    const data = result?.view.activeIndicators.find(item => item.id === "rsi")?.lines?.[0]?.data ?? [];
    const window = fixture.bars.slice(props.first, Math.min(props.last, props.count));
    const expected = points.filter(point => window.some(bar => bar.time === point.time));
    assert(JSON.stringify(data) === JSON.stringify(expected), `wrong projected RSI for ${JSON.stringify(props)}`);
    main.setData(window.map(bar => ({ time: bar.time as UTCTimestamp, value: bar.close })));
    study.setData(data.map(point => ({ time: point.time as UTCTimestamp, value: point.value })));
    chart.timeScale().fitContent();
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const range = chart.timeScale().getVisibleRange();
    assert(range?.from === window[0]?.time && range?.to === window.at(-1)?.time, "indicator prefix extended the chart's shared time axis");
    samples.push({ ...props, outputBars: data.length, range, remoteCalls });
  };
  try {
    await render({ count: 32, first: 22, last: 32, scope: "run-a|1m" });
    const firstCalls = remoteCalls;
    await render({ count: 32, first: 14, last: 32, scope: "run-a|1m" });
    await render({ count: 32, first: 27, last: 32, scope: "run-a|1m" });
    assert(remoteCalls === firstCalls, "viewport prepend/trim must not reseed the computation");
    await render({ count: 128, first: 118, last: 128, scope: "run-a|1m" });
    assert(remoteCalls === firstCalls, "forward append discarded the validated recursive checkpoint");
    await render({ count: 32, first: 22, last: 32, scope: "run-a|1m" });
    assert(remoteCalls > firstCalls, "backward seek reused a future checkpoint");
    await render({ count: 128, first: 118, last: 128, scope: "run-b|1m" });
    await render({ count: 32, first: 22, last: 32, scope: "run-a|1m" });
    return { name: "recursive indicators with independent chart windows", status: "PASS", samples };
  } finally {
    await act(async () => { root.unmount(); }); chart.remove(); host.remove(); canvas.remove();
  }
}
