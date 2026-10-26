import { t } from "../../../i18n/index.js";
import type { StrategyDraftLanguage } from "./StrategyDraftStore.js";

export function strategyLanguageLabel(language: StrategyDraftLanguage): string {
  return language === "python" ? "Python" : t("chartTester.language.pine");
}
