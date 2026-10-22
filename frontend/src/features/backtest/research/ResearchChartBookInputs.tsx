import { useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { parseResearchObjectJson, researchObjectJson } from "./backtestResearchAdvancedModel.js";
import { chartBookMode, chartBookModes, parseChartBookFile, selectChartExecutionMode } from "./chartBookInputs.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";

export default function ResearchChartBookInputs({ runtime, onLoadingChange }: {
  runtime: BacktestResearchRuntime; onLoadingChange?(loading: boolean): void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const view = runtime.view;
  const owner = useRef("");
  owner.current = JSON.stringify([view.runDraftText,view.selectedRevisionId,view.selectedDatasetId,
    view.startTimeMs,view.endTimeMs,view.session]);
  const revision = view.revisions.find((row) => row.revision_id === view.selectedRevisionId);
  const pine = revision?.provider_kind === "PINE_ENGINE"
    || revision?.base_revision_id === "pine-engine-chart-v1" || revision?.language === "PINE_ENGINE";
  if (!view.advancedEnabled || !pine || view.selectedTask !== "PRECISE_EXECUTION") return null;
  let draft: Record<string, unknown> | null;
  try { draft = parseResearchObjectJson(view.runDraftText, "Run draft"); } catch { draft = null; }
  const mode = String(draft?.fidelity_mode ?? "BAR_APPROX");
  const events = (draft?.execution_data as { events?: unknown[] } | null)?.events;
  return <fieldset className="research-advanced-details research-chart-book-inputs" disabled={view.busy || loading || !draft}>
    <label className="research-field">
      <span>{t("native.external.fidelity")}</span>
      <select value={mode} onChange={(event) => {
        if (!draft) return;
        setError(null);
        runtime.actions.setRunDraftText(researchObjectJson(selectChartExecutionMode(draft, event.target.value)));
      }}>
        {["BAR_APPROX", "AGG_TRADE_EXECUTION", ...chartBookModes].map((item) => <option key={item} value={item}
          disabled={chartBookMode(item) && !view.capabilities?.fidelity_modes.includes(item)}>{item}</option>)}
      </select>
    </label>
    {chartBookMode(mode) && <>
      <p className="research-panel-copy">{t("research.book.help")}</p>
      <label className="research-field"><span>{t("native.external.executionData")}</span>
        <input type="file" accept=".json,application/json" onChange={(event) => {
          const input = event.currentTarget;
          const file = input.files?.[0];
          if (!file || !draft) return;
          const selected = draft;
          const selection = owner.current;
          setError(null);
          setLoading(true);
          onLoadingChange?.(true);
          void (async () => {
            try {
              if (file.size > 32 * 1024 * 1024) throw new Error("file size ceiling");
              const data = parseChartBookFile(await file.text());
              if (selection !== owner.current) {
                setError(t("research.book.changed"));
                return;
              }
              runtime.actions.setRunDraftText(researchObjectJson({ ...selected, execution_data: data }));
            } catch {
              if (selection === owner.current) {
                const next = { ...selected };
                delete next.execution_data;
                runtime.actions.setRunDraftText(researchObjectJson(next));
                setError(t("research.book.invalid"));
              } else setError(t("research.book.changed"));
            }
            finally { setLoading(false); onLoadingChange?.(false); input.value = ""; }
          })();
        }} />
      </label>
      <p className="research-panel-copy" role="status">{loading ? t("research.book.loading") : Array.isArray(events)
        ? t("research.book.loaded", { count: events.length }) : t("research.book.required")}</p>
      {error && <p className="research-panel-copy" role="alert">{error}</p>}
    </>}
  </fieldset>;
}
