import { useEffect, useState, type ReactNode } from "react";

import { t } from "../../../i18n/index.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousParameterField } from "./continuousTypes.js";

type Value = string | number | boolean;

export default function ContinuousParameterEditor({ manager, source, parameters, enabled, disabled, onChange, fallback }: {
  manager: ContinuousStrategyDataManager | undefined;
  source: string;
  parameters: Record<string, unknown>;
  enabled: boolean;
  disabled: boolean;
  onChange(name: string, value: Value): void;
  fallback: ReactNode;
}) {
  const [inspection, setInspection] = useState<{ source: string; fields: ContinuousParameterField[] } | null>(null);
  useEffect(() => {
    if (!enabled || !manager || !source.trim()) return;
    const abort = new AbortController();
    const timeout = window.setTimeout(() => {
      void manager.editorParameters(source, abort.signal).then(
        ({ fields }) => { if (!abort.signal.aborted) setInspection({ source, fields }); },
        () => { if (!abort.signal.aborted) setInspection({ source, fields: [] }); },
      );
    }, 300);
    return () => { window.clearTimeout(timeout); abort.abort(); };
  }, [enabled, manager, source]);
  const fields = enabled && inspection?.source === source ? inspection.fields : [];
  if (!fields.length) return fallback;

  return <section className="strategy-parameters-editor" aria-label={t("ux.parameters")}>
    <h3>{t("ux.parameters")}</h3>
    <p>{t("continuous.parameterHint")}</p>
    <div className="strategy-condition-grid">
      {fields.map((field) => {
        const current = Object.hasOwn(parameters, field.name) ? parameters[field.name] : field.default;
        const change = (value: Value) => onChange(field.name, value);
        return <label key={field.name}>{field.name}
          {field.type === "boolean" ? <input type="checkbox" disabled={disabled}
            checked={current === true} onChange={(event) => change(event.currentTarget.checked)} />
            : field.type === "string" ? <input type="text" disabled={disabled} maxLength={256}
              value={String(current ?? "")} onChange={(event) => change(event.currentTarget.value)} />
              : <input type="number" step={field.type === "integer" ? 1 : "any"} disabled={disabled}
                value={typeof current === "number" || typeof current === "string" ? current : ""}
                onChange={(event) => {
                  const value = event.currentTarget.valueAsNumber;
                  if (field.type === "integer" ? Number.isSafeInteger(value) : Number.isFinite(value)) change(value);
                }} />}
        </label>;
      })}
    </div>
  </section>;
}
