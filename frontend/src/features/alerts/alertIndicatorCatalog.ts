import { fetchRegistry } from "../../services/indicatorApi.js";
import type { IndicatorParameterSchema, IndicatorRegistrySpec } from "../indicators/indicatorTypes.js";
import {
  alertIndicatorFieldKey,
  alertIndicatorFieldLabel,
  type AlertIndicatorField,
  type AlertIndicatorParamValue,
} from "./alertRuleModel.js";

export interface AlertIndicatorParamSpec {
  key: string;
  label: string;
  type: "int" | "float" | "string";
  defaultValue: AlertIndicatorParamValue;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

/** A builtin indicator as an alert source: calculation parameters only. */
export interface AlertIndicatorSpec {
  name: string;
  outputs: string[];
  params: AlertIndicatorParamSpec[];
}

export interface AlertIndicatorOption {
  value: string;
  label: string;
}

function paramSpec(schema: IndicatorParameterSchema): AlertIndicatorParamSpec | null {
  const key = schema.key ?? schema.name;
  const type = schema.type;
  if (!key || (type !== "int" && type !== "float" && type !== "string")) return null;
  const fallback = type === "string" ? "" : 0;
  const defaultValue = typeof schema.default === "number" || typeof schema.default === "string"
    ? schema.default : fallback;
  return {
    key,
    label: schema.label || key,
    type,
    defaultValue,
    ...(schema.min === undefined ? {} : { min: schema.min }),
    ...(schema.max === undefined ? {} : { max: schema.max }),
    ...(schema.step === undefined ? {} : { step: schema.step }),
    ...(schema.options === undefined ? {} : { options: [...schema.options] }),
  };
}

export function alertIndicatorSpecs(registry: readonly IndicatorRegistrySpec[]): AlertIndicatorSpec[] {
  return registry
    .filter((spec) => spec.is_builtin && spec.outputs.length > 0)
    .map((spec) => ({
      name: spec.name,
      outputs: [...spec.outputs],
      params: spec.paramSchema.map(paramSpec).filter((item): item is AlertIndicatorParamSpec => item !== null),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

export async function loadAlertIndicatorSpecs(): Promise<AlertIndicatorSpec[]> {
  return alertIndicatorSpecs(await fetchRegistry());
}

export function defaultAlertIndicatorField(spec: AlertIndicatorSpec, output: string): AlertIndicatorField {
  return {
    name: spec.name,
    output,
    params: Object.fromEntries(spec.params.map((param) => [param.key, param.defaultValue])),
  };
}

/** Every builtin output at its default parameters, ready for a source select. */
export function alertIndicatorOptions(specs: readonly AlertIndicatorSpec[]): AlertIndicatorOption[] {
  return specs.flatMap((spec) => spec.outputs.map((output) => {
    const field = defaultAlertIndicatorField(spec, output);
    return { value: alertIndicatorFieldKey(field), label: alertIndicatorFieldLabel(field) };
  }));
}

/** Coerce typed input within the schema, or return null to keep the last valid value. */
export function coerceAlertIndicatorParam(
  spec: AlertIndicatorParamSpec,
  raw: string,
): AlertIndicatorParamValue | null {
  if (spec.type === "string") {
    return spec.options && !spec.options.includes(raw) ? null : raw;
  }
  if (raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || (spec.type === "int" && !Number.isInteger(value))) return null;
  if ((spec.min !== undefined && value < spec.min) || (spec.max !== undefined && value > spec.max)) return null;
  return value;
}
