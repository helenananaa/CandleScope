import { useState } from "react";
import { t } from "../../i18n/index.js";
import { importLocalMarketTrades, type LocalDatasetManifest } from "./researchDataApi.js";

const TRADE_CSV_HEADER = "time,sequence,price,quantity,is_buyer_maker";

export function ResearchMarketTradeImportForm({ selected, onImported }: {
  selected: LocalDatasetManifest | null;
  onImported(dataset: LocalDatasetManifest): Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previous = selected?.market_trade_input;
  return (
    <details className="local-management-details">
      <summary>{t("local.import")} · {t("settings.exchange.channel.trade")}</summary>
      <form className="local-import-form" data-testid="research-market-trade-import"
        key={selected?.dataset_id} onSubmit={(event) => {
          event.preventDefault();
          if (submitting) return;
          const fields = new FormData(event.currentTarget);
          const file = fields.get("file");
          const timestampUnit = fields.get("timestampUnit");
          const tradeKind = fields.get("tradeKind");
          const start = Date.parse(String(fields.get("start")) + "Z");
          const end = Date.parse(String(fields.get("end")) + "Z");
          if (!(file instanceof File) || file.size === 0 || !Number.isFinite(start) || !(end > start)
            || (timestampUnit !== "s" && timestampUnit !== "ms")
            || (tradeKind !== "MARKET_TRADE" && tradeKind !== "MARKET_AGG_TRADE")) {
            setError(t("ux.invalidConditions"));
            return;
          }
          setError(null);
          setSubmitting(true);
          void importLocalMarketTrades({
            file, name: String(fields.get("name")).trim() || file.name.replace(/\.csv$/i, ""),
            symbol: String(fields.get("symbol")), baseAsset: String(fields.get("baseAsset")),
            quoteAsset: String(fields.get("quoteAsset")), timestampUnit, tradeKind,
            coverageStartMs: start, coverageEndMs: end,
            ...(previous && selected && fields.has("revision") ? { datasetId: selected.dataset_id } : {}),
          }).then(onImported).catch((reason: unknown) => {
            setError(reason instanceof Error ? reason.message : t("local.importFailed"));
          }).finally(() => setSubmitting(false));
        }}>
        <p>{t("local.marketTradeCoverage")}</p>
        <code>{TRADE_CSV_HEADER}</code>
        <fieldset className="local-import-grid" disabled={submitting}>
          <label>{t("local.chooseFile")}<input required name="file" type="file" accept=".csv,text/csv" /></label>
          <label>{t("local.datasetName")}<input name="name" maxLength={160} placeholder={t("local.namePh")} /></label>
          <label>{t("local.symbol")}<input required name="symbol" maxLength={80} defaultValue={previous ? selected?.symbol : ""} /></label>
          <label>{t("local.baseAsset")}<input required name="baseAsset" maxLength={32} defaultValue={previous ? selected?.instrument?.base_asset : ""} /></label>
          <label>{t("local.quoteAsset")}<input required name="quoteAsset" maxLength={32} defaultValue={previous ? selected?.instrument?.quote_asset : ""} /></label>
          <label>{t("local.timeFormat")}
            <select required name="timestampUnit" defaultValue="">
              <option value="">—</option><option value="s">{t("local.unixS")}</option><option value="ms">{t("local.unixMs")}</option>
            </select>
          </label>
          <label>{t("settings.exchange.channel.trade")}
            <select required name="tradeKind" defaultValue={previous?.kind ?? ""}>
              <option value="">—</option>
              <option value="MARKET_TRADE">{t("settings.exchange.channel.trade")}</option>
              <option value="MARKET_AGG_TRADE">{t("settings.exchange.channel.aggTrade")}</option>
            </select>
          </label>
          <label>{t("ux.startUtc")}<input required type="datetime-local" name="start" /></label>
          <label>{t("ux.endUtc")}<input required type="datetime-local" name="end" /></label>
        </fieldset>
        {previous && selected && <label>
          <input type="checkbox" name="revision" disabled={submitting} />{t("local.asRevision", { name: selected.name })}
        </label>}
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>{t(submitting ? "local.csvValidating" : "local.importBtn")}</button>
      </form>
    </details>
  );
}
