import type { BacktestResearchRuntime } from "../backtest/research/backtestResearchTypes.js";
import { BACKTEST_RESEARCH_TASKS } from "../backtest/research/backtestResearchTypes.js";
import { MARKET_CHART_SOURCE_MODES } from "../market-chart-platform/marketChartSourceRuntime.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { choice, empty, json, nullable, number, object, record, text } from "./commandSchema.js";
import { publishControlFile } from "./controlFiles.js";

export function backtestCommands(runtime: BacktestResearchRuntime): ControlCommandGroup {
  const { view: v, actions: a } = runtime;
  const enabled = () => v.phase === "READY" && v.advancedEnabled && !v.busy;
  const noArgs = (name: keyof typeof a, description: string) => command(name, description, empty, () => {
    const selected = a[name] as () => void | Promise<void>; return selected();
  }, { available: name === "cancelRun" || name === "cancelStudy" ? () => v.phase === "READY" && v.advancedEnabled : enabled,
    interrupt: name === "cancelRun" || name === "cancelStudy" });
  return { id: "backtest", title: "Advanced strategy revisions, runs, studies and review", context: () => ({
    phase: v.phase, task: v.selectedTask, dataset: v.selectedDatasetId, revision: v.selectedRevisionId, snapshot: v.snapshot?.snapshot_hash,
    run: v.activeRun?.run_id, study: v.activeStudy?.study_id, range: [v.startTimeMs, v.endTimeMs], runDraft: v.runDraftText, studyDraft: v.studyDraftText,
  }), snapshot: () => ({ ...v, chart: v.chart ? { symbol: v.chart.symbol, interval: v.chart.interval } : null, report: v.report,
    revisions: v.revisions.slice(0, 100), datasets: v.datasets.slice(0, 100), runs: v.runs.slice(0, 100), studies: v.studies.slice(0, 100) }), commands: [
    command("selectTask", "Select an existing advanced research task.", object({ task: nullable(choice(BACKTEST_RESEARCH_TASKS)) }), ({ task }) => a.selectTask(task)),
    command("sourceMode", "Switch the chart source mode; frozen/run results retain domain availability guards.", object({ mode: choice(MARKET_CHART_SOURCE_MODES) }), ({ mode }) => a.selectSourceMode(mode)),
    command("selectDataset", "Select an existing dataset and its current epoch.", object({ datasetId: text(128) }), ({ datasetId }) => {
      if (!v.datasets.some((d) => d.dataset_id === datasetId)) throw new Error("DATASET_UNAVAILABLE"); a.selectDataset(datasetId);
    }),
    command("selectRevision", "Select an existing strategy revision.", object({ revisionId: text(128) }), ({ revisionId }) => {
      if (!v.revisions.some((r) => r.revision_id === revisionId)) throw new Error("REVISION_UNAVAILABLE"); a.selectRevision(revisionId);
    }),
    command("setRange", "Set an increasing backtest time range in milliseconds.", object({ startTimeMs: number(0, 1e15, true), endTimeMs: number(0, 1e15, true) }), ({ startTimeMs, endTimeMs }) => {
      if (endTimeMs <= startTimeMs) throw new Error("INVALID_RANGE"); a.setRange(startTimeMs, endTimeMs);
    }),
    command("runDraft", "Replace the Run JSON draft. Server/domain validation still applies when creating the run.", object({ draft: record }), ({ draft }) => a.setRunDraftText(JSON.stringify(draft))),
    command("studyDraft", "Replace the Study JSON draft.", object({ draft: record }), ({ draft }) => a.setStudyDraftText(JSON.stringify(draft))),
    command("createRevision", "Create/compile a strategy revision using existing API permissions and trust policy.", object({ body: record }), ({ body }) => {
      if (body.python_trusted_confirmed === true || body.python_runtime_mode === "TRUSTED_LOCAL") throw new Error("TRUST_GRANT_NOT_AVAILABLE"); return a.createStrategyRevision(body);
    }, { available: enabled }),
    command("openRun", "Select an existing run and load its report/chart.", object({ runId: text(128) }), ({ runId }) => a.openRun(runId), { available: () => !v.busy }),
    command("openStudy", "Select an existing study.", object({ studyId: text(128) }), ({ studyId }) => a.openStudy(studyId), { available: () => !v.busy }),
    command("cloneRun", "Clone the active run with one parameter change.", object({ parameter: text(128), value: json }), ({ parameter, value }) => a.cloneRun(parameter, value), { available: enabled }),
    command("compareRun", "Compare another run to the current run.", object({ runId: text(128) }), ({ runId }) => a.compareRun(runId), { available: enabled }),
    command("refresh", "Refresh research capabilities and records.", empty, () => a.refresh()),
    command("exportRun", "Export the current domain-generated run report to a window-bound file.", empty, async () => { let result: unknown; await a.exportRun(async (blob, name) => { result = await publishControlFile(blob, name); }); if (!result) throw new Error("EXPORT_UNAVAILABLE"); return result; }, { available: enabled }),
    ...(["resetRunDraft", "resetStudyDraft", "copyStrategyRevision", "archiveStrategyRevision", "smokeStrategyRevision", "createRun", "cancelRun", "resumeRun", "loadSignalTrace", "createStudy", "startStudy", "cancelStudy", "revealStudyHoldout", "compareStudy", "createReviewBridge", "revealReviewBridge"] as const)
      .map((name) => noArgs(name, `Use the existing ${name} UI action; inspect operationError and domain state afterward.`)),
  ] };
}
