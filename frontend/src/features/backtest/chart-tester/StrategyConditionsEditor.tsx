import { Checkbox, Field, InlineAlert, Input, Select } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { validStrategyRunSettings, type StrategyRunSettings, type StrategyExecutionOverrides } from "../../../shared/strategyRunSettings.js";

export function StrategyConditionsEditor({ settings, marketType, capitalAsset = "USDT", preciseAvailable, preciseArchiveHint = true, onChange }: {
  settings: StrategyRunSettings;
  marketType: string;
  capitalAsset?: string | undefined;
  preciseAvailable?: boolean;
  preciseArchiveHint?: boolean;
  onChange(settings: StrategyRunSettings): void;
}) {
  const profile = settings.pythonBarExecution;
  const values = settings.executionOverrides ?? {
    initialBalance: "10000", equityPercent: "10", leverage: "1", feeBps: marketType === "spot" ? "10" : "4", slippageBps: "1",
  };
  const fields = [
    ["initialBalance", "chartTester.settings.capital", capitalAsset],
    ["equityPercent", "backtest.equityPct", ""],
    ["leverage", "backtest.leverage", "×"],
    ["feeBps", "chartTester.settings.fee", "bps"],
    ["slippageBps", "ux.slippage", "bps"],
  ] as const;
  const dateValue = (value: number | undefined) => Number.isFinite(value) && value! > 0 ? new Date(value!).toISOString().slice(0, 16) : "";
  return <section className="strategy-conditions-editor" aria-label={t("chartTester.tab.settings")}>
    {profile && <p className="strategy-editor-note">{t("continuous.researchProfile", {
      output: t(profile.outputMode === "SIGNAL" ? "continuous.signal" : profile.outputMode === "ORDER_INTENT" ? "continuous.order" : "continuous.target"),
      model: profile.executionModel, warmup: profile.warmupBars,
    })}</p>}
    {preciseAvailable !== undefined && !profile && <>
      <Field label={t("chartTester.settings.fidelity")}>
        <Select size="sm" value={settings.fidelityPreference ?? "FAST"} onChange={(event) => onChange({
          ...settings, fidelityPreference: event.currentTarget.value === "PRECISE" ? "PRECISE" : "FAST",
        })}>
          <option value="FAST">{t("chartTester.settings.fast")}</option>
          <option value="PRECISE" disabled={!preciseAvailable}>{t("chartTester.settings.precise")}</option>
        </Select>
      </Field>
      {!preciseAvailable ? <p className="strategy-editor-note">{t("research.capability.tapeDenied")}</p>
        : preciseArchiveHint && settings.fidelityPreference === "PRECISE" && <p className="strategy-editor-note">{t("research.execution.preciseArchiveHint")}</p>}
    </>}
    <Field label={t("chartTester.settings.date")}>
      <Select size="sm" disabled={!!profile} value={settings.rangeMode} onChange={(event) => onChange({ ...settings, rangeMode: event.target.value as StrategyRunSettings["rangeMode"], customRange: event.target.value === "ALL_AVAILABLE" ? null : { startMs: 0, endMs: 0 } })}>
        <option value="ALL_AVAILABLE">{t("chartTester.settings.allAvailable")}</option><option value="CUSTOM">{t("ux.customRange")}</option>
      </Select>
    </Field>
    {settings.rangeMode === "CUSTOM" && <div className="strategy-condition-grid">
      {(["startMs", "endMs"] as const).map((key) => <Field key={key} label={t(key === "startMs" ? "ux.startUtc" : "ux.endUtc")}>
        <Input size="sm" type="datetime-local" value={dateValue(settings.customRange?.[key])} onInput={(event) => onChange({ ...settings, customRange: { startMs: settings.customRange?.startMs ?? 0, endMs: settings.customRange?.endMs ?? 0, [key]: event.currentTarget.value ? Date.parse(`${event.currentTarget.value}Z`) : 0 } })} />
      </Field>)}
    </div>}
    <Checkbox checked={settings.executionOverrides !== undefined} label={t("ux.customExecution")}
      onChange={(event) => { const { executionOverrides: _removed, ...range } = settings; void _removed; onChange(event.target.checked ? { ...settings, executionOverrides: values } : range); }} />
    <div className="strategy-condition-grid">
      {fields.map(([key, label, unit]) => <Field key={key} label={`${t(label)}${unit ? ` · ${unit}` : ""}`}>
        <Input size="sm" type="number" step="any" max={key === "leverage" && (marketType === "spot" || profile) ? 1 : undefined} disabled={!settings.executionOverrides} value={values[key]}
          onChange={(event) => onChange({ ...settings, executionOverrides: { ...values, [key]: event.target.value } as StrategyExecutionOverrides })} />
      </Field>)}
    </div>
    <ul className="strategy-editor-notes">
      <li>{t(settings.executionOverrides ? "ux.customExecutionHint" : "chartTester.settings.feePending")}</li>
      <li>{t("ux.positionFromCode")}</li>
      <li>{t("ux.signalSizingHint")}</li>
      {marketType === "spot" && <li>{t("ux.spotCashHint")}</li>}
    </ul>
    {!validStrategyRunSettings(settings) && <InlineAlert tone="danger">{t("ux.invalidConditions")}</InlineAlert>}
  </section>;
}
