import { useRef, useState } from "react";
import { Button, Checkbox, Field, Popover, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import ChartNoteFilterFields from "../chart-workspace/ChartNoteFilterFields.js";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import { useTradingAccountsRuntime } from "./useTradingAccountsRuntime.js";

export default function ChartAccountOverlayMenu({ cellId, settings, error, onChange }: {
  cellId: string;
  settings: ChartAccountOverlaySettings | undefined;
  error: string | null;
  onChange(settings: ChartAccountOverlaySettings): void;
}) {
  useLocale();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const { view } = useTradingAccountsRuntime(open);
  const value = normalizeChartAccountOverlay(settings);
  const title = t("trading.overlay.title", { n: cellId.slice("cell-".length) });
  return <>
    <Button ref={trigger} size="sm" className="chart-account-overlay-trigger"
      aria-label={title} title={error ?? title} data-error={error ? "true" : undefined} aria-haspopup="dialog" aria-expanded={open}
      onDoubleClick={event => event.stopPropagation()} onClick={() => setOpen(current => !current)}>
      {t("trading.overlay.trigger")}
    </Button>
    <Popover open={open} onClose={() => setOpen(false)} anchorRef={trigger} label={title} className="chart-account-overlay-menu">
      <strong>{title}</strong>
      <Field label={t("trading.overlay.source")}>
        <Select size="sm" value={value.accountId ?? ""} onChange={event => onChange({ ...value, accountId: event.target.value || null })}>
          <option value="">{t("trading.overlay.followPanel")}{view.selected ? ` · ${view.selected.name}` : ""}</option>
          {value.accountId && !view.accounts.some(account => account.id === value.accountId)
            && <option value={value.accountId}>{t("trading.overlay.unavailable", { id: value.accountId })}</option>}
          {view.accounts.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}
        </Select>
      </Field>
      {(["trades", "positions", "notes"] as const).map(key => <Checkbox key={key} label={t(`trading.overlay.${key}`)}
        checked={value[key]} onChange={event => onChange({ ...value, [key]: event.target.checked })} />)}
      <ChartNoteFilterFields value={value} onChange={onChange} />
      {(error ?? view.error) && <p className="chart-account-overlay-status" role="status">{error ?? view.error}</p>}
      <Button size="sm" variant="ghost" className="chart-account-overlay-close" onClick={() => { setOpen(false); trigger.current?.focus(); }}>{t("trading.close")}</Button>
    </Popover>
  </>;
}
