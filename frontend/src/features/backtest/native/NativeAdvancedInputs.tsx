import { useEffect, useState } from "react";
import { Button, Disclosure, Field, InlineAlert, Input, Select, Textarea } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { nativeApi, nativeTimeframe } from "./nativeBacktestApi.js";
import type { AdvancedInputs, InputDataset } from "./nativeInputs.js";
import { PineCurrencyInputs } from "../../indicators/PineCurrencyInputs.js";

export function NativeAdvancedInputs({ value, onChange, language, disabled, exchange, native = true, contextsOnly = false }: {
  value: AdvancedInputs; onChange: (value: AdvancedInputs) => void;
  language: "pine"; disabled: boolean; exchange: string; native?: boolean;
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
  const contextPatch = (index: number, patch: Partial<AdvancedInputs["contexts"][number]>) =>
    onChange({ ...value, contexts: value.contexts.map((row, i) => i === index ? { ...row, ...patch } : row) });
  return <Disclosure className="native-advanced-inputs" summary={t(contextsOnly || !native ? "native.inputs.addContext" : "native.inputs.title")}>
    <p className="native-settings-note">{t("native.inputs.hint")}</p>
    {language === "pine" && !contextsOnly && <Field label={t("native.inputs.priceTick")}>
      <Input size="sm" type="number" min="0" step="any" disabled={disabled} value={value.priceTickSize ?? ""}
        onChange={(event) => onChange({ ...value, priceTickSize: event.target.value })} />
    </Field>}
    <div className="native-inputs-picker">
      <Field label={t("native.inputs.addContext")}><Select size="sm" value="" disabled={disabled || value.contexts.length >= 16} onChange={(event) => {
        const dataset = datasets.find((item) => item.dataset_id === event.target.value);
        if (dataset) onChange({ ...value, contexts: [...value.contexts, { dataset, symbol: `${(dataset.exchange || exchange).toUpperCase()}:${dataset.symbol}`,
          ...(dataset.market_type ? { marketType: dataset.market_type } : {}) }] });
      }}><option value="">{t("native.inputs.choose")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}</Select></Field>
      <Button size="sm" variant="ghost" disabled={disabled} onClick={() => refresh((n) => n+1)}>{t("native.inputs.refresh")}</Button>
    </div>
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    {value.contexts.map((item, index) => <fieldset key={`${item.dataset.dataset_id}:${index}`} className="native-context" disabled={disabled}>
      <legend>{item.dataset.name} · {item.dataset.interval}</legend>
      <p className="native-settings-note">{t("native.inputs.timeframe")}: {nativeTimeframe(item.dataset.interval)} · <code>{item.dataset.data_epoch.slice(0, 19)}</code></p>
      <div className="strategy-settings-grid">
        <Field label={t("native.inputs.symbol")}><Input size="sm" value={item.symbol} onChange={(event) => contextPatch(index, { symbol: event.target.value })} /></Field>
        <Field label={t("backtest.marketType")}><Input size="sm" value={item.marketType ?? item.dataset.market_type ?? ""}
          placeholder={t("backtest.marketType")} onChange={(event) => contextPatch(index, { marketType: event.target.value })} /></Field>
        {language === "pine" && <>
          <Field label={t("native.inputs.priceTick")}><Input size="sm" type="number" min="0" step="any" value={item.priceTickSize ?? ""}
            onChange={(event) => contextPatch(index, { priceTickSize: event.target.value })} /></Field>
          <Field label={t("native.inputs.currency")}><Input size="sm" value={item.currency ?? ""}
            onChange={(event) => contextPatch(index, { currency: event.target.value })} /></Field>
          <Field label={t("native.inputs.quantityPrecision")}><Input size="sm" type="number" min="0" max="9" step="1" value={item.quantityPrecision ?? ""}
            onChange={(event) => contextPatch(index, { quantityPrecision: event.target.value })} /></Field>
          {(["pointValue", "quantityStep", "minContract"] as const).map(key => <Field key={key} label={t(`native.inputs.${key}`)}><Input size="sm" inputMode="decimal" value={item[key] ?? ""}
            onChange={(event) => contextPatch(index, { [key]: event.target.value })} /></Field>)}
        </>}
      </div>
      <Button size="sm" variant="ghost" className="strategy-settings-action" onClick={() => onChange({ ...value, contexts: value.contexts.filter((_, i) => i !== index) })}>{t("native.inputs.remove")}</Button>
    </fieldset>)}
    {language === "pine" && !contextsOnly && <>
      <div className="strategy-settings-grid">
        <Field label={t("indicator.pine.quoteCurrency")}><Input size="sm" disabled={disabled} value={value.currency ?? ""}
          onChange={(event) => onChange({ ...value, currency: event.target.value })} /></Field>
        <Field label={t("native.inputs.quantityPrecision")}><Input size="sm" type="number" min="0" max="9" step="1" disabled={disabled} value={value.quantityPrecision ?? ""}
          onChange={(event) => onChange({ ...value, quantityPrecision: event.target.value })} /></Field>
        {(["pointValue", "quantityStep", "minContract"] as const).map(key => <Field key={key} label={t(`native.inputs.${key}`)}><Input size="sm" inputMode="decimal" disabled={disabled} value={value[key] ?? ""}
          onChange={(event) => onChange({ ...value, [key]: event.target.value })} /></Field>)}
      </div>
      {native && <Field label={t("native.inputs.magnifier")} hint={t("native.inputs.magnifierHint")}><Select size="sm" disabled={disabled} value={value.magnifier?.dataset_id ?? ""} onChange={(event) => onChange({ ...value,
        magnifier: datasets.find((item) => item.dataset_id === event.target.value) ?? null })}>
        <option value="">{t("native.inputs.none")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}
      </Select></Field>}
      <Field label={t("native.inputs.libraries")}><Textarea className="native-json" disabled={disabled} spellCheck={false} value={value.libraries} onChange={(event) => onChange({ ...value, libraries: event.target.value })} /></Field>
      <Field label={t("pine.host.title")} hint={t("pine.host.hint")}><Textarea className="native-json" disabled={disabled} spellCheck={false} value={value.hostInputs || "{}"} onChange={(event) => onChange({ ...value, hostInputs: event.target.value })} /></Field>
      <PineCurrencyInputs value={value.currencyRates ?? ""} readOnly={disabled}
        onChange={(currencyRates) => onChange({ ...value, currencyRates })} />
    </>}
  </Disclosure>;
}
