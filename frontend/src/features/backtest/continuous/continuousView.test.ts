import assert from "node:assert/strict";
import test from "node:test";
import { ContinuousViewReducer } from "./continuousView.js";
import { resultKinds, type ContinuousPage, type ResultKind } from "./continuousTypes.js";

export function page(revision = 1, items: ContinuousPage["items"] = [], counts: Partial<Record<ResultKind, number>> = {}): ContinuousPage {
  const identity = { id: "one", generation: 1, revision, checkpoint_revision: revision, sequence: revision, event_time_ms: revision * 60000, data_revision: "source" };
  return { identity, run: { ...identity, phase: "LIVE" }, summary: { valuation: { equity: "100" } }, stale: false,
    counts: { ...Object.fromEntries(resultKinds.map((kind) => [kind, 0])) as Record<ResultKind, number>, ...counts },
    items, more: false, next_cursor: null };
}
const row = (index: number, value: unknown = index) => ({ kind: "fills" as const, index, value });
const start = { snapshot: true, begin: true, complete: true, after: 0 };

test("partial snapshots never replace the last complete view; reset retains it", () => {
  const view = new ContinuousViewReducer("one"), before = page(1, [row(0, "old")], { fills: 1 });
  view.accept(before, start);
  const partial = { ...page(2, [row(0, "new")], { fills: 2 }), more: true, next_cursor: [2, "fills", 0] as ContinuousPage["next_cursor"] };
  assert.equal(view.accept(partial, { ...start, complete: false }), null);
  assert.deepEqual(view.rows("fills", before.identity), ["old"]);
  view.reset(); assert.deepEqual(view.rows("fills", before.identity), ["old"]);
  view.accept(page(2, [row(0, "new"), row(1)], { fills: 2 }), start);
  assert.deepEqual(view.rows("fills", view.current!.identity), ["new", 1]);
  assert.throws(() => view.rows("fills", before.identity), { code: "CONTINUOUS_VIEW_INVALID" });
});

test("multi-page updates replace only changed rows and publish atomically", () => {
  const view = new ContinuousViewReducer("one"), before = page(1, [row(0, "first")], { fills: 1 });
  view.accept(before, start);
  const update = page(2, [row(0, "changed")], { fills: 2 });
  view.accept({ ...update, more: true }, { snapshot: false, begin: true, complete: false, after: 1 });
  assert.deepEqual(view.rows("fills", before.identity), ["first"]);
  view.accept({ ...update, items: [row(1, "second")] }, { snapshot: false, begin: false, complete: true, after: 1 });
  assert.deepEqual(view.rows("fills", update.identity), ["changed", "second"]);
  assert.equal(view.diagnostics().pendingBytes, 0);
});

test("incomplete, duplicate, wrong-run and mixed-commit groups fail without publishing", () => {
  for (const invalid of [page(1, [], { fills: 1 }), page(1, [row(0), row(0)], { fills: 2 }),
    { ...page(), identity: { ...page().identity, id: "other" } }, page(1, [row(2)], { fills: 1 })]) {
    const view = new ContinuousViewReducer("one");
    assert.throws(() => view.accept(invalid, start), { code: "CONTINUOUS_VIEW_INVALID" });
    assert.equal(view.current, null);
  }
  const view = new ContinuousViewReducer("one");
  view.accept({ ...page(1, [row(0)], { fills: 2 }), more: true }, { ...start, complete: false });
  assert.throws(() => view.accept(page(2, [row(1)], { fills: 2 }), { ...start, begin: false }), { code: "CONTINUOUS_VIEW_INVALID" });
  assert.equal(view.current, null);
});

test("incremental baselines and generations are guarded; explicit snapshots can replace a generation", () => {
  const view = new ContinuousViewReducer("one"); view.accept(page(), start);
  assert.throws(() => view.accept(page(2), { snapshot: false, begin: true, complete: true, after: 0 }), { code: "CONTINUOUS_VIEW_INVALID" });
  const replacement = page(); replacement.identity.generation = 2; replacement.run.generation = 2;
  view.reset(); view.accept(replacement, start);
  assert.equal(view.current!.identity.generation, 2);
});

test("stale metadata updates keep prior financial rows at the same checkpoint", () => {
  const view = new ContinuousViewReducer("one"), before = page(1, [row(0, { price: "5" })], { fills: 1 });
  view.accept(before, start);
  const stale = { ...before, identity: { ...before.identity, revision: 2 }, run: { ...before.run, revision: 2, phase: "REPAIR_REQUIRED" }, stale: true, items: [] };
  view.accept(stale, { snapshot: false, begin: true, complete: true, after: 1 });
  assert.equal(view.current!.stale, true); assert.deepEqual(view.rows("fills", stale.identity), [{ price: "5" }]);
  assert.throws(() => { (view.rows("fills", stale.identity)[0] as { price: string }).price = "changed"; }, TypeError);
  assert.throws(() => { view.current!.identity.revision = 999; }, TypeError);
});

test("view memory is bounded and clear drops committed and partial data", () => {
  const view = new ContinuousViewReducer("one", 300); view.accept(page(1, [row(0)], { fills: 1 }), start);
  assert.throws(() => view.accept(page(2, [row(1, "x".repeat(100))], { fills: 2 }), { snapshot: false, begin: true, complete: true, after: 1 }), { code: "BUDGET_EXCEEDED" });
  assert.equal(view.current!.identity.revision, 1); assert.equal(view.diagnostics().pendingBytes, 0);
  view.clear(); assert.equal(view.diagnostics().bytes, 0); assert.equal(view.current, null);
});
