import type { BacktestResultReplayCursor } from "../backtest/backtestTypes.js";
import type { ResearchSourceRefV1 } from "../research-data/researchDataTypes.js";
import { getStrategyStorage } from "../../shared/strategyStorage.js";
import { validStrategyRunSettings, type StrategyRunSettings } from "../../shared/strategyRunSettings.js";
import { parseResearchSourceRef, ResearchDataError } from "../research-data/researchDataSourceModel.js";

export const STRATEGY_RESEARCH_WORKSPACE_KEY = "candlescope:strategy-research:v1";

export type StrategyResearchStaleReason =
  | "DATA_REVISION_CHANGED"
  | "SOURCE_CHANGED"
  | "RANGE_CHANGED"
  | "SCRIPT_CHANGED"
  | null;

export type StrategyResearchSourceSlice = {
  source: ResearchSourceRefV1 | null;
  previewFrozen: boolean;
  libraryOpen: boolean;
};

export type StrategyResearchScriptSlice = {
  configuration?: StrategyRunSettings;
  draftId: string | null;
  contentRevision: number;
};

export type StrategyResearchResultSlice = {
  runId: string | null;
  stale: boolean;
  staleReason: StrategyResearchStaleReason;
  replay?: BacktestResultReplayCursor;
};

export type StrategyResearchState = {
  source: StrategyResearchSourceSlice;
  script: StrategyResearchScriptSlice;
  result: StrategyResearchResultSlice;
};

export type StrategyResearchAction =
  | { type: "result/viewHistory"; runId: string }
  | { type: "result/invalidate" }
  | { type: "result/replay"; replay: BacktestResultReplayCursor | null }
  | { type: "script/configure"; configuration: StrategyRunSettings }
  | { type: "source/select"; source: ResearchSourceRefV1 }
  | { type: "source/clear" }
  | { type: "source/revisionChanged"; source: ResearchSourceRefV1 }
  | { type: "source/libraryOpen"; open: boolean }
  | { type: "source/frozenPreview"; frozen: boolean }
  | { type: "script/setDraft"; draftId: string | null }
  | { type: "script/setContentRevision"; revision: number }
  | { type: "result/setRun"; runId: string | null }
  | { type: "result/clear" };

export const EMPTY_STRATEGY_RESEARCH_STATE: StrategyResearchState = {
  source: { source: null, previewFrozen: false, libraryOpen: false },
  script: { draftId: null, contentRevision: 0 },
  result: { runId: null, stale: false, staleReason: null },
};

export function strategyResearchReducer(
  state: StrategyResearchState,
  action: StrategyResearchAction,
): StrategyResearchState {
  switch (action.type) {
    case "result/viewHistory": return { ...state, result: { runId: action.runId, stale: true, staleReason: null } };
    case "result/replay": {
      if (action.replay && action.replay.runId !== state.result.runId) return state;
      if (action.replay) return { ...state, result: { ...state.result, replay: action.replay } };
      const { replay: _replay, ...result } = state.result;
      return { ...state, result };
    }
    case "result/invalidate": return { ...state, result: { ...state.result, stale: true } };
    case "script/configure":
      return { ...state, script: { ...state.script, configuration: action.configuration }, result: state.result.runId ? { ...state.result, stale: true, staleReason: "RANGE_CHANGED" } : state.result };
    case "source/select":
      return {
        ...state,
        source: { ...state.source, source: action.source, previewFrozen: false },
        result: state.result.runId
          ? { ...state.result, stale: true, staleReason: "SOURCE_CHANGED" }
          : state.result,
      };
    case "source/clear":
      return {
        ...state,
        source: { ...state.source, source: null, previewFrozen: false },
      };
    case "source/revisionChanged":
      return {
        source: { ...state.source, source: action.source, previewFrozen: false },
        script: state.script,
        result: {
          ...state.result,
          stale: state.result.runId !== null,
          staleReason: state.result.runId !== null ? "DATA_REVISION_CHANGED" : null,
        },
      };
    case "source/libraryOpen":
      return { ...state, source: { ...state.source, libraryOpen: action.open } };
    case "source/frozenPreview":
      return { ...state, source: { ...state.source, previewFrozen: action.frozen } };
    case "script/setDraft":
      if (state.script.draftId === action.draftId) return state;
      return {
        ...state,
        script: { ...state.script, draftId: action.draftId, contentRevision: 0 },
        result: state.result.runId
          ? { ...state.result, stale: true, staleReason: "SCRIPT_CHANGED" }
          : state.result,
      };
    case "script/setContentRevision":
      if (state.script.contentRevision === action.revision) return state;
      return {
        ...state,
        script: { ...state.script, contentRevision: action.revision },
        result: state.result.runId
          ? { ...state.result, stale: true, staleReason: "SCRIPT_CHANGED" }
          : state.result,
      };
    case "result/setRun":
      return { ...state, result: { runId: action.runId, stale: false, staleReason: null } };
    case "result/clear":
      return { ...state, result: { runId: null, stale: false, staleReason: null } };
    default:
      return state;
  }
}

