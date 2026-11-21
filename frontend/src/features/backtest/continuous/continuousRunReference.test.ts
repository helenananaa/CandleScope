import assert from "node:assert/strict";
import test from "node:test";
import {
  activateContinuousReference, backendContinuousReferences, CONTINUOUS_REFERENCE_IMPORT_MARKER, continuousArchiveScope, continuousReferenceKey,
  listContinuousReferences, readContinuousReference, saveContinuousReference, type ContinuousRunReference,
} from "./continuousRunReference.js";
import { loadChartStrategyPanelPreferences, saveChartStrategyPanelPreferences } from "../chart-tester/chartStrategyPanelPreferences.js";
function storage(): Storage {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key(index) { return [...values.keys()][index] ?? null; },
    clear() { values.clear(); }, getItem(key) { return values.get(key) ?? null; }, removeItem(key) { values.delete(key); }, setItem(key, value) { values.set(key, value); } };
}
const reference: ContinuousRunReference = { schema: 1, requestKey: "chart/stable", runId: null, inputRevision: "123", createdAtMs: 1,
  settings: { from: "2026-11-01T00:00", balance: "1000", percent: "10", fee: "4", slippage: "1", output: "SIGNAL" } };
test("uncertain creation key and settings survive a new reader; account references remain scope-specific", () => {
  const saved = storage(); saveContinuousReference(saved, "cell/A/history", reference);
  assert.deepEqual(readContinuousReference(saved, "cell/A/history"), reference);
  saveContinuousReference(saved, "cell/A/history", { ...reference, runId: "account" });
  assert.equal(readContinuousReference(saved, "cell/A/history")!.requestKey, "chart/stable");
  assert.equal(readContinuousReference(saved, "cell/A/live"), null); assert.equal(readContinuousReference(saved, "cell/B/history"), null);
});
test("malformed or over-capacity references preserve existing local records", () => {
  const saved = storage(); saved.setItem(continuousReferenceKey("bad"), "{invalid");
  assert.throws(() => readContinuousReference(saved, "bad")); assert.equal(saved.getItem(continuousReferenceKey("bad")), "{invalid");
  for (let index = 0; index < 63; index += 1) saveContinuousReference(saved, String(index), reference);
  assert.throws(() => saveContinuousReference(saved, "overflow", reference), /CAPACITY/);
  saveContinuousReference(saved, "0", { ...reference, runId: "restored" });
  assert.equal(saved.length, 64); assert.equal(readContinuousReference(saved, "0")!.runId, "restored");
});
test("saved run mode survives preference reload and old preferences keep historical default", () => {
  const saved = storage(); saveChartStrategyPanelPreferences("cell", { height: 300, activeTab: "script", runMode: "LIVE_ONLY" }, saved);
  assert.equal(loadChartStrategyPanelPreferences("cell", saved).runMode, "LIVE_ONLY");
  assert.equal(loadChartStrategyPanelPreferences("old", saved).runMode, undefined);
});
test("switching runs retains earlier accounts and uncertain requests within the same series scope", () => {
  const saved = storage(); activateContinuousReference(saved, "cell", reference);
  const next = { ...reference, createdAtMs: 2, requestKey: "chart/new", runId: "next-account" };
  activateContinuousReference(saved, "cell", next);
  assert.deepEqual(listContinuousReferences(saved, "cell").map((value) => value.requestKey), ["chart/new", "chart/stable"]);
  assert.deepEqual(listContinuousReferences(saved, "other-cell"), []);
  saveContinuousReference(saved, continuousArchiveScope("cell", next.requestKey), next);
  assert.equal(listContinuousReferences(saved, "cell").length, 2, "current and archive references are deduplicated");
});

// -- ADR-BACKTEST-015 P3c: references in the backend ---------------------------

function backend(options: { importFails?: boolean } = {}) {
  const values = new Map<string, unknown>();
  const calls: string[] = [];
  return {
    values, calls,
    async loadStrategyReference(_kind: "continuous-run", key: string) { calls.push(`get:${key}`); return values.get(key) ?? null; },
    async listStrategyReferences(_kind: "continuous-run", prefix = "") {
      return [...values].filter(([key]) => key.startsWith(prefix)).map(([key, value]) => ({ key, value }));
    },
    async saveStrategyReference(_kind: "continuous-run", key: string, value: unknown) { calls.push(`put:${key}`); values.set(key, value); },
    async importStrategyReferences(_kind: "continuous-run", entries: Array<{ key: string; value: unknown }>) {
      calls.push(`import:${entries.length}`);
      if (options.importFails) throw new Error("backend unreachable");
      for (const entry of entries) if (!values.has(entry.key)) values.set(entry.key, entry.value);
      return {};
    },
  };
}

test("browser references are imported once into the backend and the originals are kept", async () => {
  const legacy = storage();
  activateContinuousReference(legacy, "cell/A", { ...reference, runId: "cs_a" });
  saveContinuousReference(legacy, continuousArchiveScope("cell/A", "chart/old"), { ...reference, requestKey: "chart/old", createdAtMs: 0 });
  legacy.setItem(continuousReferenceKey("cell/broken"), "{\"schema\":2}");
  legacy.setItem("unrelated", "x");
  const before = new Map([...Array(legacy.length).keys()].map((index) => [legacy.key(index)!, legacy.getItem(legacy.key(index)!)]));
  const server = backend();
  const store = backendContinuousReferences(server, legacy);
  assert.equal((await store.read("cell/A"))?.runId, "cs_a");
  assert.deepEqual((await store.list("cell/A")).map((value) => value.requestKey), ["chart/stable", "chart/old"]);
  assert.deepEqual(server.calls.filter((call) => call.startsWith("import")), ["import:3"], "the invalid entry is skipped");
  assert.ok(legacy.getItem(CONTINUOUS_REFERENCE_IMPORT_MARKER));
  for (const [key, value] of before) assert.equal(legacy.getItem(key), value, "originals stay");
  assert.ok(!CONTINUOUS_REFERENCE_IMPORT_MARKER.startsWith("candlescope.continuous-run.v1:"), "the marker is never read as a reference");
  // Another chart, or the next launch, does not import again; the backend alone decides from now on.
  legacy.setItem(continuousReferenceKey("cell/A"), JSON.stringify({ ...reference, runId: "browser-only" }));
  const again = backendContinuousReferences(server, legacy);
  assert.equal((await again.read("cell/A"))?.runId, "cs_a");
  assert.equal(server.calls.filter((call) => call.startsWith("import")).length, 1);
});

test("until the import succeeds, browser references stay readable; selecting archives first", async () => {
  const legacy = storage();
  activateContinuousReference(legacy, "cell/B", { ...reference, runId: "cs_b" });
  const server = backend({ importFails: true });
  const store = backendContinuousReferences(server, legacy);
  assert.equal((await store.read("cell/B"))?.runId, "cs_b");
  assert.equal(legacy.getItem(CONTINUOUS_REFERENCE_IMPORT_MARKER), null, "a failed import is retried");
  const next = { ...reference, requestKey: "chart/next", runId: "cs_next", createdAtMs: 9 };
  await store.activate("cell/B", next);
  assert.deepEqual(server.calls.filter((call) => call.startsWith("put")), [`put:${continuousArchiveScope("cell/B", "chart/next")}`, "put:cell/B"]);
  assert.deepEqual((await store.list("cell/B")).map((value) => value.requestKey), ["chart/next", "chart/stable"]);
  assert.equal((await store.read("cell/B"))?.runId, "cs_next");
});
