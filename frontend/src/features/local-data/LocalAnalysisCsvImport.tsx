import { describeError } from "../../i18n/serverErrors.js";
import { useState } from "react";
import { useControlCommands } from "../app-control/useControlCommands.js";
import { command } from "../app-control/commandRegistry.js";
import { choice, empty, nullable, object, text } from "../app-control/commandSchema.js";
import { readControlFile } from "../app-control/controlFiles.js";
import { t, type MessageKey } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { resolveLocalEventTimes } from "./localDataApi.js";
import {
  MAX_EVENT_CSV_BYTES,
  parseEventCsvText,
  prepareEventCsv,
  sha256EventCsv,
  suggestEventCsvMapping,
  type EventCsvDocument,
  type EventCsvMapping,
  type EventCsvRejection,
  type EventCsvTimestampUnit,
} from "./localAnalysisCsv.js";
import type { LocalAnalysisEventStore } from "./localAnalysisStore.js";
import {
  LOCAL_ANALYSIS_EVENT_KINDS,
  LOCAL_ANALYSIS_KIND_LABELS,
  type LocalAnalysisEventImportDraft,
  type LocalAnalysisEventKind,
} from "./localAnalysisTypes.js";
import type {
  LocalDatasetManifest,
  LocalEventTimeResolutionMode,
} from "./localDataTypes.js";

interface LoadedEventCsv {
  fileName: string;
  hash: string;
  document: EventCsvDocument;
}

interface ImportReport {
  imported: number;
  skipped: number;
  rejected: readonly EventCsvRejection[];
}

const MAPPING_LABEL_KEYS: Readonly<Record<keyof EventCsvMapping, MessageKey>> = {
  time: "local.csvTimeCol",
  price: "local.csvPriceCol",
  kind: "local.csvKindCol",
  label: "local.csvLabelCol",
  note: "local.csvNoteCol",
  color: "local.csvColorCol",
};

const EMPTY_MAPPING: EventCsvMapping = {
  time: null,
  price: null,
  kind: null,
  label: null,
  note: null,
  color: null,
};

