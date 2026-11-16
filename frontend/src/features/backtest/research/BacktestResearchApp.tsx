import { t } from "../../../i18n/index.js";
import AppPageShell from "../../../app/AppPageShell.js";
import ResearchMarketChart from "./ResearchMarketChart.js";
import ResearchTaskPicker from "./ResearchTaskPicker.js";
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
      <section>
        <span>{t("research.kicker")}</span>
        <h1>{error ? t("research.errorTitle") : t("research.loading")}</h1>
        {error && <p>{error}</p>}
        {error && <button type="button" onClick={onRetry}>{t("research.retry")}</button>}
        <a href="/">{t("research.live")}</a>
      </section>
    </main>
  );
}

export default function BacktestResearchApp({
  search,
}: {
  search?: string;
} = {}) {
  const runtime = useBacktestResearchRuntime(search === undefined ? {} : { search });
  usePageControlBridge();
  useControlCommands(() => backtestCommands(runtime));
  // Pages without a chart share the app header like every other page.
  if (runtime.view.phase !== "READY") {
    return <AppPageShell source="research"><ResearchStatus error={runtime.view.phase === "ERROR" ? runtime.view.error : null} onRetry={runtime.actions.refresh} /></AppPageShell>;
  }
  if (runtime.view.selectedTask === null) {
    return (
      <AppPageShell source="research">
        <ResearchTaskPicker
          returnHref={runtime.view.returnHref}
          onSelect={runtime.actions.selectTask}
        />
      </AppPageShell>
    );
  }
  const workspaceKey = runtime.view.activeRun?.run_id
    ?? runtime.view.launchContext?.context_id
    ?? runtime.view.activeStudy?.study_id
    ?? "research-home";
  return <ResearchMarketChart key={workspaceKey} runtime={runtime} />;
}
