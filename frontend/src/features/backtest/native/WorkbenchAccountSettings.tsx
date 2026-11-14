import { Button, Checkbox, Field, FileDrop, InlineAlert, Input, Select } from "../../../components/ui/index.js";
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
      <Field label={t("native.account.model")}><Select size="sm" disabled={disabled} value={value.accountModel}
        onChange={(event) => patch({ accountModel: event.target.value })}>
        <option value="AUTO">{t("native.account.auto")}</option>
        <option value="LINEAR_PERP_ONE_WAY_V2">{t("native.account.perp")}</option>
      </Select></Field>
      {value.accountModel === "LINEAR_PERP_ONE_WAY_V2" && <>
        <Field label={t("native.account.leverage")}><Input size="sm" type="number" min="1" max="1000" step="any" disabled={disabled}
          value={value.leverage} onChange={(event) => patch({ leverage: Number(event.target.value) })} /></Field>
        <Field label={t("native.account.funding")}><Select size="sm" disabled={disabled} value={value.fundingMode}
          onChange={(event) => patch({ fundingMode: event.target.value })}>
          <option value="OFF">{t("native.account.fundingOff")}</option>
          <option value="HISTORICAL_REQUIRED">{t("native.account.fundingHistorical")}</option>
        </Select></Field>
      </>}
    </div>
    {value.accountModel === "LINEAR_PERP_ONE_WAY_V2" && <>
      <FileDrop key={props.inputKey} compact label={t("native.account.data")} hint={t("native.account.dataHelp")} accept="application/json,.json"
        disabled={disabled} onFiles={([file]) => props.onFile(file ?? null)} />
      {props.data && <p role="status">{props.data.symbol} · {props.data.events.length} {t("native.account.events")}</p>}
      {(props.data || props.state !== "ready") && <Button size="sm" variant="ghost" className="strategy-settings-action" disabled={disabled} onClick={() => props.onFile(null)}>{t("native.account.clear")}</Button>}
    </>}
    <Checkbox disabled={disabled} checked={value.participationEnabled}
      onChange={(event) => patch({ participationEnabled: event.target.checked })} label={t("native.account.participation")} description={t("native.account.pathHelp")} />
    {value.participationEnabled && <div className="strategy-settings-grid"><Field label={t("native.account.rate")}><Input size="sm" type="number" min="0" max="1" step=".01" disabled={disabled}
      value={value.participationRate} onChange={(event) => patch({ participationRate: Number(event.target.value) })} /></Field></div>}
    {props.error && <InlineAlert tone="danger">{props.error}</InlineAlert>}
  </section>;
}
