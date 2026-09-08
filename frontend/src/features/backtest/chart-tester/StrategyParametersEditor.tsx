import { t } from "../../../i18n/index.js";
import { strategySourceParameters, replaceStrategySourceParameter } from "./strategySourceParameters.js";

export function StrategyParametersEditor({ source, onChange }: { source: string; onChange(source: string): void }) {
  const fields = strategySourceParameters(source);
  return <section className="strategy-parameters-editor" aria-label={t("ux.parameters")}>
    <h3>{t("ux.parameters")}</h3>
    <p>{t(fields.length ? "ux.parametersHint" : "ux.noParameters")}</p>
    <div className="strategy-condition-grid">{fields.map((field) => <label key={field.line}>{field.label}
      <input type="number" step={field.prefix.includes("=") && field.prefix.includes("(") ? "1" : "any"} value={field.value}
        onChange={(event) => onChange(replaceStrategySourceParameter(source, field, event.target.value))} />
    </label>)}</div>
  </section>;
}
