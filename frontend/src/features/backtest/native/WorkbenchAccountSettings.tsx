import { t } from "../../../i18n/index.js";
import type { AccountInputState, FrozenAccountData, WorkbenchAccountDraft } from "./workbenchAccountInputs.js";

export function WorkbenchAccountSettings(props: {
  value: WorkbenchAccountDraft; data: FrozenAccountData | null; state: AccountInputState; inputKey: number;
  disabled: boolean; error: string; onChange(value: WorkbenchAccountDraft): void; onFile(file: File | null): void;
}) {
  const { value, disabled } = props;
  const patch = (change: Partial<WorkbenchAccountDraft>) => props.onChange({ ...value, ...change });
  return <section className="strategy-settings-section">
    <h3>{t("native.account.title")}</h3>
    <div className="strategy-settings-grid">
      <label>{t("native.account.model")}<select disabled={disabled} value={value.accountModel}
        onChange={(event) => patch({ accountModel: event.target.value })}>
        <option value="AUTO">{t("native.account.auto")}</option>
        <option value="LINEAR_PERP_ONE_WAY_V2">{t("native.account.perp")}</option>
      </select></label>
      {value.accountModel === "LINEAR_PERP_ONE_WAY_V2" && <>
        <label>{t("native.account.leverage")}<input type="number" min="1" max="1000" step="any" disabled={disabled}
          value={value.leverage} onChange={(event) => patch({ leverage: Number(event.target.value) })} /></label>
        <label>{t("native.account.funding")}<select disabled={disabled} value={value.fundingMode}
          onChange={(event) => patch({ fundingMode: event.target.value })}>
          <option value="OFF">{t("native.account.fundingOff")}</option>
          <option value="HISTORICAL_REQUIRED">{t("native.account.fundingHistorical")}</option>
        </select></label>
        <label>{t("native.account.data")}<input key={props.inputKey} type="file" accept="application/json,.json"
          disabled={disabled} onChange={(event) => props.onFile(event.target.files?.[0] ?? null)} /></label>
      </>}
    </div>
    {value.accountModel === "LINEAR_PERP_ONE_WAY_V2" && <>
      <p>{t("native.account.dataHelp")}</p>
      {props.data && <p role="status">{props.data.symbol} · {props.data.events.length} {t("native.account.events")}</p>}
      {(props.data || props.state !== "ready") && <button type="button" disabled={disabled} onClick={() => props.onFile(null)}>{t("native.account.clear")}</button>}
    </>}
    <label className="strategy-settings-check"><input type="checkbox" disabled={disabled} checked={value.participationEnabled}
      onChange={(event) => patch({ participationEnabled: event.target.checked })} />{t("native.account.participation")}</label>
    {value.participationEnabled && <div className="strategy-settings-grid"><label>{t("native.account.rate")}<input type="number" min="0" max="1" step=".01" disabled={disabled}
      value={value.participationRate} onChange={(event) => patch({ participationRate: Number(event.target.value) })} /></label></div>}
    <p>{t("native.account.pathHelp")}</p>
    {props.error && <p role="alert">{props.error}</p>}
  </section>;
}
