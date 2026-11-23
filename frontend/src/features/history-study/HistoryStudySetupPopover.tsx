import { useEffect, useState, type FormEvent, type RefObject } from "react";
import { Button, DateTimeInput, Field, InlineAlert, Popover, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { intervalTiles } from "../../utils/intervals.js";
import type { KlineBar, MarketSeries } from "../market-data/marketDataTypes.js";
import type { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import type { SavedStudySummary } from "./historyStudyTypes.js";
import { formatDateTime } from "../trading-accounts/tradingFormat.js";
import "./historyStudySetup.css";

type RangeKey = "start" | "end" | "cursor";
const RANGE_LABELS: Record<RangeKey, "study.start" | "study.end" | "study.cursor"> = { start: "study.start", end: "study.end", cursor: "study.cursor" };

/** Default range: the closed candles on screen, with the replay time 100 candles in. */
function initialRange(series: MarketSeries, bars: readonly KlineBar[]): Record<RangeKey, number | null> {
  const timeline = createIntervalTimeline(series.interval);
  const closed = bars.filter(row => row.is_closed !== false && (timeline?.next(row.time) ?? Infinity) * 1000 <= Date.now());
  const start = Number(closed[0]?.time ?? timeline?.previous(timeline.floor(Date.now() / 1000)) ?? 0) * 1000;
  const end = (timeline?.next(closed.at(-1)?.time ?? start / 1000) ?? start / 1000) * 1000;
  const cursor = (timeline?.next(closed[Math.min(99, closed.length - 1)]?.time ?? start / 1000) ?? start / 1000) * 1000;
  // Whole seconds, as the range is saved and shown to the second.
  const second = (ms: number) => Math.floor(ms / 1000) * 1000;
  return { start: second(start), end: second(end), cursor: second(cursor) };
}

/** Sets up a historical study for one chart. Anchored to the top-bar button that opens it. */
export default function HistoryStudySetupPopover({ anchorRef, owner, manager, onSelect, series, bars, busy, error, onCapture, onClose }: {
  anchorRef: RefObject<HTMLElement | null>;
  owner: string; manager: HistoryStudyDataManager;
  onSelect(id: string, action: "activate" | "remove"): Promise<boolean>;
  series: MarketSeries; bars: readonly KlineBar[]; busy: boolean; error: unknown;
  onCapture(series: MarketSeries, startMs: number, endMs: number, cursorMs: number, sourceInterval?: string): Promise<boolean>;
  onClose(): void;
}) {
  useLocale();
  const [values, setValues] = useState(() => initialRange(series, bars));
  const [invalid, setInvalid] = useState(false);
  const [sourceInterval, setSourceInterval] = useState(series.interval);
  const [saved, setSaved] = useState<SavedStudySummary[]>([]);
  const [remove, setRemove] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [listError, setListError] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setListError(false);
    manager.saved(owner, controller.signal).then(result => { if (!controller.signal.aborted) setSaved(result.studies); })
      .catch(() => { if (!controller.signal.aborted) setListError(true); });
    return () => controller.abort();
  }, [manager, owner, refresh]);
  // Saving cannot be abandoned half way, so the popover stays open while it runs.
  const close = () => { if (!busy) onClose(); };
  async function submit(event: FormEvent) {
    event.preventDefault();
    const { start, end, cursor } = values;
    if (start === null || end === null || cursor === null || start >= end || end > Date.now() || cursor < start || cursor > end) {
      setInvalid(true); return;
    }
    setInvalid(false);
    if (await onCapture(series, start, end, cursor, sourceInterval)) onClose();
  }
  const finer = ["1m", "5m", "1h", "1d"].filter(candidate => intervalTiles(candidate, series.interval) && !intervalTiles(series.interval, candidate));
  return (
    <Popover open onClose={close} anchorRef={anchorRef} placement="bottom-end" label={t("study.title")} className="history-study-setup">
      <form onSubmit={event => { void submit(event); }}>
        <header className="history-study-setup-head">
          <h2>{t("study.title")}<span>{series.symbol} · {series.interval}</span></h2>
          <p>{t("study.scope")}</p>
        </header>
        {saved.length > 0 && (
          <section className="history-study-setup-library" aria-label={t("study.library")}>
            <h3>{t("study.library")}</h3>
            <ul>{saved.map(study => (
              <li key={study.id}>
                <span>
                  <strong>{study.series.symbol} · {study.series.interval}</strong>
                  <small>{formatDateTime(study.firstMs)} – {formatDateTime(study.lastMs)}</small>
                </span>
                <Button size="sm" disabled={busy} onClick={() => { void onSelect(study.id, "activate").then(ok => { if (ok) onClose(); }); }}>{t("study.resume")}</Button>
                <Button size="sm" variant={remove === study.id ? "danger" : "ghost"} disabled={busy} onClick={() => {
                  if (remove !== study.id) { setRemove(study.id); return; }
                  void onSelect(study.id, "remove").then(ok => { if (ok) { setRemove(null); setRefresh(n => n + 1); } });
                }}>{t(remove === study.id ? "study.removeConfirm" : "study.remove")}</Button>
              </li>
            ))}</ul>
          </section>
        )}
        {listError && <InlineAlert tone="danger">{t("study.error")}</InlineAlert>}
        <div className="history-study-setup-fields">
          <Field label={t("study.sourceInterval")} hint={t("study.fineHint")}>
            <Select size="sm" value={sourceInterval} disabled={busy} onChange={event => setSourceInterval(event.target.value)}>
              <option value={series.interval}>{series.interval}</option>
              {finer.map(candidate => <option key={candidate} value={candidate}>{candidate}</option>)}
            </Select>
          </Field>
          {(["start", "end", "cursor"] as const).map(key => (
            <Field key={key} label={t(RANGE_LABELS[key])} required>
              <DateTimeInput size="sm" seconds zoneLabel={false} value={values[key]} disabled={busy}
                onChange={next => setValues(current => ({ ...current, [key]: next }))} />
            </Field>
          ))}
          <p className="history-study-setup-note">{t("study.range")}</p>
        </div>
        {(invalid || !!error) && <InlineAlert tone="danger">{t(invalid ? "study.invalidRange" : "study.error")}</InlineAlert>}
        <footer className="history-study-setup-actions">
          <Button size="sm" variant="ghost" disabled={busy} onClick={close}>{t("study.close")}</Button>
          <Button size="sm" variant="primary" type="submit" disabled={busy}>{t(busy ? "study.saving" : "study.capture")}</Button>
        </footer>
      </form>
    </Popover>
  );
}
