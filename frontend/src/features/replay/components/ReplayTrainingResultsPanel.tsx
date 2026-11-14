import { useReplayOperations } from "../useReplayOperations.js";
import { describeError } from "../../../i18n/serverErrors.js";
import { useEffect, useId, useState } from "react";
import { useControlCommands } from "../../app-control/useControlCommands.js";
import { command } from "../../app-control/commandRegistry.js";
import { empty, object, text } from "../../app-control/commandSchema.js";

import { getNumberLocale, t } from "../../../i18n/index.js";
import { Icon } from "../../../components/icons/Icon.js";
import { Badge, Button, EmptyState, IconButton, InlineAlert, Stat } from "../../../components/ui/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { LocaleId } from "../../../i18n/locale.js";
import type {
  ReplayTrainingResultItem,
  ReplayTrainingResultsResponse,
} from "../replayV2Types.js";
import type { ReplayIntegrityRuntime } from "../useReplayIntegrityRuntime.js";

interface ReplayTrainingResultsPanelProps {
  readonly runId: string;
  readonly integrityRuntime: ReplayIntegrityRuntime;
  readonly trainingState: string | null;
  readonly onClose: () => void;
}

function decimal(value: string | null, digits = 2, locale: LocaleId): string {
  if (value === null) return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(getNumberLocale(locale), { maximumFractionDigits: digits })
    : value;
}

function percent(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : "--";
}

function duration(valueMs: number, locale: LocaleId): string {
  if (valueMs < 60_000) return t("replay.results.sec", { count: Math.round(valueMs / 1_000) }, locale);
  if (valueMs < 3_600_000) return t("replay.results.min", { count: Math.round(valueMs / 60_000) }, locale);
  if (valueMs < 86_400_000) return t("replay.results.hour", { count: (valueMs / 3_600_000).toFixed(1) }, locale);
  return t("replay.results.day", { count: (valueMs / 86_400_000).toFixed(1) }, locale);
}

function TradeRow({
  item,
  jumping,
  forking,
  canReview,
  onJump,
  onFork,
}: {
  readonly item: ReplayTrainingResultItem;
  readonly jumping: boolean;
  readonly forking: boolean;
  readonly canReview: boolean;
  readonly onJump: () => void;
  readonly onFork: () => void;
}) {
  const locale = useLocale();
  const plan = item.plans[0] ?? null;
  const pnl = Number(item.gross_realized_pnl);
  return (
    <li className="replay-training-result-row" data-pnl={pnl > 0 ? "profit" : pnl < 0 ? "loss" : "flat"}>
      <div className="replay-training-result-head">
        <strong>{item.symbol}</strong>
        <Badge tone={item.position_side === "BUY" ? "success" : "danger"}>
          {item.position_side === "BUY" ? t("replay.results.long") : t("replay.results.short")}
        </Badge>
        <span className="replay-training-result-pnl">
          {decimal(item.gross_realized_pnl, 2, locale)} {item.settlement_asset} · {item.r_multiple === null ? t("replay.results.noPlanR") : `${decimal(item.r_multiple, 2, locale)}R`}
        </span>
      </div>
      <dl className="replay-training-result-facts">
        <div><dt>{t("replay.results.entryExit")}</dt><dd>{decimal(item.entry_price, 8, locale)} / {decimal(item.exit_price, 8, locale)}</dd></div>
        <div><dt>MAE / MFE</dt><dd>{decimal(item.mae, 2, locale)} / {decimal(item.mfe, 2, locale)} {item.settlement_asset}</dd></div>
        <div><dt>{t("replay.results.hold")}</dt><dd>{duration(item.holding_duration_ms, locale)}</dd></div>
        <div><dt>{t("replay.results.qty")}</dt><dd>{decimal(item.quantity, 8, locale)}</dd></div>
        <div><dt>{t("replay.results.risk")}</dt><dd>{decimal(item.initial_risk_amount, 2, locale)} {item.settlement_asset}</dd></div>
        <div><dt>{t("replay.results.plan")}</dt><dd>{plan === null ? t("replay.results.unrecorded") : `${decimal(plan.risk_amount, 2, locale)} ${item.settlement_asset} · ${decimal(plan.reward_risk_ratio, 2, locale)} R:R`}</dd></div>
      </dl>
      {plan !== null && <p className="replay-training-result-plan" title={plan.plan_hash}>{plan.reason}</p>}
      <div className="replay-training-result-actions">
        <Button
          size="sm"
          disabled={!canReview || item.review_event_id === null || jumping}
          onClick={onJump}
        >{jumping ? t("replay.results.jumping") : t("replay.results.jump")}</Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!canReview || item.review_event_id === null || forking}
          onClick={onFork}
        >{forking ? t("replay.results.forking") : t("replay.results.fork")}</Button>
      </div>
    </li>
  );
}

