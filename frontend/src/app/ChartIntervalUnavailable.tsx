import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import type { ChartSession, NativeInterval } from "../features/chart-session/chartSessionTypes.js";

/** Capability rejection is an actionable chart state, not a transport outage. */
export function ChartIntervalUnavailable({ session, nativeIntervals, onSelectInterval }: {
  session: ChartSession;
  nativeIntervals: readonly NativeInterval[];
  onSelectInterval(interval: string): void;
}) {
  useLocale();
  return (
    <div className="chart-area" data-interval-admission="unavailable">
      <div className="error-overlay" role="status" style={{ padding: 16 }}>
        <strong>{session.symbol} · {session.interval}</strong>
        <p>{t("interval.cannotComposeSession", {
          exchange: session.exchange, marketType: session.marketType, interval: session.interval,
        })}</p>
        <p>{t("interval.unavailableHelp")}</p>
        {nativeIntervals.length > 0 && (
          <select aria-label={t("interval.title")} value="" onChange={(event) => onSelectInterval(event.target.value)}>
            <option value="" disabled>{t("interval.title")}</option>
            {nativeIntervals.map((item) => <option key={item.value} value={item.value}>{item.label || item.value}</option>)}
          </select>
        )}
      </div>
    </div>
  );
}
