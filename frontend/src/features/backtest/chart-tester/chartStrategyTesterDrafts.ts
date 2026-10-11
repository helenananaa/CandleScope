import { CHART_STRATEGY_TEMPLATES } from "./chartStrategyTesterUiModel.js";
import { getStrategyStorage } from "../../../shared/strategyStorage.js";
import {
  StrategyDraftStore,
  createLocalStorageStrategyDraftAdapter,
  createMemoryStrategyDraftAdapter,
} from "./StrategyDraftStore.js";

let browserStore: StrategyDraftStore | null = null;

export function getChartStrategyDraftStore(): StrategyDraftStore {
  if (browserStore) return browserStore;
  let adapter = createMemoryStrategyDraftAdapter();
  if (typeof window !== "undefined") {
    try {
      const storage = getStrategyStorage();
      if (storage) adapter = createLocalStorageStrategyDraftAdapter(storage);
    } catch {
      // Some embedded/private browser contexts expose localStorage but reject access.
    }
  }
  browserStore = new StrategyDraftStore(adapter);
  return browserStore;
}

export function createChartStrategyDraftId(randomValue?: string): string {
  const entropy = randomValue
    ?? globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random()}`;
  const normalized = entropy.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 152);
  return `draft-${normalized.padEnd(8, "0")}`;
}

export function strategyDraftContentRevision(source: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Preserve an existing Python program when entering from the Pine/Pyne language menu. */
export async function openPythonStrategyDraft(store: StrategyDraftStore, draftId: string | null) {
  const existing = draftId ? (await store.load(draftId)).record : null;
  if (existing?.language === "python") return existing;
  const template = CHART_STRATEGY_TEMPLATES.find((item) => item.id === "PYTHON_SMA")!;
  return store.save({ id: createChartStrategyDraftId(), displayName: template.displayName, language: "python", source: template.source, cursor: { line: 1, column: 1 } });
}
