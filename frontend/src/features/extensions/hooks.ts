import { useEffect } from "react";
import { useLocale } from "../../i18n/useLocale.js";
import { bindHostService } from "./state.js";

export function useExtensionText() {
  const locale = useLocale();
  return (zh: string, en: string) => locale.startsWith("zh") ? zh : en;
}

export function useExtensionService(name: string, value: unknown): void {
  useEffect(() => bindHostService(name, value), [name, value]);
}
