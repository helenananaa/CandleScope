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
import {
  CHART_TIME_AMOUNT_SECONDS,
  CHART_TIME_RELATIVE_JUMPS,
  type ChartTimeOutcomes,
  type ChartTimeShortcuts,
} from "./chartTimeShortcuts.js";
import "./chartTimeNavigation.css";

export default function ChartTimeNavigationDialog({ cellId, onClose, onSubmit, initialTimeMs, hint, shortcuts = null, hideDates = false }: {
  cellId: string; onClose(): void;
  initialTimeMs?: number; hint?: string;
  /** Relative jumps and Latest / First loaded bar / Last viewed (PL-8), where the chart offers them. */
  shortcuts?: ChartTimeShortcuts | null;
  /**
   * A session that hides dates (blind replay training): no date field, no
   * zone, no time in any message or tooltip. Only the shortcuts remain.
   */
  hideDates?: boolean;
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
    if (hideDates) return;
    const parsed = parseZonedDateTimeInput(value, zone);
    if (parsed === null || parsed.timeMs > Date.now()) { setMessage(t(mode === "local" ? "chartTime.invalidZoned" : "chartTime.invalid")); return; }
    const timeMs = parsed.timeMs;
    // Daylight saving: say which instant a skipped or repeated wall time became.
    const resolved = parsed.resolution === "gap"
      ? `${t("chartTime.gap", { zone, time: chartTimeLabel(timeMs, zone) })} `
      : parsed.resolution === "overlap" ? `${t("chartTime.overlap", { zone, time: chartTimeLabel(timeMs, zone) })} ` : "";
    await run(() => onSubmit(timeMs), resolved);
  }
  /** One seek at a time; a newer one supersedes the message of an older one. */
  async function run(start: () => Promise<ChartTimeOutcomes> | null, prefix = "", syncInput = false) {
    const pending = start();
    if (pending === null) { setMessage(t("chartTime.unavailable")); return; }
    const ticket = ++sequence.current;
    setBusy(true); setMessage(t(hideDates ? "chartTime.moving" : "chartTime.loading"));
    try {
      const outcomes = await pending;
      if (ticket !== sequence.current) return;
      const own = outcomes.find((item) => item.cellId === cellId)?.result;
      const status = own?.status ?? "unavailable";
      let text = status === "located" && own?.status === "located"
        ? hideDates ? t(own.exact ? "chartTime.moved" : "chartTime.movedNearest")
        : mode === "local"
          ? t(own.exact ? "chartTime.locatedZoned" : "chartTime.nearestZoned", { time: chartTimeLabel(own.actualTimeMs, zone) })
          : t(own.exact ? "chartTime.located" : "chartTime.nearest", { time: formatUtcDateTimeInput(own.actualTimeMs).replace("T", " ") })
        : t(status === "empty" ? "chartTime.empty" : status === "invalid" ? "chartTime.invalid" : "chartTime.unavailable");
      if (outcomes.some((item) => item.cellId !== cellId && item.result.status !== "located")) text += ` ${t("chartTime.linkFailed")}`;
      setMessage(prefix + text);
      // A shortcut fills the field with where it went, so it can be adjusted from there.
      if (syncInput && own?.status === "located") setValue(formatZonedDateTimeInput(own.actualTimeMs, zone));
    } catch { if (ticket === sequence.current) setMessage(t("chartTime.unavailable")); }
    finally { if (ticket === sequence.current) setBusy(false); }
  }
  async function latest(source: ChartTimeShortcuts) {
    const ticket = ++sequence.current;
    setBusy(true); setMessage(t(hideDates ? "chartTime.moving" : "chartTime.loading"));
    const edge = await source.latest().catch(() => null);
    if (ticket !== sequence.current) return;
    setBusy(false);
    if (edge !== null) setValue(formatZonedDateTimeInput(edge, zone));
    setMessage(t(edge !== null ? "chartTime.latestDone" : "chartTime.unavailable"));
  }
  return <dialog ref={dialog} className="chart-time-dialog" aria-labelledby={`${id}-title`} onCancel={onClose}>
    <form onSubmit={(event) => { void submit(event); }}>
      <h2 id={`${id}-title`}>{t(hideDates ? "chartTime.hiddenTitle" : "chartTime.title")}</h2>
      {!hideDates && <>
        <SegmentedControl label={t("chartTime.zone")} value={mode} onChange={changeMode} size="sm" fullWidth
          options={[{ value: "utc", label: t("chartTime.zoneUtc") }, { value: "local", label: t("chartTime.zoneLocal", { zone: localZone }) }]} />
        <label htmlFor={`${id}-input`}>{mode === "local" ? t("chartTime.inputZoned", { zone: localZone }) : t("chartTime.input")}</label>
        <input id={`${id}-input`} type="datetime-local" step="1" required value={value}
          onChange={(event) => setValue(event.target.value)} autoFocus />
      </>}
      <p>{hint ?? t("chartTime.hint")}</p>
      {hideDates && <p>{t("chartTime.hiddenHint")}</p>}
      {shortcuts && <>
        <div className="chart-time-shortcuts" role="group" aria-label={t("chartTime.move")}>
          <span>{t("chartTime.move")}</span>
          {CHART_TIME_RELATIVE_JUMPS.map(({ amount, direction }) => {
            const amountLabel = t(amount === "hour" ? "chartTime.amount.hour" : amount === "day" ? "chartTime.amount.day" : "chartTime.amount.week");
            return <Button key={`${direction}${amount}`} size="sm" variant="secondary"
              aria-label={t(direction < 0 ? "chartTime.back" : "chartTime.forward", { amount: amountLabel })}
              onClick={() => { void run(() => shortcuts.jumpBy(direction * CHART_TIME_AMOUNT_SECONDS[amount]), "", true); }}>
              {`${direction < 0 ? "\u2212" : "+"}${amountLabel}`}
            </Button>;
          })}
        </div>
        <div className="chart-time-shortcuts" role="group" aria-label={t("chartTime.jumpTo")}>
          <span>{t("chartTime.jumpTo")}</span>
          <Button size="sm" variant="secondary" onClick={() => { void latest(shortcuts); }}>{t("chartTime.latest")}</Button>
          <Button size="sm" variant="secondary" onClick={() => {
            sequence.current += 1; setBusy(false);
            const first = shortcuts.firstLoaded();
            if (first !== null) setValue(formatZonedDateTimeInput(first, zone));
            setMessage(first === null ? t("chartTime.unavailable")
              : hideDates ? t("chartTime.firstLoadedHidden") : t("chartTime.firstLoadedDone", { time: chartTimeLabel(first, zone) }));
          }}>{t("chartTime.firstLoaded")}</Button>
          <Button size="sm" variant="secondary" disabled={shortcuts.lastViewedMs === null}
            title={shortcuts.lastViewedMs === null ? t("chartTime.noLastViewed")
              : hideDates ? undefined : t("chartTime.lastViewedAt", { time: chartTimeLabel(shortcuts.lastViewedMs, zone) })}
            onClick={() => { void run(() => shortcuts.jumpLastViewed(), "", true); }}>{t("chartTime.lastViewed")}</Button>
        </div>
      </>}
      <p role="status" aria-live="polite" aria-busy={busy}>{message}</p>
      <footer><Button variant="ghost" onClick={onClose}>{t("chartTime.close")}</Button>
        {!hideDates && <Button type="submit" variant="primary">{t("chartTime.go")}</Button>}</footer>
    </form>
  </dialog>;
}
