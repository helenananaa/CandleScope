import { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { nativeApi, nativeTimeframe } from "./nativeBacktestApi.js";
import type { AdvancedInputs, InputDataset } from "./nativeInputs.js";

export function NativeAdvancedInputs({ value, onChange, language, disabled, exchange, native = true }: {
  value: AdvancedInputs; onChange: (value: AdvancedInputs) => void;
  language: "pine" | "pyne"; disabled: boolean; exchange: string; native?: boolean;
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
    <summary>{t(native ? "native.inputs.title" : "native.inputs.addContext")}</summary>
    <p>{t("native.inputs.hint")}</p>
    <button type="button" disabled={disabled} onClick={() => refresh((n) => n+1)}>{t("native.inputs.refresh")}</button>
    {error && <p role="alert">{error}</p>}
    <label>{t("native.inputs.addContext")}<select value="" disabled={disabled || value.contexts.length >= 16} onChange={(event) => {
      const dataset = datasets.find((item) => item.dataset_id === event.target.value);
      if (dataset) onChange({ ...value, contexts: [...value.contexts, { dataset, symbol: `${exchange.toUpperCase()}:${dataset.symbol}` }] });
    }}><option value="">{t("native.inputs.choose")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}</select></label>
    {value.contexts.map((item, index) => <fieldset key={`${item.dataset.dataset_id}:${index}`} disabled={disabled}>
      <legend>{item.dataset.name} · {item.dataset.interval}</legend>
      <label>{t("native.inputs.symbol")}<input value={item.symbol} onChange={(event) => onChange({ ...value,
        contexts: value.contexts.map((row, i) => i === index ? { ...row, symbol: event.target.value } : row) })} /></label>
      <p>{t("native.inputs.timeframe")}: {nativeTimeframe(item.dataset.interval)} · {item.dataset.data_epoch.slice(0, 19)}</p>
      <button type="button" onClick={() => onChange({ ...value, contexts: value.contexts.filter((_, i) => i !== index) })}>{t("native.inputs.remove")}</button>
    </fieldset>)}
    {native && language === "pine" && <>
      <label>{t("native.inputs.magnifier")}<select disabled={disabled} value={value.magnifier?.dataset_id ?? ""} onChange={(event) => onChange({ ...value,
        magnifier: datasets.find((item) => item.dataset_id === event.target.value) ?? null })}>
        <option value="">{t("native.inputs.none")}</option>{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.symbol} · {item.interval}</option>)}
      </select></label>
      <p>{t("native.inputs.magnifierHint")}</p>
      <label>{t("native.inputs.libraries")}<textarea disabled={disabled} spellCheck={false} value={value.libraries} onChange={(event) => onChange({ ...value, libraries: event.target.value })} /></label>
    </>}
  </details>;
}
