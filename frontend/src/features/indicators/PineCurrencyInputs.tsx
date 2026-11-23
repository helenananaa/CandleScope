import { useState } from "react";
import { t } from "../../i18n/index.js";
import { Disclosure } from "../../components/ui/Display.js";
import { Textarea } from "../../components/ui/Field.js";

import { parsePineCurrencyRates } from "./pineCurrencyModel.js";

export function PineCurrencyInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <Disclosure summary={t("indicator.pine.currencyRates")}>
    <div className="indicator-editor-advanced-body">
      <p className="indicator-editor-hint">{t("indicator.pine.currencyRatesHelp")}</p>
      <Textarea className="indicator-editor-json" aria-label={t("indicator.pine.currencyRates")} aria-invalid={error ? true : undefined} value={value} readOnly={readOnly} rows={4} spellCheck={false}
        placeholder={'{"schemaVersion":1,"pairs":[{"from":"USD","to":"EUR","rates":[{"effectiveTime":1577923200000,"rate":0.89}]}]}'}
        onChange={(event) => { onChange(event.target.value); try { parsePineCurrencyRates(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
      {error && <p className="ui-field-error" role="alert">{error}</p>}
    </div>
  </Disclosure>;
}
