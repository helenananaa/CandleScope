import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { BacktestRunRecord, RunCompareV3 } from "../backtest/backtestTypes.js";
import { getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { formatChartStrategyNumber } from "../backtest/chart-tester/chartStrategyResultModel.js";
import { formatDecimal } from "../../shared/formatDecimal.js";

function researchRunConfig(run: BacktestRunRecord): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(run.config_json ?? "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

type Pair = readonly [left: string, right: string];

const conditionFields = [
  ["initial_balance", "chartTester.settings.capital"],
  ["taker_fee_bps", "chartTester.settings.fee"],
  ["slippage_bps", "ux.slippage"],
  ["leverage", "backtest.leverage"],
  ["start_time_ms", "ux.startUtc"],
  ["end_time_ms", "ux.endUtc"],
] as const;

const metrics = [
  ["netPnl", "chartTester.result.netPnl"],
  ["maxDrawdown", "chartTester.result.maxDrawdown"],
  ["tradeCount", "chartTester.result.trades"],
] as const;

function errorText(reason: unknown): string {
  return reason instanceof Error ? describeError(reason, reason.message) : String(reason);
}

export default function StrategyRunHistory({ manager, draftId, currentRunId, onOpen }: {
  manager: Pick<StrategyDataManager, "listRuns" | "compareRuns">;
  draftId: string | null;
  currentRunId: string | null;
  onOpen(runId: string): void;
}) {
  const locale = useLocale();
  const [runs, setRuns] = useState<BacktestRunRecord[]>([]);
  const [names, setNames] = useState<Map<string, string>>(() => new Map());
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Pair>(() => ["", currentRunId ?? ""]);
  const [requested, setRequested] = useState<Pair | null>(null);
  const [response, setResponse] = useState<{ pair: Pair; comparison?: RunCompareV3; error?: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void manager.listRuns(controller.signal).then((items) => {
      if (!controller.signal.aborted) {
        setRuns(items);
        setHistoryError(null);
      }
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setHistoryError(errorText(reason)); });
    void getChartStrategyDraftStore().recent(50).then((drafts) => {
      if (!controller.signal.aborted) setNames(new Map(drafts.map(draft => [draft.id, draft.displayName])));
    }).catch(() => undefined);
    return () => controller.abort();
  }, [currentRunId, manager]);

  useEffect(() => {
    if (!requested) return;
    const controller = new AbortController();
    void manager.compareRuns(requested[0], requested[1], controller.signal).then((comparison) => {
      if (!controller.signal.aborted) setResponse({ pair: requested, comparison });
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setResponse({ pair: requested, error: errorText(reason) });
    });
    return () => controller.abort();
  }, [manager, requested]);

  const entries = runs.map(run => ({ run, config: researchRunConfig(run) }));
  const history = entries.filter(({ config }) => (config.strategy_draft_id ?? null) === draftId);
  const completed = entries.filter(({ run }) => run.state === "COMPLETED");
  const activeResponse = response?.pair === requested ? response : null;
  const comparison = activeResponse?.comparison;
  const left = completed.find(({ run }) => run.run_id === comparison?.left.runId);
  const right = completed.find(({ run }) => run.run_id === comparison?.right.runId);
  const currentAvailable = completed.some(({ run }) => run.run_id === currentRunId);
  const date = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? new Date(value).toLocaleString(locale) : "—";
  const optionLabel = ({ run, config }: (typeof completed)[number]) => {
    const name = typeof config.strategy_draft_id === "string" ? names.get(config.strategy_draft_id) : undefined;
    return [name, config.symbol, config.interval, date(config.start_time_ms), run.run_id.slice(-8)].filter(Boolean).join(" · ");
  };
  const canCompare = selected[0] !== selected[1]
    && selected.every(id => completed.some(({ run }) => run.run_id === id));
  const pick = (position: 0 | 1, runId: string) => {
    setSelected(position === 0 ? [runId, selected[1]] : [selected[0], runId]);
    setRequested(null);
  };
  const openComparison = (pair: Pair) => { setSelected(pair); setRequested(pair); };
  const metric = (value: unknown) => formatDecimal(typeof value === "number" || typeof value === "string" ? String(value) : "—");

  return <section className="strategy-run-history" aria-label={t("ux.history")}>
    {historyError && <p role="alert">{historyError}</p>}
    {!history.length && <p>{t("ux.historyEmpty")}</p>}
    <div className="strategy-history-list">{history.map(({ run, config }) => <article key={run.run_id}>
      <div><strong>{String(config.symbol ?? "—")} · {String(config.interval ?? "—")}</strong><p>{date(config.start_time_ms)} — {date(config.end_time_ms)}</p><small>{run.state} · {run.run_id.slice(-8)}</small></div>
      <button type="button" disabled={run.state !== "COMPLETED"} onClick={() => onOpen(run.run_id)}>{t("ux.openResult")}</button>
      <button type="button" disabled={run.state !== "COMPLETED" || !currentAvailable || run.run_id === currentRunId}
        onClick={() => { if (currentRunId) openComparison([run.run_id, currentRunId]); }}>{t("ux.compare")}</button>
    </article>)}</div>
    {completed.length >= 2 && <fieldset>
      <legend>{t("ux.compare")}</legend>
      {([0, 1] as const).map(position => <label key={position}>
        {t(position === 0 ? "researchBatch.compareFirst" : "researchBatch.compareSecond")}
        <select aria-label={t(position === 0 ? "researchBatch.compareFirst" : "researchBatch.compareSecond")} value={selected[position]} onChange={(event) => pick(position, event.target.value)}>
          <option value="">{t("research.run.select")}</option>
          {completed.map(entry => <option key={entry.run.run_id} value={entry.run.run_id} disabled={entry.run.run_id === selected[1 - position]}>
            {optionLabel(entry)}
          </option>)}
        </select>
      </label>)}
      <button type="button" disabled={!canCompare} onClick={() => openComparison([...selected])}>{t("ux.compare")}</button>
    </fieldset>}
    {requested && !activeResponse && <p role="status">{t("researchBatch.compareLoading")}</p>}
    {activeResponse?.error && <p role="alert">{activeResponse.error}</p>}
    {comparison && left && right && <div className="strategy-history-comparison" data-testid="strategy-history-comparison">
      <h3>{t("ux.compare")}</h3>
      <p>{t(comparison.directComparisonAllowed ? "chartTester.compare.compatible" : "chartTester.compare.incompatible")}</p>
      {!comparison.directComparisonAllowed && <p>{comparison.incompatibleFields.join(" · ")} {comparison.precisionExplanation}</p>}
      <table><thead><tr><th>{t("chartTester.tab.settings")}</th><th>{optionLabel(left)}</th><th>{optionLabel(right)}</th></tr></thead><tbody>
        {conditionFields.map(([key, label]) => <tr key={key}><th>{t(label)}</th><td>{key.endsWith("_ms") ? date(left.config[key]) : String(left.config[key] ?? "—")}</td><td>{key.endsWith("_ms") ? date(right.config[key]) : String(right.config[key] ?? "—")}</td></tr>)}
        {Object.entries(comparison.parameterDiff).map(([key, values]) => <tr key={key}><th>{key}</th><td>{JSON.stringify(values.left)}</td><td>{JSON.stringify(values.right)}</td></tr>)}
      </tbody></table>
      <table><thead><tr><th>{t("chartTester.tab.overview")}</th><th>{left.run.run_id.slice(-8)}</th><th>{right.run.run_id.slice(-8)}</th>
        {comparison.directComparisonAllowed && <th>{t("researchBatch.compareDelta")}</th>}</tr></thead><tbody>
        {metrics.map(([key, label]) => {
          const values = comparison.tradeDiff[key];
          const format = key === "maxDrawdown" ? (value: unknown) => formatChartStrategyNumber(value, "percent") : metric;
          return <tr key={key}><th>{t(label)}</th><td>{format(values?.left)}</td><td>{format(values?.right)}</td>
            {comparison.directComparisonAllowed && <td>{format(values?.delta)}</td>}</tr>;
        })}
      </tbody></table>
      {comparison.fingerprintDiff.available && comparison.directComparisonAllowed && <p>{t("chartTester.compare.tradeChanges")} · {t("chartTester.compare.addRemove", {
        added: comparison.fingerprintDiff.addedCount ?? 0, removed: comparison.fingerprintDiff.removedCount ?? 0,
      })}</p>}
      {[left, right].map(({ run }) => <button type="button" key={run.run_id} onClick={() => onOpen(run.run_id)}>
        {t("ux.openResult")} · {run.run_id.slice(-8)}
      </button>)}
    </div>}
  </section>;
}
