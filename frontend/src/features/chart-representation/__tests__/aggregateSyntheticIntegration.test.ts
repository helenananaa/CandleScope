import assert from "node:assert/strict";
import test from "node:test";
import type { KlineBar } from "../../market-data/marketDataTypes.js";
import { aggregateReplayBaseBars } from "../../replay/replayViewerProjection.js";
import { resolveChartCrosshairSourceTime, resolveChartPaneLegendValues } from "../../../components/chartPaneLegendModel.js";
import { buildDisplaySourceTimeIndex, projectSourceTimedEntries } from "../derivedAuxiliaryProjection.js";
import { ProjectionStore } from "../projectionStore.js";
import { IdentityProjector } from "../projectors/identityProjector.js";
import { HeikinAshiProjector } from "../projectors/heikinAshiProjector.js";
import { RenkoProjector } from "../projectors/renkoProjector.js";
import { PointFigureProjector } from "../projectors/pointFigureProjector.js";
import { KagiProjector } from "../projectors/kagiProjector.js";
import { LineBreakProjector } from "../projectors/lineBreakProjector.js";
import type { DisplayRow, Projector, SourceBar } from "../chartRepresentationTypes.js";

// Real aggregation deliberately has different source bar identity and lineage
// end. Point-only fixtures (time === sourceToTime) cannot expose this defect.
function aggregate(closes: number[], interval: "7m" | "90m"): SourceBar[] {
  const minutes = interval === "7m" ? 7 : 90;
  const base = closes.flatMap((close, index) => Array.from({ length: minutes }, (_, minute) => ({
    time: ((10 + index) * minutes * 60 + minute * 60) as KlineBar["time"],
    open: close, high: close, low: close, close, volume: 2, replayClosed: true, is_closed: true,
  })));
  return [...aggregateReplayBaseBars(base, "1m", interval)];
}

const projectors: Array<() => Projector> = [
  () => new IdentityProjector(),
  () => new HeikinAshiProjector(),
  () => new RenkoProjector({ boxSize: 1, minTick: 1 }),
  () => new PointFigureProjector({ boxSize: 1, minTick: 1, reversalAmount: 3 }),
  () => new KagiProjector({ reversalTicks: 3, minTick: 1 }),
  () => new LineBreakProjector({ numberOfLines: 3, minTick: 1 }),
];

function assertSourceBindings(display: readonly DisplayRow[], source: readonly SourceBar[]) {
  assert.ok(display.length > 0);
  const raw = new Map(source.map(row => [row.time, row]));
  const input = source.map((row, index) => ({ time: row.time, value: 30 + index }));
  const output = projectSourceTimedEntries(input, buildDisplaySourceTimeIndex(display));
  assert.equal(output.length, display.length, "every emitted column has an exact indicator source");
  for (const row of display) {
    const time = resolveChartCrosshairSourceTime(row.time, row);
    const sourceRow = time === null ? undefined : raw.get(time);
    assert.ok(sourceRow, `crosshair ${JSON.stringify(row.time)} must identify a source aggregate`);
    assert.equal(row.customValues?.chartProjection?.sourceToTime, sourceRow.sourceToTime,
      "drawing/execution lineage must keep the final base bar, not the aggregate open");
    assert.ok(Number(sourceRow.volume) > 0, "volume resolves from that same source aggregate");
    const expected = input.find(point => point.time === time)?.value;
    assert.equal(resolveChartPaneLegendValues([{ id: "rsi", data: input }], time)[0]?.value, expected);
  }
}

for (const interval of ["7m", "90m"] as const) {
  for (const create of projectors) {
    const id = create().id;
    test(`${id} ${interval}: aggregate identity survives load, no-op, extension, reversal and retraction`, () => {
      const closes = [10, 13, 12, 15, 10, 11, 17, 9, 10];
      const all = aggregate(closes, interval);
      const store = new ProjectionStore({ projector: create() });
      store.reset(all.slice(0, 2));
      assertSourceBindings(store.displaySnapshot(), all.slice(0, 2));
      for (let count = 3; count <= all.length; count++) {
        const rows = all.slice(0, count);
        store.applySourceDelta({ type: "tick", appended: true, bar: rows.at(-1) }, rows);
        assert.deepEqual(store.displaySnapshot(), create().project(rows), `append ${count} equals cold projection`);
        assertSourceBindings(store.displaySnapshot(), rows);
      }
      const changed = aggregate([...closes.slice(0, -1), 18], interval);
      store.applySourceDelta({ type: "tick", replaced: true, bar: changed.at(-1) }, changed);
      assert.deepEqual(store.displaySnapshot(), create().project(changed));
      assertSourceBindings(store.displaySnapshot(), changed);

      // Incremental provisional updates must not corrupt the confirmed source
      // identity when an extension is undone before the bar closes.
      for (const close of [20, 18, 8]) {
        const forming = aggregate([...closes.slice(0, -1), close], interval);
        forming[forming.length - 1] = { ...forming[forming.length - 1]!, is_closed: false };
        store.applySourceDelta({ type: "tick", replaced: true, bar: forming.at(-1) }, forming);
        assertSourceBindings(store.displaySnapshot(), forming);
      }
    });

    test(`${id} ${interval}: history prepend and trim keep indicator and drawing time identities`, () => {
      const rows = aggregate([10, 13, 12, 15, 10, 11, 17, 9, 10], interval);
      const store = new ProjectionStore({ projector: create() });
      store.reset(rows.slice(3));
      store.applySourceDelta({ type: "prepend" }, rows);
      assert.deepEqual(store.displaySnapshot(), create().project(rows));
      assertSourceBindings(store.displaySnapshot(), rows);
      store.applySourceDelta({ type: "trim-left", trimmedLeft: 3 }, rows.slice(3));
      // A retained synthetic leg may originate before the current source
      // window; compare against full history for its identity and lineage.
      assertSourceBindings(store.displaySnapshot(), rows);
    });
  }
}
