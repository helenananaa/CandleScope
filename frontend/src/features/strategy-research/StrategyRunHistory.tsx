import { useEffect, useState } from "react";
import { Badge, Button, EmptyState, Field, InlineAlert, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { BacktestRunRecord, RunCompareV3 } from "../backtest/backtestTypes.js";
import { getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { formatChartStrategyNumber, sampledReportDrawdown } from "../backtest/chart-tester/chartStrategyResultModel.js";
import { formatDecimal } from "../../shared/formatDecimal.js";
import { researchStateTone } from "../backtest/research/researchStateTone.js";

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
  const history = entries.filter(({ config }) => (config.strategy_draft_id ?? null) === draftId
    || typeof config.external_connection_id === "string");
  const completed = entries.filter(({ run }) => run.state === "COMPLETED");
  const activeResponse = response?.pair === requested ? response : null;
  const comparison = activeResponse?.comparison;
  const left = completed.find(({ run }) => run.run_id === comparison?.left.runId);
  const right = completed.find(({ run }) => run.run_id === comparison?.right.runId);
  const drawdown = comparison?.tradeDiff.maxDrawdown;
  const needsSampledDrawdown = comparison && left && right && (drawdown?.left == null || drawdown?.right == null);
  const sampledLeft = needsSampledDrawdown
    ? sampledReportDrawdown({ equity_curve: comparison.left.equity, account: { initial_balance: left.config.initial_balance } })
    : null;
  const sampledRight = needsSampledDrawdown
    ? sampledReportDrawdown({ equity_curve: comparison.right.equity, account: { initial_balance: right.config.initial_balance } })
    : null;
  const sampled = sampledLeft && sampledRight ? {
    left: sampledLeft.maximum,
    right: sampledRight.maximum,
    delta: sampledRight.maximum - sampledLeft.maximum,
  } : null;
  const currentAvailable = completed.some(({ run }) => run.run_id === currentRunId);
  const date = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? new Date(value).toLocaleString(locale) : "—";
  const optionLabel = ({ run, config }: (typeof completed)[number]) => {
    const name = typeof config.strategy_draft_id === "string" ? names.get(config.strategy_draft_id) : undefined;
    const label = name ?? (typeof config.external_connection_id === "string" ? t("research.external.title") : undefined);
    return [label, config.symbol, config.interval, date(config.start_time_ms), run.run_id.slice(-8)].filter(Boolean).join(" · ");
  };
  const canCompare = selected[0] !== selected[1]
    && selected.every(id => completed.some(({ run }) => run.run_id === id));
  const pick = (position: 0 | 1, runId: string) => {
    setSelected(position === 0 ? [runId, selected[1]] : [selected[0], runId]);
    setRequested(null);
  };
  const openComparison = (pair: Pair) => { setSelected(pair); setRequested(pair); };
  const metric = (value: unknown) => formatDecimal(typeof value === "number" || typeof value === "string" ? String(value) : "—");

  const shortId = (runId: string) => runId.slice(-8);
  return <section className="strategy-history" aria-label={t("ux.history")}>
    {historyError && <InlineAlert tone="danger">{historyError}</InlineAlert>}
    {!history.length && <EmptyState compact title={t("ux.historyEmpty")} />}
    {history.length > 0 && <ul className="strategy-history-list">{history.map(({ run, config }) => <li key={run.run_id}
      className="strategy-history-row" data-active={run.run_id === currentRunId ? "true" : undefined}>
      <div className="strategy-history-run">
        <strong>{String(config.symbol ?? "—")} · {String(config.interval ?? "—")}</strong>
        <span>{date(config.start_time_ms)} — {date(config.end_time_ms)}</span>
        <small>{typeof config.external_connection_id === "string" && `${t("research.external.title")} · `}{shortId(run.run_id)}</small>
      </div>
      <Badge tone={researchStateTone(run.state)}>{run.state}</Badge>
      <div className="strategy-history-actions">
        <Button size="sm" disabled={run.state !== "COMPLETED"} onClick={() => onOpen(run.run_id)}>{t("ux.openResult")}</Button>
        <Button size="sm" variant="ghost" disabled={run.state !== "COMPLETED" || !currentAvailable || run.run_id === currentRunId}
          onClick={() => { if (currentRunId) openComparison([run.run_id, currentRunId]); }}>{t("ux.compare")}</Button>
      </div>
    </li>)}</ul>}
    {completed.length >= 2 && <section className="strategy-history-compare" aria-label={t("ux.compare")}>
      <h3>{t("ux.compare")}</h3>
      {([0, 1] as const).map(position => <Field key={position} label={t(position === 0 ? "researchBatch.compareFirst" : "researchBatch.compareSecond")}>
        <Select size="sm" value={selected[position]} onChange={(event) => pick(position, event.target.value)}>
          <option value="">{t("research.run.select")}</option>
          {completed.map(entry => <option key={entry.run.run_id} value={entry.run.run_id} disabled={entry.run.run_id === selected[1 - position]}>
            {optionLabel(entry)}
          </option>)}
        </Select>
      </Field>)}
      <Button size="sm" variant="primary" disabled={!canCompare} onClick={() => openComparison([...selected])}>{t("ux.compare")}</Button>
    </section>}
    {requested && !activeResponse && <p className="strategy-research-note" role="status">{t("researchBatch.compareLoading")}</p>}
    {activeResponse?.error && <InlineAlert tone="danger">{activeResponse.error}</InlineAlert>}
    {comparison && left && right && <div className="strategy-history-comparison" data-testid="strategy-history-comparison">
      <h3>{t("ux.compare")}</h3>
      {comparison.directComparisonAllowed
        ? <p className="strategy-research-note">{t("chartTester.compare.compatible")}</p>
        : <InlineAlert tone="warning" title={t("chartTester.compare.incompatible")}>
          {comparison.incompatibleFields.join(" · ")} {comparison.precisionExplanation}
        </InlineAlert>}
      <table className="strategy-history-table"><thead><tr><th scope="col">{t("chartTester.tab.settings")}</th>
        <th scope="col" title={optionLabel(left)}>{shortId(left.run.run_id)}</th><th scope="col" title={optionLabel(right)}>{shortId(right.run.run_id)}</th></tr></thead><tbody>
        {conditionFields.map(([key, label]) => <tr key={key}><th scope="row">{t(label)}</th><td>{key.endsWith("_ms") ? date(left.config[key]) : String(left.config[key] ?? "—")}</td><td>{key.endsWith("_ms") ? date(right.config[key]) : String(right.config[key] ?? "—")}</td></tr>)}
        {Object.entries(comparison.parameterDiff).map(([key, values]) => <tr key={key}><th scope="row">{key}</th><td>{JSON.stringify(values.left)}</td><td>{JSON.stringify(values.right)}</td></tr>)}
      </tbody></table>
      <table className="strategy-history-table"><thead><tr><th scope="col">{t("chartTester.tab.overview")}</th><th scope="col">{shortId(left.run.run_id)}</th><th scope="col">{shortId(right.run.run_id)}</th>
        {comparison.directComparisonAllowed && <th scope="col">{t("researchBatch.compareDelta")}</th>}</tr></thead><tbody>
        {metrics.map(([key, label]) => {
          const values = key === "maxDrawdown" && sampled ? sampled : comparison.tradeDiff[key];
          const format = key === "maxDrawdown" ? (value: unknown) => formatChartStrategyNumber(value, "percent") : metric;
          return <tr key={key}><th scope="row">{t(label)}{key === "maxDrawdown" && sampled && <small> · {t("chartTester.result.drawdownBasis")}</small>}</th><td>{format(values?.left)}</td><td>{format(values?.right)}</td>
            {comparison.directComparisonAllowed && <td>{format(values?.delta)}</td>}</tr>;
        })}
      </tbody></table>
      {comparison.fingerprintDiff.available && comparison.directComparisonAllowed && <p className="strategy-research-note">{t("chartTester.compare.tradeChanges")} · {t("chartTester.compare.addRemove", {
        added: comparison.fingerprintDiff.addedCount ?? 0, removed: comparison.fingerprintDiff.removedCount ?? 0,
      })}</p>}
      <div className="strategy-history-actions">
        {[left, right].map(({ run }) => <Button size="sm" key={run.run_id} onClick={() => onOpen(run.run_id)}>
          {t("ux.openResult")} · {shortId(run.run_id)}
        </Button>)}
      </div>
    </div>}
  </section>;
}
