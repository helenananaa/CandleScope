import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { defaultBacktestApi } from "../backtest/backtestApi.js";
import type { BacktestRunRecord, RunCompareV3 } from "../backtest/backtestTypes.js";
import { formatDecimal } from "../../shared/formatDecimal.js";

function researchRunConfig(run: BacktestRunRecord): Record<string, unknown> {
  try { const value: unknown = JSON.parse(run.config_json ?? "{}"); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; } catch { return {}; }
}

export default function StrategyRunHistory({ draftId, currentRunId, onOpen }: { draftId: string | null; currentRunId: string | null; onOpen(runId: string): void }) {
  const locale = useLocale();
  const [runs, setRuns] = useState<BacktestRunRecord[]>([]);
  const [comparison, setComparison] = useState<RunCompareV3 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void defaultBacktestApi.listRuns(controller.signal).then((items) => {
      if (!controller.signal.aborted) setRuns(items.filter((run) => researchRunConfig(run).strategy_draft_id === draftId));
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [draftId, currentRunId]);
  useEffect(() => {
    const controller = new AbortController();
    setComparison(null);
    if (baseline && currentRunId && baseline !== currentRunId) {
      void defaultBacktestApi.compareRuns(baseline, currentRunId, controller.signal).then((value) => {
        if (!controller.signal.aborted) setComparison(value);
      }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(String(reason)); });
    }
    return () => controller.abort();
  }, [baseline, currentRunId]);
  const date = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? new Date(value).toLocaleString(locale) : "—";
  const conditionFields = [
    ["initial_balance", "chartTester.settings.capital"], ["taker_fee_bps", "chartTester.settings.fee"],
    ["slippage_bps", "ux.slippage"], ["leverage", "backtest.leverage"],
    ["start_time_ms", "ux.startUtc"], ["end_time_ms", "ux.endUtc"],
  ] as const;
  const leftRun = runs.find((run) => run.run_id === comparison?.left.runId);
  const rightRun = runs.find((run) => run.run_id === comparison?.right.runId);
  const leftConfig = leftRun ? researchRunConfig(leftRun) : {};
  const rightConfig = rightRun ? researchRunConfig(rightRun) : {};
  return <section className="strategy-run-history" aria-label={t("ux.history")}>
    {error && <p role="alert">{error}</p>}
    {!runs.length && <p>{t("ux.historyEmpty")}</p>}
    <div className="strategy-history-list">{runs.map((run) => { const config = researchRunConfig(run); return <article key={run.run_id}>
      <div><strong>{String(config.symbol ?? "—")} · {String(config.interval ?? "—")}</strong><p>{date(config.start_time_ms)} — {date(config.end_time_ms)}</p><small>{run.state} · {run.run_id.slice(-8)}</small></div>
      <button type="button" disabled={run.state !== "COMPLETED"} onClick={() => onOpen(run.run_id)}>{t("ux.openResult")}</button>
      <button type="button" disabled={run.state !== "COMPLETED" || !currentRunId || run.run_id === currentRunId} onClick={() => setBaseline(run.run_id)}>{t("ux.compare")}</button>
    </article>; })}</div>
    {comparison && <div className="strategy-history-comparison">
      <h3>{t("ux.compare")}</h3>
      <p>{t(comparison.directComparisonAllowed ? "chartTester.compare.compatible" : "chartTester.compare.incompatible")}</p>
      {!comparison.directComparisonAllowed && <p>{comparison.incompatibleFields.join(" · ")} {comparison.precisionExplanation}</p>}
      <table><thead><tr><th>{t("chartTester.tab.settings")}</th><th>{comparison.left.runId.slice(-8)}</th><th>{comparison.right.runId.slice(-8)}</th></tr></thead><tbody>
        {conditionFields.map(([key, label]) => <tr key={key}><th>{t(label)}</th><td>{key.endsWith("_ms") ? date(leftConfig[key]) : String(leftConfig[key] ?? "—")}</td><td>{key.endsWith("_ms") ? date(rightConfig[key]) : String(rightConfig[key] ?? "—")}</td></tr>)}
        {Object.entries(comparison.parameterDiff).map(([key, values]) => <tr key={key}><th>{key}</th><td>{JSON.stringify(values.left)}</td><td>{JSON.stringify(values.right)}</td></tr>)}
      </tbody></table>
      {comparison.directComparisonAllowed && <table><tbody>{Object.entries(comparison.tradeDiff).map(([key, values]) => <tr key={key}><th>{key}</th><td>{formatDecimal(String(values.left ?? "—"))}</td><td>{formatDecimal(String(values.right ?? "—"))}</td><td>{formatDecimal(values.delta ?? "—")}</td></tr>)}</tbody></table>}
    </div>}
  </section>;
}
