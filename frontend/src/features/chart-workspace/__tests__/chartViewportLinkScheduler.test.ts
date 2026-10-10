import assert from "node:assert/strict";
import test from "node:test";
import { createChartViewportLinkScheduler } from "../useChartViewportLink.js";

function harness() {
  let next = 0;
  const frames = new Map<number, () => void>();
  const delivered: unknown[] = [];
  const scheduler = createChartViewportLinkScheduler({
    publishTimeAnchor: (cell, time) => { delivered.push([cell, "anchor", time]); },
    publishDateRange: (cell, range) => { delivered.push([cell, "range", range]); },
  }, "cell-1", (callback) => { frames.set(++next, callback); return next; },
  (handle) => { frames.delete(handle); });
  return { scheduler, frames, delivered, tick() {
    const ready = [...frames.values()]; frames.clear();
    ready.forEach((callback) => callback());
  } };
}

test("continuous dragging delivers the latest range every frame without waiting for idle", () => {
  const h = harness();
  for (let frame = 0; frame < 120; frame++) {
    for (let event = 0; event < 10; event++) {
      const time = frame * 10 + event;
      h.scheduler.schedule({ time: { from: time, to: time + 100 }, rightmostTime: time + 100 });
    }
    assert.equal(h.frames.size, 1);
    h.tick();
    assert.equal(h.delivered.length, (frame + 1) * 2);
    assert.deepEqual(h.delivered.at(-1), ["cell-1", "range", { from: frame * 10 + 9, to: frame * 10 + 109 }]);
  }
  h.tick();
  assert.equal(h.delivered.length, 240, "idle must not repeat or echo linked updates");
});

test("unmount or scope switch cancels pending updates and permits a fresh gesture", () => {
  const h = harness();
  h.scheduler.schedule({ time: { from: 1, to: 2 } });
  h.scheduler.cancel(); h.tick();
  assert.deepEqual(h.delivered, []);
  h.scheduler.schedule({ time: { from: 3, to: 4 } }); h.tick();
  assert.deepEqual(h.delivered, [["cell-1", "range", { from: 3, to: 4 }]]);
});
