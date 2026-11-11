import { createContext, useContext, useEffect, useState } from "react";
import {
  coerceAlertIndicatorParam,
  type AlertIndicatorOption,
  type AlertIndicatorParamSpec,
  type AlertIndicatorSpec,
} from "../../features/alerts/alertIndicatorCatalog.js";
import {
  alertIndicatorFieldKey,
  canonicalAlertField,
  isAlertIndicatorField,
  labelForSource,
  parseAlertIndicatorField,
} from "../../features/alerts/alertRuleModel.js";
import { indicatorParamLabel, indicatorSourceLabel } from "../../features/indicators/indicatorParamLabels.js";

export interface AlertIndicatorCatalog {
  specs: AlertIndicatorSpec[];
  options: AlertIndicatorOption[];
}

export const AlertIndicatorCatalogContext = createContext<AlertIndicatorCatalog>({ specs: [], options: [] });

const ALIAS_FIELDS = ["rsi", "macdHist", "ma20"] as const;

/** Indicator choices for a select, always including the current value. */
export function useAlertIndicatorOptions(current: string): AlertIndicatorOption[] {
  const { options } = useContext(AlertIndicatorCatalogContext);
  const base = options.length
    ? options
    : ALIAS_FIELDS.map((field) => ({ value: canonicalAlertField(field), label: labelForSource(field) }));
  if (!isAlertIndicatorField(current)) return base;
  const value = canonicalAlertField(current);
  return base.some((option) => option.value === value)
    ? base
    : [...base, { value, label: labelForSource(current) }];
}

interface ParamInputProps {
  spec: AlertIndicatorParamSpec;
  value: string | number | undefined;
  onCommit(value: string | number): void;
}

function ParamInput({ spec, value, onCommit }: ParamInputProps) {
  const external = value === undefined ? String(spec.defaultValue) : String(value);
  const [text, setText] = useState(external);
  useEffect(() => setText(external), [external]);
  const label = indicatorParamLabel(spec.key, spec.label, true);
  const commit = (raw: string) => {
    setText(raw);
    const coerced = coerceAlertIndicatorParam(spec, raw);
    if (coerced !== null && coerced !== value) onCommit(coerced);
  };
  return (
    <label className="alert-field compact">
      <span>{label}</span>
      {spec.options ? (
        <select value={text} onChange={(event) => commit(event.target.value)}>
          {spec.options.map((option) => (
            <option key={option} value={option}>{spec.key === "source" ? indicatorSourceLabel(option) : option}</option>
          ))}
        </select>
      ) : (
        <input
          type="number"
          value={text}
          min={spec.min}
          max={spec.max}
          step={spec.step ?? (spec.type === "int" ? 1 : "any")}
          onChange={(event) => commit(event.target.value)}
          onBlur={() => setText(external)}
        />
      )}
    </label>
  );
}

interface AlertIndicatorParamFieldsProps {
  value: string;
  onChange(value: string): void;
}

/** Calculation parameters of an indicator field; each valid edit writes a canonical key. */
export function AlertIndicatorParamFields({ value, onChange }: AlertIndicatorParamFieldsProps) {
  const { specs } = useContext(AlertIndicatorCatalogContext);
  const field = parseAlertIndicatorField(value);
  const spec = field ? specs.find((item) => item.name === field.name) : undefined;
  if (!field || !spec || spec.params.length === 0) return null;
  return (
    <div className="alert-condition-grid">
      {spec.params.map((param) => (
        <ParamInput
          key={param.key}
          spec={param}
          value={field.params[param.key]}
          onCommit={(next) => onChange(alertIndicatorFieldKey({ ...field, params: { ...field.params, [param.key]: next } }))}
        />
      ))}
    </div>
  );
}
