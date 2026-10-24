import { useState } from "react";
import { t } from "../../i18n/index.js";
import {
  formatAmount,
  formatDateTime,
  formatPercent,
  formatProfitFactor,
  formatR,
  formatRBucket,
  formatSigned,
  pnlTone,
} from "./tradingFormat.js";
import type {
  TradingAccount,
  TradingRBucket,
  TradingStats,
  TradingStatsGroup,
} from "./tradingTypes.js";
import { useTradingStats } from "./useTradingStats.js";

const DAY_MS = 86_400_000;
const PERIODS = [
  { id: "all", days: null },
  { id: "7d", days: 7 },
  { id: "30d", days: 30 },
  { id: "90d", days: 90 },
] as const;

type PeriodId = (typeof PERIODS)[number]["id"];

export interface TradingStatsViewProps {
  account: TradingAccount;
  /** Changes whenever closed trades or journal entries change. */
  revision: string;
}

/** Closed-trade statistics of one account: headline, R, breakdowns. */
export default function TradingStatsView({ account, revision }: TradingStatsViewProps) {
  const [period, setPeriod] = useState<{ id: PeriodId; fromMs: number | null }>({ id: "all", fromMs: null });
  const [tag, setTag] = useState<string | null>(null);
  const { stats, loading, error } = useTradingStats(account.id, period.fromMs, tag, revision);

  return (
    <div className="trading-stats" aria-busy={loading}>
      <div className="trading-stats-filters">
        <div className="trading-segmented" role="group" aria-label={t("trading.stats.period")}>
          {PERIODS.map((item) => (
            <button
              key={item.id}
              type="button"
              data-active={period.id === item.id}
              aria-pressed={period.id === item.id}
              onClick={() => setPeriod({
                id: item.id,
                fromMs: item.days === null ? null : Date.now() - item.days * DAY_MS,
              })}
            >
              {t(`trading.stats.period.${item.id}` as const)}
            </button>
          ))}
        </div>
        {tag !== null && (
          <button
            type="button"
            className="trading-badge trading-stats-chip"
            data-tone="accent"
            aria-label={t("trading.stats.clearTag", { tag })}
            onClick={() => setTag(null)}
          >
            {t("trading.stats.tagFilter", { tag })}
            <span aria-hidden="true">×</span>
          </button>
        )}
      </div>
      {error && <p className="trading-error" role="alert">{error}</p>}
      {stats === null
        ? !error && <p className="trading-empty-line">{t("trading.stats.loading")}</p>
        : <StatsBody stats={stats} onTag={tag === null ? setTag : null} />}
    </div>
  );
}

function StatsBody({ stats, onTag }: { stats: TradingStats; onTag: ((tag: string) => void) | null }) {
  const threshold = stats.lowSampleThreshold;
  const tags = stats.breakdowns.tag;
  return (
    <>
      <p className="trading-help">
        {t("trading.stats.scope")}
        {stats.openTrades > 0 && ` ${t("trading.stats.openExcluded", { count: stats.openTrades })}`}
      </p>
      {stats.tradeCount === 0 ? (
        <p className="trading-empty-line">{t("trading.stats.empty")}</p>
      ) : (
        <>
          <Headline stats={stats} />
          <RSection stats={stats} />
          <Breakdown
            title={t("trading.stats.byTiming")}
            hint={t("trading.stats.timingHint")}
            groups={stats.breakdowns.planTiming}
            label={(key) => t(`trading.stats.timing.${key}` as const)}
            threshold={threshold}
          />
          <Breakdown
            title={t("trading.stats.byDirection")}
            groups={stats.breakdowns.direction}
            label={(key) => t(key === "long" ? "trading.long" : "trading.short")}
            threshold={threshold}
          />
          {tags.every((group) => group.key === null) ? (
            <section className="trading-stats-section">
              <h3 className="trading-subhead">{t("trading.stats.byTag")}</h3>
              <p className="trading-empty-line">{t("trading.stats.noTags")}</p>
            </section>
          ) : (
            <Breakdown
              title={t("trading.stats.byTag")}
              hint={t("trading.stats.tagHint")}
              groups={tags}
              label={(key) => key ?? t("trading.stats.untagged")}
              threshold={threshold}
              onSelect={onTag}
            />
          )}
          <p className="trading-help">
            <span className="trading-stats-mark" aria-hidden="true">*</span>
            {t("trading.stats.lowSampleHint", { count: threshold })}
          </p>
        </>
      )}
    </>
  );
}

