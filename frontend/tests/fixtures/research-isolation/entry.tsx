import { useState } from "react";
import { createRoot } from "react-dom/client";
import { setLocaleAsync, t } from "../../../src/i18n/index.js";
import { appCommandRegistry } from "../../../src/features/app-control/commandRegistry.js";
import { CandleScopeStrategyTesterPanel } from "../../../src/features/backtest/chart-tester/ChartStrategyTesterPanel.js";
import { createChartStrategyTesterState } from "../../../src/features/backtest/chart-tester/chartStrategyTesterState.js";
import { getChartStrategyDraftStore } from "../../../src/features/backtest/chart-tester/chartStrategyTesterDrafts.js";
import { StrategyResearchScriptPanel } from "../../../src/features/strategy-research/StrategyResearchScriptPanel.js";
import { saveResearchHandoff, readResearchHandoff, type ResearchHandoff } from "../../../src/features/strategy-research/strategyResearchHandoff.js";
import type { ChartStrategyAttachmentRecord } from "../../../src/features/chart-workspace/chartWorkspaceTypes.js";
import "../../../src/styles/tokens.css";
import "../../../src/features/backtest/chart-tester/chartStrategyTester.css";
import "../../../src/features/backtest/chart-tester/strategyDock.css";
import "../../../src/features/strategy-research/strategyResearch.css";

await setLocaleAsync("zh-CN");
// Only the host registration capability is supplied by this browser fixture.
// Actual components, command registry, draft persistence and handoff are unchanged.
Object.assign(window, { candlescopeDesktop: { controlEnabled: true } });
const store = getChartStrategyDraftStore(), session = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const language = new URLSearchParams(location.search).get("language") === "python" ? "python" : "pine";
const originalId = `draft-chart-${language}12`;
if (!(await store.load(originalId)).record) await store.save({ id: originalId, displayName: "Original chart", language,
  source: language === "python" ? "# Original chart\nvalue = 1" : "//@version=5\nstrategy(\"Original chart\")\nplot(close)", cursor: null });
const attachment: ChartStrategyAttachmentRecord = { schemaVersion: 1, strategyDraftId: originalId, strategyRevisionId: null,
  displayName: "Original chart", language, parameters: { fast: 8 }, rangeMode: "ALL_AVAILABLE", customRange: null,
  fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false };
const runState = createChartStrategyTesterState({ session, attachment, draftContentRevision: 1 }, "isolation");
const noop = () => undefined;
const refuseRun = () => { throw new Error("This isolation fixture must never execute a strategy"); };
const selectedKey = `qa-research-isolation-handoff:${language}`;
let last: ResearchHandoff | null = readResearchHandoff(localStorage.getItem(selectedKey) ?? "");
Object.assign(window, { researchIsolationQA: { registry: appCommandRegistry, labels: { more: t("report.more"), open: t("ux.openWorkspace") },
  inspect: async () => ({ original: (await store.load(originalId)).record, handoff: last,
    experiment: last ? (await store.load(last.draftId)).record : null }) } });

export function Fixture() {
  const [handoff, setHandoff] = useState<ResearchHandoff | null>(last), [draftId, setDraftId] = useState<string | null>(last?.draftId ?? null);
  return <main><h1>Chart → research draft isolation</h1><p>Actual production editors, autosave, draft store and handoff; no market or strategy execution.</p>
    <div className="fixture-grid"><section><h2>Originating chart editor</h2><CandleScopeStrategyTesterPanel cellScope="isolation" session={session}
      attachment={attachment} draftStore={store} onAttachmentChange={noop} onEntryStateChange={noop} onRunRequest={refuseRun}
      runState={runState} resolution={null} sourceDiagnostics={[]} pendingDataDraftRevision={null}
      onPrepareData={refuseRun} onStopObserving={noop} onResumeObserving={noop} onSourceDirty={noop} onClose={noop}
      onOpenWorkspace={async (draft) => {
        const href = await saveResearchHandoff({ session, workspaceId: "workspace-isolation", cellId: "cell-1", attachment, draft, runId: null }, store);
        const id = new URL(href, location.href).searchParams.get("handoff")!;
        last = readResearchHandoff(id);localStorage.setItem(selectedKey, id);setHandoff(last);setDraftId(last!.draftId);
      }} /></section><section><h2>Independent research editor</h2>{handoff && <StrategyResearchScriptPanel cellScope="experiment" session={session}
        sourceKind="CURRENT_CHART" draftId={draftId} barOnly runStatus="READY" needsData={false}
        onDraftId={setDraftId} onDraftRevision={noop} onRun={refuseRun} onConfirmNeedsData={refuseRun} onOpenAdvanced={noop}
        configuration={handoff.configuration} />}</section></div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
