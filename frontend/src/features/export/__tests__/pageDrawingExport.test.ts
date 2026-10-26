import assert from "node:assert/strict";
import test from "node:test";
import type { ChartSurfaceActions } from "../../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntimeExportLease } from "../../drawings/useDrawingRuntime.js";
import { PageDrawingExportRegistry } from "../pageDrawingExport.js";
import { sameDrawingExportTarget } from "../useExportRuntime.js";

function drawing(scopeKey: string, revision = 1) {
  let restoreCount = 0;
  let valid = true;
  const lease = {
    leaseId: 1,
    receipt: { scopeKey, documentRevision: revision, scene: { kind: "legacy-frame" } },
    revalidate: async () => valid,
    restore: async () => { restoreCount++; },
  } as unknown as DrawingRuntimeExportLease;
  const surface = { prepareExport: async () => lease } as unknown as ChartSurfaceActions;
  return { lease, surface, restored: () => restoreCount, invalidate: () => { valid = false; } };
}

test("whole-page capture owns other charts and restores every main/subpane barrier once", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  const other = drawing("SOL-with-RSI");
  let hidden: boolean | undefined;
  registry.register("active", { prepareExport: async () => { throw new Error("active must not be acquired twice"); } } as unknown as ChartSurfaceActions);
  registry.register("other", { prepareExport: async (options) => { hidden = options?.hideDrawings; return other.lease; } } as ChartSurfaceActions);
  const page = await registry.prepare("active", active.lease, { hideDrawings: true });
  assert.equal(hidden, true);
  assert.equal(await page.revalidate(), true);
  assert.equal(page.receipt, active.lease.receipt);
  other.invalidate();
  assert.equal(await page.revalidate(), false);
  await page.restore();
  await page.restore();
  assert.equal(active.restored(), 1);
  assert.equal(other.restored(), 1);
  assert.equal(await page.revalidate(), false);
});

test("changed membership invalidates capture and stale unregistration cannot remove replacement", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  const old = drawing("SOL");
  registry.register("active", active.surface);
  const removeOld = registry.register("other", old.surface);
  const page = await registry.prepare("active", active.lease, {});
  registry.register("other", drawing("LTC").surface);
  removeOld();
  assert.equal(await page.revalidate(), false);
  await page.restore();
  const replacement = await registry.prepare("active", drawing("DOGE").lease, {});
  assert.match(replacement.pageTargetsKey!, /LTC/);
  await replacement.restore();
});

test("failed peer preparation waits for and restores late successful peers and active chart", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  const late = drawing("SOL");
  let resolveLate!: (lease: DrawingRuntimeExportLease) => void;
  registry.register("active", active.surface);
  registry.register("late", { prepareExport: () => new Promise((resolve) => { resolveLate = resolve; }) } as ChartSurfaceActions);
  registry.register("broken", { prepareExport: async () => { throw new Error("scene failed"); } } as unknown as ChartSurfaceActions);
  const preparation = registry.prepare("active", active.lease, {});
  resolveLate(late.lease);
  await assert.rejects(preparation, /Page drawing preparation failed/);
  assert.equal(active.restored(), 1);
  assert.equal(late.restored(), 1);
});

test("abort restores every acquired lease, even when peers finish after cancellation", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  const peer = drawing("SOL");
  const controller = new AbortController();
  registry.register("active", active.surface);
  registry.register("peer", { prepareExport: async () => { controller.abort(); return peer.lease; } } as unknown as ChartSurfaceActions);
  await assert.rejects(registry.prepare("active", active.lease, { signal: controller.signal }), { name: "AbortError" });
  assert.equal(active.restored(), 1);
  assert.equal(peer.restored(), 1);
});

test("peer not ready or unmounted never silently exports an incomplete drawing page", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  registry.register("active", active.surface);
  registry.register("peer", { prepareExport: async () => null } as unknown as ChartSurfaceActions);
  await assert.rejects(registry.prepare("active", active.lease, {}), /Page drawing preparation failed/);
  assert.equal(active.restored(), 1);
});

test("a restoration failure does not strand the remaining charts", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  const peer = drawing("SOL");
  registry.register("active", active.surface);
  registry.register("peer", peer.surface);
  const page = await registry.prepare("active", { ...active.lease, restore: async () => { throw new Error("restore failed"); } }, {});
  await assert.rejects(page.restore(), /Page drawing restoration failed/);
  assert.equal(peer.restored(), 1);
});

test("saving a page preview checks other charts' revisions, visibility and membership", async () => {
  const registry = new PageDrawingExportRegistry();
  const active = drawing("DOGE");
  registry.register("active", active.surface);
  registry.register("peer", drawing("SOL", 1).surface);
  const first = await registry.prepare("active", active.lease, {});
  const before = { scopeKey: "DOGE", documentRevision: 1, pageTargetsKey: first.pageTargetsKey! };
  await first.restore();
  registry.register("peer", drawing("SOL", 2).surface);
  const second = await registry.prepare("active", drawing("DOGE").lease, {});
  const after = { ...before, pageTargetsKey: second.pageTargetsKey! };
  assert.equal(sameDrawingExportTarget(before, after), false);
  await second.restore();
  const hidden = drawing("SOL", 2);
  registry.register("peer", { prepareExport: async () => ({ ...hidden.lease,
    receipt: { ...hidden.lease.receipt, scene: { kind: "hidden-frame" } },
  }) } as unknown as ChartSurfaceActions);
  const third = await registry.prepare("active", drawing("DOGE").lease, {});
  assert.notEqual(third.pageTargetsKey, second.pageTargetsKey);
  await third.restore();
});
