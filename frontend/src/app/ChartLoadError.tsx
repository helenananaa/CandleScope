import { useState } from "react";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import { buildChartLoadDiagnostic, copyChartLoadDiagnostic } from "./chartLoadDiagnostic.js";

export function ChartLoadError({ error, context, onRetry }: { error: string; context?: { symbol: string; interval: string }; onRetry(): void }) {
  useLocale();
  const diagnostic = buildChartLoadDiagnostic(error, context);
  const [copyResult, setCopyResult] = useState<{ diagnostic: string; success: boolean } | null>(null);
  const result = copyResult?.diagnostic === diagnostic ? copyResult : null;
  const copy = async () => {
    const success = await copyChartLoadDiagnostic(diagnostic, (text) => navigator.clipboard.writeText(text));
    setCopyResult({ diagnostic, success });
  };
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
        <button className="retry-btn" onClick={() => void copy()}>{t("chart.copyDiagnostic")}</button>
        {result && <div role="status">{t(result.success ? "chart.diagnosticCopied" : "chart.diagnosticCopyFailed")}</div>}
        {result?.success === false && (
          <textarea
            aria-label={t("chart.copyDiagnostic")}
            readOnly
            value={diagnostic}
            onFocus={(event) => event.currentTarget.select()}
            rows={6}
            style={{ width: "100%", maxWidth: 520, color: "var(--text-primary)", background: "var(--bg-primary)" }}
          />
        )}
      </div>
    </div>
  );
}
