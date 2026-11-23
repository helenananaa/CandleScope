import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { t } from "../../../../i18n/index.js";
import { createDefaultChartWorkspaceRecord } from "../../../chart-workspace/chartWorkspaceLibrary.js";
import { createChartWorkspaceRepository } from "../../../chart-workspace/chartWorkspaceRepository.js";
import {
  chartWorkspaceCell,
  removeChartWorkspaceCellRetiredStrategyAttachment,
  updateChartWorkspaceCellStrategyAttachment,
} from "../../../chart-workspace/chartWorkspaceDocument.js";
import { normalizeChartWorkspaceWithDiagnostics } from "../../../chart-workspace/chartWorkspaceStorage.js";
import type { ChartStrategyAttachmentRecord, ChartWorkspaceLibrarySnapshot } from "../../../chart-workspace/chartWorkspaceTypes.js";
import { normalizeNativeStrategies, withoutRetiredStrategy } from "../../native/nativeStrategyCollection.js";
import { RetiredStrategyDraftList } from "../RetiredStrategyDraftList.js";
import { RetiredStrategySwitcherSection } from "../StrategySwitcher.js";
import {
  createLocalStorageStrategyDraftAdapter, STRATEGY_DRAFT_STORAGE_KEY, StrategyDraftStore, type StrategyDraftRecord,
} from "../StrategyDraftStore.js";
import { createBackendStrategyDraftAdapter, STRATEGY_DRAFT_IMPORT_MARKER, type StrategyDraftClient } from "../strategyDraftBackend.js";
import { strategyLanguageLabel } from "../strategyLanguageLabel.js";

// Builds before PR #105 (2026-10-26), including the 0.3.0 build of 2026-10-25, saved Pyne strategies
// as browser drafts, chart attachments and native strategy entries with `language: "pyne"`.
const PYNE_SOURCE = "strategy.entry_when(close > ta.sma(close, 20))\n";
const pyneDraft = {
  schemaVersion: 1, id: "draft-oldpyne1", revision: 4, displayName: "My Pyne Cross", language: "pyne",
  source: PYNE_SOURCE, cursor: { line: 2, column: 1 }, createdAt: 1_760_000_000_000, updatedAt: 1_761_000_000_000,
};
const pineDraft: StrategyDraftRecord = {
  schemaVersion: 1, id: "draft-current1", revision: 2, displayName: "Pine SMA", language: "pine",
  source: "//@version=6\nstrategy('SMA')", cursor: null, createdAt: 1_760_000_000_000, updatedAt: 1_760_500_000_000,
};
const pyneAttachment = {
  schemaVersion: 1, strategyDraftId: "draft-oldpyne1", strategyRevisionId: null, displayName: "My Pyne Cross",
  language: "pyne", parameters: { fast: 9, slow: 21 }, rangeMode: "ALL_AVAILABLE", customRange: null,
  fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: true,
};
const pineAttachment: ChartStrategyAttachmentRecord = {
  ...pyneAttachment, schemaVersion: 1, strategyDraftId: "draft-current1", displayName: "Pine SMA", language: "pine",
  rangeMode: "ALL_AVAILABLE", fidelityPreference: "FAST", autoRun: false,
};
const pyneNative = { id: "old-pyne", name: "Old Pyne", language: "pyne", drafts: { "pyne:NATIVE": PYNE_SOURCE }, runs: {} };
const pineNative = { id: "pine-1", name: "Pine one", language: "pine", drafts: {}, runs: {} };

function draftStorage() {
  const items = new Map<string, string>([[STRATEGY_DRAFT_STORAGE_KEY, JSON.stringify({
    schemaVersion: 1, drafts: { [pyneDraft.id]: pyneDraft, [pineDraft.id]: pineDraft },
  })]]);
  const storage = { getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => { items.set(key, value); } };
  return { items, storage, adapter: createLocalStorageStrategyDraftAdapter(storage) };
}

function draftServer() {
  const drafts = new Map<string, StrategyDraftRecord>();
  const sent: string[] = [];
  const client: StrategyDraftClient = {
    async get(id) { sent.push(`get:${id}`); return drafts.get(id) ?? null; },
    async list() { sent.push("list"); return [...drafts.values()]; },
    async put(value) { sent.push(`put:${value.id}`); drafts.set(value.id, value); return value; },
    async remove(id) { sent.push(`remove:${id}`); drafts.delete(id); },
    async importDrafts(records) {
      sent.push(`import:${records.map((value) => `${value.id}:${value.language}`).join(",")}`);
      records.forEach((value) => drafts.set(value.id, value));
      return { imported: records.map((value) => value.id), kept: [] };
    },
  };
  return { client, drafts, sent };
}

/** The stored text of one draft inside the envelope, as the old build wrote it. */
function storedDraftText(envelope: string | undefined, id: string): string | undefined {
  return envelope ? JSON.stringify((JSON.parse(envelope) as { drafts: Record<string, unknown> }).drafts[id]) : undefined;
}

