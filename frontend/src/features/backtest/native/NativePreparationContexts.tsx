import { t } from "../../../i18n/index.js";
import type { NativePreparationContext } from "./nativePreparationInputs.js";

export function NativePreparationContexts({ value, onChange, disabled, exchange, marketType, symbol }: {
  value: NativePreparationContext[]; onChange: (value: NativePreparationContext[]) => void;
  disabled: boolean; exchange: string; marketType: string; symbol: string;
}) {
  const update = (index: number, patch: Partial<NativePreparationContext>) => onChange(value.map((row, i) => i === index ? { ...row, ...patch } : row));
  return <details className="native-advanced-inputs">
    <summary>{t("preparation.contextsTitle")}</summary>
    <p>{t("preparation.contextsHint")}</p>
    {value.map((row, index) => <fieldset key={index} disabled={disabled}>
      <legend>{row.symbol || t("native.inputs.symbol")} · {row.interval}</legend>
      <label>{t("preparation.contextExchange")}<input value={row.exchange} onChange={(event) => update(index, { exchange: event.target.value })} /></label>
      <label>{t("preparation.contextMarket")}<input value={row.market_type} onChange={(event) => update(index, { market_type: event.target.value })} /></label>
      <label>{t("native.inputs.symbol")}<input value={row.symbol} onChange={(event) => update(index, { symbol: event.target.value })} /></label>
      <label>{t("native.inputs.timeframe")}<input value={row.interval} placeholder="1h" onChange={(event) => update(index, { interval: event.target.value })} /></label>
      <label>{t("preparation.contextBinding")}<input value={row.binding_symbol} onChange={(event) => update(index, { binding_symbol: event.target.value })} /></label>
      <label>{t("preparation.contextWarmup")}<input type="number" min={0} max={5000} step={1} value={row.warmup_bars ?? ""}
        placeholder={t("preparation.contextAutomatic")} onChange={(event) => update(index, { warmup_bars: event.target.value === "" ? undefined : Number(event.target.value) })} /></label>
      <button type="button" onClick={() => onChange(value.filter((_, i) => i !== index))}>{t("native.inputs.remove")}</button>
    </fieldset>)}
    <button type="button" disabled={disabled || value.length >= 16} onClick={() => onChange([...value,
      { exchange, market_type: marketType, symbol, interval: "1h", binding_symbol: "" }])}>{t("native.inputs.addContext")}</button>
  </details>;
}
