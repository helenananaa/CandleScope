import { createChartEx, LineSeries, type Logical } from "lightweight-charts";
import { createOrdinalHorzScaleBehavior } from "../ordinalHorzScaleBehavior.js";
import type { OrdinalHorzScaleBehavior } from "../ordinalHorzScaleBehavior.js";
import type { OrdinalAxisTime } from "../../features/chart-representation/chartRepresentationTypes.js";
import { ViewportController } from "../viewportController.js";
import { FUTURE_TIME_AXIS_ORDINAL_ORDER_START, futureTimeAxisRenderData } from "../futureTimeAxis.js";
import { replaceFutureTimeAxisData } from "../seriesLifecycle.js";
import { refreshOrdinalTimeScale } from "../ordinalTimeScaleRefresh.js";
import { structuralMock } from "../../test/testHelpers.js";

/** Uses the installed chart engine, including its shared-axis bookkeeping. */
export async function checkOrdinalViewportHydration() {
  const container = document.createElement("div"); document.body.append(container);
  const chart = createChartEx<OrdinalAxisTime, OrdinalHorzScaleBehavior>(container, createOrdinalHorzScaleBehavior(), { width: 600, height: 200 });
  const main = chart.addSeries(LineSeries), indicator = chart.addSeries(LineSeries), future = chart.addSeries(LineSeries);
  const rows = (count: number) => Array.from({ length: count }, (_, order) => ({
    time: { order, sourceTime: 1_800_000_000 + order * 60, sourceOrdinal: 0 }, value: 100 + order,
  }));
  const carriers = (count: number, length = 64) => Array.from({ length }, (_, index) => ({
    time: { order: FUTURE_TIME_AXIS_ORDINAL_ORDER_START + index, sourceTime: 1_800_000_000 + (count + index) * 60, sourceOrdinal: 0 },
  }));
  try {
    main.setData(rows(200)); indicator.setData(rows(200)); future.setData(carriers(200));
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    main.setData(rows(20)); future.setData(carriers(20));
    const controller = new ViewportController({ chartProvider: () => structuralMock(chart) });
    controller.restoreProjectionRange({ from: 18, to: 26 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    const before = chart.timeScale().getVisibleLogicalRange();
    indicator.setData(rows(20));
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    const after = chart.timeScale().getVisibleLogicalRange();
    controller.restoreProjectionRange({ from: 18, to: 26 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    const restored = chart.timeScale().getVisibleLogicalRange();
    if (restored?.from !== 18 || restored.to !== 26) throw new Error("post-auxiliary restore lost the owned range");
    main.setData(rows(200)); indicator.setData(rows(200)); future.setData(carriers(200));
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    main.setData(rows(20)); future.setData(carriers(20));
    controller.restoreProjectionRange({ from: 18, to: 26 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    indicator.setData(rows(20));
    controller.restoreProjectionRange({ from: 18, to: 26 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const immediateRestored = chart.timeScale().getVisibleLogicalRange();
    if (immediateRestored?.from !== 18 || immediateRestored.to !== 26) throw new Error(`same-commit auxiliary restore lost range: ${JSON.stringify(immediateRestored)}`);
    controller.restoreProjectionRange({ from: 19.5, to: 22 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const sparseBefore = chart.timeScale().getVisibleLogicalRange();
    future.applyOptions({ visible: false });
    future.setData(structuralMock(futureTimeAxisRenderData(carriers(20))));
    controller.restoreProjectionRange({ from: 19.5, to: 22 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const sparseRestored = chart.timeScale().getVisibleLogicalRange();
    if (Math.abs(Number(sparseRestored?.from) - 19.5) > 1e-7 || Math.abs(Number(sparseRestored?.to) - 22) > 1e-7) {
      throw new Error(`sparse ordinal future range clamped: ${JSON.stringify(sparseRestored)}`);
    }
    chart.timeScale().applyOptions({ shiftVisibleRangeOnNewBar: true });
    replaceFutureTimeAxisData(structuralMock(chart), structuralMock(future), carriers(20, 128));
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const expanded = chart.timeScale().getVisibleLogicalRange();
    if (Math.abs(Number(expanded?.from) - 19.5) > 1e-7 || Math.abs(Number(expanded?.to) - 22) > 1e-7) {
      throw new Error(`carrier expansion navigated into future: ${JSON.stringify(expanded)}`);
    }
    if (!chart.timeScale().options().shiftVisibleRangeOnNewBar) throw new Error("carrier expansion changed live scrolling policy");
    refreshOrdinalTimeScale(structuralMock(chart), structuralMock(main), new Map([
      [structuralMock(future), futureTimeAxisRenderData(carriers(20, 128))],
    ]));
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const firstFutureCoordinate = chart.timeScale().logicalToCoordinate(20 as Logical);
    const firstFutureTime = firstFutureCoordinate === null ? null : chart.timeScale().coordinateToTime(firstFutureCoordinate);
    if (firstFutureTime?.sourceTime !== carriers(20, 128)[0]!.time.sourceTime) {
      throw new Error(`ordinal refresh discarded carrier whitespace: ${JSON.stringify(firstFutureTime)}`);
    }
    return { name: "ordinal auxiliary hydration", status: "PASS", before, after, restored, immediateRestored, sparseBefore, sparseRestored, expanded, firstFutureTime };
  } finally { chart.remove(); container.remove(); }
}
