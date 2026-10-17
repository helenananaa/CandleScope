import { createChart, LineSeries, type Logical, type UTCTimestamp } from "lightweight-charts";
import { ViewportController } from "../viewportController.js";
import { planVisibleRangeRestore } from "../../features/chart-session/visibleRangeStorage.js";
import { structuralMock } from "../../test/testHelpers.js";
import { createFutureTimeAxisSeries, replaceFutureTimeAxisData } from "../seriesLifecycle.js";

/** The real shared-axis base index includes our invisible render anchor. */
export async function checkSemanticSessionViewport() {
  const samples: unknown[] = [];
  const frame = () => new Promise(requestAnimationFrame);
  for (const count of [6, 600]) {
    const host = document.createElement("div"); document.body.append(host);
    const chart = createChart(host, { width: 680, height: 260,
      timeScale: { barSpacing: 64, rightOffset: 5 } });
    const source = Array.from({ length: count }, (_, index) => ({
      time: (1_800_000_000 + index * 60) as UTCTimestamp, value: 100 + index / 100,
    }));
    const main = chart.addSeries(LineSeries); main.setData(source);
    const adapter = structuralMock<NonNullable<ReturnType<ViewportController["getChart"]>>>(chart);
    const future = createFutureTimeAxisSeries(adapter);
    const carriers = (length: number) => Array.from({ length }, (_, index) => ({
      time: 1_800_000_000 + (count + index) * 60,
    }));
    const controller = new ViewportController({ chartProvider: () => adapter,
      contentLogicalRangeProvider: () => ({ from: 0, to: count - 1 }) });
    const scale = chart.timeScale();
    const expectTail = (tail: number, label: string) => {
      const range = scale.getVisibleLogicalRange();
      if (!range || Math.abs(range.to - tail) > 1e-6) {
        throw new Error(`${count} ${label}: ${JSON.stringify({ range, tail })}`);
      }
      return range;
    };
    try {
      replaceFutureTimeAxisData(adapter, future, carriers(64)); await frame(); await frame();
      scale.setVisibleLogicalRange({ from: (count - 9) as Logical, to: (count - 1) as Logical });
      const legacyOffset = Math.max(0, scale.scrollPosition());
      scale.scrollToPosition(legacyOffset, false); await frame(); await frame();
      const legacy = scale.getVisibleLogicalRange();
      if (!legacy || legacy.to < count + 50) throw new Error("fixture did not reproduce carrier-based legacy restore");

      controller.applySessionRestore(planVisibleRangeRestore({ barSpacing: 64, rightOffset: 0 }, source));
      await frame(); await frame();
      const reopened = expectTail(count - 1, "reopen");
      const saved = { barSpacing: scale.options().barSpacing, rightOffset: controller.captureRightOffset() };
      if (Math.abs(saved.barSpacing - 64) > 1e-6) throw new Error("saved zoom was not restored");
      if (Math.abs(Number(saved.rightOffset)) > 1e-6) throw new Error("saved offset includes render carriers");
      replaceFutureTimeAxisData(adapter, future, carriers(128)); await frame(); await frame();
      expectTail(count - 1, "capacity growth");
      controller.applySessionRestore(planVisibleRangeRestore(saved, source)); await frame(); await frame();
      expectTail(count - 1, "restore with different carrier capacity");
      controller.resetToDefault(); await frame(); await frame();
      const reset = expectTail(count + 4, "default reset");
      if (main.data().length !== count) throw new Error("viewport repair mutated market rows");
      samples.push({ count, legacy, reopened, saved, reset });
    } finally { controller.dispose(); chart.remove(); host.remove(); }
  }
  return { name: "semantic market-tail persistence with hidden future carriers", status: "PASS", samples };
}