function Headline({ stats }: { stats: TradingStats }) {
  const drawdown = Number(stats.maxDrawdown.amount);
  return (
    <section className="trading-stats-grid" aria-label={t("trading.tab.stats")}>
      <Stat
        label={t("trading.stats.trades")}
        value={String(stats.tradeCount)}
        sub={t("trading.stats.wonLost", { wins: stats.wins, losses: stats.losses, breakeven: stats.breakeven })}
        lowSample={stats.lowSample ? stats.lowSampleThreshold : null}
      />
      <Stat label={t("trading.stats.winRate")} value={formatPercent(stats.winRate)} />
      <Stat
        label={t("trading.stats.netPnl")}
        value={formatSigned(stats.netPnl)}
        tone={pnlTone(stats.netPnl)}
        sub={t("trading.stats.perTrade", { value: formatSigned(stats.avgPnl) })}
      />
      <Stat label={t("trading.stats.fees")} value={formatAmount(stats.fees)} />
      <Stat label={t("trading.stats.avgWin")} value={formatSigned(stats.avgWin)} tone={pnlTone(stats.avgWin)} />
      <Stat label={t("trading.stats.avgLoss")} value={formatSigned(stats.avgLoss)} tone={pnlTone(stats.avgLoss)} />
      <Stat label={t("trading.stats.profitFactor")} value={formatProfitFactor(stats)} />
      <Stat
        label={t("trading.stats.maxDrawdown")}
        value={drawdown > 0 ? formatSigned(-drawdown) : formatAmount(0)}
        tone={drawdown > 0 ? "down" : "flat"}
        {...(stats.maxDrawdown.troughAtMs !== null
          ? { sub: t("trading.stats.drawdownLow", { time: formatDateTime(stats.maxDrawdown.troughAtMs) }) }
          : {})}
      />
    </section>
  );
}

interface StatProps {
  label: string;
  value: string;
  tone?: "up" | "down" | "flat";
  sub?: string;
  title?: string;
  /** The low-sample threshold when this figure is below it. */
  lowSample?: number | null;
}

