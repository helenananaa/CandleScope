import assert from "node:assert/strict";
import test from "node:test";

import {
  ChartWorkDroppedError,
  ChartWorkScheduler,
} from "../chartWorkScheduler.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((onResolve) => { resolve = onResolve; });
  return { promise, resolve };
}

async function turn(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

test("the default display budget serves both visible charts in the first frame", () => {
  const frames: Array<() => void> = [];
  const painted: string[] = [];
  const scheduler = new ChartWorkScheduler({ requestFrame: cb => frames.push(cb), cancelFrame: () => {} });
  scheduler.registerCell("a", "focused");
  scheduler.registerCell("b", "visible-secondary");
  for (const id of ["a", "b"]) scheduler.enqueueFrame(id, "candle-display", "bars", () => painted.push(id));
  frames.shift()!();
  assert.deepEqual(painted, ["a", "b"]);
});

test("hidden display work resumes without requiring another market event", () => {
  const frames: Array<() => void> = [];
  const painted: number[] = [];
  const scheduler = new ChartWorkScheduler({ requestFrame: cb => frames.push(cb), cancelFrame: () => {} });
  scheduler.registerCell("a", "hidden");
  scheduler.enqueueFrame("a", "candle-display", "bars", () => painted.push(1));
  scheduler.enqueueFrame("a", "candle-display", "bars", () => painted.push(2));
  assert.equal(frames.length, 0);
  scheduler.setCellTier("a", "focused");
  frames.shift()?.();
  assert.deepEqual(painted, [2]);
});

test("display precedes preview and an expensive frame yields without an empty frame or secondary starvation", () => {
  let now = 0;
  const frames: Array<() => void> = [], painted: string[] = [];
  const scheduler = new ChartWorkScheduler({ now: () => now, requestFrame: cb => frames.push(cb), cancelFrame: () => {} });
  scheduler.registerCell("a", "focused"); scheduler.registerCell("b", "visible-secondary");
  scheduler.enqueueFrame("a", "indicator-preview", "rsi", () => painted.push("preview"));
  scheduler.enqueueFrame("a", "candle-display", "bars", () => { painted.push("a"); now += 12; });
  scheduler.enqueueFrame("b", "candle-display", "bars", () => painted.push("b"));
  frames.shift()!();
  assert.deepEqual(painted, ["a"]);
  now = 40;
  scheduler.enqueueFrame("a", "candle-display", "bars", () => painted.push("a-next"));
  frames.shift()!();
  assert.deepEqual(painted, ["a", "b", "a-next"]);
  frames.shift()!();
  assert.deepEqual(painted, ["a", "b", "a-next", "preview"]);
});

test("replaceable Canvas fan-out is staggered across bounded animation frames", () => {
  const frames: Array<() => void> = [];
  const commits: string[] = [];
  const scheduler = new ChartWorkScheduler({
    maxFrameTasksPerFrame: 2,
    yieldFrameBetweenTasks: false,
    requestFrame: (callback) => {
      frames.push(callback);
      return frames.length;
    },
    cancelFrame: () => undefined,
  });
  for (let index = 1; index <= 5; index += 1) {
    const cellId = `cell-${index}`;
    scheduler.registerCell(cellId, "visible-secondary");
    scheduler.enqueueFrame(cellId, "candle-display", "BTCUSDT@1m", () => {
      commits.push(cellId);
    });
  }

  frames[0]?.();
  assert.deepEqual(commits, ["cell-1", "cell-2"]);
  assert.equal(scheduler.diagnostics().pendingFrames, 3);
  frames[1]?.();
  assert.deepEqual(commits, ["cell-1", "cell-2", "cell-3", "cell-4"]);
  assert.equal(scheduler.diagnostics().pendingFrames, 1);
  frames[2]?.();
  assert.deepEqual(commits, ["cell-1", "cell-2", "cell-3", "cell-4", "cell-5"]);
  assert.equal(scheduler.diagnostics().pendingFrames, 0);
});

test("hidden and minimized Cells run no replaceable Canvas or preview work", () => {
  const frames: Array<() => void> = [];
  const scheduler = new ChartWorkScheduler({
    requestFrame: (callback) => {
      frames.push(callback);
      return frames.length;
    },
    cancelFrame: () => undefined,
  });
  scheduler.registerCell("cell-a", "hidden");
  assert.equal(scheduler.enqueueFrame("cell-a", "indicator-preview", "rsi", () => {}), false);
  scheduler.setCellTier("cell-a", "visible-secondary");
  assert.equal(scheduler.enqueueFrame("cell-a", "indicator-preview", "rsi", () => {}), true);
  scheduler.setWindowVisible(false);
  frames[0]?.();
  assert.equal(scheduler.diagnostics().pendingFrames, 0);
  assert.equal(scheduler.diagnostics().cells[0]?.tier, "minimized");
  assert.equal(scheduler.diagnostics().cells[0]?.dropped, 2);
  assert.equal(scheduler.diagnostics().cells[0]?.committed["indicator-preview"] || 0, 0);
});

test("equal tier and lane tasks are selected round-robin without first-Cell starvation", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  scheduler.registerCell("cell-a", "visible-secondary");
  scheduler.registerCell("cell-b", "visible-secondary");
  scheduler.registerCell("cell-c", "visible-secondary");
  const first = deferred<void>();
  const order: string[] = [];

  const a1 = scheduler.run("cell-a", "load-more", async () => {
    order.push("a1");
    await first.promise;
  });
  const a2 = scheduler.run("cell-a", "load-more", () => { order.push("a2"); });
  const b1 = scheduler.run("cell-b", "load-more", () => { order.push("b1"); });
  const c1 = scheduler.run("cell-c", "load-more", () => { order.push("c1"); });
  await turn();
  assert.deepEqual(order, ["a1"]);
  first.resolve();
  await Promise.all([a1, a2, b1, c1]);
  assert.deepEqual(order, ["a1", "b1", "c1", "a2"]);
});

