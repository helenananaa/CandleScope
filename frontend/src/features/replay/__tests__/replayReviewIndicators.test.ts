import assert from "node:assert/strict";
import test from "node:test";
import { reviewIndicatorBars, reviewIndicatorPersistence } from "../useReplayReviewIndicators.js";
import type { KlineBar } from "../../market-data/marketDataTypes.js";
import { epochSeconds } from "../../../test/testHelpers.js";
import { buildIndicatorOhlcv } from "../../indicators/indicatorComputeRuntime.js";
import { createReplayBuiltinCompute } from "../replayBuiltinCompute.js";
import { aggregateReplayBaseBars } from "../replayViewerProjection.js";
import { commitReplayReviewPrefix, replayReviewDataMeta } from "../replayReviewPrefix.js";
import { hasCurrentDatasetOwnership } from "../../../components/singleChartPaneLifecycle.js";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";

const rows: KlineBar[] = [0, 60, 120].map(time => ({ time: epochSeconds(time),
  open: 10, high: 11, low: 9, close: 10, volume: 1, replayClosed: true,
  replayCloseTimeMs: (time + 60) * 1_000 - 1, replayLastBaseOpenMs: time * 1_000 }));

test("review input fails closed during navigation, failed loads and exit", () => {
  assert.deepEqual(reviewIndicatorBars(rows, "early", "late", 119_999), []);
  assert.deepEqual(reviewIndicatorBars(rows, "early", null, 119_999), []);
  assert.deepEqual(reviewIndicatorBars(rows, null, null, 119_999), []);
  assert.deepEqual(reviewIndicatorBars(rows, "early", "early", 119_999), rows.slice(0, 2));
  assert.deepEqual(reviewIndicatorBars(rows, "early", "early", null), []);
});

test("review definitions preserve pane identity without current output, schema or durable writes", () => {
  const inputs = [{ id: "rsi", name: "RSI", paneTarget: "sub", params: { period: 14 },
    lines: [{ name: "RSI", data: [{ time: 120, value: 90 }] }], error: "future",
    paramSchema: [{ key: "period", type: "int" }] }];
  const before = structuredClone(inputs);
  const persistence = reviewIndicatorPersistence(inputs);
  const definition = persistence.load()[0]!;
  assert.equal(definition.id, "rsi");
  assert.equal(definition.paneTarget, "sub");
  assert.deepEqual(definition.params, { period: 14 });
  assert.deepEqual(definition.lines, []);
  assert.equal(definition.error, undefined);
  assert.equal(definition.paramSchema, undefined);
  persistence.save([{ id: "replacement" }]);
  assert.deepEqual(inputs, before);
  assert.equal(persistence.load()[0]!.id, "rsi");
});

test("review compute sends only the historical prefix, including after rewinding from later data", async () => {
  const requests: number[][] = [];
  const compute = createReplayBuiltinCompute(async ({ jobs }) => {
    requests.push(jobs[0]!.request.ohlcv.map(bar => bar.time));
    return { ok: true, results: [] };
  });
  for (const [key, cursor] of [["late", 179_999], ["early", 119_999]] as const) {
    const bars = reviewIndicatorBars(rows, key, key, cursor);
    await compute({ jobs: [{ clientId: "rsi", jobKey: key,
      request: { mode: "builtin", name: "RSI", ohlcv: buildIndicatorOhlcv(bars) } }] });
  }
  assert.deepEqual(requests, [[0, 60, 120], [0, 60]]);
});

test("a bounded source starting mid custom-period bucket still computes the later complete prefix", () => {
  const source: KlineBar[] = Array.from({ length: 90 * 4 - 1 }, (_, index) => {
    const time = (index + 1) * 60;
    return { ...rows[0]!, time: epochSeconds(time), replayCloseTimeMs: (time + 60) * 1_000 - 1,
      replayLastBaseOpenMs: time * 1_000 };
  });
  for (const interval of ["7m", "90m"]) {
    const display = aggregateReplayBaseBars(source, "1m", interval);
    assert.equal(display[0]!.replayClosed, false);
    const revealed = reviewIndicatorBars(display, interval, interval, 90 * 4 * 60_000);
    assert.ok(revealed.length > 0);
    assert.ok(revealed.slice(0, -1).every(bar => bar.replayClosed === true));
    if (revealed.at(-1)!.replayClosed !== true) {
      assert.ok(Number(revealed.at(-1)!.replayCloseTimeMs) >= 90 * 4 * 60_000);
    }
    assert.ok(Number(revealed[0]!.time) > Number(display[0]!.time));
  }
});

test("a known incomplete historical bucket separates indicator state but does not weaken finality checks", () => {
  const missing = { ...rows[1]!, replayClosed: false, replayComponentCount: 1, replayExpectedComponents: 2 };
  assert.deepEqual(reviewIndicatorBars([rows[0]!, missing, rows[2]!], "same", "same", 179_999), [rows[2]!]);
  const unexplained = { ...rows[1]!, replayClosed: false };
  assert.deepEqual(reviewIndicatorBars([rows[0]!, unexplained, rows[2]!], "same", "same", 179_999), [rows[0]!]);
  // Current forming tails remain eligible, preserving the actual revealed OHLCV.
  assert.deepEqual(reviewIndicatorBars([rows[0]!, missing], "same", "same", 100_000), [rows[0]!, missing]);
});

test("historical indicator rendering owns the selected review event and rejects a prior event", () => {
  const source = new SeriesWindowStore({ intervalSeconds: 60 });
  source.replace(rows);
  const target = new SeriesWindowStore();
  for (const event of ["review:latest:ltc:7m", "review:earlier:ltc:7m"]) {
    assert.equal(hasCurrentDatasetOwnership({ datasetKey: event, dataMeta: replayReviewDataMeta(target, true), seriesStore: target }), false);
    commitReplayReviewPrefix(target, source, "7m", event);
    const dataMeta = replayReviewDataMeta(target, false);
    assert.equal(dataMeta.optimistic, false);
    assert.equal(hasCurrentDatasetOwnership({ datasetKey: event, dataMeta, seriesStore: target }), true);
    assert.equal(hasCurrentDatasetOwnership({ datasetKey: "live:ltc:7m", dataMeta, seriesStore: target }), false);
  }
});