test("a retired Pyne draft is listed as retired but never opened, imported or relabelled", async () => {
  const legacy = draftStorage();
  const original = legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY);
  const server = draftServer();
  const store = new StrategyDraftStore(createBackendStrategyDraftAdapter(server.client, legacy));

  assert.deepEqual(await store.retired(), [{
    id: pyneDraft.id, displayName: "My Pyne Cross", language: "pyne", updatedAt: pyneDraft.updatedAt,
  }]);
  assert.deepEqual((await store.recent(20)).map((draft) => [draft.id, draft.language]), [[pineDraft.id, "pine"]]);
  assert.equal((await store.load(pyneDraft.id)).record, null, "it cannot be opened in the editor");
  assert.deepEqual(server.sent.filter((call) => call.startsWith("import")), [`import:${pineDraft.id}:pine`]);
  assert.ok(!server.drafts.has(pyneDraft.id), "the backend never receives it");
  assert.notEqual(legacy.items.get(STRATEGY_DRAFT_IMPORT_MARKER), undefined);
  // After the import the backend is authoritative, but the retired draft is still listed from the browser copy.
  assert.deepEqual((await store.retired()).map((draft) => draft.id), [pyneDraft.id]);
  assert.equal(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), original, "the stored drafts stay byte-identical");
});

test("browser-draft writes keep a retired draft exactly as stored, and only the user deletes it", async () => {
  const legacy = draftStorage();
  const pyneText = storedDraftText(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), pyneDraft.id);
  await legacy.adapter.save({ ...pineDraft, revision: 3, source: "//@version=6\nstrategy('SMA 2')" });
  await legacy.adapter.remove("draft-missing1");
  assert.equal(storedDraftText(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), pyneDraft.id), pyneText);
  await assert.rejects(legacy.adapter.save({ ...pineDraft, id: pyneDraft.id }), /retired/,
    "a save cannot replace the Pyne draft with a Pine one");
  await legacy.adapter.remove(pyneDraft.id);
  assert.equal(storedDraftText(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), pyneDraft.id), pyneText,
    "the normal delete does not reach it");

  const server = draftServer();
  const store = new StrategyDraftStore(createBackendStrategyDraftAdapter(server.client, legacy));
  await store.removeRetired(pineDraft.id);
  assert.ok(storedDraftText(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), pineDraft.id), "only retired drafts are removed this way");
  await store.removeRetired(pyneDraft.id);
  assert.equal(storedDraftText(legacy.items.get(STRATEGY_DRAFT_STORAGE_KEY), pyneDraft.id), undefined);
  assert.deepEqual(await store.retired(), []);
  assert.ok(!server.sent.some((call) => call.includes(pyneDraft.id)), "deleting it never involves the backend");
});

test("the draft list shows a retired draft with a Retired label and a delete, never as Pine", () => {
  const html = renderToStaticMarkup(<RetiredStrategyDraftList locale="en" onDelete={() => undefined}
    drafts={[{ id: pyneDraft.id, displayName: "My Pyne Cross", language: "pyne", updatedAt: pyneDraft.updatedAt }]} />);
  assert.match(html, /data-retired="true"/);
  assert.match(html, /data-draft-id="draft-oldpyne1"/);
  assert.ok(html.includes("My Pyne Cross"));
  assert.ok(html.includes(t("strategyCollection.retiredBadge")));
  assert.ok(html.includes(t("strategyCollection.pyneRetired")));
  assert.ok(html.includes(t("chartTester.deleteRetiredDraft", { name: "My Pyne Cross" })));
  const labels = html.replace(t("strategyCollection.pyneRetired"), "");
  assert.ok(!labels.includes(strategyLanguageLabel("pine")) && !labels.includes("Python"), "no language label but the notice");
  assert.doesNotMatch(html, /chart-strategy-start-row|chart-strategy-run-button/, "it is not an openable or runnable row");
  assert.equal(renderToStaticMarkup(<RetiredStrategyDraftList locale="en" onDelete={() => undefined} drafts={[]} />), "");
});

function oldWorkspaceRecord(): unknown {
  const record = JSON.parse(JSON.stringify(createDefaultChartWorkspaceRecord(1_761_000_000_000))) as {
    document: { cells: Record<string, Record<string, unknown>> };
  };
  const cell = record.document.cells["cell-1"]!;
  (cell.session as Record<string, unknown>).symbol = "ETHUSDT";
  cell.strategyAttachment = pyneAttachment;
  cell.strategyTesterMode = "NATIVE";
  cell.nativeStrategies = { activeId: "old-pyne", items: [pyneNative, pineNative] };
  return record;
}

async function loadOldWorkspace() {
  const raw = oldWorkspaceRecord();
  const stored = JSON.stringify(raw);
  const saved: ChartWorkspaceLibrarySnapshot[] = [];
  const repository = createChartWorkspaceRepository({
    storage: null,
    adapter: {
      loadV7Records: async () => [raw],
      compareAndSwapV7Library: async (snapshot) => { saved.push(JSON.parse(JSON.stringify(snapshot)) as ChartWorkspaceLibrarySnapshot); },
    },
  });
  const library = await repository.loadLibrary();
  return { raw, stored, repository, library, saved, cell: chartWorkspaceCell(library.workspaces[0]!.document, "cell-1") };
}

