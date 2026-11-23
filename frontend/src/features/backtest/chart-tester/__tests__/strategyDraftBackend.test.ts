import assert from "node:assert/strict";
import test from "node:test";
import {
  createLocalStorageStrategyDraftAdapter, STRATEGY_DRAFT_SCHEMA_VERSION, STRATEGY_DRAFT_STORAGE_KEY, StrategyDraftStore,
  type StrategyDraftRecord, type StrategyDraftStoreAdapter,
} from "../StrategyDraftStore.js";
import {
  createBackendStrategyDraftAdapter, STRATEGY_DRAFT_IMPORT_MARKER, StrategyDraftConflictError, type StrategyDraftClient,
} from "../strategyDraftBackend.js";

function record(id: string, revision: number, source = `src ${revision}`): StrategyDraftRecord {
  return { schemaVersion: STRATEGY_DRAFT_SCHEMA_VERSION, id, revision, displayName: id, language: "pine", source,
    cursor: null, createdAt: 1, updatedAt: 10 + revision };
}

/** The backend's semantics: compare-and-set on the revision; import keeps the newer copy. */
function backend() {
  const drafts = new Map<string, StrategyDraftRecord>();
  const calls: string[] = [];
  let down = false;
  const reachable = () => { if (down) throw new Error("backend unreachable"); };
  const client: StrategyDraftClient = {
    async get(id) { calls.push(`get:${id}`); reachable(); return drafts.get(id) ?? null; },
    async list() { calls.push("list"); reachable(); return [...drafts.values()]; },
    async put(value, expected) {
      calls.push(`put:${value.id}:${expected}:${value.revision}`); reachable();
      const current = drafts.get(value.id);
      if ((current?.revision ?? null) !== expected) throw new StrategyDraftConflictError(current?.revision ?? null);
      drafts.set(value.id, value);
      return value;
    },
    async remove(id) { calls.push(`remove:${id}`); reachable(); drafts.delete(id); },
    async importDrafts(records) {
      calls.push(`import:${records.length}`); reachable();
      const imported: string[] = [], kept: string[] = [];
      for (const value of records) {
        if ((drafts.get(value.id)?.revision ?? -1) >= value.revision) kept.push(value.id);
        else { drafts.set(value.id, value); imported.push(value.id); }
      }
      return { imported, kept };
    },
  };
  return { client, drafts, calls, setDown(value: boolean) { down = value; } };
}

function legacyStorage(records: StrategyDraftRecord[]) {
  const items = new Map<string, string>([[STRATEGY_DRAFT_STORAGE_KEY, JSON.stringify({
    schemaVersion: 1, drafts: Object.fromEntries(records.map((value) => [value.id, value])) })]]);
  const storage = { getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => { items.set(key, value); } };
  return { storage, items, adapter: createLocalStorageStrategyDraftAdapter(storage) };
}

test("browser drafts are imported once and the originals are kept", async () => {
  const server = backend();
  server.drafts.set("draft-newer001", record("draft-newer001", 9, "edited elsewhere"));
  const legacy = legacyStorage([record("draft-legacy01", 3), record("draft-newer001", 2, "stale")]);
  const original = legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY);
  const adapter = createBackendStrategyDraftAdapter(server.client, legacy);
  assert.equal((await adapter.load("draft-legacy01") as StrategyDraftRecord).revision, 3);
  assert.equal(await adapter.imported(), true);
  assert.equal(server.drafts.get("draft-newer001")?.source, "edited elsewhere", "a newer backend copy wins");
  assert.equal(server.drafts.get("draft-legacy01")?.revision, 3);
  assert.equal(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), original, "the original drafts stay");
  assert.ok(legacy.items.get(STRATEGY_DRAFT_IMPORT_MARKER));
  // Another window, or the next launch, does not import again.
  const again = createBackendStrategyDraftAdapter(server.client, legacy);
  await again.list();
  assert.equal(server.calls.filter((call) => call.startsWith("import")).length, 1);
});

