import { Field, Input } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { strategySourceParameters, replaceStrategySourceParameter } from "./strategySourceParameters.js";

export function StrategyParametersEditor({ source, onChange, disabled }: { source: string; onChange(source: string): void; disabled?: boolean }) {
  const fields = strategySourceParameters(source);
  return <section className="strategy-parameters-editor" aria-label={t("ux.parameters")}>
    <h3>{t("ux.parameters")}</h3>
    <p className="strategy-editor-note">{t(fields.length ? "ux.parametersHint" : "ux.noParameters")}</p>
    {fields.length > 0 && <div className="strategy-condition-grid">{fields.map((field) => <Field key={field.line} label={<code>{field.label}</code>}>
      <Input size="sm" type="number" disabled={disabled} step={field.prefix.includes("=") && field.prefix.includes("(") ? "1" : "any"} value={field.value}
        onChange={(event) => onChange(replaceStrategySourceParameter(source, field, event.target.value))} />
    </Field>)}</div>}
  </section>;
}
