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
  let shift = true;
  const scale = { getVisibleLogicalRange: () => ({ ...range }), setVisibleLogicalRange: (next: typeof range) => { range = next; },
    options: () => ({ shiftVisibleRangeOnNewBar: shift }),
    applyOptions: (options: { shiftVisibleRangeOnNewBar: boolean }) => { shift = options.shiftVisibleRangeOnNewBar; } };
  const chart = structuralMock<NonNullable<Parameters<typeof refreshOrdinalTimeScale>[0]>>({
    panes: () => [{ getSeries: () => [overlay] }, { getSeries: () => [main] }],
    timeScale: () => scale,
  });
  refreshOrdinalTimeScale(chart, structuralMock<Parameters<typeof refreshOrdinalTimeScale>[1]>(main));
  assert.equal(points.get(0), 20);
  assert.deepEqual(main.data(), [row(0, 20)]);
  assert.deepEqual(overlay.data(), [row(0, 10)]);
  assert.deepEqual(range, { from: -2, to: 5 });
  assert.equal(shift, true);
});

test("refresh uses owned whitespace snapshots and suppresses automatic scrolling throughout the rebuild", () => {
  type Row = { time: ReturnType<typeof row>["time"]; value?: number };
  type Series = Parameters<typeof refreshOrdinalTimeScale>[1];
  let shift = true;
  const writes: Row[][] = [];
  const main = structuralMock<Series>({ data: () => [row(0, 10)], setData: () => { assert.equal(shift, false); } });
  const fullCarrier: Row[] = [{ time: row(100, 20).time }, row(101, 30)];
  const carrier = structuralMock<Series>({
    data: () => fullCarrier.filter(item => item.value !== undefined),
    setData: (data: Row[]) => { assert.equal(shift, false); writes.push(data); },
  });
  const visible = { from: 0.5, to: 2 };
  const chart = structuralMock<NonNullable<Parameters<typeof refreshOrdinalTimeScale>[0]>>({
    panes: () => [{ getSeries: () => [main, carrier] }],
    timeScale: () => ({
      options: () => ({ shiftVisibleRangeOnNewBar: shift }),
      applyOptions: (options: { shiftVisibleRangeOnNewBar: boolean }) => { shift = options.shiftVisibleRangeOnNewBar; },
      getVisibleLogicalRange: () => visible,
      setVisibleLogicalRange: (range: typeof visible) => assert.deepEqual(range, visible),
    }),
  });
  assert.equal(carrier.data().length, 1, "engine data omits whitespace");
  refreshOrdinalTimeScale(chart, main, new Map([[carrier, fullCarrier]]));
  assert.deepEqual(writes, [[], fullCarrier]);
  assert.equal(shift, true);
});