export default function ReplayTrainingResultsPanel({
  runId,
  integrityRuntime,
  trainingState,
  onClose,
}: ReplayTrainingResultsPanelProps) {
  const { api } = useReplayOperations(runId, "rail");
  const locale = useLocale();
  const [results, setResults] = useState<ReplayTrainingResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jumpingId, setJumpingId] = useState<string | null>(null);
  const [forkingId, setForkingId] = useState<string | null>(null);
  const [forkedRunId, setForkedRunId] = useState<string | null>(null);

  const load = () => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void api.trainingResultsRun(runId, controller.signal).then((response) => {
      setResults(response);
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? describeError(cause, cause.message) : t("replay.results.loadFailed"));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return controller;
  };

  useEffect(() => {
    const controller = load();
    return () => controller.abort();
    // The panel is remounted for each run; explicit refresh handles later mutations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const canReview = trainingState === "PAUSED" || trainingState === "ENDED";
  const jump = async (item: ReplayTrainingResultItem) => {
    if (item.review_event_id === null) return;
    setJumpingId(item.trade_id);
    setError(null);
    try {
      if (integrityRuntime.review === null) {
        await integrityRuntime.actions.startReview(item.review_event_id);
      } else {
        await integrityRuntime.actions.controlReview("JUMP", {
          eventId: item.review_event_id,
        });
      }
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? describeError(cause, cause.message) : t("replay.results.jumpFailed"));
    } finally {
      setJumpingId(null);
    }
  };

  const fork = async (item: ReplayTrainingResultItem) => {
    if (item.review_event_id === null) return;
    setForkingId(item.trade_id);
    setError(null);
    try {
      const response = await integrityRuntime.actions.forkReview(item.review_event_id);
      setForkedRunId(response.run.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? describeError(cause, cause.message) : t("replay.results.forkFailed"));
    } finally {
      setForkingId(null);
    }
  };

  const summary = results?.summary ?? null;
  const controlId = useId();
  useControlCommands(() => ({ id: `replay-results:${controlId}`, title: "Replay training trade results", context: () => ({ runId, trainingState, jumpingId, forkingId, results }), snapshot: () => ({ runId, results, loading, error, jumpingId, forkingId, forkedRunId, canReview }), commands: [
    command("refresh", "Refresh public training results.", empty, () => { load(); }, { available: () => !loading }),
    command("jump", "Review a listed trade with a domain review event, while paused/ended.", object({ tradeId: text(128) }), ({ tradeId }) => { const item = results?.items.find((item) => item.trade_id === tradeId); if (!item || item.review_event_id === null) throw new Error("TRADE_REVIEW_UNAVAILABLE"); return jump(item); }, { available: () => canReview && !jumpingId && !forkingId }),
    command("fork", "Fork from a listed trade's review event using the existing domain workflow.", object({ tradeId: text(128) }), ({ tradeId }) => { const item = results?.items.find((item) => item.trade_id === tradeId); if (!item || item.review_event_id === null) throw new Error("TRADE_REVIEW_UNAVAILABLE"); return fork(item); }, { available: () => canReview && !jumpingId && !forkingId }),
    command("close", "Close training results.", empty, onClose),
  ] }));
  const summaryAsset = results?.items[0]?.settlement_asset ?? "";
  const net = summary === null ? 0 : Number(summary.net_realized_pnl);
  return (
    <section className="replay-drawer-panel" data-replay-panel="training-results" aria-labelledby={`${controlId}-title`}>
      <header className="replay-drawer-head">
        <div>
          <h2 id={`${controlId}-title`}>{t("replay.results.title")}</h2>
          <p>{t("replay.results.hint")}</p>
        </div>
        <div className="replay-drawer-actions">
          <IconButton size="sm" label={t("replay.hub.refresh")} icon={<Icon name="refresh" size={15} />} disabled={loading} onClick={() => load()} />
          <IconButton size="sm" label={t("replay.hub.close")} icon={<Icon name="close" size={15} />} onClick={onClose} />
        </div>
      </header>

      <div className="replay-drawer-body">
        {summary !== null && (
          <div className="replay-training-result-summary">
            <Stat label={t("replay.results.winRate")} value={percent(summary.win_rate)} />
            <Stat label={t("replay.results.payoff")} value={decimal(summary.payoff_ratio, 2, locale)} />
            <Stat label={t("replay.results.net")} value={`${decimal(summary.net_realized_pnl, 2, locale)} ${summaryAsset}`.trim()}
              tone={net > 0 ? "success" : net < 0 ? "danger" : "neutral"} />
            <Stat label={t("replay.results.drawdown")} value={`${decimal(summary.max_drawdown, 2, locale)} ${summaryAsset}`.trim()} />
            <Stat label={t("replay.results.avgR")} value={summary.average_r_multiple === null ? "--" : `${decimal(summary.average_r_multiple, 2, locale)}R`} />
            <Stat label={t("replay.results.avgHold")} value={duration(summary.average_holding_duration_ms, locale)} />
            <Stat label={t("replay.results.avgMae")} value={`${decimal(summary.average_mae, 2, locale)} ${summaryAsset}`.trim()} />
            <Stat label={t("replay.results.avgMfe")} value={`${decimal(summary.average_mfe, 2, locale)} ${summaryAsset}`.trim()} />
          </div>
        )}

        {!canReview && <InlineAlert tone="info">{t("replay.results.pauseToJump")}</InlineAlert>}
        {forkedRunId !== null && <InlineAlert tone="success">{t("replay.results.forked", { id: forkedRunId })}</InlineAlert>}
        {error !== null && <InlineAlert tone="danger">{error}</InlineAlert>}
        {loading && results === null && <EmptyState compact icon={<span className="replay-loading-spinner" />} title={t("replay.results.loading")} />}
        {!loading && results !== null && results.items.length === 0 && <EmptyState compact title={t("replay.results.empty")} />}
        {results !== null && results.items.length > 0 && (
          <ul className="replay-training-result-list">
            {results.items.map((item) => (
              <TradeRow
                key={`${item.track_id}:${item.trade_id}`}
                item={item}
                jumping={jumpingId === item.trade_id}
                forking={forkingId === item.trade_id}
                canReview={canReview}
                onJump={() => void jump(item)}
                onFork={() => void fork(item)}
              />
            ))}
          </ul>
        )}
        {results?.truncated && <p className="replay-drawer-note">{t("replay.results.truncated", { count: results.returned_count })}</p>}
      </div>
    </section>
  );
}
