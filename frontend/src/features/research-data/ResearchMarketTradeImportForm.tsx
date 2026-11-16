import { useState } from "react";
import { Button, Checkbox, Disclosure, Field, FileDrop, InlineAlert, Input, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { importLocalMarketTrades, type LocalDatasetManifest } from "./researchDataApi.js";

const TRADE_CSV_HEADER = "time,sequence,price,quantity,is_buyer_maker";

export function ResearchMarketTradeImportForm({ selected, onImported }: {
  selected: LocalDatasetManifest | null;
  onImported(dataset: LocalDatasetManifest): Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const previous = selected?.market_trade_input;
  return (
    <Disclosure className="research-trade-import" summary={`${t("local.import")} · ${t("settings.exchange.channel.trade")}`}>
      <form className="research-import-form" data-testid="research-market-trade-import"
        key={selected?.dataset_id} onSubmit={(event) => {
          event.preventDefault();
          if (submitting) return;
          const fields = new FormData(event.currentTarget);
          const timestampUnit = fields.get("timestampUnit");
          const tradeKind = fields.get("tradeKind");
          const start = Date.parse(String(fields.get("start")) + "Z");
          const end = Date.parse(String(fields.get("end")) + "Z");
          if (file === null || file.size === 0 || !Number.isFinite(start) || !(end > start)
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
        <p className="research-import-note">{t("local.marketTradeCoverage")}</p>
        <code className="research-import-columns">{TRADE_CSV_HEADER}</code>
        <FileDrop compact label={file?.name ?? t("local.chooseFile")} hint=".csv" accept=".csv,text/csv" disabled={submitting}
          onFiles={([selectedFile]) => setFile(selectedFile ?? null)} />
        <fieldset className="research-import-grid" disabled={submitting}>
          <Field label={t("local.datasetName")}><Input size="sm" name="name" maxLength={160} placeholder={t("local.namePh")} /></Field>
          <Field label={t("local.symbol")} required><Input size="sm" required name="symbol" maxLength={80} defaultValue={previous ? selected?.symbol : ""} /></Field>
          <Field label={t("local.baseAsset")} required><Input size="sm" required name="baseAsset" maxLength={32} defaultValue={previous ? selected?.instrument?.base_asset : ""} /></Field>
          <Field label={t("local.quoteAsset")} required><Input size="sm" required name="quoteAsset" maxLength={32} defaultValue={previous ? selected?.instrument?.quote_asset : ""} /></Field>
          <Field label={t("local.timeFormat")} required>
            <Select size="sm" required name="timestampUnit" defaultValue="">
              <option value="">—</option><option value="s">{t("local.unixS")}</option><option value="ms">{t("local.unixMs")}</option>
            </Select>
          </Field>
          <Field label={t("settings.exchange.channel.trade")} required>
            <Select size="sm" required name="tradeKind" defaultValue={previous?.kind ?? ""}>
              <option value="">—</option>
              <option value="MARKET_TRADE">{t("settings.exchange.channel.trade")}</option>
              <option value="MARKET_AGG_TRADE">{t("settings.exchange.channel.aggTrade")}</option>
            </Select>
          </Field>
          <Field label={t("ux.startUtc")} required><Input size="sm" required type="datetime-local" name="start" /></Field>
          <Field label={t("ux.endUtc")} required><Input size="sm" required type="datetime-local" name="end" /></Field>
        </fieldset>
        {previous && selected && <Checkbox name="revision" disabled={submitting} label={t("local.asRevision", { name: selected.name })} />}
        {error && <InlineAlert tone="danger">{error}</InlineAlert>}
        <Button variant="primary" type="submit" className="research-import-submit" disabled={submitting || file === null}>{t(submitting ? "local.csvValidating" : "local.importBtn")}</Button>
      </form>
    </Disclosure>
  );
}
