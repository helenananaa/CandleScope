import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { ChartStrategyAttachmentRecord } from "../chart-workspace/chartWorkspaceTypes.js";
import { parseResearchSourceRef } from "../research-data/researchDataSourceModel.js";
import type { CurrentChartSourceRefV1 } from "../research-data/researchDataTypes.js";
import { validStrategyRunSettings, type StrategyRunSettings } from "../../shared/strategyRunSettings.js";
import type { StrategyDraftRecord, StrategyDraftStore } from "../backtest/chart-tester/StrategyDraftStore.js";
import { createChartStrategyDraftId, getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";

export interface ResearchHandoff { schemaVersion: 2; source: CurrentChartSourceRefV1; draftId: string;
  origin: { draftId: string; draftRevision: number }; configuration: StrategyRunSettings; runId: string | null; }
const PREFIX = "candlescope:research-handoff:";
export async function saveResearchHandoff(input: { session: ChartSession; workspaceId: string; cellId: string;
  attachment: ChartStrategyAttachmentRecord; draft: StrategyDraftRecord; runId: string | null },
  store: StrategyDraftStore = getChartStrategyDraftStore()): Promise<string> {
  // Capture settings and the explicitly saved code before the first await.
  // The experiment must never subscribe/autosave to the originating draft ID.
  const configuration: unknown = JSON.parse(JSON.stringify({
    parameters: { ...input.attachment.parameters },
    fidelityPreference: input.attachment.fidelityPreference,
    rangeMode: input.attachment.rangeMode === "VISIBLE" ? "CUSTOM" : input.attachment.rangeMode,
    customRange: input.attachment.customRange,
    ...(input.attachment.executionOverrides ? { executionOverrides: input.attachment.executionOverrides } : {}),
  }));
  if (!input.attachment.strategyDraftId || input.draft.id !== input.attachment.strategyDraftId
    || input.draft.language !== input.attachment.language || !Number.isSafeInteger(input.draft.revision)
    || input.draft.revision < 0 || !validStrategyRunSettings(configuration)) throw new Error("Save the strategy and check the backtest conditions first");
  const copy = { id: createChartStrategyDraftId(), displayName: input.draft.displayName, language: input.draft.language,
    source: input.draft.source, cursor: input.draft.cursor ? { ...input.draft.cursor } : null };
  const record: ResearchHandoff = {
    schemaVersion: 2,
    source: { schemaVersion: "candlescope.research-source/1", kind: "CURRENT_CHART", workspaceId: input.workspaceId, cellId: input.cellId,
      exchange: input.session.exchange, marketType: input.session.marketType, symbol: input.session.symbol, interval: input.session.interval },
    draftId: copy.id,
    origin: { draftId: input.draft.id, draftRevision: input.draft.revision },
    configuration,
    runId: input.runId,
  };
  const id = crypto.randomUUID();
  // Failed persistence leaves the chart and its original program untouched;
  // callers navigate only after both the independent draft and handoff exist.
  await store.save(copy);
  window.localStorage.setItem(`${PREFIX}${id}`, JSON.stringify(record));
  return `/strategy.html?handoff=${encodeURIComponent(id)}`;
}
export function readResearchHandoff(id: string): ResearchHandoff | null {
  try {
    if (!/^[a-zA-Z0-9-]{8,80}$/.test(id)) return null;
    const record = JSON.parse(window.localStorage.getItem(`${PREFIX}${id}`) ?? "null") as ResearchHandoff | null;
    if (!record || record.schemaVersion !== 2 || typeof record.draftId !== "string" || !/^draft-[A-Za-z0-9_-]{8,152}$/.test(record.draftId)
      || !record.origin || typeof record.origin.draftId !== "string" || !/^draft-[A-Za-z0-9_-]{8,152}$/.test(record.origin.draftId)
      || record.origin.draftId === record.draftId || !Number.isSafeInteger(record.origin.draftRevision) || record.origin.draftRevision < 0
      || !validStrategyRunSettings(record.configuration)) return null;
    const source = parseResearchSourceRef(record.source);
    if (source.kind !== "CURRENT_CHART") return null;
    return { ...record, source, runId: typeof record.runId === "string" && /^bt_[\w-]+$/.test(record.runId) ? record.runId : null };
  } catch { return null; }
}
