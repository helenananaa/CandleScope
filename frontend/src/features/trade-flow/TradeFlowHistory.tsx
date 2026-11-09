import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui/Button.js";
import { getNumberLocale, t } from "../../i18n/index.js";
import type { MessageKey } from "../../i18n/index.js";
import { PreparationApiError } from "../data-preparation/api.js";
import type { PreparationJob } from "../data-preparation/api.js";
import { fillTradeHistory, readTradeHistory, supportsTradeHistoryArchive, TRADE_HISTORY_MINUTES } from "./tradeFlowHistoryApi.js";
import type { TradeHistoryPage } from "./tradeFlowHistoryApi.js";
import type { TradeFlowIdentity } from "./tradeFlowTypes.js";

const HOUR_MS = 3_600_000;

function archiveMessage(error: unknown): MessageKey {
  if (!(error instanceof PreparationApiError)) return "trade.history.error";
  switch (error.code) {
    case "TRADE_DAY_UNAVAILABLE": return "trade.history.unavailable";
    case "TRADE_DAY_UNPUBLISHED": return "trade.history.unpublished";
    case "TRADE_ARCHIVE_UNAVAILABLE":
    case "TRADE_ARCHIVE_READ_ONLY":
    case "PREPARATION_UNAVAILABLE": return "trade.history.archiveDisabled";
    default: return "trade.history.error";
  }
}

function TradeHistoryHour({ identity, startMs, canDownload }: {
  identity: TradeFlowIdentity;
  startMs: number;
  canDownload: boolean;
}) {
  const [page, setPage] = useState<TradeHistoryPage | null>(null);
  const [busy, setBusy] = useState<"reading" | "preparing" | null>("reading");
  const [job, setJob] = useState<PreparationJob | null>(null);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [archiveOutcome, setArchiveOutcome] = useState<MessageKey | null>(null);
  const observer = useRef<AbortController | null>(null);
  const submissionKey = useRef<string | null>(null);

  const load = useCallback(async (download = false) => {
    if (observer.current) return;
    const controller = new AbortController();
    const { signal } = controller;
    observer.current = controller;
    setBusy(download ? "preparing" : "reading");
    setNotice(null);
    setJob(null);
    try {
      if (download) {
        submissionKey.current ??= crypto.randomUUID();
        const outcome = await fillTradeHistory(identity, startMs, submissionKey.current, (progress) => {
          if (!signal.aborted) setJob(progress);
        }, signal);
        if (signal.aborted) return;
        if (outcome === "unavailable") {
          setArchiveOutcome("trade.history.unpublished");
          return;
        }
        setArchiveOutcome("trade.history.archiveChecked");
        setBusy("reading");
        setJob(null);
      }
      const next = await readTradeHistory(identity, startMs, signal);
      if (!signal.aborted) setPage(next);
    } catch (error) {
      if (!signal.aborted) {
        const message = archiveMessage(error);
        if (message === "trade.history.unavailable" || message === "trade.history.unpublished") {
          setArchiveOutcome(message);
        } else {
          setNotice(message);
        }
      }
    } finally {
      if (observer.current === controller) observer.current = null;
      if (!signal.aborted) setBusy(null);
    }
  }, [identity, startMs]);
  useEffect(() => {
    void load();
    return () => {
      observer.current?.abort();
      observer.current = null;
    };
  }, [load]);

  const rows = page?.data ?? [];
  const verified = rows.filter((row) => row.is_complete && row.is_final).length;
  const complete = page?.complete === true && page.has_more === false;
  const allowDownload = page && !complete && verified < TRADE_HISTORY_MINUTES && canDownload && !archiveOutcome;
  const formatter = new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 8 });
  return (
    <>
      <div className="tf-history-actions">
        <Button size="sm" disabled={busy !== null} onClick={() => void load()}>{t("trade.history.read")}</Button>
        {allowDownload && <Button size="sm" disabled={busy !== null} onClick={() => void load(true)}>
          {t("trade.history.download")}
        </Button>}
      </div>
      <div className="tf-history-status" role="status">
        {busy === "reading" && <div>{t("trade.history.reading")}</div>}
        {busy === "preparing" && <div>{job?.waiting
          ? t("preparation.rateLimited", { time: new Date(job.waiting.retry_at_ms).toISOString() })
          : t("trade.history.preparing", { done: job?.completed ?? 0, total: job?.total ?? 1 })}</div>}
        {notice && <div>{t(notice)}</div>}
        {archiveOutcome && <div>{t(archiveOutcome)}</div>}
        {page && <div>{t("trade.history.rows", {
          count: rows.length, verified, quiet: page.coverage?.verified_empty_minutes ?? 0,
        })}</div>}
        {page && <div>{t(complete ? "trade.history.complete" : "trade.history.unverified")}</div>}
      </div>
      {rows.length > 0 && <table className="tf-history-table">
        <thead><tr>
          <th>{t("trade.history.utc")}</th><th>{t("trade.history.aggregates")}</th>
          <th>{t("trade.delta")}</th><th>{t("trade.history.quality")}</th>
        </tr></thead>
        <tbody>{rows.map((row) => {
          const utc = new Date(row.bucket_start_ms).toISOString();
          return <tr key={row.bucket_start_ms}>
            <td><time dateTime={utc}>{utc.slice(11, 16)}</time></td>
            <td>{formatter.format(row.agg_trade_count)}</td>
            <td>{formatter.format(row.volume_delta_base)}</td>
            <td>{t(!row.is_final ? "trade.history.forming"
              : row.is_complete ? "trade.history.verified" : "trade.history.observed")}</td>
          </tr>;
        })}</tbody>
      </table>}
    </>
  );
}

export function TradeFlowHistory({ identity }: { identity: TradeFlowIdentity }) {
  const [day, setDay] = useState(() => new Date(Date.now() - 24 * HOUR_MS).toISOString().slice(0, 10));
  const [hour, setHour] = useState("00");
  const now = Date.now();
  const today = new Date(now).toISOString().slice(0, 10);
  const startMs = Date.parse(`${day}T${hour}:00:00Z`);
  const archiveSupported = supportsTradeHistoryArchive(identity);
  const valid = day.length === 10 && Number.isFinite(startMs) && startMs >= 0 && startMs <= now;
  return (
    <div className="tf-history">
      <div className="tf-history-actions">
        <label>{t("trade.history.date")} <input type="date" value={day} max={today}
          onChange={(event) => setDay(event.target.value)} /></label>
        <label>{t("trade.history.hour")} <select value={hour} onChange={(event) => setHour(event.target.value)}>
          {Array.from({ length: 24 }, (_, index) => String(index).padStart(2, "0")).map((value) => (
            <option key={value} value={value}>{value}:00</option>
          ))}
        </select></label>
      </div>
      {!archiveSupported && <div className="tf-history-status">{t("trade.history.localOnly")}</div>}
      {archiveSupported && day === today && <div className="tf-history-status">{t("trade.history.unpublished")}</div>}
      {valid ? <TradeHistoryHour key={startMs} identity={identity} startMs={startMs}
        canDownload={archiveSupported && day < today} /> : <div className="tf-history-status">{t("trade.history.invalid")}</div>}
    </div>
  );
}
