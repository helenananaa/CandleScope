import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { createDefaultChartWorkspaceRecord } from "../chart-workspace/chartWorkspaceLibrary.js";
import {
  CHART_WORKSPACE_FALLBACK_LIBRARY_KEY,
  createChartWorkspaceRepository,
  type ChartWorkspaceKeyValueStorage,
} from "../chart-workspace/chartWorkspaceRepository.js";

function browserStorage(): ChartWorkspaceKeyValueStorage | null {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

/** Replay never reads/writes the live IndexedDB, bootstrap journal or bus. */
export function createReplayChartWorkspaceRepository(
  runId: string,
  initialSession: ChartSession,
  storage: ChartWorkspaceKeyValueStorage | null = browserStorage(),
) {
  const prefix = `candlescope:replay-workspace:v1:${encodeURIComponent(runId)}:`;
  const seed = createDefaultChartWorkspaceRecord();
  for (const cell of Object.values(seed.document.cells)) {
    cell.session = { ...initialSession };
    cell.indicators = [];
    cell.strategyAttachment = null;
    cell.linkGroupId = null;
  }
  const initial = JSON.stringify({ activeWorkspaceId: seed.id, workspaces: [seed] });
  const fallback = new Map<string, string>();
  return createChartWorkspaceRepository({
    indexedDB: null,
    storage: {
      getItem: (key) => storage?.getItem(prefix + key) ?? fallback.get(key)
        ?? (key === CHART_WORKSPACE_FALLBACK_LIBRARY_KEY ? initial : null),
      setItem: (key, value) => {
        if (storage) storage.setItem(prefix + key, value);
        else fallback.set(key, value);
      },
      removeItem: (key) => {
        storage?.removeItem?.(prefix + key);
        fallback.delete(key);
      },
    },
  });
}
