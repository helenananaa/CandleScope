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
type HandoffReferences = {
  saveStrategyReference(kind: "research-handoff", key: string, value: unknown): Promise<void>;
  loadStrategyReference(kind: "research-handoff", key: string): Promise<unknown>;
};

/** The hand-off is stored in the backend (ADR-BACKTEST-015 P3c), so it outlives the page and the origin. */
export async function saveResearchHandoff(input: { session: ChartSession; workspaceId: string; cellId: string;
  attachment: ChartStrategyAttachmentRecord; draft: StrategyDraftRecord; runId: string | null },
  references: Pick<HandoffReferences, "saveStrategyReference">,
  store: StrategyDraftStore = getChartStrategyDraftStore()): Promise<string> {
  // Capture settings and the explicitly saved code before the first await.
  // The experiment must never subscribe/autosave to the originating draft ID.
  const configuration: unknown = JSON.parse(JSON.stringify({
    parameters: { ...input.attachment.parameters },
    fidelityPreference: input.attachment.fidelityPreference,
    rangeMode: input.attachment.rangeMode === "VISIBLE" ? "CUSTOM" : input.attachment.rangeMode,
    customRange: input.attachment.customRange,
    ...(input.attachment.pythonBarExecution ? { pythonBarExecution: input.attachment.pythonBarExecution } : {}),
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
  await references.saveStrategyReference("research-handoff", id, record);
  return `/strategy.html?handoff=${encodeURIComponent(id)}`;
}
/** The hand-off behind a `?handoff=` link: from the backend, else (a link from before P3c) browser storage. */
export async function loadResearchHandoff(id: string, references: Pick<HandoffReferences, "loadStrategyReference">): Promise<ResearchHandoff | null> {
  if (!/^[a-zA-Z0-9-]{8,80}$/.test(id)) return null;
  const stored = await references.loadStrategyReference("research-handoff", id).catch(() => null);
  return parseResearchHandoff(stored) ?? readResearchHandoff(id);
}
export function readResearchHandoff(id: string): ResearchHandoff | null {
  try {
    if (!/^[a-zA-Z0-9-]{8,80}$/.test(id)) return null;
    return parseResearchHandoff(JSON.parse(window.localStorage.getItem(`${PREFIX}${id}`) ?? "null"));
  } catch { return null; }
}
export function parseResearchHandoff(raw: unknown): ResearchHandoff | null {
  try {
    const record = raw as ResearchHandoff | null;
    if (!record || typeof record !== "object" || record.schemaVersion !== 2 || typeof record.draftId !== "string" || !/^draft-[A-Za-z0-9_-]{8,152}$/.test(record.draftId)
      || !record.origin || typeof record.origin.draftId !== "string" || !/^draft-[A-Za-z0-9_-]{8,152}$/.test(record.origin.draftId)
      || record.origin.draftId === record.draftId || !Number.isSafeInteger(record.origin.draftRevision) || record.origin.draftRevision < 0
      || !validStrategyRunSettings(record.configuration)) return null;
    const source = parseResearchSourceRef(record.source);
    if (source.kind !== "CURRENT_CHART") return null;
    return { ...record, source, runId: typeof record.runId === "string" && /^bt_[\w-]+$/.test(record.runId) ? record.runId : null };
  } catch { return null; }
}
