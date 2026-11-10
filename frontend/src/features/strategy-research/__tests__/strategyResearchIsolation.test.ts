import assert from "node:assert/strict";
import test from "node:test";
import { saveResearchHandoff, readResearchHandoff } from "../strategyResearchHandoff.js";
import { StrategyDraftStore, createMemoryStrategyDraftAdapter } from "../../backtest/chart-tester/StrategyDraftStore.js";
import type { ChartStrategyAttachmentRecord } from "../../chart-workspace/chartWorkspaceTypes.js";

for (const language of ["pine", "python"] as const) test(`${language} research edits cannot rewrite the originating chart draft`, async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window"), values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    setItem(key: string, value: string) { values.set(key, value); }, getItem(key: string) { return values.get(key) ?? null; },
  } } });
  const adapter = createMemoryStrategyDraftAdapter(), store = new StrategyDraftStore(adapter);
  try {
    const original = await store.save({ id: "draft-original12", displayName: "Original", language, source: "original source", cursor: { line: 2, column: 3 } });
    const attachment: ChartStrategyAttachmentRecord = { schemaVersion: 1, strategyDraftId: original.id, strategyRevisionId: null,
      displayName: original.displayName, language, parameters: { fast: 8 }, rangeMode: "CUSTOM", customRange: { startMs: 1000, endMs: 2000 },
      fidelityPreference: "PRECISE", quickPresetId: "CRYPTO_PERP_STANDARD_V1", autoRun: false };
    const href = await saveResearchHandoff({ session: { exchange: "binance", marketType: "futures", symbol: "ETHUSDT", interval: "15m" },
      workspaceId: "workspace-main", cellId: "cell-1", attachment, draft: original, runId: null }, store);
    const handoff = readResearchHandoff(new URL(href, "http://localhost").searchParams.get("handoff")!)!;
    const experiment = (await new StrategyDraftStore(adapter).load(handoff.draftId)).record!;
    assert.equal(experiment.source, original.source); assert.equal(experiment.language, language);
    assert.deepEqual(experiment.cursor, original.cursor);
    await store.save({ ...experiment, source: "research edits" });
    assert.deepEqual((await store.load(original.id)).record, original, "Research autosave must preserve the original chart source and revision");
    assert.notEqual(handoff.draftId, original.id);
    await store.save({ ...original, source: "later chart edits" });
    assert.equal((await new StrategyDraftStore(adapter).load(handoff.draftId)).record?.source, "research edits");
    assert.deepEqual(readResearchHandoff(new URL(href, "http://localhost").searchParams.get("handoff")!)!.configuration.parameters, { fast: 8 });
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window");
  }
});

test("handoff freezes clicked code and conditions while the independent draft write is pending", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window"), values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    setItem(key: string, value: string) { values.set(key, value); }, getItem(key: string) { return values.get(key) ?? null; },
  } } });
  const adapter = createMemoryStrategyDraftAdapter();
  let release!: () => void, entered!: () => void;
  const enteredWrite = new Promise<void>((resolve) => { entered = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  const store = new StrategyDraftStore({ ...adapter, async save(record) {
    if (record.id !== "draft-original12") { entered(); await held; }
    await adapter.save(record);
  } });
  try {
    const draft = await store.save({ id: "draft-original12", displayName: "Original", language: "python", source: "clicked code", cursor: null });
    const attachment: ChartStrategyAttachmentRecord = { schemaVersion: 1, strategyDraftId: draft.id, strategyRevisionId: null,
      displayName: draft.displayName, language: "python", parameters: { nested: { period: 8 } }, rangeMode: "CUSTOM", customRange: { startMs: 1000, endMs: 2000 },
      fidelityPreference: "PRECISE", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false };
    const pending = saveResearchHandoff({ session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
      workspaceId: "workspace-main", cellId: "cell-1", attachment, draft, runId: null }, store);
    await enteredWrite; assert.equal(values.size, 0, "No handoff is published before the independent draft is durable");
    draft.source = "later code"; (attachment.parameters.nested as { period: number }).period = 99; attachment.customRange!.endMs = 9000;
    release(); const href = await pending;
    const handoff = readResearchHandoff(new URL(href, "http://localhost").searchParams.get("handoff")!)!;
    assert.equal((await new StrategyDraftStore(adapter).load(handoff.draftId)).record?.source, "clicked code");
    assert.deepEqual(handoff.configuration.parameters, { nested: { period: 8 } });
    assert.deepEqual(handoff.configuration.customRange, { startMs: 1000, endMs: 2000 });
  } finally {
    release(); if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window");
  }
});

test("a failed experiment save publishes no handoff and leaves the chart program intact", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window"), values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    setItem(key: string, value: string) { values.set(key, value); }, getItem(key: string) { return values.get(key) ?? null; },
  } } });
  const adapter = createMemoryStrategyDraftAdapter(), store = new StrategyDraftStore({ ...adapter, async save(record) {
    if (record.id !== "draft-original12") throw new Error("quota"); await adapter.save(record);
  } });
  try {
    const draft = await store.save({ id: "draft-original12", displayName: "Original", language: "python", source: "original", cursor: null });
    const attachment: ChartStrategyAttachmentRecord = { schemaVersion: 1, strategyDraftId: draft.id, strategyRevisionId: null,
      displayName: draft.displayName, language: "python", parameters: {}, rangeMode: "ALL_AVAILABLE", customRange: null,
      fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false };
    await assert.rejects(saveResearchHandoff({ session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
      workspaceId: "workspace-main", cellId: "cell-1", attachment, draft, runId: null }, store), /quota/);
    assert.equal(values.size, 0); assert.deepEqual((await new StrategyDraftStore(adapter).load(draft.id)).record, draft);
    const key = "candlescope:research-handoff:legacy-context";
    values.set(key, JSON.stringify({ source: {}, draftId: draft.id, configuration: { rangeMode: "ALL_AVAILABLE", customRange: null }, runId: null }));
    const before = values.get(key); assert.equal(readResearchHandoff("legacy-context"), null); assert.equal(values.get(key), before);
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window");
  }
});
