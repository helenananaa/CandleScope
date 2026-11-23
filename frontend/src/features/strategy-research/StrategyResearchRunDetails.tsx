import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Disclosure, Field, InlineAlert, Input, Select, Textarea, buttonClassName } from "../../components/ui/index.js";
import type { StrategyVersionDraft } from "../backtest/runResult/strategyRun.js";
import { researchFidelityLabel } from "../backtest/research/researchLabels.js";
import { changedSettings, derivableSettings } from "./runDerivation.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import { researchReplayHref } from "../backtest/research/backtestResearchAdvancedModel.js";
import { researchStateLabel } from "../backtest/research/researchLabels.js";
import { researchStateTone } from "../backtest/research/researchStateTone.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";

type DetailsManager = Pick<StrategyDataManager, "loadBacktestCapabilities" | "exportRun" | "loadSignalTrace"
  | "createReviewBridge" | "revealReviewBridge" | "deriveRun" | "loadRunStatus" | "listStrategyVersionNames"
  | "nameStrategyVersion" | "loadStrategyVersionDraft">;

const FILL_MODES = [["BAR_APPROX", "BAR"], ["AGG_TRADE_EXECUTION", "AGG_TRADE"]] as const;

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
export function StrategyResearchRunDetails({ result, manager, onRunCreated, onOpenVersion }: {
  result: ChartStrategyResultBundle;
  manager: DetailsManager;
  /** A run created from this one with changed settings; the workspace shows it. */
  onRunCreated?(runId: string): void;
  /** A named version's editor text, to edit as a new draft. */
  onOpenVersion?(version: StrategyVersionDraft, name: string): void;
}) {
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
  const original = useMemo(() => derivableSettings(result.config), [result.config]);
  const [settingsText, setSettingsText] = useState(() => JSON.stringify(original, null, 2));
  const [notice, setNotice] = useState<string | null>(null);
  let fillMode = typeof original.fidelity_mode === "string" ? original.fidelity_mode : "BAR_APPROX";
  try { const parsed = JSON.parse(settingsText) as Record<string, unknown>; if (typeof parsed.fidelity_mode === "string") fillMode = parsed.fidelity_mode; }
  catch { /* the text is being edited */ }
  const [versionHash, setVersionHash] = useState<string | null>(null);
  const [names, setNames] = useState<Array<{ name: string; version_hash: string }>>([]);
  const [versionName, setVersionName] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void manager.loadRunStatus(runId, controller.signal).then((status) => {
      if (!controller.signal.aborted) setVersionHash(status.version_hash);
    }, () => undefined);
    void manager.listStrategyVersionNames(controller.signal).then((value) => {
      if (!controller.signal.aborted) setNames(value);
    }, () => undefined);
    return () => controller.abort();
  }, [manager, runId]);
  const bridgeState = typeof bridge?.state === "string" ? bridge.state : null;
  const replayHref = researchReplayHref(bridge);
  return <div className="strategy-research-run-details" data-testid="strategy-research-run-details">
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    {notice && <p className="strategy-research-note" role="status">{notice}</p>}
    {onRunCreated && <section className="strategy-research-detail-section" data-testid="strategy-research-rerun">
      <h4>{t("researchResult.rerun")}</h4>
      <p className="strategy-research-note">{t("researchResult.rerunHint")}</p>
      <Field label={t("native.external.fidelity")}>
        <Select size="sm" value={fillMode} disabled={busy} onChange={(event) => {
          const mode = FILL_MODES.find(([value]) => value === event.target.value);
          if (!mode) return;
          try {
            const parsed = JSON.parse(settingsText) as Record<string, unknown>;
            setSettingsText(JSON.stringify({ ...parsed, fidelity_mode: mode[0], source_event_kind: mode[1] }, null, 2));
          } catch { setError(t("researchResult.invalidSettings")); }
        }}>
          {FILL_MODES.map(([value]) => <option key={value} value={value}>{researchFidelityLabel(value)}</option>)}
          {!FILL_MODES.some(([value]) => value === fillMode) && <option value={fillMode}>{researchFidelityLabel(fillMode)}</option>}
        </Select>
      </Field>
      <Field label={t("researchResult.settings")}>
        <Textarea className="strategy-research-detail-editor" rows={10} spellCheck={false} disabled={busy}
          value={settingsText} onChange={(event) => setSettingsText(event.target.value)} />
      </Field>
      <div className="strategy-research-detail-actions">
        <Button size="sm" variant="primary" disabled={busy} onClick={() => act(async () => {
          const overrides = changedSettings(original, settingsText);
          if (overrides === null) throw new Error(t("researchResult.invalidSettings"));
          if (!Object.keys(overrides).length) throw new Error(t("researchResult.noChange"));
          onRunCreated((await manager.deriveRun(runId, overrides)).run_id);
        })}>{t("researchExperiment.retry")}</Button>
      </div>
    </section>}
    <section className="strategy-research-detail-section" data-testid="strategy-research-version">
      <h4>{t("researchResult.version")}</h4>
      {versionHash && <p className="strategy-research-note"><code title={versionHash}>{versionHash.slice(0, 19)}…</code>
        {names.filter((item) => item.version_hash === versionHash).map((item) => <Badge key={item.name}>{item.name}</Badge>)}</p>}
      {versionHash && <div className="strategy-research-detail-actions">
        <Input size="sm" aria-label={t("researchResult.versionName")} placeholder={t("researchResult.versionName")} maxLength={80}
          value={versionName} onChange={(event) => setVersionName(event.target.value)} />
        <Button size="sm" disabled={busy || !versionName.trim()} onClick={() => act(async () => {
          const name = versionName.trim();
          await manager.nameStrategyVersion(name, versionHash);
          setNames(await manager.listStrategyVersionNames());
          setVersionName("");
          setNotice(t("researchResult.versionNamed", { name }));
        })}>{t("researchResult.nameVersion")}</Button>
      </div>}
      {onOpenVersion && names.length > 0 && <Disclosure summary={t("researchResult.namedVersions")}>
        <ul className="strategy-history-list">{names.map((item) => <li key={item.name} className="strategy-history-row">
          <div className="strategy-history-run"><strong>{item.name}</strong><span><code>{item.version_hash.slice(0, 19)}…</code></span></div>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(async () => {
            onOpenVersion(await manager.loadStrategyVersionDraft(item.version_hash), item.name);
          })}>{t("researchResult.openVersion")}</Button>
        </li>)}</ul>
      </Disclosure>}
    </section>
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
