import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { ReplayTrainingMarketTrack, ReplayViewerState } from "./replayV2Types.js";
import { createDefaultChartWorkspaceRecord } from "../chart-workspace/chartWorkspaceLibrary.js";
import { normalizeChartWorkspace } from "../chart-workspace/chartWorkspaceStorage.js";
import { visibleCellIds } from "../chart-workspace/chartWorkspaceLayout.js";
import { MAIN_CHART_WINDOW_ID, type ChartWorkspaceDocument } from "../chart-workspace/chartWorkspaceTypes.js";
import {
  CHART_WORKSPACE_FALLBACK_LIBRARY_KEY,
  createChartWorkspaceRepository,
  type ChartWorkspaceKeyValueStorage,
} from "../chart-workspace/chartWorkspaceRepository.js";

function browserStorage(): ChartWorkspaceKeyValueStorage | null {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

export interface ReplayWorkspaceSeed {
  document: ChartWorkspaceDocument;
  windowId: string;
  workspaceId?: string;
  /** A fork already has its own admitted markets; live launch seeds rebind. */
  preserveMarketBindings?: boolean;
}

export const replayWorkspaceSeedKey = (runId: string) => `candlescope:replay-workspace-seed:v1:${encodeURIComponent(runId)}`;
const seedKey = replayWorkspaceSeedKey;

/** Capture configuration only, before opening a newly created training. */
export function seedReplayChartWorkspace(runId: string, seed: ReplayWorkspaceSeed,
  storage: ChartWorkspaceKeyValueStorage | null = browserStorage()): boolean {
  if (!storage) return false;
  try {
    if (storage.getItem(seedKey(runId)) !== null) return true;
    const window = seed.document.windows[seed.windowId];
    if (!window) return false;
    const cells = Object.fromEntries(visibleCellIds(window.layoutTree).map((id) => {
      const cell = seed.document.cells[id]!;
      return [id, { id:cell.id, session:cell.session, linkGroupId:cell.linkGroupId,
        drawingLayerSet:cell.drawingLayerSet, chartSettings:cell.chartSettings,
        priceScale:cell.priceScale, indicators:cell.indicators.map((indicator) => ({
          ...indicator, error:null, renderHints:undefined,
          lines:indicator.lines?.map((line) => ({ ...line, data:[], colorData:null, renderUpdate:null })),
        })), strategyAttachment:null }];
    }));
    const document = normalizeChartWorkspace({ ...seed.document, cells,
      windows:{ [MAIN_CHART_WINDOW_ID]: { ...window, id:MAIN_CHART_WINDOW_ID,
        boundsDip:null,monitorFingerprint:null,dpiScale:null,windowState:"normal" } },
      activeWindowId:MAIN_CHART_WINDOW_ID });
    storage.setItem(seedKey(runId), JSON.stringify(seed.preserveMarketBindings ? {
      schemaVersion: 2, document, workspaceId: seed.workspaceId,
      preserveMarketBindings: true,
    } : document));
    return true;
  } catch { return false; }
}

/** Copy presentation only. Event-specific drawings come from the fork server. */
export function seedForkReplayChartWorkspace(runId: string, source: ReplayWorkspaceSeed,
  fork: {
    tracks: readonly Pick<ReplayTrainingMarketTrack, "track_id" | "exchange" | "market_type" | "symbol">[];
    viewer_state: Pick<ReplayViewerState, "selected_track_id" | "display_interval">;
  },
  storage: ChartWorkspaceKeyValueStorage | null = browserStorage()): boolean {
  const document = normalizeChartWorkspace(JSON.parse(JSON.stringify(source.document)));
  const window = document.windows[source.windowId];
  const selected = fork.tracks.find(track => track.track_id === fork.viewer_state.selected_track_id);
  if (!window || !selected) return false;
  const ids = visibleCellIds(window.layoutTree);
  const matches = (cellId: string, track: typeof selected) => {
    const session = document.cells[cellId]!.session;
    return session.exchange === track.exchange && session.marketType === track.market_type && session.symbol === track.symbol;
  };
  for (const id of ids) {
    if (!fork.tracks.some(track => matches(id, track))) {
      document.cells[id]!.session = { ...document.cells[id]!.session,
        exchange: selected.exchange, marketType: selected.market_type, symbol: selected.symbol };
    }
  }
  // A fork can target an earlier event/market than the currently active chart.
  const active = ids.find(id => id === window.activeCellId && matches(id, selected))
    ?? ids.find(id => matches(id, selected))
    ?? (ids.includes(window.activeCellId) ? window.activeCellId : ids[0]);
  if (!active) return false;
  window.activeCellId = active;
  document.cells[active]!.session = { ...document.cells[active]!.session,
    exchange: selected.exchange, marketType: selected.market_type, symbol: selected.symbol,
    interval: fork.viewer_state.display_interval };
  return seedReplayChartWorkspace(runId, { ...source, document, preserveMarketBindings: true }, storage);
}

/** Replay never reads/writes the live IndexedDB, bootstrap journal or bus. */
export function createReplayChartWorkspaceRepository(
  runId: string,
  initialSession: ChartSession,
  storage: ChartWorkspaceKeyValueStorage | null = browserStorage(),
) {
  const prefix = `candlescope:replay-workspace:v1:${encodeURIComponent(runId)}:`;
  const seed = createDefaultChartWorkspaceRecord();
  let inherited = false;
  let preserveMarketBindings = false;
  try {
    const raw = storage?.getItem(seedKey(runId));
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      const envelope = parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed as Record<string, unknown> : {};
      preserveMarketBindings = envelope.schemaVersion === 2 && envelope.preserveMarketBindings === true;
      seed.document = normalizeChartWorkspace(preserveMarketBindings ? envelope.document : parsed);
      if (preserveMarketBindings && typeof envelope.workspaceId === "string" && envelope.workspaceId) seed.id = envelope.workspaceId;
      inherited = true;
    }
  } catch { /* Invalid optional seed uses the ordinary isolated default. */ }
  for (const cell of Object.values(seed.document.cells)) {
    // Every initial cell binds to the training market, never a live feed. Its
    // display interval and indicator definitions are configuration only; the
    // replay runtime computes values from its revealed projection.
    if (!preserveMarketBindings) cell.session = { ...initialSession, interval:inherited ? cell.session.interval : initialSession.interval };
    if (!inherited) cell.indicators = [];
    cell.strategyAttachment = null;
    delete cell.nativeStrategies;
    if (!inherited) cell.linkGroupId = null;
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