test("async lanes honor tier and lane priority and expose bounded per-Cell diagnostics", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  scheduler.registerCell("secondary", "visible-secondary");
  scheduler.registerCell("focused", "focused");
  const blocker = deferred<void>();
  const order: string[] = [];

  const active = scheduler.run("focused", "load-more", async () => {
    order.push("active");
    await blocker.promise;
  });
  await turn();
  const secondaryInitial = scheduler.run("secondary", "initial-history", () => { order.push("secondary-initial"); });
  const focusedPrefetch = scheduler.run("focused", "prefetch", () => { order.push("focused-prefetch"); });
  const focusedInitial = scheduler.run("focused", "initial-history", () => { order.push("focused-initial"); });
  await turn();
  blocker.resolve();
  await Promise.all([active, secondaryInitial, focusedPrefetch, focusedInitial]);
  assert.deepEqual(order, ["active", "focused-initial", "focused-prefetch", "secondary-initial"]);
  assert.equal(scheduler.diagnostics().pendingAsync, 0);
  assert.equal(scheduler.diagnostics().cells.length, 2);
});

test("active hydration is serialized without consuming foreground concurrency", async () => {
  const scheduler = new ChartWorkScheduler({
    maxConcurrent: 4,
    maxConcurrentHydration: 1,
  });
  const first = deferred<void>();
  const order: string[] = [];
  const hydrationA = scheduler.run("cell-a", "active-hydration", async () => {
    order.push("hydrate-a");
    await first.promise;
  });
  const hydrationB = scheduler.run("cell-b", "active-hydration", () => {
    order.push("hydrate-b");
  });
  const foreground = scheduler.run("cell-c", "initial-history", () => {
    order.push("foreground");
  });
  await turn();
  assert.deepEqual(order, ["foreground", "hydrate-a"]);
  assert.equal(scheduler.diagnostics().activeHydration, 1);
  first.resolve();
  await Promise.all([hydrationA, hydrationB, foreground]);
  assert.deepEqual(order, ["foreground", "hydrate-a", "hydrate-b"]);
  assert.equal(scheduler.diagnostics().activeHydration, 0);
});

test("hidden speculative lanes fail closed while authoritative history remains schedulable", async () => {
  const scheduler = new ChartWorkScheduler();
  scheduler.registerCell("cell-a", "hidden");
  await assert.rejects(
    scheduler.run("cell-a", "prefetch", () => "unexpected"),
    (error: unknown) => error instanceof ChartWorkDroppedError,
  );
  assert.equal(await scheduler.run("cell-a", "load-more", () => "retained"), "retained");
});

test("dispose rejects queued work and clears frame/tier state", async () => {
  const scheduler = new ChartWorkScheduler({ maxConcurrent: 1 });
  const blocker = deferred<void>();
  const active = scheduler.run("cell-a", "load-more", () => blocker.promise);
  const queued = scheduler.run("cell-b", "load-more", () => undefined);
  await turn();
  scheduler.dispose();
  await assert.rejects(queued, (error: unknown) => error instanceof ChartWorkDroppedError);
  blocker.resolve();
  await active;
  await turn();
  assert.deepEqual(scheduler.diagnostics(), {
    activeAsync: 0,
    activeHydration: 0,
    cells: [],
    disposed: true,
    pendingAsync: 0,
    pendingFrames: 0,
    runnableFrames: 0,
    windowVisible: true,
  });
});

test("async lanes hold and always release an app-level window budget lease", async () => {
  const actions: string[] = [];
  const scheduler = new ChartWorkScheduler({
    appBudget: {
      acquire: async (cellId, lane) => {
        actions.push(`acquire:${cellId}:${lane}`);
        return "lease-1";
      },
      release: (lease) => { actions.push(`release:${lease}`); },
    },
  });
  const result = await scheduler.run("cell-a", "initial-history", () => {
    actions.push("work");
    return 42;
  });
  await turn();
  assert.equal(result, 42);
  assert.deepEqual(actions, [
    "acquire:cell-a:initial-history",
    "work",
    "release:lease-1",
  ]);
});
