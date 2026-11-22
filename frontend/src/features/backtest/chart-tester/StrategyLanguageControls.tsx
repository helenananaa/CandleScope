import { Checkbox, Field, InlineAlert, Select } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import type { StrategyDraftLanguage } from "./StrategyDraftStore.js";
import { strategyLanguageLabel } from "./strategyLanguageLabel.js";

export function StrategyLanguageControls({ language, onLanguage, confirmed, onConfirm, languageFixed = false }: {
  language: StrategyDraftLanguage;
  onLanguage(language: StrategyDraftLanguage): void;
  confirmed: boolean;
  onConfirm(confirmed: boolean): void;
  /** The chart's strategy list fixes each strategy's language (ADR-BACKTEST-015 P4c): no language switch. */
  languageFixed?: boolean;
}) {
  return <div className="strategy-language-controls">
    {!languageFixed && <Field label={t("research.strategy.language")}>
      <Select size="sm" data-testid="strategy-language" value={language} onChange={(event) => onLanguage(event.target.value as StrategyDraftLanguage)}>
        <option value="pine">{strategyLanguageLabel("pine")}</option><option value="python">{strategyLanguageLabel("python")}</option>
      </Select>
    </Field>}
    {language === "python" && <InlineAlert tone="warning">
      <div className="strategy-python-permissions" data-testid="strategy-python-permissions">
        <p>{t("python.fact.noSandbox")} {t("python.fact.fsAccess")}</p>
        <Checkbox data-testid="strategy-python-confirm" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} label={t("python.confirmTrusted")} />
      </div>
    </InlineAlert>}
  </div>;
}
