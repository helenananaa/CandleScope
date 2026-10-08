import { describeError } from "../../i18n/serverErrors.js";
import { Profiler, useEffect, useState } from "react";
import type { ProfilerOnRenderCallback } from "react";
import { recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import AppPageShell from "../../app/AppPageShell.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import {
  useChartSettingsRuntime,
  type ChartSettingsRuntime,
} from "../settings/chartAppearanceSettings.js";
import type { ReplayEntry } from "./replayEntry.js";
import type { TrainingRunCard } from "./replayV2Types.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import { getReplayControllerClientInstanceId } from "./replayControllerIdentity.js";
import ReplayInitialMarketPicker from "./components/ReplayInitialMarketPicker.js";
import TrainingHubDialog from "./components/TrainingHubDialog.js";
import ReplayChartWorkspace from "./ReplayChartWorkspace.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { createReplayChartRuntimePool, useSharedReplayChartRuntime } from "./replayChartRuntimePool.js";
import { useReplayViewerRuntime } from "./useReplayViewerRuntime.js";
import { useTrainingHub } from "./useTrainingHub.js";

export { default as ReplayInitialMarketPicker } from "./components/ReplayInitialMarketPicker.js";

export interface ReplayAppProps {
  entry: ReplayEntry;
}

const recordReplayCommit: ProfilerOnRenderCallback = (id, phase, actualDuration, baseDuration, startTime, commitTime) => {
  recordPerfEvent("replay.react.commit", { id, phase, actualDuration, baseDuration, startTime, commitTime });
};

function ReplayTrainingHubApp() {
  const runtime = useTrainingHub();
  return <AppPageShell source="replay"><TrainingHubDialog runtime={runtime} /></AppPageShell>;
}

function ReplayStatusSurface({
  title,
  message,
  retry,
}: {
  title: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <AppPageShell source="replay">
    <main className="training-hub-page">
      <section className="training-hub-shell">
        <header className="training-hub-heading">
          <div>
            <span className="training-hub-kicker">{t("replay.kicker.runCentric")}</span>
            <h1>{title}</h1>
            <p>{message}</p>
          </div>
          <div className="training-hub-heading-actions">
            {retry !== undefined && <button type="button" onClick={retry}>{t("replay.retry")}</button>}
            <a href="/replay.html">{t("replay.backToHub")}</a>
          </div>
        </header>
      </section>
    </main>
    </AppPageShell>
  );
}

function ReplayInitializedRun({
  chartSettingsRuntime,
  onSelectedSessionChange,
  runId,
  sessionId,
}: {
  chartSettingsRuntime: ChartSettingsRuntime;
  onSelectedSessionChange: (sessionId: string) => void;
  runId: string;
  sessionId: string;
}) {
  const [pool] = useState(() => createReplayChartRuntimePool(getReplayControllerClientInstanceId(runId)));
  const replay = useSharedReplayChartRuntime(pool, sessionId);
  const viewer = useReplayViewerRuntime(replay, { onSelectedSessionChange, controllerOnly: true });
  const [initialSession, setInitialSession] = useState<ChartSession | null>(null);
  useEffect(() => {
    const config = replay.store.sessionConfig;
    if (initialSession !== null || config === null) return;
    setInitialSession({ exchange: config.exchange, marketType: config.market_type,
      symbol: config.symbol, interval: config.base_interval });
  }, [initialSession, replay.store.sessionConfig]);
  if (initialSession === null) return <ReplayStatusSurface title={t("replay.opening")} message={replay.error?.message ?? t("replay.openingMessage", { runId })} />;
  return <ReplayChartWorkspace runId={runId} initialSession={initialSession}
    runtime={replay} viewer={viewer} pool={pool} chartSettingsRuntime={chartSettingsRuntime} />;
}

function ReplayTrainingRunApp({
  chartSettingsRuntime,
  runId,
}: {
  chartSettingsRuntime: ChartSettingsRuntime;
  runId: string;
}) {
  const [run, setRun] = useState<TrainingRunCard | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void defaultReplayV2Api.getRun(runId, controller.signal).then(async ({ run: loaded }) => {
      if (loaded.adapter_session_id !== null && loaded.state === "PAUSED") {
        await defaultReplayV2Api.prepareIndex(runId, controller.signal, getReplayControllerClientInstanceId(runId));
      }
      if (controller.signal.aborted) return;
      setRun(loaded);
    }).catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? describeError(reason, reason.message) : t("replay.runLoadFailed"));
    });
    return () => controller.abort();
  }, [attempt, runId]);

  if (error !== null) {
    return <ReplayStatusSurface title={t("replay.openFailed")} message={error} retry={() => {
      setRun(null);
      setError(null);
      setAttempt((value) => value + 1);
    }} />;
  }
  if (run === null) {
    return <ReplayStatusSurface title={t("replay.opening")} message={t("replay.openingMessage", { runId })} />;
  }
  if (run.state === "AWAITING_MARKET" || run.resume_action === "SELECT_MARKET") {
    return <AppPageShell source="replay"><ReplayInitialMarketPicker run={run} onInitialized={(initialized) => {
      setRun(null);
      void defaultReplayV2Api.prepareIndex(runId, undefined, getReplayControllerClientInstanceId(runId)).then(() => setRun(initialized)).catch((reason: unknown) => {
        setError(reason instanceof Error ? describeError(reason, reason.message) : t("replay.runLoadFailed"));
      });
    }} /></AppPageShell>;
  }
  if (run.adapter_session_id === null) {
    return <ReplayStatusSurface title={t("replay.incomplete")} message={t("replay.incompleteMessage")} />;
  }
  return (
    <ReplayInitializedRun
      key={run.run_id}
      chartSettingsRuntime={chartSettingsRuntime}
      runId={run.run_id}
      sessionId={selectedSessionId ?? run.adapter_session_id}
      onSelectedSessionChange={setSelectedSessionId}
    />
  );
}

/** Run-centric replay composition root. */
export default function ReplayApp({ entry }: ReplayAppProps) {
  useLocale();
  const chartSettingsRuntime = useChartSettingsRuntime();
  if (entry.kind === "configure") return <ReplayTrainingHubApp />;
  if (entry.kind === "run") {
    const workspace = (
      <ReplayTrainingRunApp
        key={entry.runId}
        chartSettingsRuntime={chartSettingsRuntime}
        runId={entry.runId}
      />
    );
    return import.meta.env?.DEV
      ? <Profiler id="replay" onRender={recordReplayCommit}>{workspace}</Profiler>
      : workspace;
  }
  return <ReplayStatusSurface title={t("replay.invalidUrl")} message={entry.message} />;
}
