import { describeError } from "../../i18n/serverErrors.js";
import { useMemo, useState } from "react";
import { t, getLocale } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
import LocalAnalysisCsvImport from "./LocalAnalysisCsvImport.js";
import type { LocalAnalysisEventStore } from "./localAnalysisStore.js";
import {
  LOCAL_ANALYSIS_EVENT_KINDS,
  LOCAL_ANALYSIS_KIND_COLORS,
  LOCAL_ANALYSIS_KIND_LABELS,
  type LocalAnalysisEvent,
  type LocalAnalysisEventKind,
  type LocalAnalysisSnapshot,
} from "./localAnalysisTypes.js";
import type { LocalDatasetManifest } from "./localDataTypes.js";
import { useControlCommands } from "../app-control/useControlCommands.js";
import { command } from "../app-control/commandRegistry.js";
import { choice, empty, nullable, number, object, text } from "../app-control/commandSchema.js";
import { publishControlFile } from "../app-control/controlFiles.js";

interface EventAnchor {
  time: number;
  price: number | null;
}

function anchorFromCrosshair(value: MainSeriesCrosshairValue | null): EventAnchor | null {
  if (value === null || typeof value.time !== "number" || !Number.isFinite(value.time)) return null;
  return { time: value.time, price: Number.isFinite(value.close) ? value.close : null };
}

function formatEventTime(time: number, timezone: string): string {
  try {
    return new Intl.DateTimeFormat(getLocale(), {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: timezone,
      hour12: false,
    }).format(new Date(time * 1_000));
  } catch {
    return new Date(time * 1_000).toLocaleString(getLocale());
  }
}

function formatPrice(price: number | null): string {
  return price === null
    ? t("local.noPrice")
    : new Intl.NumberFormat(getLocale(), { maximumFractionDigits: 12 }).format(price);
}

function eventTitle(event: LocalAnalysisEvent): string {
  return event.label || LOCAL_ANALYSIS_KIND_LABELS[event.kind];
}

