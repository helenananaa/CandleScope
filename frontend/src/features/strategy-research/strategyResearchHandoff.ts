import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { ChartStrategyAttachmentRecord } from "../chart-workspace/chartWorkspaceTypes.js";
import { parseResearchSourceRef } from "../research-data/researchDataSourceModel.js";
import type { CurrentChartSourceRefV1 } from "../research-data/researchDataTypes.js";
import { validStrategyRunSettings, type StrategyRunSettings } from "../../shared/strategyRunSettings.js";

export interface ResearchHandoff { source: CurrentChartSourceRefV1; draftId: string; configuration: StrategyRunSettings; runId: string | null; }
const PREFIX = "candlescope:research-handoff:";
export function saveResearchHandoff(input: { session: ChartSession; workspaceId: string; cellId: string; attachment: ChartStrategyAttachmentRecord; runId: string | null }): string {
  const configuration: StrategyRunSettings = {
    parameters: { ...input.attachment.parameters },
    fidelityPreference: input.attachment.fidelityPreference,
    rangeMode: input.attachment.rangeMode === "VISIBLE" ? "CUSTOM" : input.attachment.rangeMode,
    customRange: input.attachment.customRange,
    ...(input.attachment.executionOverrides ? { executionOverrides: input.attachment.executionOverrides } : {}),
  };
  if (!input.attachment.strategyDraftId || !validStrategyRunSettings(configuration)) throw new Error("Save the strategy and check the backtest conditions first");
  const record: ResearchHandoff = {
    source: { schemaVersion: "candlescope.research-source/1", kind: "CURRENT_CHART", workspaceId: input.workspaceId, cellId: input.cellId,
      exchange: input.session.exchange, marketType: input.session.marketType, symbol: input.session.symbol, interval: input.session.interval },
    draftId: input.attachment.strategyDraftId,
    configuration,
    runId: input.runId,
  };
  const id = crypto.randomUUID();
  window.localStorage.setItem(`${PREFIX}${id}`, JSON.stringify(record));
  return `/strategy.html?handoff=${encodeURIComponent(id)}`;
}
export function readResearchHandoff(id: string): ResearchHandoff | null {
  try {
    if (!/^[a-zA-Z0-9-]{8,80}$/.test(id)) return null;
    const record = JSON.parse(window.localStorage.getItem(`${PREFIX}${id}`) ?? "null") as ResearchHandoff | null;
    if (!record || typeof record.draftId !== "string" || !record.draftId.startsWith("draft-") || !validStrategyRunSettings(record.configuration)) return null;
    const source = parseResearchSourceRef(record.source);
    if (source.kind !== "CURRENT_CHART") return null;
    return { ...record, source, runId: typeof record.runId === "string" && /^bt_[\w-]+$/.test(record.runId) ? record.runId : null };
  } catch { return null; }
}
