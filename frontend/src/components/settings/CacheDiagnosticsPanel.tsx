import { Button } from "../ui/Button.js";
import { Disclosure, InlineAlert, Stat } from "../ui/Display.js";
import type { ReactNode } from "react";
import { getLocale, t, type MessageKey } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { GcVictim } from "../../features/cache-gc/cacheGcTypes.js";
import type {
  BackendDiagnosticsResult,
  BackendGcVictim,
  CacheDiagnosticsRuntime,
} from "../../features/settings/cacheDiagnosticsSettingsRuntime.js";

const REASON_KEYS: Record<string, MessageKey> = {
  "cold-cache-over-budget": "settings.diag.reason.coldOverBudget",
  "estimated-bytes-over-budget": "settings.diag.reason.bytesOverBudget",
  "cold-non-ephemeral-storage-backed": "settings.diag.reason.coldStorageBacked",
  "ephemeral-over-limit": "settings.diag.reason.ephemeralOverLimit",
  "indicator-points-over-budget": "settings.diag.reason.indicatorOverBudget",
  "kline-bars-over-budget": "settings.diag.reason.klineOverBudget",
  "missing-kline-dependency": "settings.diag.reason.missingKline",
  "minutes-tier-retention": "settings.diag.reason.minutesRetention",
  "hours-tier-retention": "settings.diag.reason.hoursRetention",
  "daily-tier-retention": "settings.diag.reason.dailyRetention",
  "sqlite-budget-pressure": "settings.diag.reason.sqlitePressure",
  "warm-cache-over-budget": "settings.diag.reason.warmOverBudget",
};

const RISK_KEYS: Record<string, MessageKey> = {
  "active-or-subscribed": "settings.diag.risk.active",
  "custom-interval": "settings.diag.risk.customInterval",
  "latest-data-close-to-now": "settings.diag.risk.nearRealtime",
  "storage-intent": "settings.diag.risk.storageIntent",
};

const WATERMARK_KEYS: Record<string, MessageKey> = {
  unconfigured: "settings.diag.watermark.unconfigured",
  normal: "settings.diag.watermark.normal",
  high: "settings.diag.watermark.high",
  critical: "settings.diag.watermark.critical",
  over_budget: "settings.diag.watermark.overBudget",
};