export default function LocalAnalysisPanel({
  manifest,
  snapshot,
  eventStore,
  crosshair,
  onFocus,
  onError,
}: {
  manifest: LocalDatasetManifest;
  snapshot: LocalAnalysisSnapshot;
  eventStore: LocalAnalysisEventStore;
  crosshair: MainSeriesCrosshairValue | null;
  onFocus(event: LocalAnalysisEvent): void;
  onError(message: string): void;
}) {
  useLocale();
  const [kind, setKind] = useState<LocalAnalysisEventKind>("note");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [color, setColor] = useState(LOCAL_ANALYSIS_KIND_COLORS.note);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingAnchor, setEditingAnchor] = useState<EventAnchor | null>(null);
  const [filter, setFilter] = useState<"all" | LocalAnalysisEventKind>("all");
  const liveAnchor = anchorFromCrosshair(crosshair);
  const activeAnchor = editingId === null ? liveAnchor : editingAnchor;
  const visibleEvents = useMemo(() => [...snapshot.events]
    .filter((event) => filter === "all" || event.kind === filter)
    .sort((left, right) => right.time - left.time || right.created_at.localeCompare(left.created_at)), [filter, snapshot.events]);

  const resetForm = () => {
    setEditingId(null);
    setEditingAnchor(null);
    setKind("note");
    setLabel("");
    setNote("");
    setColor(LOCAL_ANALYSIS_KIND_COLORS.note);
  };

  const startEdit = (event: LocalAnalysisEvent) => {
    setEditingId(event.id);
    setEditingAnchor({ time: event.time, price: event.price });
    setKind(event.kind);
    setLabel(event.label);
    setNote(event.note);
    setColor(event.color);
  };

  const submit = () => {
    if (activeAnchor === null) {
      onError(t("local.needHover"));
      return;
    }
    try {
      const draft = {
        time: activeAnchor.time,
        price: activeAnchor.price,
        kind,
        label,
        note,
        color,
      };
      if (editingId === null) eventStore.create(draft);
      else eventStore.update(editingId, draft);
      resetForm();
    } catch (reason) {
      onError(reason instanceof Error ? describeError(reason, reason.message) : t("local.saveFailed"));
    }
  };

  const eventInput = object({ time: number(0.001), price: nullable(number()), kind: choice(LOCAL_ANALYSIS_EVENT_KINDS), label: text(160, 0), note: text(8000, 0), color: text(7) });
  useControlCommands(() => ({ id: "local-analysis", title: "Imported dataset analysis events", context: () => ({ datasetId: manifest.dataset_id, dataEpoch: manifest.data_epoch, revision: snapshot.revision }),
    snapshot: () => ({ datasetId: manifest.dataset_id, dataEpoch: manifest.data_epoch, revision: snapshot.revision, storageError: snapshot.storage_error, count: snapshot.events.length, filter }), commands: [
      command("events", "Read a bounded event page.", object({ offset: number(0, 5000, true), limit: number(1, 500, true) }), ({ offset, limit }) => snapshot.events.slice(offset, offset + limit), { readOnly: true }),
      command("create", "Create a manual analysis event through the existing persisted event store.", eventInput, (draft) => eventStore.create(draft), { available: () => !snapshot.storage_error }),
      command("update", "Update an existing analysis event.", object({ eventId: text(200), event: eventInput }), ({ eventId, event }) => eventStore.update(eventId, event), { available: () => !snapshot.storage_error }),
      command("delete", "Delete an existing analysis event.", object({ eventId: text(200) }), ({ eventId }) => { if (!eventStore.delete(eventId)) throw new Error("EVENT_UNAVAILABLE"); }, { available: () => !snapshot.storage_error }),
      command("focus", "Focus a loaded analysis event on the chart.", object({ eventId: text(200) }), ({ eventId }) => { const event = snapshot.events.find((row) => row.id === eventId); if (!event) throw new Error("EVENT_UNAVAILABLE"); onFocus(event); }),
      command("filter", "Filter the analysis panel.", object({ kind: choice(["all", ...LOCAL_ANALYSIS_EVENT_KINDS]) }), ({ kind }) => setFilter(kind)),
      command("export", "Export the identity-bound analysis document to a fileRef.", empty, () => publishControlFile(new Blob([JSON.stringify({ schema_version: 1, dataset_id: manifest.dataset_id, data_epoch: manifest.data_epoch, events: snapshot.events })], { type: "application/json" }), "analysis-events.json")),
      command("resetCorrupt", "Reset a corrupt analysis document with explicit confirmation.", object({ confirmed: choice([true]) }), () => eventStore.resetCorruptDocument(), { available: () => !!snapshot.storage_error }),
    ] }));
  return (
    <section className="local-analysis-panel" aria-label={t("local.analysisAria")}>
      <header>
        <div>
          <span>{t("local.kicker.analysis")}</span>
          <strong>{t("local.events")}</strong>
        </div>
        <small>{t("local.autoSave", { count: snapshot.events.length })}</small>
      </header>

      {snapshot.storage_error !== null && (
        <div className="local-analysis-storage-error" role="alert">
          <span>{snapshot.storage_error}</span>
          <button
            type="button"
            onClick={() => {
              try { eventStore.resetCorruptDocument(); }
              catch (reason) { onError(reason instanceof Error ? describeError(reason, reason.message) : t("local.resetFailed")); }
            }}
          >
            {t("local.resetFile")}
          </button>
        </div>
      )}

      <div className="local-analysis-anchor" data-ready={activeAnchor !== null ? "true" : "false"}>
        <span>{editingId === null ? t("local.currentPoint") : t("local.markerPos")}</span>
        <strong>{activeAnchor === null ? t("local.moveHint") : formatEventTime(activeAnchor.time, manifest.timezone)}</strong>
        <small>{activeAnchor === null ? t("local.keepLast") : formatPrice(activeAnchor.price)}</small>
        {editingId !== null && liveAnchor !== null && (
          <button type="button" onClick={() => setEditingAnchor(liveAnchor)}>{t("local.moveToPoint")}</button>
        )}
      </div>

      <div className="local-analysis-form">
        <div className="local-analysis-form-grid">
          <label>
            {t("local.kind")}
            <select
              value={kind}
              onChange={(event) => {
                const next = event.target.value as LocalAnalysisEventKind;
                setKind(next);
                setColor(LOCAL_ANALYSIS_KIND_COLORS[next]);
              }}
            >
              {LOCAL_ANALYSIS_EVENT_KINDS.map((value) => (
                <option value={value} key={value}>{LOCAL_ANALYSIS_KIND_LABELS[value]}</option>
              ))}
            </select>
          </label>
          <label className="local-analysis-color-field">
            {t("local.color")}
            <input type="color" value={color} onChange={(event) => setColor(event.target.value)} />
          </label>
        </div>
        <label>
          {t("local.title")}
          <input
            value={label}
            maxLength={160}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={t("local.kindOptional", { kind: LOCAL_ANALYSIS_KIND_LABELS[kind] })}
          />
        </label>
        <label>
          {t("local.note")}
          <textarea
            value={note}
            maxLength={8_000}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("local.notePh")}
          />
        </label>
        <div className="local-analysis-form-actions">
          {editingId !== null && <button type="button" className="secondary" onClick={resetForm}>{t("replay.hub.cancel")}</button>}
          <button
            type="button"
            onClick={submit}
            disabled={activeAnchor === null || snapshot.storage_error !== null}
          >
            {editingId === null ? t("local.addToChart") : t("local.saveEdit")}
          </button>
        </div>
      </div>

      <LocalAnalysisCsvImport
        manifest={manifest}
        eventStore={eventStore}
        storageError={snapshot.storage_error}
        onError={onError}
      />

      <div className="local-analysis-list-head">
        <strong>{t("local.projectEvents")}</strong>
        <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
          <option value="all">{t("local.allKinds")}</option>
          {LOCAL_ANALYSIS_EVENT_KINDS.map((value) => (
            <option value={value} key={value}>{LOCAL_ANALYSIS_KIND_LABELS[value]}</option>
          ))}
        </select>
      </div>
      <div className="local-analysis-event-list">
        {visibleEvents.length === 0 ? (
          <div className="local-analysis-event-empty">
            {snapshot.events.length === 0 ? t("local.noMarkers") : t("local.noFilter")}
          </div>
        ) : visibleEvents.map((event) => (
          <article className={event.id === editingId ? "editing" : ""} key={event.id}>
            <button type="button" className="local-analysis-event-main" onClick={() => onFocus(event)}>
              <i style={{ background: event.color }} />
              <span>
                <strong>{eventTitle(event)}{event.source === "csv" ? " · CSV" : ""}</strong>
                <small>{formatEventTime(event.time, manifest.timezone)} · {formatPrice(event.price)}</small>
                {event.note && <em>{event.note}</em>}
              </span>
            </button>
            <div className="local-analysis-event-actions">
              <button type="button" onClick={() => onFocus(event)}>{t("local.locate")}</button>
              <button type="button" onClick={() => startEdit(event)}>{t("local.edit")}</button>
              <button
                type="button"
                className="danger"
                onClick={() => {
                  try {
                    eventStore.delete(event.id);
                    if (editingId === event.id) resetForm();
                  } catch (reason) {
                    onError(reason instanceof Error ? describeError(reason, reason.message) : t("local.deleteMarkerFailed"));
                  }
                }}
              >
                {t("replay.hub.delete")}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
