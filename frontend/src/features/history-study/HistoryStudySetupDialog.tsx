import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { intervalTiles } from "../../utils/intervals.js";
import { formatUtcDateTimeInput, parseUtcDateTimeInput } from "../../utils/utcDateTimeInput.js";
import type { KlineBar, MarketSeries } from "../market-data/marketDataTypes.js";
import type { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import type { SavedStudySummary } from "./historyStudyTypes.js";
import { formatDateTime } from "../trading-accounts/tradingFormat.js";
import "../market-data/chartTimeNavigation.css";

export default function HistoryStudySetupDialog({ owner, manager, onSelect, series, bars, busy, error, onCapture, onClose }: {
  owner: string; manager: HistoryStudyDataManager;
  onSelect(id: string, action: "activate" | "remove"): Promise<boolean>;
  series: MarketSeries; bars: readonly KlineBar[]; busy: boolean; error: unknown;
  onCapture(series: MarketSeries, startMs: number, endMs: number, cursorMs: number, sourceInterval?: string): Promise<boolean>;
  onClose(): void;
}) {
  useLocale();
  const dialog = useRef<HTMLDialogElement>(null);
  const [values, setValues] = useState(() => {
    const timeline = createIntervalTimeline(series.interval);
    const closed = bars.filter(row => row.is_closed !== false && (timeline?.next(row.time) ?? Infinity) * 1000 <= Date.now());
    const start = Number(closed[0]?.time ?? timeline?.previous(timeline.floor(Date.now() / 1000)) ?? 0) * 1000;
    const end = (timeline?.next(closed.at(-1)?.time ?? start / 1000) ?? start / 1000) * 1000;
    const cursor = (timeline?.next(closed[Math.min(99, closed.length - 1)]?.time ?? start / 1000) ?? start / 1000) * 1000;
    return { start: formatUtcDateTimeInput(start), end: formatUtcDateTimeInput(end), cursor: formatUtcDateTimeInput(cursor) };
  });
  const [invalid, setInvalid] = useState(false);
  const [sourceInterval, setSourceInterval] = useState(series.interval);
  const sourceId = useId();
  const [saved, setSaved] = useState<SavedStudySummary[]>([]);
  const [remove, setRemove] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [listError, setListError] = useState(false);
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    const controller = new AbortController(); setListError(false);
    manager.saved(owner, controller.signal).then(result => { if (!controller.signal.aborted) setSaved(result.studies); })
      .catch(() => { if (!controller.signal.aborted) setListError(true); });
    return () => controller.abort();
  }, [manager, owner, refresh]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const start = parseUtcDateTimeInput(values.start), end = parseUtcDateTimeInput(values.end), cursor = parseUtcDateTimeInput(values.cursor);
    if (start === null || end === null || cursor === null || start >= end || end > Date.now() || cursor < start || cursor > end) {
      setInvalid(true); return;
    }
    setInvalid(false);
    if (await onCapture(series, start, end, cursor, sourceInterval)) onClose();
  }
  return <dialog ref={dialog} className="chart-time-dialog" aria-label={t("study.title")}
    onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <form onSubmit={event => { void submit(event); }}>
      <h2>{t("study.title")} · {series.symbol} {series.interval}</h2>
      {saved.length > 0 && <section aria-label={t("study.library")}><h3>{t("study.library")}</h3>
        <ul>{saved.map(study => <li key={study.id}>
          <span>{study.series.symbol} {study.series.interval} · {formatDateTime(study.firstMs)} – {formatDateTime(study.lastMs)}</span>
          <button type="button" disabled={busy} onClick={() => { void onSelect(study.id, "activate").then(ok => { if (ok) onClose(); }); }}>{t("study.resume")}</button>
          <button type="button" disabled={busy} onClick={() => {
            if (remove !== study.id) { setRemove(study.id); return; }
            void onSelect(study.id, "remove").then(ok => { if (ok) { setRemove(null); setRefresh(n => n + 1); } });
          }}>{t(remove === study.id ? "study.removeConfirm" : "study.remove")}</button>
        </li>)}</ul>
      </section>}
      {listError && <p role="alert">{t("study.error")}</p>}
      <p>{t("study.scope")}</p><p>{t("study.range")}</p>
      <label htmlFor={sourceId}>{t("study.sourceInterval")}</label><select id={sourceId} value={sourceInterval} disabled={busy}
        onChange={event => setSourceInterval(event.target.value)}>
        <option value={series.interval}>{series.interval}</option>
        {["1m", "5m", "1h", "1d"].filter(candidate => intervalTiles(candidate, series.interval)
          && !intervalTiles(series.interval, candidate)).map(candidate => <option key={candidate} value={candidate}>{candidate}</option>)}
      </select>
      <p>{t("study.fineHint")}</p>
      {(["start", "end", "cursor"] as const).map(key => <label key={key}>
        {t(key === "start" ? "study.start" : key === "end" ? "study.end" : "study.cursor")}
        <input type="datetime-local" step="1" required value={values[key]} disabled={busy}
          onChange={event => setValues(current => ({ ...current, [key]: event.target.value }))} />
      </label>)}
      {(invalid || !!error) && <p role="alert">{t(invalid ? "study.invalidRange" : "study.error")}</p>}
      <div className="chart-time-actions"><button type="button" disabled={busy} onClick={onClose}>{t("study.close")}</button>
        <button type="submit" disabled={busy}>{t(busy ? "study.saving" : "study.capture")}</button></div>
    </form>
  </dialog>;
}
