import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { Button, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { JournalEditor } from "../trading-accounts/journalEditor.js";
import type { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import type { StudyNote } from "./historyStudyTypes.js";

/** Reuses the journal save queue, persisted drafts, idempotent client IDs and
 * optimistic revisions without inventing a trading account or financial plan. */
export default function StudyNoteEditor({ manager, studyId, marketMs, note, onChanged, onClose }: {
  manager: HistoryStudyDataManager; studyId: string; marketMs: number; note: StudyNote | null;
  onChanged(): void; onClose(): void;
}) {
  const inputId = useId();
  const [editor] = useState(() => new JournalEditor<StudyNote>({
    key: `candlescope.study-note-draft.v1:${studyId}:${note?.id ?? marketMs}`,
    storage: () => localStorage,
    create: (fields, id) => manager.saveNote(studyId, { id, fields, marketTimeMs: marketMs, expectedRevision: 0 }),
    save: (id, fields, expectedRevision) => manager.saveNote(studyId, { id, fields, marketTimeMs: marketMs, expectedRevision }),
    quick: async () => undefined,
  }));
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot, editor.getSnapshot);
  useEffect(() => { editor.activate(); editor.initialize(note); return () => editor.dispose(); }, [editor, note]);
  const save = async (close: boolean) => { if (await editor.flush()) { onChanged(); if (close) onClose(); } };
  return <section className="study-note-editor" aria-label={t("study.noteEdit")}>
    <label htmlFor={inputId}>{t("study.noteBody")}</label><Textarea id={inputId} value={state.fields.entryBasis ?? ""} disabled={!state.ready}
      onChange={event => editor.edit({ ...state.fields, entryBasis: event.target.value })} />
    <p className="trading-help">{t("study.noteHint")}</p>
    {state.error != null && <p role="alert">{t("study.error")}</p>}
    <div className="study-actions"><Button size="sm" disabled={!state.ready || state.status === "saving"}
      onClick={() => { void save(false); }}>{t(state.status === "saving" ? "study.saving" : state.status === "saved" ? "study.saved" : "study.noteSave")}</Button>
      <Button size="sm" disabled={!state.ready || state.status === "saving"}
        onClick={() => { void save(true); }}>{t("study.noteClose")}</Button></div>
  </section>;
}
