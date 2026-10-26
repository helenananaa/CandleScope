import { t } from "../../../i18n/index.js";
import type { StrategyDraftLanguage } from "./StrategyDraftStore.js";
import { strategyLanguageLabel } from "./strategyLanguageLabel.js";

export function StrategyLanguageControls({ language, onLanguage, confirmed, onConfirm }: {
  language: StrategyDraftLanguage;
  onLanguage(language: StrategyDraftLanguage): void;
  confirmed: boolean;
  onConfirm(confirmed: boolean): void;
}) {
  return <div className="strategy-language-controls">
    <label>{t("research.strategy.language")}
      <select data-testid="strategy-language" value={language} onChange={(event) => onLanguage(event.target.value as StrategyDraftLanguage)}>
        <option value="pine">{strategyLanguageLabel("pine")}</option><option value="python">{strategyLanguageLabel("python")}</option>
      </select>
    </label>
    {language === "python" && <div data-testid="strategy-python-permissions">
      <p>{t("python.fact.noSandbox")} {t("python.fact.fsAccess")}</p>
      <label><input type="checkbox" data-testid="strategy-python-confirm" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />{t("python.confirmTrusted")}</label>
    </div>}
  </div>;
}
