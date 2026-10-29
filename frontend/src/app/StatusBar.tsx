import { memo } from "react";
import type { ReactNode } from "react";
import { t, tPlural, translateMarketType, translateWsStatus } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import MarketStatusBar from "./MarketStatusBar.js";
import { APP_VERSION } from "../shared/appVersion.js";

export type ConnectionStatus = "connected" | "loading" | "disconnected" | string;

export interface StatusBarModel {
  connectionStatus: ConnectionStatus;
  historyOnly?: boolean;
  dataSource: string;
  exchangeLabel: string;
  marketLabel: string;
  wsStatus?: string;
  wsStatusLabel: string;
  barCount: number;
  loadingMoreLeft: boolean;
  hasMoreLeft: boolean;
  exchangeCatalogStatus: string;
  exchangeLimitations?: string[];
}

export interface StatusBarProps {
  status: StatusBarModel;
  extensions?: ReactNode;
}

function connectionLabel(status: StatusBarModel): string {
  if (status.historyOnly) return t("interval.historyOnly");
  if (status.connectionStatus === "connected") {
    if (status.wsStatus && status.wsStatus !== "live") return translateWsStatus(status.wsStatus);
    return t("status.connectedTo", { exchange: status.exchangeLabel });
  }
  if (status.connectionStatus === "loading") {
    return status.dataSource === "mock" ? t("status.mockDataMode") : t("status.loading");
  }
  if (status.connectionStatus === "disconnected") return t("status.disconnected");
  return status.connectionStatus;
}

function localizedMarketLabel(label: string): string {
  const normalized = label.trim().toLowerCase();
  return normalized === "spot" || normalized === "futures" || normalized === "swap"
    ? translateMarketType(normalized)
    : label;
}

function StatusBar({ status, extensions }: StatusBarProps) {
  useLocale();
  const {
    connectionStatus: dataConnectionStatus,
    dataSource,
    exchangeLabel,
    marketLabel,
    wsStatus,
    wsStatusLabel,
    barCount,
    loadingMoreLeft,
    hasMoreLeft,
    exchangeCatalogStatus,
    exchangeLimitations = [],
  } = status;
  const connectionStatus = status.historyOnly ? "disconnected" : dataConnectionStatus === "connected" && wsStatus && wsStatus !== "live"
    ? wsStatus === "disconnected" ? "disconnected" : "loading"
    : dataConnectionStatus;
  const wsLabel = status.historyOnly ? t("interval.historyOnly") : wsStatus ? translateWsStatus(wsStatus) : wsStatusLabel;

  return (
    <MarketStatusBar
      source="live"
      connectionStatus={connectionStatus}
      left={<>
        <span title={t("status.klineScopeDetail")}>
          <span className={`status-dot ${connectionStatus}`} />
          {t("status.klineScope")} {connectionLabel(status)}
        </span>
        <span data-live-bar-count={barCount}>{tPlural("status.barCount", barCount)}</span>
        {loadingMoreLeft && <span style={{ color: "var(--text-accent)" }}>{t("status.loadingOlder")}</span>}
        {!hasMoreLeft && !loadingMoreLeft && <span style={{ color: "var(--text-muted)" }}>{t("status.noMoreHistory")}</span>}
        {dataSource === "mock" && (
          <span style={{ color: "var(--text-warning)" }}>
            {t("status.mockUnavailable", { exchange: exchangeLabel })}
          </span>
        )}
        {exchangeCatalogStatus === "fallback" && (
          <span style={{ color: "var(--text-warning)" }}>{t("status.exchangeCapabilitiesFallback")}</span>
        )}
        {exchangeLimitations.length > 0 && (
          <span title={exchangeLimitations.join(" | ")} style={{ color: "var(--text-muted)" }}>
            {tPlural("status.exchangeLimitationCount", exchangeLimitations.length)}
          </span>
        )}
      </>}
      right={<>
        {extensions}
        <span>{dataSource === "mock"
          ? t("status.demoMode")
          : `${exchangeLabel} ${localizedMarketLabel(marketLabel)}`}</span>
        <span title={t("status.klineScopeDetail")}>{t("status.klineScope")} {wsLabel}</span>
        <span>{`CandleScope v${APP_VERSION}`}</span>
      </>}
    />
  );
}

export default memo(StatusBar);