export function persistStrategyResearchWorkspace(state: StrategyResearchState): void {
  const payload = {
    schemaVersion: 1,
    source: state.source.source,
    libraryOpen: state.source.libraryOpen,
    draftId: state.script.draftId,
    contentRevision: state.script.contentRevision,
    configuration: state.script.configuration,
    stale: state.result.stale,
    runId: state.result.runId,
    replay: state.result.replay,
  };
  try {
    void Promise.resolve(getStrategyStorage()?.setItem(STRATEGY_RESEARCH_WORKSPACE_KEY, JSON.stringify(payload))).catch(() => {});
  } catch {
    // Persistence is optional; in-memory state remains.
  }
}

function loadResultReplay(value: unknown, runId: unknown): BacktestResultReplayCursor | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const replay = value as Partial<BacktestResultReplayCursor>;
  const hash = /^sha256:[a-f0-9]{64}$/;
  if (typeof replay.runId !== "string" || replay.runId !== runId || !/^bt_[a-zA-Z0-9_-]+$/.test(replay.runId)
    || typeof replay.snapshotHash !== "string" || !hash.test(replay.snapshotHash)
    || typeof replay.reportHash !== "string" || !hash.test(replay.reportHash)
    || typeof replay.cursor !== "number" || !Number.isSafeInteger(replay.cursor) || replay.cursor < 0
    || typeof replay.interval !== "string" || replay.interval.length < 2 || replay.interval.length > 64) return undefined;
  const dataset = replay.comparisonDataset;
  const comparisonDataset = dataset && typeof dataset.datasetId === "string" && /^local-[0-9a-f]{32}$/.test(dataset.datasetId)
    && typeof dataset.dataEpoch === "string" && hash.test(dataset.dataEpoch)
    ? { datasetId: dataset.datasetId, dataEpoch: dataset.dataEpoch } : undefined;
  const comparisonInterval = typeof replay.comparisonInterval === "string"
    && (dataset === undefined ? replay.comparisonInterval !== replay.interval : comparisonDataset !== undefined)
    && replay.comparisonInterval.length >= 2 && replay.comparisonInterval.length <= 64 ? replay.comparisonInterval : undefined;
  const validPeriod = (period: number | undefined): period is number =>
    typeof period === "number" && Number.isInteger(period) && period >= 1 && period <= 500;
  return { runId: replay.runId, snapshotHash: replay.snapshotHash, reportHash: replay.reportHash,
    cursor: replay.cursor, interval: replay.interval,
    ...(comparisonInterval ? { comparisonInterval, ...(comparisonDataset ? { comparisonDataset } : {}) } : {}),
    ...(validPeriod(replay.maPeriod) ? { maPeriod: replay.maPeriod } : {}),
    ...(comparisonInterval && validPeriod(replay.comparisonMaPeriod) ? { comparisonMaPeriod: replay.comparisonMaPeriod } : {}) };
}

export function loadStrategyResearchWorkspace(): StrategyResearchState {
  try {
    const raw = getStrategyStorage()?.getItem(STRATEGY_RESEARCH_WORKSPACE_KEY);
    if (raw == null) return EMPTY_STRATEGY_RESEARCH_STATE;
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return EMPTY_STRATEGY_RESEARCH_STATE;
    }
    const record = parsed as Record<string, unknown>;
    let source: ResearchSourceRefV1 | null = null;
    if (record.source != null) {
      try {
        source = parseResearchSourceRef(record.source);
      } catch (error) {
        if (!(error instanceof ResearchDataError)) throw error;
        return EMPTY_STRATEGY_RESEARCH_STATE;
      }
    }
    const replay = loadResultReplay(record.replay, record.runId);
    return {
      source: {
        source,
        previewFrozen: false,
        libraryOpen: record.libraryOpen === true,
      },
      script: { draftId: typeof record.draftId === "string" ? record.draftId : null,
        contentRevision: typeof record.contentRevision === "number" ? record.contentRevision : 0,
        ...(validStrategyRunSettings(record.configuration) ? { configuration: record.configuration } : {}),
      },
      result: {
        runId: typeof record.runId === "string" ? record.runId : null,
        stale: record.stale === true || (typeof record.runId === "string" && typeof record.contentRevision !== "number"),
        staleReason: null,
        ...(replay ? { replay } : {}),
      },
    };
  } catch {
    return EMPTY_STRATEGY_RESEARCH_STATE;
  }
}
