import { useEffect, useMemo, useState } from "react";
import { t } from "../../i18n/index.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { computeLocalIndicatorBatch } from "../local-data/localDataApi.js";
import { resolveLocalIndicatorSupport } from "../local-data/localIndicatorCatalog.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { studyDatasetKey, type StudyDataset } from "./researchIndicatorScope.js";

type Receipt = { state: "ready"; points: number } | { state: "error"; message: string };
type ScopedIndicator = { indicator: IndicatorDefinition; datasets: readonly StudyDataset[] };

function outputKey(indicator: IndicatorDefinition, dataset: StudyDataset) {
  return JSON.stringify([indicator.id, indicator.engineName, indicator.params ?? {}, studyDatasetKey(dataset), dataset.interval]);
}

/** Use the same dataset/epoch-bound compute endpoint as the imported chart. */
export function useResearchIndicatorScopeResults(scopes: readonly ScopedIndicator[], datasets: readonly LocalDatasetManifest[]) {
  const available = useMemo(() => new Map(datasets.filter(dataset => !dataset.archived)
    .map(dataset => [studyDatasetKey(dataset), dataset])), [datasets]);
  const plan = useMemo(() => {
    const groups = new Map<string, { manifest: LocalDatasetManifest; indicators: IndicatorDefinition[] }>();
    for (const scope of scopes) {
      for (const target of scope.datasets) {
        const key = studyDatasetKey(target);
        const manifest = available.get(key);
        if (!manifest || !resolveLocalIndicatorSupport(scope.indicator, manifest).supported) continue;
        const group = groups.get(key) ?? { manifest, indicators: [] };
        group.indicators.push(scope.indicator);
        groups.set(key, group);
      }
    }
    return [...groups.values()];
  }, [scopes, available]);
  const [completed, setCompleted] = useState<{ plan: typeof plan; receipts: ReadonlyMap<string, Receipt> } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!plan.length) return;
    const controller = new AbortController();
    const signal = controller.signal;
    async function compute() {
      const receipts = new Map<string, Receipt>();
      for (const { manifest, indicators } of plan) {
        if (signal.aborted) return;
        try {
          const result = await computeLocalIndicatorBatch(manifest, indicators.map(indicator => ({
            clientId: indicator.id, jobKey: indicator.id, name: indicator.engineName!, params: indicator.params ?? {},
          })), manifest.interval, signal);
          if (signal.aborted) return;
          for (const [index, indicator] of indicators.entries()) {
            const payload = result.results[index]?.payload;
            receipts.set(outputKey(indicator, manifest), payload?.ok === true
              ? { state: "ready", points: payload.lines.reduce((sum, line) => sum + line.data.length, 0) }
              : { state: "error", message: payload?.error ?? t("researchBatch.studyFailed") });
          }
        } catch (error) {
          if (signal.aborted) return;
          for (const indicator of indicators) receipts.set(outputKey(indicator, manifest), {
            state: "error", message: error instanceof Error ? error.message : String(error),
          });
        }
        setCompleted({ plan, receipts: new Map(receipts) });
      }
    }
    void compute();
    return () => controller.abort();
  }, [plan, retry]);
  return {
    result: (indicator: IndicatorDefinition, dataset: StudyDataset) =>
      completed?.plan === plan ? completed.receipts.get(outputKey(indicator, dataset)) : undefined,
    retry: () => { setCompleted(null); setRetry(value => value + 1); },
  };
}
