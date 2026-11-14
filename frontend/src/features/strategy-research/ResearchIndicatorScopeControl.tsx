import { useState } from "react";
import { Badge, Button, Checkbox, Disclosure, InlineAlert, type Tone } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { ActiveIndicatorPersistence } from "../indicators/activeIndicatorStore.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { resolveLocalIndicatorSupport } from "../local-data/localIndicatorCatalog.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { MAX_STUDY_DATASETS, studyDatasetKey, type StudyDataset } from "./researchIndicatorScope.js";

import type { useResearchIndicatorScopeResults } from "./useResearchIndicatorScopeResults.js";

export function ResearchIndicatorScopeControl({ indicator, current, datasets, targets, results, storageError, local, apply }: {
  indicator: IndicatorDefinition;
  current: LocalDatasetManifest;
  datasets: readonly LocalDatasetManifest[];
  targets: readonly StudyDataset[];
  results: ReturnType<typeof useResearchIndicatorScopeResults>;
  storageError: boolean;
  local: ActiveIndicatorPersistence;
  apply(indicator: IndicatorDefinition, current: LocalDatasetManifest, selected: readonly LocalDatasetManifest[], local: ActiveIndicatorPersistence): Promise<void>;
}) {
  useLocale();
  const [draft, setDraft] = useState<readonly string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const currentKey = studyDatasetKey(current);
  const available = datasets.filter(dataset => !dataset.archived);
  if (indicator.is_builtin !== true || (available.length < 2 && !targets.length)) return null;
  const chosen = draft ?? (targets.length ? targets.map(studyDatasetKey) : [currentKey]);
  const selected = available.filter(dataset => chosen.includes(studyDatasetKey(dataset))
    && resolveLocalIndicatorSupport(indicator, dataset).supported);
  async function save() {
    setSaving(true);
    setError(false);
    try { await apply(indicator, current, selected, local); setDraft(null); }
    catch { setError(true); }
    finally { setSaving(false); }
  }
  const statusTone = (status: string): Tone => status === "ready" ? "success" : status === "error" ? "danger"
    : status === "unavailable" || status === "unsupported" ? "warning" : "accent";
  return <Disclosure className="strategy-research-scope" summary={`${t("researchBatch.studyScope")}${targets.length ? ` · ${targets.length}` : ""}`}>
    <div data-research-indicator-scope="">
    <p className="strategy-research-note">{t("researchBatch.studyHint")}</p>
    <fieldset className="strategy-research-checklist" disabled={saving || storageError}>
      <legend>{t("researchBatch.studyScope")}</legend>
      {available.map(dataset => {
        const key = studyDatasetKey(dataset);
        const checked = chosen.includes(key);
        const support = resolveLocalIndicatorSupport(indicator, dataset);
        return <Checkbox key={key} checked={checked} disabled={key === currentKey || !support.supported
          || (!checked && selected.length >= MAX_STUDY_DATASETS)}
          label={`${dataset.name} · ${dataset.interval}`}
          {...(!support.supported ? { description: support.reason } : {})}
          onChange={event => setDraft(event.target.checked ? [...chosen, key] : chosen.filter(value => value !== key))} />;
      })}
    </fieldset>
    <Button size="sm" variant="primary" onClick={() => void save()} disabled={saving || storageError || selected.length < 2}>
      {t("researchBatch.studyApply")}
    </Button>
    {(error || storageError) && <InlineAlert tone="danger">{t("researchBatch.storage")}</InlineAlert>}
    {targets.length > 0 && <ul className="strategy-history-list" aria-live="polite">
      {targets.map(dataset => {
        const key = studyDatasetKey(dataset);
        const manifest = available.find(item => studyDatasetKey(item) === key);
        const support = manifest ? resolveLocalIndicatorSupport(indicator, manifest) : null;
        const result = results.result(indicator, dataset);
        const status = !manifest ? "unavailable" : support?.supported === false ? "unsupported" : result?.state ?? "computing";
        return <li key={key} className="strategy-history-row" data-study-dataset={dataset.dataset_id} data-status={status}>
          <div className="strategy-history-run"><strong>{dataset.name} · {dataset.interval}</strong></div>
          <Badge tone={statusTone(status)}>{
            status === "unavailable" ? t("researchBatch.studyUnavailable")
              : status === "unsupported" ? support?.reason
              : result?.state === "ready" ? t("researchBatch.studyReady", { count: result.points })
              : result?.state === "error" ? result.message
              : t("researchBatch.preparing")
          }</Badge>
          {status === "error" && <Button size="sm" variant="ghost" onClick={results.retry}>{t("replay.retry")}</Button>}
        </li>;
      })}
    </ul>}
    </div>
  </Disclosure>;
}
