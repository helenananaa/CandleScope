import { useMemo, useState } from "react";
import { Button, Disclosure, Field, InlineAlert, Input, Select, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { importedResearchRange } from "./importedDatasetSource.js";
import {
  ROBUSTNESS_OBJECTIVES, RobustnessFormError, defaultRobustnessForm, robustnessPlan, robustnessStudyFields, studyRange,
  type RobustnessForm, type RobustnessObjective, type StudyRange,
} from "./researchRobustness.js";

type StudyFields = Record<string, unknown> & { start_ms: number; end_ms: number };

function rangeOf(request: ChartStrategyRunRequest | null, dataset: LocalDatasetManifest | null): StudyRange | null {
  if (!request || !dataset) return null;
  try {
    const { startMs, endMs } = importedResearchRange(dataset, request.attachment);
    return studyRange(dataset, { startMs, endMs });
  } catch {
    return null;  // precise research without imported trades
  }
}

/**
 * A robustness check of the workspace's strategy (ADR-BACKTEST-015 P5c3): parameter candidates on
 * walk-forward folds over the imported dataset, as a backend Study V2 experiment. Its progress and
 * verdict appear with the other experiments.
 */
export function ResearchRobustness({ request, dataset, onSubmit }: {
  /** The current strategy, or null until a Python strategy is confirmed to run on this computer. */
  request: ChartStrategyRunRequest | null;
  /** The imported dataset the research page shows, or null for exchange data. */
  dataset: LocalDatasetManifest | null;
  onSubmit(fields: StudyFields): Promise<void>;
}) {
  useLocale();
  const range = rangeOf(request, dataset);
  const key = range && dataset ? `${dataset.dataset_id}:${dataset.data_epoch}:${range.startMs}:${range.endMs}` : "";
  const parameters = request?.attachment.parameters;
  const initial = useMemo(() => range ? defaultRobustnessForm(range, parameters ?? {}) : null,
    // A new range or dataset starts a new form; edits to the strategy's parameters do not reset it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key]);
  const [edited, setEdited] = useState<{ key: string; form: RobustnessForm } | null>(null);
  const form = edited?.key === key ? edited.form : initial;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const blocked = !dataset ? "researchRobustness.dataOnly"
    : !request ? "researchRobustness.trustRequired"
      : request.language !== "python" ? "researchRobustness.pythonOnly"
        : !range ? "researchRobustness.fixedInterval" : null;
  const change = (patch: Partial<RobustnessForm>) => {
    if (form) setEdited({ key, form: { ...form, ...patch } });
    setError(null);
  };
  const bars = (name: "trainBars" | "testBars" | "stepBars" | "holdoutBars", label: string) => (
    <Field label={label}>
      <Input size="sm" type="number" min={name === "holdoutBars" ? 0 : 1} step={1} value={form?.[name] ?? 0} disabled={busy}
        onChange={(event) => change({ [name]: Number(event.target.value) })} />
    </Field>
  );
  const plan = form && range ? robustnessPlan(form, range) : null;
  return <Disclosure className="strategy-research-robustness" summary={t("researchRobustness.title")}>
    <p className="strategy-research-note">{t("researchRobustness.help")}</p>
    {blocked || !form || !range ? <p className="strategy-research-note" role="status">{t(blocked ?? "researchRobustness.fixedInterval")}</p> : <>
      <Field label={t("researchRobustness.hypothesis")} hint={t("researchRobustness.hypothesisHint")}>
        <Input size="sm" value={form.hypothesis} maxLength={500} disabled={busy} onChange={(event) => change({ hypothesis: event.target.value })} />
      </Field>
      <Field label={t("researchRobustness.space")} hint={t("researchRobustness.spaceHint")}>
        <Textarea className="strategy-research-detail-editor" rows={4} spellCheck={false} value={form.space} disabled={busy}
          onChange={(event) => change({ space: event.target.value })} />
      </Field>
      <div className="strategy-research-robustness-grid">
        {bars("trainBars", t("researchRobustness.train"))}
        {bars("testBars", t("researchRobustness.test"))}
        {bars("stepBars", t("researchRobustness.step"))}
        {bars("holdoutBars", t("researchRobustness.holdout"))}
        <Field label={t("researchRobustness.sampler")}>
          <Select size="sm" value={form.sampler} disabled={busy} onChange={(event) => change({ sampler: event.target.value === "random" ? "random" : "grid" })}>
            <option value="grid">{t("researchRobustness.samplerGrid")}</option>
            <option value="random">{t("researchRobustness.samplerRandom")}</option>
          </Select>
        </Field>
        <Field label={t("researchRobustness.candidates")}>
          <Input size="sm" type="number" min={1} step={1} value={form.candidates} disabled={busy}
            onChange={(event) => change({ candidates: Number(event.target.value) })} />
        </Field>
        <Field label={t("researchRobustness.objective")}>
          <Select size="sm" value={form.objective} disabled={busy} onChange={(event) => change({ objective: event.target.value as RobustnessObjective })}>
            {ROBUSTNESS_OBJECTIVES.map((objective) => <option key={objective} value={objective}>{t(`researchRobustness.objective.${objective}`)}</option>)}
          </Select>
        </Field>
      </div>
      <Disclosure summary={t("researchRobustness.advanced")}>
        <Textarea className="strategy-research-detail-editor" rows={10} spellCheck={false} value={form.advanced} disabled={busy}
          aria-label={t("researchRobustness.advanced")} onChange={(event) => change({ advanced: event.target.value })} />
      </Disclosure>
      {plan && <p className="strategy-research-note" role="status" data-testid="research-robustness-plan">
        {t("researchRobustness.plan", { folds: plan.folds, candidates: plan.candidates, runs: plan.runs })}
      </p>}
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
      <div className="strategy-research-batch-actions">
        <Button variant="primary" size="sm" disabled={busy} onClick={() => {
          let fields: StudyFields;
          try {
            fields = robustnessStudyFields(form, range) as StudyFields;
          } catch (reason) {
            setError(reason instanceof RobustnessFormError ? t(reason.key) : String(reason));
            return;
          }
          setBusy(true);
          setError(null);
          void onSubmit(fields)
            .catch((reason: unknown) => setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason)))
            .finally(() => setBusy(false));
        }}>{t("researchRobustness.run")}</Button>
      </div>
    </>}
  </Disclosure>;
}
