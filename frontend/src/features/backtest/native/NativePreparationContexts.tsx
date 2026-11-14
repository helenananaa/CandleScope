import { Button, Disclosure, Field, Input } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import type { NativePreparationContext } from "./nativePreparationInputs.js";

export function NativePreparationContexts({ value, onChange, disabled, exchange, marketType, symbol }: {
  value: NativePreparationContext[]; onChange: (value: NativePreparationContext[]) => void;
  disabled: boolean; exchange: string; marketType: string; symbol: string;
}) {
  const update = (index: number, patch: Partial<NativePreparationContext>) => onChange(value.map((row, i) => i === index ? { ...row, ...patch } : row));
  return <Disclosure className="native-advanced-inputs" summary={t("preparation.contextsTitle")}>
    <p className="native-settings-note">{t("preparation.contextsHint")}</p>
    {value.map((row, index) => <fieldset key={index} className="native-context" disabled={disabled}>
      <legend>{row.symbol || t("native.inputs.symbol")} · {row.interval}</legend>
      <div className="strategy-settings-grid">
        <Field label={t("preparation.contextExchange")}><Input size="sm" value={row.exchange} onChange={(event) => update(index, { exchange: event.target.value })} /></Field>
        <Field label={t("preparation.contextMarket")}><Input size="sm" value={row.market_type} onChange={(event) => update(index, { market_type: event.target.value })} /></Field>
        <Field label={t("native.inputs.symbol")}><Input size="sm" value={row.symbol} onChange={(event) => update(index, { symbol: event.target.value })} /></Field>
        <Field label={t("native.inputs.timeframe")}><Input size="sm" value={row.interval} placeholder="1h" onChange={(event) => update(index, { interval: event.target.value })} /></Field>
        <Field label={t("preparation.contextBinding")}><Input size="sm" value={row.binding_symbol} onChange={(event) => update(index, { binding_symbol: event.target.value })} /></Field>
        <Field label={t("preparation.contextWarmup")}><Input size="sm" type="number" min={0} max={5000} step={1} value={row.warmup_bars ?? ""}
          placeholder={t("preparation.contextAutomatic")} onChange={(event) => update(index, { warmup_bars: event.target.value === "" ? undefined : Number(event.target.value) })} /></Field>
      </div>
      <Button size="sm" variant="ghost" className="strategy-settings-action" onClick={() => onChange(value.filter((_, i) => i !== index))}>{t("native.inputs.remove")}</Button>
    </fieldset>)}
    <Button size="sm" className="strategy-settings-action" disabled={disabled || value.length >= 16} onClick={() => onChange([...value,
      { exchange, market_type: marketType, symbol, interval: "1h", binding_symbol: "" }])}>{t("native.inputs.addContext")}</Button>
  </Disclosure>;
}
