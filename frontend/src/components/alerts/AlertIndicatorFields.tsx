import { useContext, useEffect, useState } from "react";
import { Field, Input, Select } from "../ui/Field.js";
import {
  coerceAlertIndicatorParam,
  type AlertIndicatorParamSpec,
} from "../../features/alerts/alertIndicatorCatalog.js";
import {
  alertIndicatorFieldKey,
  parseAlertIndicatorField,
} from "../../features/alerts/alertRuleModel.js";
import { indicatorParamLabel, indicatorSourceLabel } from "../../features/indicators/indicatorParamLabels.js";

import { AlertIndicatorCatalogContext } from "./alertIndicatorCatalogContext.js";

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
    <Field label={label}>
      {spec.options ? (
        <Select size="sm" value={text} onChange={(event) => commit(event.target.value)}>
          {spec.options.map((option) => (
            <option key={option} value={option}>{spec.key === "source" ? indicatorSourceLabel(option) : option}</option>
          ))}
        </Select>
      ) : (
        <Input size="sm"
          type="number"
          value={text}
          min={spec.min}
          max={spec.max}
          step={spec.step ?? (spec.type === "int" ? 1 : "any")}
          onChange={(event) => commit(event.target.value)}
          onBlur={() => setText(external)}
        />
      )}
    </Field>
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
    <div className="alert-field-grid">
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
