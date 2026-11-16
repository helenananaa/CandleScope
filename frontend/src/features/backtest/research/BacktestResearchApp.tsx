import { useEffect } from "react";
import { Button, buttonClassName, EmptyState } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import AppPageShell from "../../../app/AppPageShell.js";
import ResearchMarketChart from "./ResearchMarketChart.js";
import { ResearchModeLayout } from "./ResearchModeLayout.js";
import type { BacktestResearchTask } from "./backtestResearchTypes.js";
import { useBacktestResearchRuntime } from "./useBacktestResearchRuntime.js";
import { useControlCommands, usePageControlBridge } from "../../app-control/useControlCommands.js";
import { backtestCommands } from "../../app-control/backtestCommands.js";

function ResearchStatus({
  error,
  onRetry,
}: {
  error?: string | null;
  onRetry(): void;
}) {
  return (
    <main className="research-status-page" data-state={error ? "error" : "loading"}>
      <EmptyState
        tone={error ? "danger" : "neutral"}
        role={error ? "alert" : "status"}
        title={error ? t("research.errorTitle") : t("research.loading")}
        description={error ?? undefined}
        action={(
          <span className="research-status-actions">
            {error && <Button size="sm" variant="primary" onClick={onRetry}>{t("research.retry")}</Button>}
            <a className={buttonClassName({ size: "sm", variant: "ghost" })} href="/">{t("research.live")}</a>
          </span>
        )}
      />
    </main>
  );
}

export default function BacktestResearchApp({
  search,
  task = null,
  onTaskResolved,
}: {
  search?: string;
  /** The research tool the page's mode rail asks for; null lets the launch context or deep link decide. */
  task?: BacktestResearchTask | null;
  /** Reports the tool actually open, so the mode rail follows deep links and commands. */
  onTaskResolved?(task: BacktestResearchTask): void;
} = {}) {
  const runtime = useBacktestResearchRuntime({ ...(search === undefined ? {} : { search }), initialTask: task });
  usePageControlBridge();
  useControlCommands(() => backtestCommands(runtime));
  const { phase, selectedTask } = runtime.view;
  const { selectTask } = runtime.actions;
  // The rail drives the tool; a deep link without a tool falls back to 精确成交验证 once loaded.
  useEffect(() => {
    if (task !== null && task !== selectedTask) selectTask(task);
    // Only a new request from the rail selects a tool.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task]);
  useEffect(() => {
    if (phase === "READY" && selectedTask === null) selectTask(task ?? "PRECISE_EXECUTION");
  }, [phase, selectedTask, selectTask, task]);
  useEffect(() => {
    if (selectedTask !== null && selectedTask !== task) onTaskResolved?.(selectedTask);
    // Report only changes of the open tool.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask]);
  // Pages without a chart share the app header like every other page.
  if (phase !== "READY" || selectedTask === null) {
    return (
      <AppPageShell source="research">
        <ResearchModeLayout>
          <ResearchStatus error={phase === "ERROR" ? runtime.view.error : null} onRetry={runtime.actions.refresh} />
        </ResearchModeLayout>
      </AppPageShell>
    );
  }
  const workspaceKey = runtime.view.activeRun?.run_id
    ?? runtime.view.launchContext?.context_id
    ?? runtime.view.activeStudy?.study_id
    ?? "research-home";
  return <ResearchMarketChart key={workspaceKey} runtime={runtime} />;
}