function Stat({ label, value, tone, sub, title, lowSample = null }: StatProps) {
  return (
    <div className="trading-stat" title={title}>
      <span>
        {label}
        {lowSample !== null && <LowSampleBadge threshold={lowSample} />}
      </span>
      <strong data-tone={tone}>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function LowSampleBadge({ threshold }: { threshold: number }) {
  return (
    <em className="trading-badge" data-tone="warning" title={t("trading.stats.lowSampleMark", { count: threshold })}>
      {t("trading.stats.lowSample")}
    </em>
  );
}

function RSection({ stats }: { stats: TradingStats }) {
  const r = stats.r;
  const coverage = Math.round(Number(r.coverage ?? 0) * 100);
  return (
    <section className="trading-stats-section">
      <h3 className="trading-subhead">
        {t("trading.stats.rTitle")}
        {r.count > 0 && r.lowSample && <LowSampleBadge threshold={stats.lowSampleThreshold} />}
      </h3>
      <div className="trading-stats-coverage" data-tone={r.missing > 0 ? "warning" : undefined}>
        <span>{t("trading.stats.rCoverage", { count: r.count, total: stats.tradeCount, pct: formatPercent(r.coverage) })}</span>
        <span
          className="trading-meter"
          role="meter"
          aria-label={t("trading.stats.rCoverageLabel")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={coverage}
        >
          <span style={{ width: `${coverage}%` }} />
        </span>
      </div>
      {r.missing > 0 && <p className="trading-help">{t("trading.stats.rCoverageHint")}</p>}
      {r.count === 0 ? (
        <p className="trading-empty-line">{t("trading.stats.rNone")}</p>
      ) : (
        <>
          <div className="trading-stats-grid">
            <Stat
              label={t("trading.stats.expectancyR")}
              title={t("trading.stats.expectancyHint")}
              value={formatR(r.expectancyR)}
              tone={pnlTone(r.expectancyR)}
              sub={t("trading.stats.rWinRate", { pct: formatPercent(r.winRate) })}
            />
            <Stat label={t("trading.stats.totalR")} value={formatR(r.totalR)} tone={pnlTone(r.totalR)} />
            <Stat label={t("trading.stats.avgWinR")} value={formatR(r.avgWinR)} tone={pnlTone(r.avgWinR)} />
            <Stat label={t("trading.stats.avgLossR")} value={formatR(r.avgLossR)} tone={pnlTone(r.avgLossR)} />
          </div>
          <Distribution buckets={stats.rDistribution} />
        </>
      )}
    </section>
  );
}

function Distribution({ buckets }: { buckets: TradingRBucket[] }) {
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  return (
    <figure className="trading-stats-dist">
      <figcaption className="trading-help">{t("trading.stats.distribution")}</figcaption>
      <ul>
        {buckets.map((bucket) => (
          <li key={`${bucket.fromR}:${bucket.toR}`}>
            <span>{formatRBucket(bucket)}</span>
            <span className="trading-stats-bar-track" aria-hidden="true">
              <span
                className="trading-stats-bar"
                data-tone={bucket.toR !== null && Number(bucket.toR) <= 0 ? "down" : "up"}
                style={{ width: `${(bucket.count / max) * 100}%` }}
              />
            </span>
            <span>{bucket.count}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

interface BreakdownProps<K extends string | null> {
  title: string;
  hint?: string;
  groups: TradingStatsGroup<K>[];
  label(key: K): string;
  threshold: number;
  onSelect?: ((key: string) => void) | null;
}

function Breakdown<K extends string | null>({ title, hint, groups, label, threshold, onSelect = null }: BreakdownProps<K>) {
  return (
    <section className="trading-stats-section">
      <h3 className="trading-subhead">{title}</h3>
      {hint && <p className="trading-help">{hint}</p>}
      <table className="trading-stats-table">
        <thead>
          <tr>
            <th scope="col">{t("trading.stats.col.group")}</th>
            <th scope="col">{t("trading.stats.col.trades")}</th>
            <th scope="col">{t("trading.stats.col.winRate")}</th>
            <th scope="col">{t("trading.stats.col.net")}</th>
            <th scope="col">{t("trading.stats.col.expectancyR")}</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const name = label(group.key);
            const key = group.key;
            const empty = group.tradeCount === 0;
            return (
              <tr key={key ?? ""} data-low-sample={group.lowSample} data-empty={empty}>
                <th scope="row" title={name}>
                  {onSelect && key !== null ? (
                    <button
                      type="button"
                      className="trading-link"
                      title={t("trading.stats.filterTag", { tag: key })}
                      onClick={() => onSelect(key)}
                    >
                      {name}
                    </button>
                  ) : name}
                </th>
                <td>
                  {group.tradeCount}
                  {group.lowSample && !empty && (
                    <abbr className="trading-stats-mark" title={t("trading.stats.lowSampleMark", { count: threshold })}>*</abbr>
                  )}
                </td>
                <td>{formatPercent(group.winRate)}</td>
                <td data-tone={pnlTone(group.netPnl)}>{empty ? "—" : formatSigned(group.netPnl)}</td>
                <td>
                  {group.r.count > 0 ? (
                    <>
                      <span data-tone={pnlTone(group.r.expectancyR)}>{formatR(group.r.expectancyR)}</span>
                      <small title={t("trading.stats.rCoverageLabel")}>{`${group.r.count}/${group.tradeCount}`}</small>
                    </>
                  ) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