test("until the import succeeds, drafts only the browser holds stay readable", async () => {
  const server = backend();
  server.setDown(true);
  const legacy = legacyStorage([record("draft-legacy01", 3)]);
  const adapter = createBackendStrategyDraftAdapter(server.client, legacy);
  assert.equal((await adapter.load("draft-legacy01") as StrategyDraftRecord).source, "src 3");
  assert.deepEqual((await adapter.list() as StrategyDraftRecord[]).map((value) => value.id), ["draft-legacy01"]);
  assert.equal(legacy.items.get(STRATEGY_DRAFT_IMPORT_MARKER), undefined, "a failed import is retried");
  server.setDown(false);
  assert.deepEqual((await adapter.list() as StrategyDraftRecord[]).map((value) => value.id), ["draft-legacy01"]);
  assert.ok(legacy.items.get(STRATEGY_DRAFT_IMPORT_MARKER));
  // After the import the backend alone decides: a removed draft does not come back from the browser copy.
  await adapter.remove("draft-legacy01");
  assert.deepEqual(await adapter.list(), []);
  assert.equal(await adapter.load("draft-legacy01"), null);
});

test("saves are compare-and-set; a save racing another window lands on top of it", async () => {
  const server = backend();
  const store = new StrategyDraftStore(createBackendStrategyDraftAdapter(server.client, null), () => 50);
  const first = await store.save({ id: "draft-shared01", displayName: "A", language: "pine", source: "mine", cursor: null });
  assert.equal(first.revision, 0);
  server.drafts.set("draft-shared01", record("draft-shared01", 4, "other window"));
  const second = await store.save({ id: "draft-shared01", displayName: "A", language: "pine", source: "mine again", cursor: null });
  assert.equal(second.revision, 5, "the store adopts the revision the backend stored");
  assert.equal(server.drafts.get("draft-shared01")?.source, "mine again");
  assert.deepEqual(server.calls.filter((call) => call.startsWith("put")),
    ["put:draft-shared01:null:0", "put:draft-shared01:0:1", "put:draft-shared01:4:5"]);
  const third = await store.save({ id: "draft-shared01", displayName: "A", language: "pine", source: "v3", cursor: null });
  assert.equal(third.revision, 6);
});

test("an unreachable store never rejects a load or a recent list", async () => {
  let down = false;
  const failing: StrategyDraftStoreAdapter = {
    async load() { if (down) throw new Error("backend unreachable"); return null; },
    async list() { if (down) throw new Error("backend unreachable"); return []; },
    async save(value) { return value; },
    async remove() {},
  };
  const store = new StrategyDraftStore(failing, () => 5);
  await store.save({ id: "draft-local001", displayName: "A", language: "pine", source: "kept", cursor: null });
  down = true;
  const view = await store.load("draft-local001");
  assert.deepEqual([view.saveState, view.error, view.record?.source], ["ERROR", "backend unreachable", "kept"]);
  assert.deepEqual((await store.recent()).map((value) => value.id), ["draft-local001"]);
});

test("large imports are sent in bounded batches", async () => {
  const server = backend();
  const many = Array.from({ length: 450 }, (_, index) => record(`draft-bulk${String(index).padStart(4, "0")}`, 1));
  const legacy = legacyStorage(many);
  const adapter = createBackendStrategyDraftAdapter(server.client, legacy);
  assert.equal(await adapter.imported(), true);
  assert.deepEqual(server.calls.filter((call) => call.startsWith("import")), ["import:200", "import:200", "import:50"]);
  assert.equal(server.drafts.size, 450);
});

// Drafts saved by builds before PR #105 may say `language: "pyne"`. They are
// never imported, shown or relabelled, and the browser copy stays as it was.
test("retired Pyne drafts are not imported, listed or rewritten", async () => {
  const server = backend();
  const pyne = { ...record("draft-oldpyne1", 4, "plot(close)"), language: "pyne" } as unknown as StrategyDraftRecord;
  const legacy = legacyStorage([record("draft-current1", 2), pyne]);
  const original = legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY);
  const adapter = createBackendStrategyDraftAdapter(server.client, legacy);
  assert.equal(await adapter.imported(), true);
  assert.deepEqual([...server.drafts.keys()], ["draft-current1"]);
  assert.deepEqual((await adapter.list() as StrategyDraftRecord[]).map((item) => item.id), ["draft-current1"]);
  assert.equal(await legacy.adapter.load("draft-oldpyne1"), null, "never read back as another language");
  assert.equal(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), original, "the original Pyne draft stays byte-identical");
});
