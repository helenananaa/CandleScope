import { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { nativeApi, nativeTimeframe } from "./nativeBacktestApi.js";
import type { AdvancedInputs, InputDataset } from "./nativeInputs.js";
import { PineCurrencyInputs } from "../../indicators/PineCurrencyInputs.js";

export function NativeAdvancedInputs({ value, onChange, language, disabled, exchange, native = true, contextsOnly = false }: {
  value: AdvancedInputs; onChange: (value: AdvancedInputs) => void;
  language: "pine" | "pyne"; disabled: boolean; exchange: string; native?: boolean;
  contextsOnly?: boolean;
}) {
  const [datasets, setDatasets] = useState<InputDataset[]>([]);
  const [error, setError] = useState("");
  const [revision, refresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void nativeApi<{ datasets: InputDataset[] }>("/datasets", undefined, undefined, abort.signal)
      .then((result) => { setDatasets(result.datasets); setError(""); })
      .catch((reason) => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [revision]);
  return <details className="native-advanced-inputs">
    <summary>{t(contextsOnly || !native ? "native.inputs.addContext" : "native.inputs.title")}</summary>
    <p>{t("native.inputs.hint")}</p>
    {language === "pine" && !contextsOnly && <label>{t("native.inputs.priceTick")}
      <input type="number" min="0" step="any" disabled={disabled} value={value.priceTickSize ?? ""}
        onChange={(event) => onChange({ ...value, priceTickSize: event.target.value })} />
    </label>}
    <button type="button" disabled={disabled} onClick={() => refresh((n) => n+1)}>{t("native.inputs.refresh")}</button>
    {error && <p role="alert">{error}</p>}
    <label>{t("native.inputs.addContext")}<select value="" disabled={disabled || value.contexts.length >= 16} onChange={(event) => {
      const dataset = datasets.find((item) => item.dataset_id === event.target.value);
      if (dataset) onChange({ ...value, contexts: [...value.contexts, { dataset, symbol: `${(dataset.exchange || exchange).toUpperCase()}:${dataset.symbol}`,
        ...(dataset.market_type ? { marketType: dataset.market_type } : {}) }] });
    }}><option value="">{t("native.inputs.choose")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}</select></label>
    {value.contexts.map((item, index) => <fieldset key={`${item.dataset.dataset_id}:${index}`} disabled={disabled}>
      <legend>{item.dataset.name} · {item.dataset.interval}</legend>
      <label>{t("native.inputs.symbol")}<input value={item.symbol} onChange={(event) => onChange({ ...value,
        contexts: value.contexts.map((row, i) => i === index ? { ...row, symbol: event.target.value } : row) })} /></label>
      <p>{t("native.inputs.timeframe")}: {nativeTimeframe(item.dataset.interval)} · {item.dataset.data_epoch.slice(0, 19)}</p>
      <label>{t("backtest.marketType")}<input value={item.marketType ?? item.dataset.market_type ?? ""}
        placeholder={t("backtest.marketType")} onChange={(event) => onChange({ ...value,
          contexts: value.contexts.map((row, i) => i === index ? { ...row, marketType: event.target.value } : row) })} /></label>
      <button type="button" onClick={() => onChange({ ...value, contexts: value.contexts.filter((_, i) => i !== index) })}>{t("native.inputs.remove")}</button>
      {language === "pine" && <>
        <label>{t("native.inputs.priceTick")}<input type="number" min="0" step="any" value={item.priceTickSize ?? ""}
          onChange={(event) => onChange({ ...value, contexts: value.contexts.map((row, i) => i === index ? { ...row, priceTickSize: event.target.value } : row) })} /></label>
        <label>{t("native.inputs.currency")}<input value={item.currency ?? ""}
          onChange={(event) => onChange({ ...value, contexts: value.contexts.map((row, i) => i === index ? { ...row, currency: event.target.value } : row) })} /></label>
        <label>{t("native.inputs.quantityPrecision")}<input type="number" min="0" max="9" step="1" value={item.quantityPrecision ?? ""}
          onChange={(event) => onChange({ ...value, contexts: value.contexts.map((row, i) => i === index ? { ...row, quantityPrecision: event.target.value } : row) })} /></label>
        {(["pointValue", "quantityStep", "minContract"] as const).map(key => <label key={key}>{t(`native.inputs.${key}`)}<input inputMode="decimal" value={item[key] ?? ""}
          onChange={(event) => onChange({ ...value, contexts: value.contexts.map((row, i) => i === index ? { ...row, [key]: event.target.value } : row) })} /></label>)}
      </>}
    </fieldset>)}
    {language === "pine" && !contextsOnly && <>
      <label>{t("indicator.pine.quoteCurrency")}<input disabled={disabled} value={value.currency ?? ""}
        onChange={(event) => onChange({ ...value, currency: event.target.value })} /></label>
      <label>{t("native.inputs.quantityPrecision")}<input type="number" min="0" max="9" step="1" disabled={disabled} value={value.quantityPrecision ?? ""}
        onChange={(event) => onChange({ ...value, quantityPrecision: event.target.value })} /></label>
      {(["pointValue", "quantityStep", "minContract"] as const).map(key => <label key={key}>{t(`native.inputs.${key}`)}<input inputMode="decimal" disabled={disabled} value={value[key] ?? ""}
        onChange={(event) => onChange({ ...value, [key]: event.target.value })} /></label>)}
      {native && <><label>{t("native.inputs.magnifier")}<select disabled={disabled} value={value.magnifier?.dataset_id ?? ""} onChange={(event) => onChange({ ...value,
        magnifier: datasets.find((item) => item.dataset_id === event.target.value) ?? null })}>
        <option value="">{t("native.inputs.none")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}
      </select></label>
      <p>{t("native.inputs.magnifierHint")}</p></>}
      <label>{t("native.inputs.libraries")}<textarea disabled={disabled} spellCheck={false} value={value.libraries} onChange={(event) => onChange({ ...value, libraries: event.target.value })} /></label>
      <PineCurrencyInputs value={value.currencyRates ?? ""} readOnly={disabled}
        onChange={(currencyRates) => onChange({ ...value, currencyRates })} />
    </>}
  </details>;
}
