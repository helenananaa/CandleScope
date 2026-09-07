import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";

export function ChartLoadError({ error, onRetry }: { error: string; onRetry(): void }) {
  useLocale();
  return (
    <div className="chart-area">
      <div className="error-overlay" style={{ overflow: "auto", padding: 16 }}>
        <div className="error-icon">!</div>
        <div className="error-message" style={{ maxWidth: "100%" }}>
          <strong>{t("chart.dataLoadFailed")}</strong>
          <br />
          {t("chart.dataLoadDetail")}
          <small style={{ color: "var(--text-muted)", marginTop: 8, display: "block" }}>
            {t("chart.backendHint")}
          </small>
          <details style={{ marginTop: 12, textAlign: "left" }}>
            <summary style={{ cursor: "pointer" }}>{t("chartTester.error.details")}</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 160, overflow: "auto", userSelect: "text" }}>{error}</pre>
          </details>
        </div>
        <button className="retry-btn" onClick={onRetry} id="retry-btn">{t("shell.retry")}</button>
      </div>
    </div>
  );
}
