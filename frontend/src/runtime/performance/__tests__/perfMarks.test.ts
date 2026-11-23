import assert from "node:assert/strict";
import { performance, PerformanceObserver } from "node:perf_hooks";
import { setImmediate } from "node:timers/promises";
import test from "node:test";

import { buildPerfReport, markPerf, measurePerf } from "../perfMarks.js";

test("repeated computation timing retains bounded entries without losing observer events", async t => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: { performance } });
  const names = ["indicator.compute.start", "indicator.compute.end", "qa.compute.duration"] as const;
  let observed = 0;
  const observer = new PerformanceObserver(list => { observed += list.getEntries().length; });
  observer.observe({ entryTypes: ["mark"] });
  t.after(() => {
    observer.disconnect();
    names.forEach(name => { performance.clearMarks(name); performance.clearMeasures(name); });
    if (descriptor) Object.defineProperty(globalThis, "window", descriptor);
    else Reflect.deleteProperty(globalThis, "window");
  });
  for (let index = 0; index < 5_000; index++) {
    markPerf("indicator.compute.start", { index });
    markPerf("indicator.compute.end", { index });
    assert.notEqual(measurePerf(names[2], names[0], names[1]), null);
  }
  await setImmediate();
  assert.equal(observed, 10_000, "a live observer still receives every computation mark");
  assert.equal(performance.getEntriesByName(names[0]).length, 1);
  assert.equal(performance.getEntriesByName(names[1]).length, 1);
  assert.equal(performance.getEntriesByName(names[2]).length, 1);
  const report = buildPerfReport();
  assert.equal(report?.events.length, 240);
  assert.deepEqual(report?.marks[names[1]]?.detail, { index: 4_999 });
  assert.equal(typeof report?.timings.indicatorComputeMs, "number");
});
