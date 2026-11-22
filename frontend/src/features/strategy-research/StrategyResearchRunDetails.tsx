import { useEffect, useState } from "react";
import { Badge, Button, Disclosure, InlineAlert, buttonClassName } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import { researchReplayHref } from "../backtest/research/backtestResearchAdvancedModel.js";
import { researchStateLabel } from "../backtest/research/researchLabels.js";
import { researchStateTone } from "../backtest/research/researchStateTone.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";

type DetailsManager = Pick<StrategyDataManager, "loadBacktestCapabilities" | "exportRun" | "loadSignalTrace"
  | "createReviewBridge" | "revealReviewBridge">;

function download(name: string, payload: unknown): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 1_000);
}

function failure(reason: unknown): string {
  return reason instanceof Error ? describeError(reason, reason.message) : String(reason);
}

/**
 * A fixed run's details in the research workspace (ADR-BACKTEST-015 P5c): its recorded strategy
 * decisions, data quality and fill model, the server's export, and a blind review in training replay.
 * These were the research tools' result panels; the run is the one the workspace shows.
 */
export function StrategyResearchRunDetails({ result, manager }: { result: ChartStrategyResultBundle; manager: DetailsManager }) {
  const runId = result.run.run_id;
  const report = result.report;
  const [trace, setTrace] = useState<unknown[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bridge, setBridge] = useState<Record<string, unknown> | null>(null);
  const [replayAvailable, setReplayAvailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void manager.loadBacktestCapabilities(controller.signal).then((capabilities) => {
      if (controller.signal.aborted) return;
      setReplayAvailable(capabilities.flags.BACKTEST_REPLAY_REVIEW_BRIDGE_ENABLED === true
        && capabilities.flags.BACKTEST_REPLAY_TRAINING_AVAILABLE === true);
    }, () => undefined);
    return () => controller.abort();
  }, [manager]);
  const act = (operation: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    void operation().catch((reason: unknown) => setError(failure(reason))).finally(() => setBusy(false));
  };
  const bridgeState = typeof bridge?.state === "string" ? bridge.state : null;
  const replayHref = researchReplayHref(bridge);
  return <div className="strategy-research-run-details" data-testid="strategy-research-run-details">
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    <section className="strategy-research-detail-section">
      <h4>{t("research.results.tab.trace")}</h4>
      <div className="strategy-research-detail-actions">
        <Button size="sm" disabled={busy} onClick={() => act(async () => setTrace((await manager.loadSignalTrace(runId)).items))}>
          {t("research.results.trace")}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(async () => download(`${runId}.backtest.json`, await manager.exportRun(runId)))}>
          {t("research.run.export")}
        </Button>
      </div>
      {trace !== null && <>
        <p className="strategy-research-note" role="status">{t("research.notice.traceLoaded", { count: trace.length })}</p>
        <pre className="strategy-research-detail-readout" data-testid="strategy-research-signal-trace">{JSON.stringify(trace, null, 2)}</pre>
      </>}
    </section>
    <section className="strategy-research-detail-section">
      <h4>{t("research.results.tab.quality")}</h4>
      <Disclosure summary={t("plugin.techDetails")}>
        <pre className="strategy-research-detail-readout">{JSON.stringify({
          data_quality: report.data_quality,
          quality: report.performance?.quality,
          reconciliation: report.performance?.reconciliation,
          fill_model: report.fill_model,
          fill_trace: report.fill_trace,
          unmodeled: report.unmodeled,
          suitable_for: report.suitable_for,
          not_suitable_for: report.not_suitable_for,
        }, null, 2)}</pre>
      </Disclosure>
    </section>
    {replayAvailable && <section className="strategy-research-detail-section" data-testid="strategy-research-review-bridge">
      <h4>{t("research.replay.eyebrow")}</h4>
      <p className="strategy-research-note">{t("research.replay.copy")}</p>
      <div className="strategy-research-detail-actions">
        <Button size="sm" disabled={busy || result.run.state !== "COMPLETED" || bridge !== null}
          onClick={() => act(async () => setBridge(await manager.createReviewBridge(runId, result.config.start_time_ms, result.config.end_time_ms)))}>
          {t("research.replay.create")}
        </Button>
        {bridgeState && <Badge tone={researchStateTone(bridgeState)}>{t("research.replay.state")} · {researchStateLabel(bridgeState)}</Badge>}
        {bridgeState === "BLINDED" && <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => act(async () => {
            const bridgeId = typeof bridge?.bridgeId === "string" ? bridge.bridgeId : "";
            const revealed = await manager.revealReviewBridge(bridgeId);
            setBridge((current) => ({ ...current, ...revealed }));
          })}>{t("research.replay.reveal")}</Button>}
        {replayHref && <a className={buttonClassName({ size: "sm", variant: "ghost" })} href={replayHref} target="_blank" rel="noreferrer">
          {t("research.replay.open")}
        </a>}
      </div>
    </section>}
  </div>;
}
