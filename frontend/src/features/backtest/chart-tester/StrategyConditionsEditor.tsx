import { t } from "../../../i18n/index.js";
import { validStrategyRunSettings, type StrategyRunSettings, type StrategyExecutionOverrides } from "../../../shared/strategyRunSettings.js";

export function StrategyConditionsEditor({ settings, marketType, preciseAvailable, preciseArchiveHint = true, onChange }: {
  settings: StrategyRunSettings;
  marketType: string;
  preciseAvailable?: boolean;
  preciseArchiveHint?: boolean;
  onChange(settings: StrategyRunSettings): void;
}) {
  const profile = settings.pythonBarExecution;
  const values = settings.executionOverrides ?? {
    initialBalance: "10000", equityPercent: "10", leverage: "1", feeBps: marketType === "spot" ? "10" : "4", slippageBps: "1",
  };
  const fields = [
    ["initialBalance", "chartTester.settings.capital", "USDT"],
    ["equityPercent", "backtest.equityPct", ""],
    ["leverage", "backtest.leverage", "×"],
    ["feeBps", "chartTester.settings.fee", "bps"],
    ["slippageBps", "ux.slippage", "bps"],
  ] as const;
  const dateValue = (value: number | undefined) => Number.isFinite(value) && value! > 0 ? new Date(value!).toISOString().slice(0, 16) : "";
  return <section className="strategy-conditions-editor" aria-label={t("chartTester.tab.settings")}>
    {profile && <p>{t("continuous.researchProfile", {
      output: t(profile.outputMode === "SIGNAL" ? "continuous.signal" : profile.outputMode === "ORDER_INTENT" ? "continuous.order" : "continuous.target"),
      model: profile.executionModel, warmup: profile.warmupBars,
    })}</p>}
    {preciseAvailable !== undefined && !profile && <>
      <label className="strategy-condition-range">{t("chartTester.settings.fidelity")}
        <select value={settings.fidelityPreference ?? "FAST"} onChange={(event) => onChange({
          ...settings, fidelityPreference: event.currentTarget.value === "PRECISE" ? "PRECISE" : "FAST",
        })}>
          <option value="FAST">{t("chartTester.settings.fast")}</option>
          <option value="PRECISE" disabled={!preciseAvailable}>{t("chartTester.settings.precise")}</option>
        </select>
      </label>
      {!preciseAvailable ? <p>{t("research.capability.tapeDenied")}</p>
        : preciseArchiveHint && settings.fidelityPreference === "PRECISE" && <p>{t("research.execution.preciseArchiveHint")}</p>}
    </>}
    <label className="strategy-condition-range">{t("chartTester.settings.date")}
      <select disabled={!!profile} value={settings.rangeMode} onChange={(event) => onChange({ ...settings, rangeMode: event.target.value as StrategyRunSettings["rangeMode"], customRange: event.target.value === "ALL_AVAILABLE" ? null : { startMs: 0, endMs: 0 } })}>
        <option value="ALL_AVAILABLE">{t("chartTester.settings.allAvailable")}</option><option value="CUSTOM">{t("ux.customRange")}</option>
      </select>
    </label>
    {settings.rangeMode === "CUSTOM" && <div className="strategy-condition-grid">
      {(["startMs", "endMs"] as const).map((key) => <label key={key}>{t(key === "startMs" ? "ux.startUtc" : "ux.endUtc")}
        <input type="datetime-local" value={dateValue(settings.customRange?.[key])} onInput={(event) => onChange({ ...settings, customRange: { startMs: settings.customRange?.startMs ?? 0, endMs: settings.customRange?.endMs ?? 0, [key]: event.currentTarget.value ? Date.parse(`${event.currentTarget.value}Z`) : 0 } })} />
      </label>)}
    </div>}
    <label className="strategy-condition-toggle"><input type="checkbox" checked={settings.executionOverrides !== undefined}
      onChange={(event) => { const { executionOverrides: _removed, ...range } = settings; void _removed; onChange(event.target.checked ? { ...settings, executionOverrides: values } : range); }} />{t("ux.customExecution")}</label>
    <div className="strategy-condition-grid">
      {fields.map(([key, label, unit]) => <label key={key}>{t(label)}{unit ? ` · ${unit}` : ""}<input type="number" step="any" max={key === "leverage" && (marketType === "spot" || profile) ? 1 : undefined} disabled={!settings.executionOverrides} value={values[key]}
        onChange={(event) => onChange({ ...settings, executionOverrides: { ...values, [key]: event.target.value } as StrategyExecutionOverrides })} /></label>)}
    </div>
    <p>{t(settings.executionOverrides ? "ux.customExecutionHint" : "chartTester.settings.feePending")}</p>
    <p>{t("ux.positionFromCode")}</p>
    <p>{t("ux.signalSizingHint")}</p>
    {marketType === "spot" && <p>{t("ux.spotCashHint")}</p>}
    {!validStrategyRunSettings(settings) && <p role="alert">{t("ux.invalidConditions")}</p>}
  </section>;
}