export default function LocalAnalysisCsvImport({
  manifest,
  eventStore,
  storageError,
  onError,
}: {
  manifest: LocalDatasetManifest;
  eventStore: LocalAnalysisEventStore;
  storageError: string | null;
  onError(message: string): void;
}) {
  useLocale();
  const [loaded, setLoaded] = useState<LoadedEventCsv | null>(null);
  const [mapping, setMapping] = useState<EventCsvMapping>(EMPTY_MAPPING);
  const [timestampUnit, setTimestampUnit] = useState<EventCsvTimestampUnit>("auto");
  const [resolutionMode, setResolutionMode] = useState<LocalEventTimeResolutionMode>("containing");
  const [defaultKind, setDefaultKind] = useState<LocalAnalysisEventKind>("note");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);

  const loadFile = async (file: File) => {
    setBusy(true);
    setReport(null);
    try {
      if (file.size > MAX_EVENT_CSV_BYTES) throw new Error(t("local.csvOversize"));
      const bytes = await file.arrayBuffer();
      let text: string;
      try {
        text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        throw new Error(t("local.csvUtf8"));
      }
      const document = parseEventCsvText(text);
      const hash = await sha256EventCsv(bytes);
      setLoaded({ fileName: file.name, hash, document });
      setMapping(suggestEventCsvMapping(document.headers));
    } catch (reason) {
      setLoaded(null);
      setMapping(EMPTY_MAPPING);
      onError(reason instanceof Error ? describeError(reason, reason.message) : t("local.csvReadFailed"));
    } finally {
      setBusy(false);
    }
  };

  const importEvents = async () => {
    if (loaded === null) return;
    setBusy(true);
    setReport(null);
    try {
      const prepared = prepareEventCsv(loaded.document, mapping, timestampUnit, defaultKind);
      if (prepared.accepted.length === 0) {
        setReport({ imported: 0, skipped: 0, rejected: prepared.rejected });
        return;
      }
      const resolution = await resolveLocalEventTimes(
        manifest,
        prepared.accepted.map((row) => row.inputTimeMs),
        resolutionMode,
      );
      const rejected = [...prepared.rejected];
      const drafts: LocalAnalysisEventImportDraft[] = [];
      prepared.accepted.forEach((row, index) => {
        const resolved = resolution.results[index];
        if (resolved === undefined || !resolved.matched || resolved.bar_open_ms === undefined) {
          rejected.push({ rowNumber: row.rowNumber, reason: t("local.csvNoBar") });
          return;
        }
        drafts.push({
          id: `csv:${loaded.hash}:${row.rowNumber}`,
          ...row.draft,
          time: resolved.bar_open_ms / 1_000,
          source: "csv",
          extra: Object.freeze({
            ...row.extra,
            csv_file: loaded.fileName,
            csv_sha256: loaded.hash,
            input_time_ms: row.inputTimeMs,
            resolved_bar_open_ms: resolved.bar_open_ms,
            resolution_mode: resolutionMode,
            resolution_delta_ms: resolved.delta_ms ?? 0,
          }),
        });
      });
      const result = eventStore.importBatch(drafts);
      setReport({ imported: result.imported, skipped: result.skipped, rejected });
    } catch (reason) {
      onError(reason instanceof Error ? describeError(reason, reason.message) : t("local.csvImportFailed"));
    } finally {
      setBusy(false);
    }
  };

  useControlCommands(() => ({ id: "analysis-csv", title: "Analysis event CSV import", context: () => ({ datasetId: manifest.dataset_id, dataEpoch: manifest.data_epoch, fileHash: loaded?.hash, mapping, timestampUnit, resolutionMode, defaultKind, busy }),
    snapshot: () => ({ file: loaded ? { name: loaded.fileName, hash: loaded.hash, headers: loaded.document.headers, rows: loaded.document.rows.length } : null, mapping, timestampUnit, resolutionMode, defaultKind, busy, report, storageError }), commands: [
      command("load", "Load a staged CSV using the existing size, encoding and parser checks.", object({ fileRef: text(96) }), async ({ fileRef }) => loadFile(await readControlFile(fileRef)), { available: () => !busy }),
      command("mapping", "Edit known event column mapping and alignment options.", object({ mapping: object({ time: nullable(text(128)), price: nullable(text(128)), kind: nullable(text(128)), label: nullable(text(128)), note: nullable(text(128)), color: nullable(text(128)) }), timestampUnit: choice(["auto", "s", "ms", "iso"]), resolutionMode: choice(["exact", "containing"]), defaultKind: choice(LOCAL_ANALYSIS_EVENT_KINDS) }), (input) => { setMapping(input.mapping); setTimestampUnit(input.timestampUnit); setResolutionMode(input.resolutionMode); setDefaultKind(input.defaultKind); }, { available: () => !busy && !!loaded }),
      command("import", "Resolve each event time against the named data epoch and import with the existing hash-based deduplication.", empty, () => importEvents(), { available: () => !busy && !!loaded && !storageError }),
    ] }));
  return (
    <details className="local-analysis-csv-import">
      <summary>{t("local.csvImport")}</summary>
      <div className="local-analysis-csv-body">
        <p>{t("local.csvHint")}</p>
        <label className="local-analysis-csv-file">
          {t("local.csvFile")}
          <input
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file !== undefined) void loadFile(file);
            }}
          />
        </label>

        {loaded !== null && (
          <>
            <div className="local-analysis-csv-meta">
              <strong>{loaded.fileName}</strong>
              <small>{t("local.csvCount", { count: loaded.document.rows.length, hash: loaded.hash.slice(0, 12) })}</small>
            </div>
            <div className="local-analysis-csv-grid">
              {(Object.keys(MAPPING_LABEL_KEYS) as (keyof EventCsvMapping)[]).map((key) => (
                <label key={key}>
                  {t(MAPPING_LABEL_KEYS[key])}
                  <select
                    aria-label={t(MAPPING_LABEL_KEYS[key])}
                    value={mapping[key] ?? ""}
                    onChange={(event) => setMapping({ ...mapping, [key]: event.target.value || null })}
                  >
                    <option value="">{key === "time" ? t("local.csvPick") : t("local.csvUnmapped")}</option>
                    {loaded.document.headers.map((header) => <option value={header} key={header}>{header}</option>)}
                  </select>
                </label>
              ))}
              <label>
                {t("local.csvTimeFmt")}
                <select value={timestampUnit} onChange={(event) => setTimestampUnit(event.target.value as EventCsvTimestampUnit)}>
                  <option value="auto">{t("local.csvAuto")}</option>
                  <option value="s">{t("local.unixS")}</option>
                  <option value="ms">{t("local.unixMs")}</option>
                  <option value="iso">{t("local.csvIsoZ")}</option>
                </select>
              </label>
              <label>
                {t("local.csvBarMatch")}
                <select value={resolutionMode} onChange={(event) => setResolutionMode(event.target.value as LocalEventTimeResolutionMode)}>
                  <option value="containing">{t("local.csvContaining")}</option>
                  <option value="exact">{t("local.csvExact")}</option>
                </select>
              </label>
              <label>
                {t("local.csvDefaultKind")}
                <select value={defaultKind} onChange={(event) => setDefaultKind(event.target.value as LocalAnalysisEventKind)}>
                  {LOCAL_ANALYSIS_EVENT_KINDS.map((kind) => (
                    <option value={kind} key={kind}>{LOCAL_ANALYSIS_KIND_LABELS[kind]}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="local-analysis-csv-preview" aria-label={t("local.csvPreview")}>
              <table>
                <thead><tr>{loaded.document.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
                <tbody>{loaded.document.rows.slice(0, 3).map((row) => (
                  <tr key={row.rowNumber}>{loaded.document.headers.map((header) => <td key={header}>{row.values[header]}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
            <small className="local-analysis-csv-time-note">{t("local.csvTzNote")}</small>
            <button
              type="button"
              className="local-analysis-csv-submit"
              disabled={busy || storageError !== null || mapping.time === null}
              onClick={() => { void importEvents(); }}
            >
              {busy ? t("local.csvValidating") : t("local.csvImportBtn")}
            </button>
          </>
        )}

        {report !== null && (
          <div className="local-analysis-csv-report" role="status">
            <strong>{t("local.csvImported", { count: report.imported })}</strong>
            <span>{t("local.csvSkipped", { skipped: report.skipped, rejected: report.rejected.length })}</span>
            {report.rejected.length > 0 && (
              <ul>{report.rejected.slice(0, 20).map((item) => (
                <li key={`${item.rowNumber}:${item.reason}`}>{t("local.csvRow", { row: item.rowNumber, reason: item.reason })}</li>
              ))}</ul>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
