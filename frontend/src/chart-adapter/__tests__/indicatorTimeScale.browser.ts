import { createChart, CandlestickSeries, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { applyLineSeriesData } from "../chartSeriesData.js";
import { resyncSharedTimeScaleIndexes } from "../seriesLifecycle.js";
import type { MainSeriesHandle } from "../chartAdapterTypes.js";

const frame = () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

/** Exercise the real LWC transaction, including its synchronous hit-test. */
export async function checkIndicatorTimeScaleRepair(): Promise<string> {
  const outcomes: Array<{ away: boolean; dirty: boolean; main: string; range: string; crosshair: string }> = [];
  for (const away of [false, true]) for (const dirty of [false, true]) {
    const element = document.createElement("div");
    element.style.cssText = "width:900px;height:400px";
    document.body.append(element);
    const chart = createChart(element, { width: 900, height: 400 });
    const main = chart.addSeries(CandlestickSeries);
    const line = chart.addSeries(LineSeries);
    const complete = Array.from({ length: 40 }, (_, index) => ({
      time: (1_793_668_889 + index) as UTCTimestamp,
      open: 10 + index, high: 12 + index, low: 9 + index, close: 11 + index,
    }));
    const source = complete.filter((_, index) => ![22, 24, 25].includes(index));
    const previous = source.map((bar) => ({ time: bar.time, value: bar.close }));
    let crosshair: unknown = null;
    chart.subscribeCrosshairMove((event) => { crosshair = { time: event.time, point: event.point }; });
    try {
      main.setData(source); line.setData(previous); chart.timeScale().fitContent();
      if (away) chart.timeScale().setVisibleLogicalRange({ from: 5, to: 30 });
      await frame();
      chart.setCrosshairPosition(source[15]!.close, source[15]!.time, main);
      if (dirty) main.applyOptions({ priceLineVisible: false });
      applyLineSeriesData(line, complete.map((bar) => ({ time: bar.time, value: bar.close })), previous,
        {}, undefined, {
          preferSetData: true,
          beforeTimeScaleChange: () => resyncSharedTimeScaleIndexes([
            { series: main as MainSeriesHandle, data: source },
            { series: line as MainSeriesHandle, data: previous },
          ]),
        });
      const marketValues = main.data().map((bar) => "open" in bar
        ? [bar.time, bar.open, bar.high, bar.low, bar.close] : [bar.time]);
      assert(JSON.stringify(marketValues) === JSON.stringify(source.map((bar) =>
        [bar.time, bar.open, bar.high, bar.low, bar.close])), "Indicator repair changed market candles");
      assert(line.data().length === complete.length, "Historical indicator times were dropped");
      outcomes.push({ away, dirty, main: JSON.stringify(main.data()),
        range: JSON.stringify(chart.timeScale().getVisibleLogicalRange()), crosshair: JSON.stringify(crosshair) });
    } finally { chart.remove(); element.remove(); }
  }
  for (const outcome of outcomes.filter((item) => item.dirty)) {
    const control = outcomes.find((item) => !item.dirty && item.away === outcome.away)!;
    assert(outcome.main === control.main, "Repair changed market facts relative to the clean-style control");
    assert(outcome.range === control.range, "Repair changed the viewport relative to the clean-style control");
    assert(outcome.crosshair === control.crosshair, "Repair changed the crosshair relative to the clean-style control");
  }
  return "historical indicator time insertion preserves market candles, historical viewport and crosshair with pending candle styles";
}
