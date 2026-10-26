import assert from "node:assert/strict";
import test from "node:test";
import {
  attachExternalPriceLineSource,
  createPriceLineSource,
  type ExternalPriceLine,
} from "../externalPriceLineSource.js";

interface FakeLine {
  options: Record<string, unknown>;
  applyOptions(options: Record<string, unknown>): void;
}

function fakeSeries() {
  const live = new Set<FakeLine>();
  let created = 0;
  return {
    live,
    get created() { return created; },
    createPriceLine(options: Record<string, unknown>) {
      created += 1;
      const line: FakeLine = {
        options: { ...options },
        applyOptions(next) { this.options = { ...this.options, ...next }; },
      };
      live.add(line);
      return line;
    },
    removePriceLine(line: FakeLine) {
      live.delete(line);
    },
  };
}

function line(id: string, price: number, extra: Partial<ExternalPriceLine> = {}): ExternalPriceLine {
  return { id, price, color: "red", title: id, style: "dashed", ...extra };
}

function attach(source: ReturnType<typeof createPriceLineSource>, series: ReturnType<typeof fakeSeries>) {
  return attachExternalPriceLineSource({
    source,
    targetSeries: series as unknown as Parameters<typeof attachExternalPriceLineSource>[0]["targetSeries"],
  });
}

test("price lines are created, updated in place and removed by id", () => {
  const source = createPriceLineSource();
  const series = fakeSeries();
  source.setLines([line("entry", 100, { style: "solid" }), line("sl", 95)]);
  const detach = attach(source, series);
  assert.equal(series.live.size, 2);
  const entry = [...series.live].find((item) => item.options.title === "entry")!;
  assert.equal(entry.options.lineStyle, 0);
  assert.equal(entry.options.axisLabelVisible, true);

  source.setLines([line("entry", 101, { style: "solid" }), line("tp", 120)]);
  assert.equal(series.live.size, 2);
  assert.equal(series.created, 3);
  assert.equal(entry.options.price, 101);
  assert.deepEqual([...series.live].map((item) => item.options.title).sort(), ["entry", "tp"]);

  detach();
  assert.equal(series.live.size, 0);
  source.setLines([line("late", 1)]);
  assert.equal(series.live.size, 0);
});

test("identical line sets do not bump the revision; bad prices are skipped", () => {
  const source = createPriceLineSource();
  source.setLines([line("a", 1)]);
  const revision = source.getSnapshot().revision;
  source.setLines([line("a", 1)]);
  assert.equal(source.getSnapshot().revision, revision);

  const series = fakeSeries();
  source.setLines([line("a", Number.NaN), line("b", 2), line("b", 3)]);
  attach(source, series);
  assert.deepEqual([...series.live].map((item) => item.options.price), [2]);
});
