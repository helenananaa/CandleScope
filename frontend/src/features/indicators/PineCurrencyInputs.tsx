import { useState } from "react";
import { t } from "../../i18n/index.js";

import { parsePineCurrencyRates } from "./pineCurrencyModel.js";

export function PineCurrencyInputs({ value, onChange, readOnly }: { value: string; onChange(value: string): void; readOnly: boolean }) {
  const [error, setError] = useState("");
  return <details><summary>{t("indicator.pine.currencyRates")}</summary>
    <p>{t("indicator.pine.currencyRatesHelp")}</p>
    <textarea aria-label={t("indicator.pine.currencyRates")} rows={4} value={value} readOnly={readOnly}
      placeholder={'{"schemaVersion":1,"pairs":[{"from":"USD","to":"EUR","rates":[{"effectiveTime":1577923200000,"rate":0.89}]}]}'}
      style={{ width: "100%", fontFamily: "monospace", background: "var(--bg-primary)", color: "var(--text-primary)" }}
      onChange={(event) => { onChange(event.target.value); try { parsePineCurrencyRates(event.target.value); setError(""); } catch (err) { setError(String(err)); } }} />
    {error && <p role="alert">{error}</p>}
  </details>;
}
