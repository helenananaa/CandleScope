import type { IChartApiBase, ISeriesApi, SeriesType } from "lightweight-charts";
import type { ChartSeriesInputRow, ChartTime } from "./chartAdapterTypes.js";
import { isOrdinalAxisTime } from "../features/chart-representation/axisTime.js";

export function ordinalSourceTimesChanged(
  before: readonly { time: unknown }[],
  after: readonly { time: unknown }[],
  fromIndex = 0,
): boolean {
  for (let i = Math.max(0, fromIndex); i < Math.min(before.length, after.length); i += 1) {
    const oldTime = before[i]?.time;
    const newTime = after[i]?.time;
    if (isOrdinalAxisTime(oldTime) && isOrdinalAxisTime(newTime)
      && oldTime.order === newTime.order && oldTime.sourceTime !== newTime.sourceTime) return true;
  }
  return false;
}

/** Rebuild LWC's shared time points when ordinal positions acquire new dates. */
export function refreshOrdinalTimeScale(
  chart: IChartApiBase<ChartTime> | null,
  main: ISeriesApi<SeriesType, ChartTime>,
  renderData: ReadonlyMap<ISeriesApi<SeriesType, ChartTime>, readonly ChartSeriesInputRow[]> = new Map(),
): void {
  if (!chart) return;
  const all = [...new Set([main, ...chart.panes().flatMap((pane) => pane.getSeries())])];
  // series.data() exposes only plotted rows. In particular, an invisible
  // future carrier returns its terminal anchor but omits all whitespace.
  // Replay the owned render snapshots so shared logical indexes stay intact.
  const snapshots = all.map((series) => ({ series, data: renderData.get(series) ?? series.data() }));
  const scale = chart.timeScale();
  const range = scale.getVisibleLogicalRange();
  const shift = scale.options().shiftVisibleRangeOnNewBar;
  scale.applyOptions({ shiftVisibleRangeOnNewBar: false });
  // Clearing only the main series leaves shared point metadata alive in other
  // series. Restore the main series first so its new source dates own the axis.
  const errors: unknown[] = [];
  for (const { series } of snapshots) {
    try { series.setData([]); } catch (error) { errors.push(error); }
  }
  for (const { series, data } of snapshots) {
    try { Reflect.apply(series.setData, series, [data]); } catch (error) { errors.push(error); }
  }
  try {
    if (range) scale.setVisibleLogicalRange(range);
  } catch (error) { errors.push(error); }
  try { scale.applyOptions({ shiftVisibleRangeOnNewBar: shift }); } catch (error) { errors.push(error); }
  if (errors.length) throw new AggregateError(errors, "Could not refresh ordinal time points");
}
