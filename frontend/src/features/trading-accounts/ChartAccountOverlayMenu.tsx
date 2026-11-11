import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import ChartNoteFilterFields from "../chart-workspace/ChartNoteFilterFields.js";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import { useTradingAccountsRuntime } from "./useTradingAccountsRuntime.js";
import "./chartAccountOverlay.css";

export default function ChartAccountOverlayMenu({ cellId, settings, error, onChange }: {
  cellId: string;
  settings: ChartAccountOverlaySettings | undefined;
  error: string | null;
  onChange(settings: ChartAccountOverlaySettings): void;
}) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);
  const { view } = useTradingAccountsRuntime(open);
  const value = normalizeChartAccountOverlay(settings);
  const title = t("trading.overlay.title", { n: cellId.slice("cell-".length) });
  useEffect(() => {
    if (!open) return undefined;
    const pointer = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus();
    };
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", close);
    return () => { document.removeEventListener("pointerdown", pointer); document.removeEventListener("keydown", key); window.removeEventListener("resize", close); };
  }, [open]);
  return <>
    <button type="button" ref={trigger} className="chart-account-overlay-trigger"
      aria-label={title} title={error ?? title} data-error={error ? "true" : undefined} aria-haspopup="dialog" aria-expanded={open}
      onDoubleClick={event => event.stopPropagation()} onClick={event => {
        const rect = event.currentTarget.getBoundingClientRect();
        setPosition({ top: Math.min(rect.bottom + 6, Math.max(8, window.innerHeight - 420)), left: Math.max(8, Math.min(rect.left, window.innerWidth - 288)) });
        setOpen(current => !current);
      }}>
      {t("trading.overlay.trigger")}
    </button>
    {open && createPortal(<div ref={panel} className="chart-account-overlay-menu" role="dialog" aria-label={title} style={{ ...position, maxHeight: `calc(100vh - ${position.top + 8}px)` }}>
      <strong>{title}</strong>
      <label>{t("trading.overlay.source")}
        <select value={value.accountId ?? ""} onChange={event => onChange({ ...value, accountId: event.target.value || null })}>
          <option value="">{t("trading.overlay.followPanel")}{view.selected ? ` · ${view.selected.name}` : ""}</option>
          {value.accountId && !view.accounts.some(account => account.id === value.accountId)
            && <option value={value.accountId}>{t("trading.overlay.unavailable", { id: value.accountId })}</option>}
          {view.accounts.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}
        </select>
      </label>
      {(["trades", "positions", "notes"] as const).map(key => <label key={key} className="chart-account-overlay-toggle">
        <input type="checkbox" checked={value[key]} onChange={event => onChange({ ...value, [key]: event.target.checked })} />
        {t(`trading.overlay.${key}`)}
      </label>)}
      <ChartNoteFilterFields value={value} onChange={onChange} />
      {(error ?? view.error) && <p role="status">{error ?? view.error}</p>}
      <button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }}>{t("trading.close")}</button>
    </div>, document.body)}
  </>;
}
