import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Field, Input, Select } from "../../components/ui/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { LocalDatasetManifest } from "./researchDataApi.js";

interface Download {
  id: string;
  status: "downloading" | "complete" | "failed";
  rows: number;
  error?: string;
  dataset?: LocalDatasetManifest;
}

function utcInput(minutesAgo: number) {
  return new Date(Date.now() - minutesAgo * 60_000).toISOString().slice(0, 16);
}

export function HistoryDownloadForm({ onImported, initialSymbol = "BTCUSDT" }: {
  initialSymbol?: string;
  onImported(dataset: LocalDatasetManifest): Promise<void> | void;
}) {
  const zh = useLocale().startsWith("zh");
  const label = (chinese: string, english: string) => zh ? chinese : english;
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
    setMessage(label("正在准备行情…", "Preparing market data…"));
    try {
      const input = {
        kind: fields.get("kind"),
        symbol: String(fields.get("symbol")).trim().toUpperCase(),
        start_ms: Date.parse(fields.get("start") + "Z"),
        end_ms: Date.parse(fields.get("end") + "Z"),
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
        const result = await response.json();
        if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail ?? result));
        const job = result as Download;
        if (job.status === "complete" && job.dataset) {
          setMessage(label("已保存到资料库", "Saved to the library") + " · " + job.dataset.name);
          await onImported(job.dataset);
          return;
        }
        if (job.status !== "downloading") throw Error(job.error || label("下载失败", "Download failed"));
        setMessage(label("正在下载", "Downloading") + " · " + job.rows);
        await new Promise(resolve => setTimeout(resolve, 800));
        if (controller.signal.aborted) return;
        response = await request(path + "/" + job.id);
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : String(reason));
        setMessage("");
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <form className="research-import-form" onSubmit={submit} data-testid="history-download-form">
    <p>Binance · {label("现货", "Spot")}</p>
    <fieldset disabled={busy} className="research-import-grid">
      <Field label={label("交易对", "Symbol")}><Input name="symbol" defaultValue={initialSymbol} required pattern="[a-zA-Z0-9]{2,40}" /></Field>
      <Field label={label("行情类型", "Data")}><Select name="kind" defaultValue="bars">
        <option value="bars">{label("1 分钟 K 线", "1-minute bars")}</option>
        <option value="aggTrades">{label("聚合逐笔成交", "Aggregate trades")}</option>
      </Select></Field>
      <Field label={label("开始（UTC）", "Start (UTC)")}><Input name="start" type="datetime-local" defaultValue={utcInput(30)} required /></Field>
      <Field label={label("结束（UTC，不含）", "End (UTC, exclusive)")}><Input name="end" type="datetime-local" defaultValue={utcInput(5)} required /></Field>
    </fieldset>
    <Button variant="primary" type="submit" disabled={busy}>{label("下载并导入", "Download and import")}</Button>
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
  </form>;
}
