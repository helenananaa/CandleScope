import assert from "node:assert/strict";
import test from "node:test";
import { getStrategyStorage } from "../../../../shared/strategyStorage.js";
import { STRATEGY_DRAFT_STORAGE_KEY, createLocalStorageStrategyDraftAdapter, StrategyDraftStore } from "../StrategyDraftStore.js";

test("desktop migrates legacy drafts and restores them with a different origin's empty storage", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const profile = new Map<string, string>();
  const legacy = new Map<string, string>([[STRATEGY_DRAFT_STORAGE_KEY, JSON.stringify({ schemaVersion: 1, drafts: {
    'draft-legacy12': { schemaVersion: 1, id: 'draft-legacy12', revision: 0, displayName: 'Python draft', language: 'python',
      source: 'self.fast = 4', cursor: { line: 2, column: 1 }, createdAt: 1, updatedAt: 1 },
  } })]]);
  const bridge = { getItem: (key: string) => profile.get(key) ?? null,
    setItem: async (key: string, value: string) => { profile.set(key, value); } };
  const mount = (originStorage: Map<string, string>) => Object.defineProperty(globalThis, "window", { configurable: true,
    value: { localStorage: { getItem: (key: string) => originStorage.get(key) ?? null }, candlescopeDesktop: { strategyStorage: bridge } } });
  try {
    mount(legacy);
    const original = new StrategyDraftStore(createLocalStorageStrategyDraftAdapter(getStrategyStorage()!));
    assert.equal((await original.load('draft-legacy12')).record?.source, 'self.fast = 4');
    await original.save({ id: 'draft-legacy12', displayName: 'Python draft', language: 'python', source: 'self.fast = 2', cursor: null });
    await getStrategyStorage()!.setItem('candlescope:strategy-research:v1', '{"draftId":"draft-legacy12"}');
    mount(new Map());
    const restored = new StrategyDraftStore(createLocalStorageStrategyDraftAdapter(getStrategyStorage()!));
    assert.equal((await restored.load('draft-legacy12')).record?.source, 'self.fast = 2');
    assert.equal(getStrategyStorage()!.getItem('candlescope:strategy-research:v1'), '{"draftId":"draft-legacy12"}');
  } finally {
    if (previous) Object.defineProperty(globalThis, 'window', previous);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});
