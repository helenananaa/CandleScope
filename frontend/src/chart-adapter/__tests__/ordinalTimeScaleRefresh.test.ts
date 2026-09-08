import assert from "node:assert/strict";
import test from "node:test";
import { ordinalSourceTimesChanged, refreshOrdinalTimeScale } from "../ordinalTimeScaleRefresh.js";
import { structuralMock } from "../../test/testHelpers.js";

const row = (order: number, sourceTime: number) => ({ time: { order, sourceTime, sourceOrdinal: 0 }, value: 1 });

test("only rewritten ordinal source dates require shared time-point refresh", () => {
  assert.equal(ordinalSourceTimesChanged([row(0, 10)], [row(0, 20)]), true);
  assert.equal(ordinalSourceTimesChanged([row(0, 10)], [row(0, 10), row(1, 20)], 1), false);
  assert.equal(ordinalSourceTimesChanged([row(0, 10)], [row(0, 10)]), false);
  assert.equal(ordinalSourceTimesChanged([{ time: 10 }], [{ time: 20 }]), false);
});

test("refresh replaces shared source dates while retaining series data and viewport", () => {
  const points = new Map<number, number>();
  const members: FakeSeries[] = [];
  class FakeSeries {
    rows: ReturnType<typeof row>[] = [];
    constructor() { members.push(this); }
    data() { return this.rows; }
    setData(rows: ReturnType<typeof row>[]) {
      this.rows = rows;
      // A shared LWC time point retains its first date while another series owns it.
      for (const key of points.keys()) {
        if (!members.some(s => s.rows.some(r => r.time.order === key))) points.delete(key);
      }
      for (const r of rows) if (!points.has(r.time.order)) points.set(r.time.order, r.time.sourceTime);
    }
  }
  const main = new FakeSeries(); const overlay = new FakeSeries();
  main.setData([row(0, 10)]); overlay.setData([row(0, 10)]);
  main.setData([row(0, 20)]);
  assert.equal(points.get(0), 10, "shared metadata remains stale before refresh");
  let range = { from: -2, to: 5 };
  const scale = { getVisibleLogicalRange: () => ({ ...range }), setVisibleLogicalRange: (next: typeof range) => { range = next; } };
  const chart = structuralMock<NonNullable<Parameters<typeof refreshOrdinalTimeScale>[0]>>({
    panes: () => [{ getSeries: () => [overlay] }, { getSeries: () => [main] }],
    timeScale: () => scale,
  });
  refreshOrdinalTimeScale(chart, structuralMock<Parameters<typeof refreshOrdinalTimeScale>[1]>(main));
  assert.equal(points.get(0), 20);
  assert.deepEqual(main.data(), [row(0, 20)]);
  assert.deepEqual(overlay.data(), [row(0, 10)]);
  assert.deepEqual(range, { from: -2, to: 5 });
});