function formatBytes(bytes: unknown): string {
  const value = Number(bytes || 0);
  if (!value) return "--";
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatNumber(value: unknown): string {
  return Number(value || 0).toLocaleString(getLocale());
}

function reasonLabel(reason: unknown): string {
  const key = typeof reason === "string" ? reason : "";
  const messageKey = REASON_KEYS[key];
  return messageKey ? t(messageKey) : (key || "--");
}

function riskLabel(flags: string[] = []): string {
  if (!flags.length) return t("settings.diag.routine");
  return flags.map((flag) => {
    const messageKey = RISK_KEYS[flag];
    return messageKey ? t(messageKey) : flag;
  }).join(" / ");
}

function watermarkLabel(level: unknown): string {
  const key = typeof level === "string" ? level : "";
  const messageKey = WATERMARK_KEYS[key];
  return messageKey ? t(messageKey) : (key || "--");
}

interface StatCardProps {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}

function StatCard({ label, value, detail }: StatCardProps) {
  return <Stat label={label} value={value} {...(detail ? { hint: detail } : {})} />;
}

interface GcPlanRowsProps {
  victims?: Array<GcVictim | BackendGcVictim>;
}

function GcPlanRows({ victims = [] }: GcPlanRowsProps) {
  if (!victims.length) {
    return <div className="st-diagnostics-empty">{t("settings.diag.empty")}</div>;
  }
  return (
    <div className="st-diagnostics-list">
      {victims.slice(0, 8).map((entry) => (
        <div key={`${entry.owner}:${entry.key}`} className="st-diagnostics-row st-diagnostics-row-wide">
          <span className="st-diagnostics-row-key">{entry.key}</span>
          <span>{reasonLabel(entry.reason)}</span>
          <span>{formatBytes(entry.estimatedBytes ?? entry.estimated_bytes ?? entry.would_free_estimated_bytes)}</span>
        </div>
      ))}
    </div>
  );
}

type CacheListEntry = { key?: string } & Record<string, unknown>;

interface TopEntriesProps {
  entries?: CacheListEntry[];
  metric?: string;
}

function TopEntries({ entries = [], metric = "bars" }: TopEntriesProps) {
  const sorted = [...entries]
    .sort((left, right) => Number(right[metric] || 0) - Number(left[metric] || 0))
    .slice(0, 5);
  if (!sorted.length) {
    return <div className="st-diagnostics-empty">{t("settings.diag.noEntries")}</div>;
  }
  return (
    <div className="st-diagnostics-list">
      {sorted.map((entry) => (
        <div key={entry.key} className="st-diagnostics-row">
          <span className="st-diagnostics-row-key">{entry.key}</span>
          <span>{formatNumber(entry[metric])}</span>
        </div>
      ))}
    </div>
  );
}

export type CacheDiagnosticsPanelProps = Pick<
  CacheDiagnosticsRuntime,
  | "backendDiagnostics"
  | "backendMemoryGcPlan"
  | "backendMemoryGcResult"
  | "error"
  | "frontendDiagnostics"
  | "frontendGcPlan"
  | "frontendGcResult"
  | "loading"
  | "onPlanBackendMemoryGc"
  | "onPlanFrontendGc"
  | "onPlanStorageGc"
  | "onRunBackendMemoryGc"
  | "onRunFrontendGc"
  | "onRunStorageGc"
  | "onRefresh"
  | "onVacuumStorage"
  | "storageGcPlan"
  | "storageGcResult"
  | "storageVacuumResult"
>;

export default function CacheDiagnosticsPanel({
  backendDiagnostics,
  backendMemoryGcPlan,
  backendMemoryGcResult,
  error,
  frontendDiagnostics,
  frontendGcPlan,
  frontendGcResult,
  loading,
  onPlanBackendMemoryGc,
  onPlanFrontendGc,
  onPlanStorageGc,
  onRunBackendMemoryGc,
  onRunFrontendGc,
  onRunStorageGc,
  onRefresh,
  onVacuumStorage,
  storageGcPlan,
  storageGcResult,
  storageVacuumResult,
}: CacheDiagnosticsPanelProps) {
  useLocale();
  const frontend = frontendDiagnostics || {};
  const owners = frontend.owners || {};
  const chart = owners.chart || {};
  const market = owners.market || {};
  const indicators = owners.indicators || {};
  const backendCache = backendDiagnostics?.data_manager?.cache || {};
  const storageFiles = backendDiagnostics?.storage?.files || {};
  const storageSeries = backendDiagnostics?.storage?.series || {};
  const storageWatermarks = storageGcPlan?.watermarks || backendDiagnostics?.storage?.watermarks || {};
  const scriptCache = backendDiagnostics?.indicator?.script_cache || {};
  const canRunFrontendGc = Boolean(frontendGcPlan?.victims?.length) && !frontendGcResult;
  const canRunBackendMemoryGc = Boolean(backendMemoryGcPlan?.victims?.length) && !backendMemoryGcResult;
  const canRunStorageGc = Boolean(storageGcPlan?.series?.length) && !storageGcResult;
  const canVacuumStorage = Boolean(
    storageGcResult?.vacuum_recommended || storageGcPlan?.vacuum_recommended
  ) && !storageVacuumResult;

  return (
    <div className="st-group st-storage">
      <div className="st-ex-head">
        <p className="st-group-desc">{t("settings.diag.summary")}</p>
        <Button size="sm" onClick={() => onRefresh?.()} disabled={loading}>
          {loading ? t("settings.diag.refreshing") : t("settings.diag.refresh")}
        </Button>
      </div>

      {error ? <InlineAlert tone="warning">{error}</InlineAlert> : null}

      <section className="st-layer" aria-label={t("settings.diag.browserCache")}>
        <div className="st-layer-head">
          <div className="st-launch-text">
            <strong>{t("settings.diag.browserCache")}</strong>
            <span>{t("settings.diag.browserDesc")}</span>
          </div>
          <Stat label={t("settings.diag.estimatedMem")} value={formatBytes(frontend.estimatedBytes)} />
        </div>
        <div className="st-layer-actions">
          <Button size="sm" onClick={() => onPlanFrontendGc?.()}>{t("settings.diag.plan")}</Button>
          <Button size="sm" onClick={() => onRunFrontendGc?.()} disabled={!canRunFrontendGc}>{t("settings.diag.run")}</Button>
        </div>
        {frontendGcPlan && !frontendGcResult ? (
          <InlineAlert>{frontendGcPlan.victims?.length
            ? t("settings.diag.planSummary", { bytes: formatBytes(frontendGcPlan.wouldFreeEstimatedBytes), count: formatNumber(frontendGcPlan.victims.length) })
            : t("settings.diag.empty")}</InlineAlert>
        ) : null}
        {frontendGcResult ? (
          <InlineAlert tone="success" title={t("settings.diag.gcResult")}>
            {[
              t("settings.diag.removedEntries", { count: formatNumber(frontendGcResult.removedCount) }),
              t("settings.diag.freedEst", { bytes: formatBytes(frontendGcResult.removedEstimatedBytes) }),
              t("settings.diag.barsRemoved", { count: formatNumber(frontendGcResult.removedBars) }),
              t("settings.diag.pointsRemoved", { count: formatNumber(frontendGcResult.removedIndicatorPoints) }),
            ].join(" · ")}
          </InlineAlert>
        ) : null}
        <Disclosure summary={t("settings.diag.details")}>
          <div className="st-stat-grid">
            <StatCard label={t("settings.diag.chartBars")} value={t("settings.diag.barsUnit", { count: formatNumber(chart.totalBars) })} detail={t("settings.diag.seriesCount", { count: formatNumber(chart.seriesCount) })} />
            <StatCard label={t("settings.diag.sharedMarketCache")} value={t("settings.diag.barsUnit", { count: formatNumber(market.totalBars) })} detail={t("settings.diag.seriesCount", { count: formatNumber(market.seriesCount) })} />
            <StatCard label={t("settings.diag.indicatorResults")} value={t("settings.diag.pointsUnit", { count: formatNumber(indicators.totalPoints) })} detail={t("settings.diag.entriesUnit", { count: formatNumber(indicators.entryCount) })} />
          </div>
          <TopEntries entries={[...(chart.entries || []), ...(market.entries || [])]} metric="bars" />
          {frontendGcPlan ? (
            <div className="st-diagnostics-plan">
              <div className="st-stat-grid">
                <StatCard label={t("settings.diag.wouldFree")} value={formatBytes(frontendGcPlan.wouldFreeEstimatedBytes)} detail={t("settings.diag.entriesCount", { count: formatNumber(frontendGcPlan.victims?.length) })} />
                <StatCard label={t("settings.diag.barCount")} value={formatNumber(frontendGcPlan.wouldFreeBars)} detail={t("settings.diag.pressureBars", { count: formatNumber(frontendGcPlan.pressure?.klineBars) })} />
                <StatCard label={t("settings.diag.indicatorPoints")} value={formatNumber(frontendGcPlan.wouldFreeIndicatorPoints)} detail={t("settings.diag.pressurePoints", { count: formatNumber(frontendGcPlan.pressure?.indicatorPoints) })} />
                <StatCard label={t("settings.diag.protectedEntries")} value={formatNumber(frontendGcPlan.protectedCount)} detail={t("settings.diag.activeSubscribed")} />
              </div>
              <GcPlanRows victims={frontendGcPlan.victims || []} />
            </div>
          ) : null}
        </Disclosure>
      </section>

      <section className="st-layer" aria-label={t("settings.diag.backendMem")}>
        <div className="st-layer-head">
          <div className="st-launch-text">
            <strong>{t("settings.diag.backendMem")}</strong>
            <span>{t("settings.diag.backendDesc")}</span>
          </div>
          <Stat label={t("settings.diag.memoryBars")} value={formatNumber(backendCache.total_bars)} />
        </div>
        <div className="st-layer-actions">
          <Button size="sm" onClick={() => onPlanBackendMemoryGc?.()} disabled={loading}>{t("settings.diag.plan")}</Button>
          <Button size="sm" onClick={() => onRunBackendMemoryGc?.()} disabled={loading || !canRunBackendMemoryGc}>{t("settings.diag.run")}</Button>
        </div>
        {backendMemoryGcPlan && !backendMemoryGcResult ? (
          <InlineAlert>{backendMemoryGcPlan.victims?.length
            ? t("settings.diag.planSummary", { bytes: formatBytes(backendMemoryGcPlan.would_free_estimated_bytes), count: formatNumber(backendMemoryGcPlan.victims.length) })
            : t("settings.diag.empty")}</InlineAlert>
        ) : null}
        {backendMemoryGcResult ? (
          <InlineAlert tone="success" title={t("settings.diag.backendResult")}>
            {[
              t("settings.diag.removedSeries", { count: formatNumber(backendMemoryGcResult.removed_series) }),
              t("settings.diag.trimmedSeries", { count: formatNumber(backendMemoryGcResult.trimmed_series) }),
              t("settings.diag.freedBars", { count: formatNumber(backendMemoryGcResult.removed_bars) }),
              t("settings.diag.estimated", { bytes: formatBytes(backendMemoryGcResult.removed_estimated_bytes) }),
            ].join(" · ")}
          </InlineAlert>
        ) : null}
        <Disclosure summary={t("settings.diag.details")}>
          <div className="st-stat-grid">
            <StatCard label={t("settings.diag.memorySeries")} value={formatNumber(backendCache.total_series)} detail={t("settings.diag.cap", { count: formatNumber(backendCache.max_series) })} />
            <StatCard label={t("settings.diag.memoryBars")} value={formatNumber(backendCache.total_bars)} detail={t("settings.diag.perSeries", { count: formatNumber(backendCache.max_bars_per_series) })} />
            <StatCard label={t("settings.diag.cacheHits")} value={formatNumber(backendCache.hits)} detail={t("settings.diag.misses", { count: formatNumber(backendCache.misses) })} />
            <StatCard label={t("settings.diag.scriptCache")} value={formatNumber(scriptCache.size ?? scriptCache.items ?? 0)} detail={t("settings.diag.cap", { count: formatNumber(scriptCache.max_items ?? scriptCache.maxItems ?? 0) })} />
          </div>
          {backendMemoryGcPlan ? (
            <div className="st-diagnostics-plan">
              <div className="st-stat-grid">
                <StatCard label={t("settings.diag.wouldFree")} value={formatBytes(backendMemoryGcPlan.would_free_estimated_bytes)} detail={t("settings.diag.entriesCount", { count: formatNumber(backendMemoryGcPlan.victims?.length) })} />
                <StatCard label={t("settings.diag.wouldFreeBars")} value={formatNumber(backendMemoryGcPlan.would_free_bars)} detail={t("settings.diag.seriesUnit", { count: formatNumber(backendMemoryGcPlan.would_remove_series) })} />
                <StatCard label={t("settings.diag.protected")} value={formatNumber(backendMemoryGcPlan.protected_count)} detail={t("settings.diag.activeSubscribed")} />
                <StatCard label={t("settings.diag.pressure")} value={formatNumber(backendMemoryGcPlan.pressure?.total_bars)} detail={t("settings.diag.cap", { count: formatNumber(backendMemoryGcPlan.pressure?.max_total_bars) })} />
              </div>
              <GcPlanRows victims={backendMemoryGcPlan.victims || []} />
            </div>
          ) : null}
        </Disclosure>
      </section>

      <section className="st-layer" aria-label={t("settings.diag.localDb")}>
        <div className="st-layer-head">
          <div className="st-launch-text">
            <strong>{t("settings.diag.localDb")}</strong>
            <span>{t("settings.diag.dbDesc")}</span>
          </div>
          <Stat label={t("settings.diag.totalSize")} value={formatBytes(storageFiles.total_size_bytes)} />
        </div>
        <div className="st-layer-actions">
          <Button size="sm" onClick={() => onPlanStorageGc?.()} disabled={loading}>{t("settings.diag.plan")}</Button>
          <Button size="sm" variant="danger" onClick={() => onRunStorageGc?.()} disabled={loading || !canRunStorageGc}>{t("settings.diag.runStorage")}</Button>
          <Button size="sm" onClick={() => onVacuumStorage?.()} disabled={loading || !canVacuumStorage}>{t("settings.diag.vacuum")}</Button>
        </div>
        {storageGcPlan && !storageGcResult ? (
          <InlineAlert tone={storageGcPlan.unable_to_reach_budget ? "warning" : "info"}>
            {storageGcPlan.series?.length
              ? t("settings.diag.dbPlanSummary", { rows: formatNumber(storageGcPlan.would_delete_rows), bytes: formatBytes(storageGcPlan.would_free_estimated_bytes) })
              : t("settings.diag.noStorageVictims")}
            {storageGcPlan.unable_to_reach_budget ? <div>{t("settings.diag.budgetGap", { bytes: formatBytes(storageGcPlan.budget_gap_bytes) })}</div> : null}
          </InlineAlert>
        ) : null}
        {storageGcResult ? (
          <InlineAlert tone="success" title={t("settings.diag.storageResult")}>
            {[
              t("settings.diag.deletedRows", { count: formatNumber(storageGcResult.deleted_rows) }),
              t("settings.diag.affectedSeries", { count: formatNumber(storageGcResult.affected_series) }),
              t("settings.diag.elapsed", { count: formatNumber(storageGcResult.elapsed_ms) }),
              storageGcResult.checkpoint_result ? t("settings.diag.checkpointDone") : t("settings.diag.checkpointSkip"),
            ].join(" · ")}
          </InlineAlert>
        ) : null}
        {storageVacuumResult ? (
          <InlineAlert tone="success" title={t("settings.diag.vacuumResult")}>
            {[
              t("settings.diag.elapsed", { count: formatNumber(storageVacuumResult.elapsed_ms) }),
              t("settings.diag.currentTotal", { bytes: formatBytes(storageVacuumResult.storage_files_after?.total_size_bytes) }),
            ].join(" · ")}
          </InlineAlert>
        ) : null}
        <Disclosure summary={t("settings.diag.details")}>
          <div className="st-stat-grid">
            <StatCard label={t("settings.diag.dbFile")} value={formatBytes(storageFiles.db_size_bytes)} detail={storageFiles.exists ? t("settings.diag.created") : t("settings.diag.notCreated")} />
            <StatCard label={t("settings.diag.walFile")} value={formatBytes(storageFiles.wal_size_bytes)} detail={t("settings.diag.readonly")} />
            <StatCard label={t("settings.diag.dbSeries")} value={formatNumber(storageSeries.series_count)} detail={t("settings.diag.totalRows", { count: formatNumber(storageSeries.total_rows) })} />
            <StatCard
              label={t("settings.diag.sqliteBudget")}
              value={storageWatermarks.budget_bytes ? formatBytes(storageWatermarks.budget_bytes) : t("settings.diag.unset")}
              detail={t("settings.diag.watermark", { level: watermarkLabel(storageWatermarks.level) })}
            />
          </div>
          {storageGcPlan ? (
            <div className="st-diagnostics-plan">
              <div className="st-stat-grid">
                <StatCard label={t("settings.diag.wouldDeleteRows")} value={formatNumber(storageGcPlan.would_delete_rows)} detail={t("settings.diag.seriesUnit", { count: formatNumber(storageGcPlan.victim_count) })} />
                <StatCard label={t("settings.diag.freeEst")} value={formatBytes(storageGcPlan.would_free_estimated_bytes)} detail={t("settings.diag.roughEst")} />
                <StatCard label={t("settings.diag.budgetLevel")} value={watermarkLabel(storageGcPlan.watermarks?.level)} detail={`${((storageGcPlan.watermarks?.budget_usage_ratio || 0) * 100).toFixed(1)}%`} />
                <StatCard label={t("settings.diag.vacuumLabel")} value={storageGcPlan.vacuum_recommended ? t("settings.diag.recommended") : t("settings.diag.optional")} detail={t("settings.diag.notAuto")} />
              </div>
              {storageGcPlan.series?.length ? (
                <div className="st-diagnostics-list">
                  {storageGcPlan.series.slice(0, 8).map((entry) => (
                    <div key={`${entry.owner}:${entry.key}`} className="st-diagnostics-row st-diagnostics-row-storage">
                      <span className="st-diagnostics-row-key">{entry.key}</span>
                      <span>{reasonLabel(entry.reason)}</span>
                      <span>{t("settings.diag.rows", { count: formatNumber(entry.would_delete_rows) })}</span>
                      <span>{riskLabel(entry.risk_flags)}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <TopEntries entries={(storageSeries.largest_series || []).map((item) => ({
            key: `${item.exchange}:${item.market_type}:${item.symbol}:${item.interval}`,
            rows: item.total_count,
          }))} metric="rows" />
        </Disclosure>
      </section>
    </div>
  );
}
