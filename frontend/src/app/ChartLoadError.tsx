import { useState } from "react";
import { Button } from "../components/ui/Button.js";
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
      <div className="error-overlay chart-load-error">
        <div className="error-icon">!</div>
        <div className="error-message">
          <strong>{t("chart.dataLoadFailed")}</strong>
          <br />
          {t("chart.dataLoadDetail")}
          <small>
            {t("chart.backendHint")}
          </small>
          <details className="chart-load-error-details">
            <summary>{t("chartTester.error.details")}</summary>
            <pre>{error}</pre>
          </details>
        </div>
        <div className="error-overlay-actions">
          <Button variant="primary" onClick={onRetry} id="retry-btn">{t("shell.retry")}</Button>
          <Button onClick={() => void copy()}>{t("chart.copyDiagnostic")}</Button>
        </div>
        {result && <div role="status">{t(result.success ? "chart.diagnosticCopied" : "chart.diagnosticCopyFailed")}</div>}
        {result?.success === false && (
          <textarea
            aria-label={t("chart.copyDiagnostic")}
            readOnly
            value={diagnostic}
            onFocus={(event) => event.currentTarget.select()}
            rows={6}
            className="chart-load-error-diagnostic"
          />
        )}
      </div>
    </div>
  );
}
