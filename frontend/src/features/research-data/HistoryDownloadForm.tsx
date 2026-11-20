import { BrowserReplayMarket } from "./BrowserReplayMarket.js";
import { useReplayVenues } from "./useReplayVenues.js";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Field, Input, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { LocalDatasetManifest } from "./researchDataApi.js";

interface Download {
  id: string;
  status: "downloading" | "complete" | "failed";
  rows: number;
  error?: string;
  error_code?: string;
  dataset?: LocalDatasetManifest;
}

/** A failure the browser host reported: a code for the message, its English detail as the text. */
function hostError(code: unknown, message: unknown, status?: number): Error {
  return Object.assign(new Error(typeof message === "string" && message ? message : t("browser.download.failed")), {
    ...(typeof code === "string" ? { code } : {}),
    ...(status === undefined ? {} : { status }),
  });
}

function utcInput(minutesAgo: number) {
  return new Date(Date.now() - minutesAgo * 60_000).toISOString().slice(0, 16);
}

export function HistoryDownloadForm({ onImported, initialSymbol = "BTCUSDT" }: {
  initialSymbol?: string;
  onImported(dataset: LocalDatasetManifest): Promise<void> | void;
}) {
  useLocale();
  const { venues, error: catalogError } = useReplayVenues(true);
  const [market, setMarket] = useState({exchange:"binance",marketType:"spot",symbol:initialSymbol});
  const [kind, setKind] = useState("bars");
  const trades = venues.find(v => v.id === market.exchange)?.trades.includes(market.marketType);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current) return;
    const fields = new FormData(event.currentTarget);
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    setMessage(t("browser.download.preparing"));
    try {
      const input = {
        kind, exchange:market.exchange, market_type:market.marketType,
        symbol: String(fields.get("symbol")).trim().toUpperCase(),
        start_ms: Date.parse(String(fields.get("start")) + "Z"),
        end_ms: Date.parse(String(fields.get("end")) + "Z"),
      };
      const path = "/api/v1/local/downloads";
      // A Worker may briefly be busy flushing another request to IndexedDB.
      // The selection is idempotent and polling only reads its current state.
      async function request(url: string, options: RequestInit = {}) {
        const init = { ...options, signal: controller.signal };
        const first = await fetch(url, init);
        if (first.status !== 503 && first.status !== 504) return first;
        await new Promise(resolve => setTimeout(resolve, 800));
        return fetch(url, init);
      }
      let response = await request(path, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      });
      while (!controller.signal.aborted) {
        const result = (await response.json()) as Download & { detail?: unknown };
        if (!response.ok) {
          const detail = result.detail;
          throw typeof detail === "object" && detail !== null
            ? hostError((detail as { code?: unknown }).code, (detail as { message?: unknown }).message, response.status)
            : hostError(undefined, typeof detail === "string" ? detail : `HTTP ${response.status}`, response.status);
        }
        const job: Download = result;
        if (job.status === "complete" && job.dataset) {
          setMessage(t("browser.download.saved", { name: job.dataset.name }));
          await onImported(job.dataset);
          return;
        }
        if (job.status !== "downloading") throw hostError(job.error_code, job.error);
        setMessage(t("browser.download.progress", { count: job.rows }));
        await new Promise(resolve => setTimeout(resolve, 800));
        if (controller.signal.aborted) return;
        response = await request(path + "/" + job.id);
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(describeError(reason, t("browser.download.failed")));
        setMessage("");
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <form className="research-import-form" onSubmit={submit} data-testid="history-download-form">
    <fieldset disabled={busy} className="research-import-grid">
      <BrowserReplayMarket venues={venues} market={market} busy={busy} onChange={next=>{
        setMarket(next);
        if(!venues.find(v=>v.id===next.exchange)?.trades.includes(next.marketType))setKind("bars");
      }} />
      {catalogError && <small>{catalogError}</small>}
      <Field label={t("browser.download.kind")}><Select name="kind" value={kind} onChange={e=>setKind(e.target.value)}>
        <option value="bars">{t("browser.download.bars")}</option>
        <option value="aggTrades" disabled={!trades}>{t("replay.source.agg")}</option>
      </Select></Field>
      <Field label={t("ux.startUtc")}><Input name="start" type="datetime-local" defaultValue={utcInput(30)} required /></Field>
      <Field label={t("browser.download.end")}><Input name="end" type="datetime-local" defaultValue={utcInput(5)} required /></Field>
    </fieldset>
    <Button variant="primary" type="submit" disabled={busy}>{t("browser.download.submit")}</Button>
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
  </form>;
}
