import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, Field, FileDrop, InlineAlert, Input, Select } from "../../components/ui/index.js";
import { CSV_FIELDS, parseResearchCsvPreview, validCsvColumns, type CsvColumns, type CsvPreview } from "./researchCsvPreview.js";

import { t } from "../../i18n/index.js";
import type { LocalDatasetManifest, LocalImportJob } from "./researchDataApi.js";
import { formatResearchRows } from "./researchDataFormat.js";
import type { ResearchImportSubmitInput } from "./useResearchDataLibrary.js";

export function ResearchDataImportForm({
  importing,
  importJob,
  uploadProgress,
  selected,
  onCancel,
  onImport,
}: {
  importing: boolean;
  importJob: LocalImportJob | null;
  uploadProgress: number | null;
  selected: LocalDatasetManifest | null;
  onCancel(): void;
  onImport(input: ResearchImportSubmitInput): Promise<unknown>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [baseAsset, setBaseAsset] = useState("");
  const [quoteAsset, setQuoteAsset] = useState("");
  const [interval, setInterval] = useState("1m");
  const [timezone, setTimezone] = useState("UTC");
  const [timestampUnit, setTimestampUnit] = useState<"auto" | "s" | "ms" | "iso">("auto");
  const [volumeRequired, setVolumeRequired] = useState(false);
  const [asRevision, setAsRevision] = useState(false);
  useEffect(() => {
    if (!asRevision) return;
    setBaseAsset(selected?.instrument?.base_asset ?? "");
    setQuoteAsset(selected?.instrument?.quote_asset ?? "");
  }, [asRevision, selected]);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [columns, setColumns] = useState<CsvColumns | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const selectionRef = useRef(0);

  return (
    <form
      className="research-import-form"
      data-testid="research-data-import-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (file === null || !preview || !columns || !validCsvColumns(columns, preview.headers)) return;
        void onImport({
          file,
          columns,
          name: name.trim() || file.name.replace(/\.csv$/i, ""),
          symbol,
          interval,
          timezone,
          timestampUnit,
          volumeRequired,
          baseAsset,
          quoteAsset,
          ...(asRevision && selected !== null ? { datasetId: selected.dataset_id } : {}),
        }).then(() => {
          setFile(null);
          setName("");
          setPreview(null); setColumns(null);
        }).catch(() => undefined);
      }}
    >
      <header className="research-import-head">
        <h3>{t("local.import")}</h3>
        <p>{t("local.localOnly")}</p>
      </header>
      <FileDrop
        compact
        label={file?.name ?? t("local.chooseFile")}
        hint=".csv"
        accept=".csv,text/csv"
        onFiles={([selectedFile]) => {
          const next = selectedFile ?? null;
          const generation = ++selectionRef.current;
          setFile(next); setPreview(null); setColumns(null); setPreviewError(null);
          if (next) void next.slice(0, 65536).text().then((text) => {
            if (generation !== selectionRef.current) return;
            const parsed = parseResearchCsvPreview(text); setPreview(parsed); setColumns(parsed.suggested);
          }).catch((reason: unknown) => { if (generation === selectionRef.current) setPreviewError(String(reason)); });
        }}
      />
      {previewError && <InlineAlert tone="danger">{previewError}</InlineAlert>}
      {preview && columns && <section className="research-csv-preview">
        <h4>{t("ux.previewCsv")}</h4>
        <p className="research-import-note">{t("ux.csvHint")}</p>
        <div className="research-import-grid">{CSV_FIELDS.map((key) => <Field key={key} label={key}>
          <Select size="sm" value={columns[key]} onChange={(event) => setColumns({ ...columns, [key]: event.target.value })}>
            <option value="">{key === "volume" ? t("local.autoDetect") : "—"}</option>
            {preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}
          </Select>
        </Field>)}</div>
        <div className="research-preview-table"><table><thead><tr>{preview.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
          <tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.headers.map((header, column) => <td key={header}>{row[column] ?? ""}</td>)}</tr>)}</tbody></table></div>
        {!validCsvColumns(columns, preview.headers) && <InlineAlert tone="danger">{t("ux.csvInvalid")}</InlineAlert>}
      </section>}
      <Field label={t("local.datasetName")}>
        <Input size="sm" value={name} onChange={(event) => setName(event.target.value)} placeholder={t("local.namePh")} />
      </Field>
      <div className="research-import-grid">
        <Field label={t("local.symbol")} required>
          <Input size="sm" required value={symbol} onChange={(event) => setSymbol(event.target.value)} />
        </Field>
        <Field label={t("local.interval")} required>
          <Input size="sm" required value={interval} onChange={(event) => setInterval(event.target.value)} placeholder="1m" />
        </Field>
        <Field label={t("local.timezone")} required>
          <Input size="sm" required value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="UTC" />
        </Field>
        <Field label={t("local.timeFormat")}>
          <Select size="sm" value={timestampUnit} onChange={(event) => setTimestampUnit(event.target.value as typeof timestampUnit)}>
            <option value="auto">{t("local.autoDetect")}</option>
            <option value="s">{t("local.unixS")}</option>
            <option value="ms">{t("local.unixMs")}</option>
            <option value="iso">{t("local.iso")}</option>
          </Select>
        </Field>
        <Field label={t("local.volume")}>
          <Select
            size="sm"
            value={volumeRequired ? "required" : "optional"}
            onChange={(event) => setVolumeRequired(event.target.value === "required")}
          >
            <option value="optional">{t("local.volumeOptional")}</option>
            <option value="required">{t("local.volumeRequired")}</option>
          </Select>
        </Field>
      </div>
      <p className="research-import-note">{t("local.requiredCols")}</p>
      <div className="research-import-grid">
        <Field label={t("local.baseAsset")}><Input size="sm" value={baseAsset} disabled={asRevision} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9._\-]{0,31}"
          required={quoteAsset.trim().length > 0} onChange={event => setBaseAsset(event.target.value)} /></Field>
        <Field label={t("local.quoteAsset")}><Input size="sm" value={quoteAsset} disabled={asRevision} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9._\-]{0,31}"
          required={baseAsset.trim().length > 0} onChange={event => setQuoteAsset(event.target.value)} /></Field>
      </div>
      <p className="research-import-note">{t("local.assetUnitsHint")}</p>
      {selected !== null && (
        <Checkbox
          checked={asRevision}
          onChange={(event) => setAsRevision(event.target.checked)}
          label={t("local.asRevision", { name: selected.name })}
        />
      )}
      <Button variant="primary" type="submit" className="research-import-submit" disabled={file === null || importing || !preview || !columns || !validCsvColumns(columns, preview.headers)}>
        {importing ? t("local.importing") : t("local.importBtn")}
      </Button>
      {importing && (
        <div className="local-import-progress" role="status">
          <div><span>{importJob?.stage ?? "uploading"}</span><b>{importJob ? t("local.rows", { count: formatResearchRows(importJob.processed_rows) }) : `${Math.round((uploadProgress ?? 0) * 100)}%`}</b></div>
          <progress value={importJob?.total_rows ? importJob.processed_rows / importJob.total_rows : (uploadProgress ?? undefined)} />
          <Button size="sm" variant="ghost" onClick={onCancel}>{t("local.cancelImport")}</Button>
        </div>
      )}
    </form>
  );
}
