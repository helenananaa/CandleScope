import { useState } from "react";
import { createRoot } from "react-dom/client";
import { setLocaleAsync } from "../../../src/i18n/index.js";
import { createDefaultChartWorkspaceRecord, createTemplateChartWorkspaceDocument } from "../../../src/features/chart-workspace/chartWorkspaceLibrary.js";
import { createChartWorkspaceRepository } from "../../../src/features/chart-workspace/chartWorkspaceRepository.js";
import { useChartWorkspaceRuntime } from "../../../src/features/chart-workspace/useChartWorkspaceRuntime.js";
import { getChartStrategyDraftStore } from "../../../src/features/backtest/chart-tester/chartStrategyTesterDrafts.js";
import { createChartStrategyTesterState } from "../../../src/features/backtest/chart-tester/chartStrategyTesterState.js";
import { CandleScopeStrategyTesterPanel } from "../../../src/features/backtest/chart-tester/ChartStrategyTesterPanel.js";
import { MarketDataWorkspaceProvider } from "../../../src/features/market-data/MarketDataWorkspaceProvider.js";
import ResearchReturnButton from "../../../src/features/strategy-research/ResearchReturnButton.js";
import ResearchReturnDialog from "../../../src/features/strategy-research/ResearchReturnDialog.js";
import type { ResearchSelectedVersion } from "../../../src/features/strategy-research/researchSelectedVersion.js";
import "../../../src/styles/tokens.css";
import "../../../src/features/backtest/chart-tester/chartStrategyTester.css";
import "../../../src/features/backtest/chart-tester/strategyDock.css";

await setLocaleAsync("zh-CN");
const selected = await fetch('/api/v1/qa/selected').then(r => r.json() as Promise<{ run_id: string; source: string; selected: ResearchSelectedVersion }>);
const store = getChartStrategyDraftStore(), repository = createChartWorkspaceRepository({ indexedDB: null });
const original = (await store.load("draft-before-return12")).record ?? await store.save({ id: "draft-before-return12", displayName: "Existing chart program", language: "python", source: "# original chart program", cursor: null });
if (!localStorage.getItem("qa-research-return-seeded")) {
  const record = createDefaultChartWorkspaceRecord();
  record.document = createTemplateChartWorkspaceDocument("quad", record.document);
  for (const cell of Object.values(record.document.cells)) {
    cell.session = { exchange: "binance", marketType: "spot", symbol: cell.id === "cell-2" ? "ETHUSDT" : "BTCUSDT", interval: "1m" };
    cell.strategyAttachment = { schemaVersion: 1, strategyDraftId: original.id, strategyRevisionId: null, displayName: original.displayName,
      language: "python", parameters: { fast: 99 }, rangeMode: "ALL_AVAILABLE", customRange: null, fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false };
  }
  await repository.saveLibrary({ activeWorkspaceId: record.id, workspaces: [record] });
  localStorage.setItem("qa-research-return-seeded", "1");
}
const noop = () => undefined, refuse = () => { throw new Error("Historical execution is outside this fixture"); };
export function Fixture() {
  const workspace = useChartWorkspaceRuntime({ repository, workspaceBus: null, windowId: "main-window" });
  const [id, setId] = useState(() => new URLSearchParams(location.search).get("research-version"));
  const [showEditor, setShowEditor] = useState(() => new URLSearchParams(location.search).has("editor"));
  const active = workspace.view.activeCell;
  const runState = createChartStrategyTesterState({ session: active.session, attachment: active.strategyAttachment!, draftContentRevision: 1 }, "returned");
  Object.assign(window, { researchReturnQA: { selected, workspace: workspace.view, status: workspace.status,
    original: () => store.load(original.id), draft: () => store.load(active.strategyAttachment!.strategyDraftId!),
    changeTarget: () => workspace.actions.updateCellSession("cell-2", { ...active.session, symbol: "CHANGEDUSDT" }),
  } });
  return <main><h1>Selected immutable research version → independent chart run</h1>
    <ResearchReturnButton runId={selected.run_id} origin={{ workspaceId: workspace.view.activeWorkspaceId, cellId: "cell-1" }} />
    <div className="fixture-cells">{workspace.view.layoutCellIds.map(key => <div key={key}>{key} · {workspace.view.document.cells[key]!.session.symbol} · {workspace.view.document.cells[key]!.strategyAttachment?.strategyDraftId}</div>)}</div>
    {id && <ResearchReturnDialog id={id} workspace={workspace} onClose={() => setId(null)} onApplied={(cellId) => {
      workspace.actions.setActiveCell(cellId); setShowEditor(true); setId(null);
      history.replaceState(null, "", location.pathname + "?editor=1");
    }} />}
    {showEditor && <CandleScopeStrategyTesterPanel key={active.id} cellScope="returned" session={active.session} attachment={active.strategyAttachment}
      draftStore={store} onAttachmentChange={(value) => workspace.actions.updateCellStrategyAttachment(active.id, value)}
      onEntryStateChange={noop} onRunRequest={refuse} runState={runState} resolution={null} sourceDiagnostics={[]} pendingDataDraftRevision={null}
      onPrepareData={refuse} onStopObserving={noop} onResumeObserving={noop} onSourceDirty={noop} onClose={noop} />}
  </main>;
}
createRoot(document.getElementById("root")!).render(<MarketDataWorkspaceProvider brokerEnabled={false} batchStreamEnabled={false}><Fixture /></MarketDataWorkspaceProvider>);
