import { useState } from "react";
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
  return <details data-research-indicator-scope>
    <summary>{t("researchBatch.studyScope")}{targets.length ? ` · ${targets.length}` : ""}</summary>
    <p>{t("researchBatch.studyHint")}</p>
    <fieldset disabled={saving || storageError}>
      <legend>{t("researchBatch.studyScope")}</legend>
      {available.map(dataset => {
        const key = studyDatasetKey(dataset);
        const checked = chosen.includes(key);
        const support = resolveLocalIndicatorSupport(indicator, dataset);
        return <div key={key}>
          <label>
            <input type="checkbox" checked={checked} disabled={key === currentKey || !support.supported
              || (!checked && selected.length >= MAX_STUDY_DATASETS)}
              onChange={event => setDraft(event.target.checked ? [...chosen, key] : chosen.filter(value => value !== key))} />
            {dataset.name} · {dataset.interval}
          </label>
          {!support.supported && <small>{support.reason}</small>}
        </div>;
      })}
    </fieldset>
    <button type="button" onClick={() => void save()} disabled={saving || storageError || selected.length < 2}>
      {t("researchBatch.studyApply")}
    </button>
    {(error || storageError) && <p role="alert">{t("researchBatch.storage")}</p>}
    {targets.length > 0 && <ul aria-live="polite">
      {targets.map(dataset => {
        const key = studyDatasetKey(dataset);
        const manifest = available.find(item => studyDatasetKey(item) === key);
        const support = manifest ? resolveLocalIndicatorSupport(indicator, manifest) : null;
        const result = results.result(indicator, dataset);
        const status = !manifest ? "unavailable" : support?.supported === false ? "unsupported" : result?.state ?? "computing";
        return <li key={key} data-study-dataset={dataset.dataset_id} data-status={status}>
          {dataset.name} · {dataset.interval} · {
            status === "unavailable" ? t("researchBatch.studyUnavailable")
              : status === "unsupported" ? support?.reason
              : result?.state === "ready" ? t("researchBatch.studyReady", { count: result.points })
              : result?.state === "error" ? result.message
              : t("researchBatch.preparing")
          }
          {status === "error" && <button type="button" onClick={results.retry}>{t("replay.retry")}</button>}
        </li>;
      })}
    </ul>}
  </details>;
}
