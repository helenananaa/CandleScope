import { createContext, useContext } from "react";
import type { AlertIndicatorOption, AlertIndicatorSpec } from "../../features/alerts/alertIndicatorCatalog.js";
import { canonicalAlertField, isAlertIndicatorField, labelForSource } from "../../features/alerts/alertRuleModel.js";

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
