import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { formatUtcDateTimeInput, parseUtcDateTimeInput } from "../../utils/utcDateTimeInput.js";
import type { ChartTimeSeekResult } from "./chartTimeNavigation.js";
import "./chartTimeNavigation.css";

export default function ChartTimeNavigationDialog({ cellId, onClose, onSubmit }: {
  cellId: string; onClose(): void;
  onSubmit(timeMs: number): Promise<Array<{ cellId: string; result: ChartTimeSeekResult }>>;
}) {
  useLocale();
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const sequence = useRef(0);
  const [value, setValue] = useState(() => formatUtcDateTimeInput(Date.now()));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.showModal();
    return () => { sequence.current += 1; if (previous instanceof HTMLElement) previous.focus(); };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const timeMs = parseUtcDateTimeInput(value);
    if (timeMs === null || timeMs > Date.now()) { setMessage(t("chartTime.invalid")); return; }
    const ticket = ++sequence.current;
    setBusy(true); setMessage(t("chartTime.loading"));
    try {
      const outcomes = await onSubmit(timeMs);
      if (ticket !== sequence.current) return;
      const own = outcomes.find((item) => item.cellId === cellId)?.result;
      const status = own?.status ?? "unavailable";
      let text = status === "located" && own?.status === "located"
        ? t(own.exact ? "chartTime.located" : "chartTime.nearest", { time: formatUtcDateTimeInput(own.actualTimeMs).replace("T", " ") })
        : t(status === "empty" ? "chartTime.empty" : status === "invalid" ? "chartTime.invalid" : "chartTime.unavailable");
      if (outcomes.some((item) => item.cellId !== cellId && item.result.status !== "located")) text += ` ${t("chartTime.linkFailed")}`;
      setMessage(text);
    } catch { if (ticket === sequence.current) setMessage(t("chartTime.unavailable")); }
    finally { if (ticket === sequence.current) setBusy(false); }
  }
  return <dialog ref={dialog} className="chart-time-dialog" aria-labelledby={`${id}-title`} onCancel={onClose}>
    <form onSubmit={(event) => { void submit(event); }}>
      <h2 id={`${id}-title`}>{t("chartTime.title")}</h2>
      <label htmlFor={`${id}-input`}>{t("chartTime.input")}</label>
      <input id={`${id}-input`} type="datetime-local" step="1" required value={value}
        onChange={(event) => setValue(event.target.value)} autoFocus />
      <p>{t("chartTime.hint")}</p>
      <p role="status" aria-live="polite" aria-busy={busy}>{message}</p>
      <footer><button type="button" className="ui-control" onClick={onClose}>{t("chartTime.close")}</button>
        <button type="submit" className="ui-control">{t("chartTime.go")}</button></footer>
    </form>
  </dialog>;
}