test("an old workspace keeps its Pyne attachment and native entry as retired instead of resetting", async () => {
  const { raw, stored, cell } = await loadOldWorkspace();
  assert.equal(JSON.stringify(raw), stored, "loading does not mutate the stored record");
  // Before this change the invalid attachment made the whole workspace fall back to the default.
  const normalized = normalizeChartWorkspaceWithDiagnostics((raw as { document: unknown }).document);
  assert.deepEqual([normalized.usedFallback, normalized.diagnostics], [false, []]);
  assert.equal(cell.session.symbol, "ETHUSDT", "the rest of the chart is the user's");
  assert.equal(cell.strategyAttachment, null, "nothing attached can run");
  assert.deepEqual(cell.retiredStrategyAttachment, pyneAttachment, "the reference is kept as stored");
  assert.deepEqual(cell.nativeStrategies?.items.map((item) => [item.id, item.language]), [["pine-1", "pine"]]);
  assert.equal(cell.nativeStrategies?.activeId, "pine-1", "the retired entry is never the selected strategy");
  assert.deepEqual(cell.nativeStrategies?.retired, [pyneNative]);
});

test("saving and reloading the workspace keeps the retired references", async () => {
  const { repository, library, saved } = await loadOldWorkspace();
  await repository.saveLibrary(library);
  const savedCell = chartWorkspaceCell(saved.at(-1)!.workspaces[0]!.document, "cell-1");
  assert.deepEqual(savedCell.retiredStrategyAttachment, pyneAttachment);
  assert.deepEqual(savedCell.nativeStrategies?.retired, [pyneNative]);
  const reloaded = normalizeChartWorkspaceWithDiagnostics(JSON.parse(JSON.stringify(saved.at(-1)!.workspaces[0]!.document)));
  assert.equal(reloaded.usedFallback, false);
  const cell = chartWorkspaceCell(reloaded.document, "cell-1");
  assert.deepEqual([cell.strategyAttachment, cell.retiredStrategyAttachment], [null, pyneAttachment]);
  assert.deepEqual(normalizeNativeStrategies(cell.nativeStrategies), cell.nativeStrategies, "normalizing again changes nothing");
});

test("attaching a new strategy keeps the retired reference; only the user's remove drops it", async () => {
  const { library } = await loadOldWorkspace();
  const document = library.workspaces[0]!.document;
  const attached = updateChartWorkspaceCellStrategyAttachment(document, "cell-1", pineAttachment);
  assert.deepEqual(chartWorkspaceCell(attached, "cell-1").strategyAttachment, pineAttachment);
  assert.deepEqual(chartWorkspaceCell(attached, "cell-1").retiredStrategyAttachment, pyneAttachment);
  const detached = updateChartWorkspaceCellStrategyAttachment(attached, "cell-1", null);
  assert.deepEqual(chartWorkspaceCell(detached, "cell-1").retiredStrategyAttachment, pyneAttachment);
  const removed = removeChartWorkspaceCellRetiredStrategyAttachment(detached, "cell-1");
  assert.equal(chartWorkspaceCell(removed, "cell-1").retiredStrategyAttachment, undefined);
  assert.equal(removeChartWorkspaceCellRetiredStrategyAttachment(removed, "cell-1"), removed);

  const native = chartWorkspaceCell(document, "cell-1").nativeStrategies!;
  const withoutPyne = withoutRetiredStrategy(native, "old-pyne");
  assert.equal(withoutPyne.retired, undefined);
  assert.deepEqual(withoutPyne.items, native.items);
  assert.equal(withoutRetiredStrategy(native, "pine-1").retired?.length, 1);
});

test("removing a native strategy keeps the retired entries", () => {
  const collection = normalizeNativeStrategies({ activeId: "pine-1", items: [pyneNative, pineNative] });
  const removed = normalizeNativeStrategies({ ...collection, items: [] });
  assert.deepEqual(removed.items, []);
  assert.deepEqual(removed.retired, [pyneNative]);
});

test("the strategy menu lists retired entries with a Retired label, never as Pine or a strategy to pick", () => {
  const removed: string[] = [];
  const html = renderToStaticMarkup(<RetiredStrategySwitcherSection onRemove={(item) => removed.push(item.id)}
    items={[{ id: "old-pyne", name: "Old Pyne", onRemove: () => undefined }, { id: "listed", name: "Listed only" }]} />);
  assert.equal((html.match(/data-retired="true"/g) ?? []).length, 2);
  assert.ok(html.includes("Old Pyne") && html.includes(t("strategyCollection.retiredBadge")));
  assert.ok(html.includes(t("strategyCollection.pyneRetired")));
  assert.ok(!html.replace(t("strategyCollection.pyneRetired"), "").includes(t("chartTester.language.pine")));
  assert.doesNotMatch(html, /menuitemradio|aria-checked/, "a retired entry cannot be selected");
  assert.equal((html.match(/role="menuitem"/g) ?? []).length, 1, "only entries with a remove offer one");
  assert.ok(html.includes(t("strategyCollection.removeRetired", { name: "Old Pyne" })));
});
