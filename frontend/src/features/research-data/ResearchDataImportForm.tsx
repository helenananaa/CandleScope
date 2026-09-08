import { useRef, useState } from "react";
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
  const [interval, setInterval] = useState("1m");
  const [timezone, setTimezone] = useState("UTC");
  const [timestampUnit, setTimestampUnit] = useState<"auto" | "s" | "ms" | "iso">("auto");
  const [volumeRequired, setVolumeRequired] = useState(false);
  const [asRevision, setAsRevision] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [columns, setColumns] = useState<CsvColumns | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const selectionRef = useRef(0);

  return (
    <form
      className="local-import-form"
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
          ...(asRevision && selected !== null ? { datasetId: selected.dataset_id } : {}),
        }).then(() => {
          setFile(null);
          setName("");
          setPreview(null); setColumns(null);
          if (fileInputRef.current !== null) fileInputRef.current.value = "";
        }).catch(() => undefined);
      }}
    >
      <header>
        <div>
          <span>{t("local.kicker.import")}</span>
          <strong>{t("local.import")}</strong>
        </div>
        <small>{t("local.localOnly")}</small>
      </header>
      <label className="local-file-picker">
        <span>{file?.name ?? t("local.chooseFile")}</span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => {
            const selectedFile = event.target.files?.[0] ?? null;
            const generation = ++selectionRef.current;
            setFile(selectedFile); setPreview(null); setColumns(null); setPreviewError(null);
            if (selectedFile) void selectedFile.slice(0, 65536).text().then((text) => {
              if (generation !== selectionRef.current) return;
              const parsed = parseResearchCsvPreview(text); setPreview(parsed); setColumns(parsed.suggested);
            }).catch((reason: unknown) => { if (generation === selectionRef.current) setPreviewError(String(reason)); });
          }}
        />
      </label>
      {previewError && <p role="alert">{previewError}</p>}
      {preview && columns && <section className="research-csv-preview">
        <h3>{t("ux.previewCsv")}</h3><p>{t("ux.csvHint")}</p>
        <div className="local-import-grid">{CSV_FIELDS.map((key) => <label key={key}>{key}
          <select value={columns[key]} onChange={(event) => setColumns({ ...columns, [key]: event.target.value })}>
            <option value="">{key === "volume" ? t("local.autoDetect") : "—"}</option>
            {preview.headers.map((header) => <option key={header} value={header}>{header}</option>)}
          </select>
        </label>)}</div>
        <div className="research-preview-table"><table><thead><tr>{preview.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
          <tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.headers.map((header, column) => <td key={header}>{row[column] ?? ""}</td>)}</tr>)}</tbody></table></div>
        {!validCsvColumns(columns, preview.headers) && <p role="alert">{t("ux.csvInvalid")}</p>}
      </section>}
      <label>
        {t("local.datasetName")}
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("local.namePh")} />
      </label>
      <div className="local-import-grid">
        <label>
          {t("local.symbol")}
          <input required value={symbol} onChange={(event) => setSymbol(event.target.value)} />
        </label>
        <label>
          {t("local.interval")}
          <input required value={interval} onChange={(event) => setInterval(event.target.value)} placeholder="1m" />
        </label>
        <label>
          {t("local.timezone")}
          <input required value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="UTC" />
        </label>
        <label>
          {t("local.timeFormat")}
          <select value={timestampUnit} onChange={(event) => setTimestampUnit(event.target.value as typeof timestampUnit)}>
            <option value="auto">{t("local.autoDetect")}</option>
            <option value="s">{t("local.unixS")}</option>
            <option value="ms">{t("local.unixMs")}</option>
            <option value="iso">{t("local.iso")}</option>
          </select>
        </label>
        <label>
          {t("local.volume")}
          <select
            value={volumeRequired ? "required" : "optional"}
            onChange={(event) => setVolumeRequired(event.target.value === "required")}
          >
            <option value="optional">{t("local.volumeOptional")}</option>
            <option value="required">{t("local.volumeRequired")}</option>
          </select>
        </label>
      </div>
      <p>{t("local.requiredCols")}</p>
      {selected !== null && (
        <label className="local-revision-choice">
          <input
            type="checkbox"
            checked={asRevision}
            onChange={(event) => setAsRevision(event.target.checked)}
          />
          {t("local.asRevision", { name: selected.name })}
        </label>
      )}
      <button type="submit" disabled={file === null || importing || !preview || !columns || !validCsvColumns(columns, preview.headers)}>
        {importing ? t("local.importing") : t("local.importBtn")}
      </button>
      {importing && (
        <div className="local-import-progress" role="status">
          <div><span>{importJob?.stage ?? "uploading"}</span><b>{importJob ? t("local.rows", { count: formatResearchRows(importJob.processed_rows) }) : `${Math.round((uploadProgress ?? 0) * 100)}%`}</b></div>
          <progress value={importJob?.total_rows ? importJob.processed_rows / importJob.total_rows : (uploadProgress ?? undefined)} />
          <button type="button" onClick={onCancel}>{t("local.cancelImport")}</button>
        </div>
      )}
    </form>
  );
}
