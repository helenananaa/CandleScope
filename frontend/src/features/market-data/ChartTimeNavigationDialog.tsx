import { Button } from "../../components/ui/Button.js";
import { SegmentedControl } from "../../components/ui/Choice.js";
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { formatUtcDateTimeInput } from "../../utils/utcDateTimeInput.js";
import { formatZonedDateTimeInput, localTimeZone, parseZonedDateTimeInput } from "../../utils/zonedDateTimeInput.js";
import {
  chartTimeLabel,
  chartTimeZone,
  readChartTimeZoneMode,
  writeChartTimeZoneMode,
  type ChartTimeZoneMode,
} from "./chartTimeZoneMode.js";
import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";
import "./chartTimeNavigation.css";

export default function ChartTimeNavigationDialog({ cellId, onClose, onSubmit, initialTimeMs, hint }: {
  cellId: string; onClose(): void;
  initialTimeMs?: number; hint?: string;
  onSubmit(timeMs: number): Promise<Array<{ cellId: string; result: ChartTimeSeekResult }>>;
}) {
  useLocale();
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const sequence = useRef(0);
  const localZone = useMemo(localTimeZone, []);
  const [mode, setMode] = useState<ChartTimeZoneMode>(readChartTimeZoneMode);
  const zone = chartTimeZone(mode, localZone);
  const [value, setValue] = useState(() => formatZonedDateTimeInput(initialTimeMs ?? Date.now(), zone));
  // Switching zones keeps the same instant and rewrites the wall time.
  const changeMode = (next: ChartTimeZoneMode) => {
    const nextZone = chartTimeZone(next, localZone);
    const current = parseZonedDateTimeInput(value, zone);
    if (current) setValue(formatZonedDateTimeInput(current.timeMs, nextZone));
    setMode(next);
    writeChartTimeZoneMode(next);
  };
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  // The opener, captured once: StrictMode runs the effect again after focus moved into the dialog.
  const opener = useRef<Element | null | undefined>(undefined);
  useEffect(() => {
    if (opener.current === undefined) opener.current = document.activeElement;
    const previous = opener.current;
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    // Focus goes back to the opener once the dialog has left the page (a StrictMode re-run keeps
    // it), unless something else took focus meanwhile.
    return () => {
      sequence.current += 1;
      if (!(previous instanceof HTMLElement)) return;
      setTimeout(() => {
        if (element?.isConnected) return;
        const now = document.activeElement;
        if (previous.isConnected && (!now || now === document.body)) previous.focus({ preventScroll: true });
      }, 0);
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseZonedDateTimeInput(value, zone);
    if (parsed === null || parsed.timeMs > Date.now()) { setMessage(t(mode === "local" ? "chartTime.invalidZoned" : "chartTime.invalid")); return; }
    const timeMs = parsed.timeMs;
    // Daylight saving: say which instant a skipped or repeated wall time became.
    const resolved = parsed.resolution === "gap"
      ? `${t("chartTime.gap", { zone, time: chartTimeLabel(timeMs, zone) })} `
      : parsed.resolution === "overlap" ? `${t("chartTime.overlap", { zone, time: chartTimeLabel(timeMs, zone) })} ` : "";
    const ticket = ++sequence.current;
    setBusy(true); setMessage(t("chartTime.loading"));
    try {
      const outcomes = await onSubmit(timeMs);
      if (ticket !== sequence.current) return;
      const own = outcomes.find((item) => item.cellId === cellId)?.result;
      const status = own?.status ?? "unavailable";
      let text = status === "located" && own?.status === "located"
        ? mode === "local"
          ? t(own.exact ? "chartTime.locatedZoned" : "chartTime.nearestZoned", { time: chartTimeLabel(own.actualTimeMs, zone) })
          : t(own.exact ? "chartTime.located" : "chartTime.nearest", { time: formatUtcDateTimeInput(own.actualTimeMs).replace("T", " ") })
        : t(status === "empty" ? "chartTime.empty" : status === "invalid" ? "chartTime.invalid" : "chartTime.unavailable");
      if (outcomes.some((item) => item.cellId !== cellId && item.result.status !== "located")) text += ` ${t("chartTime.linkFailed")}`;
      setMessage(resolved + text);
    } catch { if (ticket === sequence.current) setMessage(t("chartTime.unavailable")); }
    finally { if (ticket === sequence.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="chart-time-dialog" aria-labelledby={`${id}-title`} onCancel={onClose}>
    <form onSubmit={(event) => { void submit(event); }}>
      <h2 id={`${id}-title`}>{t("chartTime.title")}</h2>
      <SegmentedControl label={t("chartTime.zone")} value={mode} onChange={changeMode} size="sm" fullWidth
        options={[{ value: "utc", label: t("chartTime.zoneUtc") }, { value: "local", label: t("chartTime.zoneLocal", { zone: localZone }) }]} />
      <label htmlFor={`${id}-input`}>{mode === "local" ? t("chartTime.inputZoned", { zone: localZone }) : t("chartTime.input")}</label>
      <input id={`${id}-input`} type="datetime-local" step="1" required value={value}
        onChange={(event) => setValue(event.target.value)} autoFocus />
      <p>{hint ?? t("chartTime.hint")}</p>
      <p role="status" aria-live="polite" aria-busy={busy}>{message}</p>
      <footer><Button variant="ghost" onClick={onClose}>{t("chartTime.close")}</Button>
        <Button type="submit" variant="primary">{t("chartTime.go")}</Button></footer>
    </form>
  </dialog>;
}
